"""A stand-in for the plugin's diagnostics channel (plugin/src/diag.cpp), for
the CLI and configurator tests. Speaks protocol 1 on 127.0.0.1.

By default it is a plugin that runs one network and, like a plugin from
before several networks, lists none in the hello. FakePlugin(networks=...)
lists them; with more than one, every request needs `network`. The first
network's state is the FakePlugin's own attributes (status, objects, present,
emcy), the others' are in `fp.network(name)`."""

import base64
import copy
import json
import time
import socket
import socketserver
import threading

from openplc_canopen_deploy import diag

TOKEN = "test-token"


def status(config_sha256="0" * 64):
    return {
        "version": "v-test", "uptime_s": 12, "config_sha256": config_sha256, "session": True,
        "master": {"node_id": 1, "state": 5},
        "bus": {"interface": "vcan0", "state": 1, "tx_errors": 0, "rx_errors": 0, "bus_off_count": 0},
        "sync": {"source": "plc_cycle", "cycles": 2, "count": 500, "last_us": 10012, "min_us": 9870,
                 "max_us": 10240, "skipped": 0, "late_pdos": 3},
        "nodes": [
            {"node_id": 2, "name": "pingpong", "state": 5, "status": True, "booted": True, "boot_error": None,
             "retry_pending": False, "hold": "none", "hold_by": None,
             "emcy": {"code": 0x4210, "error_register": 0x09, "count": 3},
             "sdo_variables": [{"name": "SDO variable 0x2001:0 (uptime)", "index": 0x2001, "subindex": 0, "type": "UNSIGNED32",
                                "direction": "read", "raw": "42", "status": 1, "abort_code": 0}]},
            {"node_id": 23, "name": "valve", "state": 0, "status": False, "booted": False, "boot_error": "J",
             "boot_error_text": "the configuration download failed (SDO abort 0x06010002 at 0x1400 sub 2)",
             "retry_pending": True, "hold": "none", "hold_by": None,
             "emcy": {"code": 0, "error_register": 0, "count": 0}, "sdo_variables": []},
        ],
    }


SCAN_RESULT = [
    {"node_id": 2, "vendor_id": 0x360, "product_code": 0, "revision_number": 0, "serial_number": 7,
     "device_type": 0x191, "device_name": "pingpong", "name": "pingpong", "match": "configured"},
    {"node_id": 40, "vendor_id": 0xAB, "product_code": 0x1234, "revision_number": 0x00010002,
     "serial_number": 99, "device_type": 0x194, "device_name": "RTD sensor", "match": "not configured"},
    {"node_id": 41, "vendor_id": 0xCD, "product_code": 0x9, "match": "not configured"},
]


# The networks of a two-network plugin, as the hello lists them.
TWO_NETWORKS = [{"name": "io", "interface": "vcan0", "bitrate": 125000, "master_node_id": 1},
                {"name": "drives", "interface": "vcan1", "bitrate": 500000, "master_node_id": 1}]


def drives_status(config_sha256="0" * 64):
    """Status of the second network of TWO_NETWORKS: another node 2."""
    return {
        "version": "v-test", "uptime_s": 12, "config_sha256": config_sha256, "network": "drives", "session": True,
        "master": {"node_id": 1, "state": 5},
        "bus": {"interface": "vcan1", "state": 1, "tx_errors": 0, "rx_errors": 0, "bus_off_count": 0},
        "nodes": [
            {"node_id": 2, "name": "drive", "state": 127, "status": True, "booted": True, "boot_error": None,
             "retry_pending": False, "hold": "none", "hold_by": None,
             "emcy": {"code": 0, "error_register": 0, "count": 0}, "sdo_variables": []},
        ],
    }


class FakeNetwork:
    """The state of a network other than the first."""

    def __init__(self, info, status):
        self.info = info
        self.status = status
        self.objects = {}
        self.present = set()
        self.emcy = {}


class FakePlugin:
    def __init__(self, token=TOKEN, allow_changes=False, scan_polls=2, networks=None):
        self.token = token
        # [{name, interface, bitrate, master_node_id}] for the hello; None: an
        # older plugin that lists no networks.
        self.networks = copy.deepcopy(networks) if networks is not None else None
        self.others = {}
        self.allow_changes = allow_changes
        self.status = status()
        self.objects = {(2, 0x1008, 0): b"pingpong", (2, 0x1018, 4): (305419896).to_bytes(4, "little"),
                        (2, 0x2000, 0): b"\x00\x00\x00\x00"}
        self.emcy = {2: [{"time": "2026-10-03T12:00:01.250Z", "code": 0x4210, "error_register": 0x09,
                          "manufacturer": "00 00 00 00 00"},
                         {"time": "2026-10-03T12:00:00.000Z", "code": 0x0000, "error_register": 0,
                          "manufacturer": "00 00 00 00 00"}]}
        self.scan_polls = scan_polls
        self.scan_nodes = copy.deepcopy(SCAN_RESULT)
        self.scan_left = None
        self.requests = []
        # LSS: devices by address (vendor, product, revision, serial) -> node ID (255: none).
        self.lss_devices = {(0x360, 0, 0, 0x42): 255, (0x360, 0, 0, 0x1234): 12}
        self.lss_polls = scan_polls
        self.lss_left = None
        self.connections = 0
        # Traces: frames the test pushes (packed 24-byte records) with sequence
        # numbers from 1; a ring of trace_ring records.
        self.trace_supported = True
        self.trace_records = []  # (seq, packed)
        self.trace_seq = 0
        self.trace_ring = 65536
        self.trace_session = True
        self.trace_starts = []
        self.trace_lock = threading.Lock()
        self.present = {2, 23, 40}  # node IDs that answer SDO
        if self.networks:
            self.status["network"] = self.networks[0]["name"]
            self.status["bus"]["interface"] = self.networks[0]["interface"]
            for info in self.networks[1:]:
                st = drives_status() if info["name"] == "drives" else dict(status(), nodes=[])
                st["network"] = info["name"]
                st["bus"]["interface"] = info["interface"]
                self.others[info["name"]] = FakeNetwork(info, st)
            if "drives" in self.others:
                self.others["drives"].objects[(2, 0x1008, 0)] = b"drive"
                self.others["drives"].present.add(2)
        self.configured = set()  # extra configured node IDs (NMT allowed)
        self.refuse_writes = {}
        self.delay = 0.0  # seconds before each SDO answer  # (node, index, sub): abort code for a write
        fake = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                fake.connections += 1
                authed = False
                for raw in self.rfile:
                    try:
                        req = json.loads(raw)
                    except ValueError:
                        self._send({"ok": False, "error": "not a JSON object"})
                        continue
                    if not authed:
                        if req.get("op") != "hello" or req.get("token") != fake.token:
                            return  # the plugin closes without an answer
                        authed = True
                        hello = {"protocol": 1, "version": "v-test", "allow_changes": fake.allow_changes,
                                 "master_node_id": 1}
                        if fake.networks is not None:
                            hello["networks"] = copy.deepcopy(fake.networks)
                        self._send({"id": req.get("id"), "ok": True, "result": hello})
                        continue
                    fake.requests.append(req)
                    if fake.delay and req.get("op") in ("sdo_read", "sdo_write"):
                        time.sleep(fake.delay)
                    self._send(dict(fake.answer(req), id=req.get("id")))

            def _send(self, obj):
                try:
                    self.wfile.write(json.dumps(obj).encode() + b"\n")
                except OSError:
                    pass

        class Server(socketserver.ThreadingTCPServer):
            daemon_threads = True
            allow_reuse_address = True

        self.server = Server(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()

    def network(self, name):
        """A network's state: the FakePlugin itself for the first one."""
        if self.networks and name != self.networks[0]["name"]:
            return self.others[name]
        return self

    def _pick(self, req):
        """(network state, None) for a request, or (None, error) as the plugin
        answers a missing or unknown network."""
        if not self.networks:
            return self, None
        names = ", ".join(n["name"] for n in self.networks)
        name = req.get("network")
        if name is None:
            if len(self.networks) == 1:
                return self, None
            return None, "network required (%s)" % names
        if name not in [n["name"] for n in self.networks]:
            return None, "unknown network '%s' (%s)" % (name, names)
        return self.network(name), None

    @property
    def runtime(self):
        return "127.0.0.1:%d" % self.port

    def push(self, frames):
        """Adds frames (bustrace.model.Frame) to the fake capture."""
        with self.trace_lock:
            for f in frames:
                self.trace_seq += 1
                self.trace_records.append((self.trace_seq, f.pack()))
            del self.trace_records[:-self.trace_ring]

    def _trace(self, req, ok, err, net):
        op = req["op"]
        if not self.trace_supported:
            return err("unknown op '%s'" % op)
        if op == "trace_start":
            if not self.trace_session:
                return err("no bus")
            self.trace_starts.append(req)
            res = {"next": self.trace_seq, "buffer_frames": self.trace_ring, "record_size": 24,
                   "interface": "vcan0", "bitrate": 125000}
            if self.networks:
                info = net.info if net is not self else self.networks[0]
                res.update(network=info["name"], interface=info["interface"], bitrate=info["bitrate"])
            return ok(res)
        if op == "trace_stop":
            return ok({})
        with self.trace_lock:
            after, most = int(req["after"]), int(req.get("max", 2000))
            oldest = self.trace_records[0][0] if self.trace_records else self.trace_seq + 1
            lost = max(0, oldest - (after + 1)) if self.trace_records else 0
            recs = [(q, b) for q, b in self.trace_records if q > after][:most]
            nxt = recs[-1][0] if recs else max(after, self.trace_seq if not self.trace_records else after)
            return ok({"count": len(recs), "next": nxt, "more": nxt < self.trace_seq, "lost": lost,
                       "kernel_drops": 0, "session": self.trace_session,
                       "frames": base64.b64encode(b"".join(b for _, b in recs)).decode()})

    def answer(self, req):
        op = req.get("op")
        ok = lambda result: {"ok": True, "result": result}  # noqa: E731
        err = lambda why: {"ok": False, "error": why}  # noqa: E731
        net, why = self._pick(req)
        if why:
            return err(why)
        if op in ("trace_start", "trace_fetch", "trace_stop"):
            return self._trace(req, ok, err, net)
        if op == "status":
            return ok(copy.deepcopy(net.status))
        if op == "emcy":
            return ok({"node_id": req["node"], "emcy": net.emcy.get(req["node"], [])})
        if op in ("sdo_write", "nmt") and not self.allow_changes:
            return err("changes not allowed")
        if op in ("sdo_read", "sdo_write"):
            node, index, sub = req["node"], req["index"], req["subindex"]
            base = {"node": node, "index": index, "subindex": sub}
            if node not in net.present:
                return ok(dict(base, success=False, error="timeout"))
            if op == "sdo_write" and (node, index, sub) in self.refuse_writes:
                code = self.refuse_writes[(node, index, sub)]
                return ok(dict(base, success=False, abort_code=code, abort_code_hex="0x%08X" % code,
                               error=diag.abort_text(code)))
            if (node, index, sub) not in net.objects:
                return ok(dict(base, success=False, abort_code=0x06020000, abort_code_hex="0x06020000",
                               error="object does not exist"))
            if op == "sdo_write":
                net.objects[(node, index, sub)] = diag.parse_hex(req["data"])
                return ok(dict(base, success=True))
            data = net.objects[(node, index, sub)]
            return ok(dict(base, success=True, data=diag.hex_bytes(data), size=len(data)))
        if op == "nmt":
            if req["node"] not in (2, 23) and req["node"] not in self.configured:
                return err("node %d is not in the configuration" % req["node"])
            for n in net.status["nodes"]:
                if n["node_id"] == req["node"]:
                    if req["command"] in ("stop", "preop"):
                        n["hold"], n["hold_by"] = ("stopped" if req["command"] == "stop" else "preop"), "operator"
                        n["state"] = 4 if req["command"] == "stop" else 127
                    elif req["command"] == "start":
                        n["hold"], n["hold_by"], n["state"] = "none", None, 5
            return ok({})
        if op.startswith("lss_") and op != "lss_find_status" and not self.allow_changes:
            return err("changes not allowed")
        if op in ("lss_find", "lss_find_status"):
            if op == "lss_find":
                self.lss_left = self.lss_polls
                self.lss_mask = (req["vendor_id"], req["product_code"]) if "vendor_id" in req else None
            if self.lss_left is None:
                return ok({"running": False})
            if self.lss_left > 0:
                self.lss_left -= 1
                return ok({"running": True, "seconds": 1.0})
            found = [a for a, nid in self.lss_devices.items() if nid == 255 and
                     (not self.lss_mask or (a[0], a[1]) == self.lss_mask)]
            res = {"running": False, "seconds": 3.5, "found": bool(found)}
            if found:
                res["device"] = dict(zip(diag.LSS_KEYS, found[0]), node_id=255)
            return ok(res)
        if op in ("lss_inquire", "lss_set_id", "lss_set_bitrate"):
            addr = tuple(req[k] for k in diag.LSS_KEYS)
            if addr not in self.lss_devices:
                return err("not found: no device with %s answered" % diag.lss_address_text(addr))
            prev = self.lss_devices[addr]
            if op == "lss_inquire":
                return ok({"node_id": prev, "configured": prev != 255})
            if op == "lss_set_id":
                for n in self.status["nodes"]:
                    if n["node_id"] == req["node"] and n["booted"]:
                        return err("node ID %d is in use by node %d (%s), which is booted"
                                   % (req["node"], req["node"], n["name"]))
                self.lss_devices[addr] = req["node"]
                return ok({"node_id": req["node"], "previous_node_id": prev, "had_node_id": prev != 255,
                           "note": "the device had no node ID and starts with the new one now" if prev == 255 else
                           "the device had another node ID; the new one becomes active after its next "
                           "communication reset or power cycle", "stored": req["store"]})
            return ok({"bitrate_kbit": req["bitrate_kbit"], "stored": req["store"],
                       "note": "the device uses the new bit rate after its next power cycle; change "
                               "adapter.bitrate to match"})
        if op in ("scan", "scan_status"):
            if op == "scan" and not self.scan_left:
                self.scan_left = self.scan_polls
            if self.scan_left is None:
                return ok({"running": False, "done": 0, "total": 0})
            if self.scan_left > 0:
                self.scan_left -= 1
                return ok({"running": True, "done": 126 - 40 * self.scan_left, "total": 126})
            return ok({"running": False, "done": 126, "total": 126, "finished_at": "2026-10-03T12:00:02.000Z",
                       "seconds": 1.8, "note": "devices in STOPPED do not answer SDO and are not found",
                       "nodes": copy.deepcopy(self.scan_nodes)})
        return err("unknown op '%s'" % op)


def closed_port():
    """A local port nothing listens on."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port
