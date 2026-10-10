"""A stand-in for the plugin's diagnostics channel (plugin/src/can/diag.cpp), for
the CLI and configurator tests. Speaks protocol 2 (TLS and the SCRAM login,
fake_tls.py) on 127.0.0.1, and tells a plain client to update.

By default it is a plugin that runs one network and, like a plugin from
before several networks, lists none in the hello. FakePlugin(networks=...)
lists them; with more than one, every request needs `network`. The first
network's state is the FakePlugin's own attributes (status, objects, present,
emcy), the others' are in `fp.network(name)`.

With sim=FakeSim(...) (fake_sim.py) the first network simulates devices and
answers the sim_ requests; without, every sim_ request answers "nothing
simulated".

send_frame, send_frame_stop, detect_bitrate and detect_bitrate_status follow
the plugin's guards: allow_changes, then force for an identifier in `cob_ids`
or while `operational` names a node. Cyclic jobs count their frames from the
time they started and end with their connection; a sweep moves on
`sweep_step` rates per detect_bitrate_status and hears what `sweep_hears`
says per rate."""

import base64
import copy
import json
import os
import re
import time
import socket
import socketserver
import threading

from canworks import diag

from . import fake_tls

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
             "emcy": {"code": 0, "error_register": 0, "count": 0}, "sdo_variables": [],
             "pdo_timeouts": [{"tpdo": 1, "timeout_ms": 500, "timed_out": True, "count": 2, "since_ms": 1800},
                              {"tpdo": 2, "timeout_ms": 200, "timed_out": False, "count": 0, "since_ms": None}]},
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


# A J1939 network as the hello lists it, and its status answer as recorded
# (design Decision 11): claimed at 128, PGN 65280 timed out with two
# senders, 0 and 3.
J1939_NETWORK = {"name": "machine", "interface": "vcan0", "bitrate": 250000, "protocol": "j1939"}
J1939_STATUS = os.path.join(os.path.dirname(__file__), "data", "diag", "j1939-status.json")


def j1939_status():
    with open(J1939_STATUS, encoding="utf-8") as f:
        return json.load(f)


# A plain CAN network (examples/raw-can) as the hello lists it, and its
# status (diag.cpp offline_answer, raw_runtime.cpp RawRuntime::status).
PLAIN_NETWORK = {"name": "cab", "interface": "can0", "bitrate": 250000, "protocol": "none"}


def plain_status():
    return {
        "version": "v-test", "uptime_s": 7, "config_sha256": "0" * 64, "network": "cab", "session": False,
        "protocol": "none", "simulated_network": False, "simulation_forced": False, "listen_only": False,
        "bus": {"interface": "can0", "bitrate": 250000, "state": 1},
        "raw": {"running": True, "listen_only": False, "confirm": "echo", "frames_sent": 40, "frames_received": 81,
                "bus_load": 3, "program": {"receivers": 1, "cyclic_jobs": 0, "frames_sent": 2, "dropped": 0},
                "rx": [{"message": "Joystick", "count": 80, "short_frames": 0, "seen": True, "timed_out": False,
                        "age_ms": 12, "last_id": 0x181, "last_dlc": 5, "last_data": "E8 03 0C FE 01"},
                       {"message": "Pedal", "count": 1, "short_frames": 1, "seen": True, "timed_out": True,
                        "age_ms": 900, "last_id": 0x18FF1020, "last_dlc": 2, "last_data": "01 F4"}],
                "tx": [{"message": "Display", "count": 38}],
                "simulated_devices": ["joystick"]},
    }


# A slave network (config/slave) as the hello lists it.
SLAVE_NETWORK = {"name": "line", "interface": "vcan1", "bitrate": 250000, "role": "slave", "node_id": 10}


def slave_status(config_sha256="0" * 64, gateway=False):
    """Status of a slave network (plc_slave.cpp DiagStatus): node 10 of
    config/slave with its default PDO mappings, TPDO2 switched off; with
    `gateway`, the upper network of a gateway."""
    st = {
        "version": "v-test", "uptime_s": 12, "config_sha256": config_sha256, "network": "line", "role": "slave",
        "session": True,
        "slave": {"node_id": 10, "state": 5, "comm_ok": True, "sync_count": 42, "emcy_code": 0x4210,
                  "error_register": 0x09,
                  "tpdos": [{"number": 1, "cob_id": 0x18A, "transmission": 255, "entries": [
                      {"index": 0x2100, "subindex": 1, "bits": 16}, {"index": 0x2100, "subindex": 2, "bits": 16},
                      {"index": 0x2101, "subindex": 1, "bits": 16}]},
                      {"number": 2, "cob_id": 0x8000028A, "transmission": 1, "entries": []}],
                  "rpdos": [{"number": 1, "cob_id": 0x20A, "transmission": 255, "entries": [
                      {"index": 0x2000, "subindex": 1, "bits": 16}, {"index": 0x2001, "subindex": 1, "bits": 8},
                      {"index": 0x2002, "subindex": 1, "bits": 1}]}]},
        "bus": {"interface": "vcan1"},
        "nodes": [],
    }
    if gateway:
        st["gateway"] = {"routes": 2, "upper_ok": False, "forwarded_errors": 1}
    return st


def slave_objects(node=10):
    return {(node, 0x1008, 0): b"OpenPLC slave example", (node, 0x2000, 1): b"\x05\x00",
            (node, 0x2100, 1): b"\x07\x00"}


class FakeNetwork:
    """The state of a network other than the first."""

    def __init__(self, info, status):
        self.info = info
        self.status = status
        self.objects = {}
        self.present = set()
        self.emcy = {}


class FakePlugin:
    def __init__(self, token=TOKEN, allow_changes=False, scan_polls=2, networks=None, sim=None, bad_signature=False):
        self.token = token
        self.bad_signature = bad_signature  # an impostor: a wrong login signature
        self.logins = []  # the login requests, as received
        self.sim = sim
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
        self.conns = set()  # the handlers of the open connections
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
            if self.networks[0].get("protocol") == "j1939":
                self.status = j1939_status()
                self.present = set()
            elif self.networks[0].get("protocol") == "none":
                self.status = plain_status()
                self.present = set()
            elif self.networks[0].get("role") == "slave":
                self.status = slave_status()
                self.objects = slave_objects(self.networks[0]["node_id"])
                self.present = {self.networks[0]["node_id"]}
            self.status["network"] = self.networks[0]["name"]
            self.status["bus"]["interface"] = self.networks[0]["interface"]
            for info in self.networks[1:]:
                slave = info.get("role") == "slave"
                st = (drives_status() if info["name"] == "drives" else slave_status() if slave
                      else j1939_status() if info.get("protocol") == "j1939" else dict(status(), nodes=[]))
                st["network"] = info["name"]
                st["bus"]["interface"] = info["interface"]
                self.others[info["name"]] = FakeNetwork(info, st)
                if slave:
                    self.others[info["name"]].objects = slave_objects(info["node_id"])
                    self.others[info["name"]].present = {info["node_id"]}
            if "drives" in self.others:
                self.others["drives"].objects[(2, 0x1008, 0)] = b"drive"
                self.others["drives"].present.add(2)
        # Raw frames (send_frame): what was sent, the cyclic jobs by number, the
        # identifiers the configured network uses (the plugin's COB-ID map) and
        # a node that is OPERATIONAL (both need force).
        self.send_supported = True
        self.sent = []  # every frame request that was sent: {id, ext, rtr, dlc, data, forced}
        self.jobs = {}  # job -> {job, id, ext, period_ms, count, sent, peer, conn, started, reason}
        self.next_job = 1
        self.job_failure = None  # a reason that ends every cyclic job after its first frame
        self.cob_ids = {0x205: "RPDO1 of node 5", 0x185: "TPDO1 of node 5", 0x000: "NMT", 0x080: "SYNC"}
        self.operational = None  # a node ID: refuses sends and sweeps without force
        # With force_running, sdo_write and nmt (all but start) to a node
        # whose status says OPERATIONAL (state 5), and a scan while any node
        # is, need force, as the plugin asks.
        self.force_running = False
        self.forced = []  # (op, node) of every request sent with force
        # Bit rate detection: per rate (kbit/s) what the sweep hears, how many
        # rates each status poll moves on, and a refusal for the network.
        self.detect_supported = True
        self.detect_refusal = None
        self.sweep_hears = {250: {"frames": 42, "error_frames": 0, "ids": [0x705, 0x185, 0x285]},
                            500: {"frames": 0, "error_frames": 12, "ids": []}}
        self.sweep_step = 2
        self.sweep = None
        self.sweeps = []  # the detect_bitrate requests that started a sweep
        self.configured_kbit = 500
        self.configured = set()  # extra configured node IDs (NMT allowed)
        self.refuse_writes = {}
        self.delay = 0.0  # seconds before each SDO answer  # (node, index, sub): abort code for a write
        # The CiA 309-3 gateway (the cia309 op): None, an older plugin ("unknown
        # op"); "off", not configured; else the op's result.
        self.cia309 = None
        self.cia309_max = 4
        self.cia309_sessions = 0
        self.cia309_lines = []  # every line the gateway sessions sent
        self.cia309_answers = {}  # command text (after "[seq] ") -> answer text
        self.cia309_notifications = []  # sent before the next answer
        fake = self

        class Handler(socketserver.StreamRequestHandler):
            def setup(self):
                self.mode = fake_tls.accept(self)
                super().setup()

            def handle(self):
                fake.connections += 1
                fake.conns.add(self)
                try:
                    self._serve()
                finally:
                    fake.conns.discard(self)

            def _serve(self):
                if self.mode != "tls":
                    if self.mode == "plain":
                        self._send({"ok": False,
                                    "error": "this runtime needs an encrypted connection; update canworks-diag"})
                    return
                login = fake_tls.Login(fake.token)
                authed = False
                for raw in self.rfile:
                    try:
                        req = json.loads(raw)
                    except ValueError:
                        self._send({"ok": False, "error": "not a JSON object"})
                        continue
                    if not authed:
                        fake.logins.append(req)
                        if login.snonce is None:
                            first = login.hello(req)
                            if first is None:
                                return
                            self._send({"id": req.get("id"), "ok": True, "result": first})
                            continue
                        sig = login.login(req)
                        if sig is None:
                            return  # the plugin closes without an answer
                        if fake.bad_signature:
                            sig = base64.b64encode(bytes(32)).decode()
                        authed = True
                        hello = {"protocol": 2, "version": "v-test", "allow_changes": fake.allow_changes,
                                 "master_node_id": 1, "signature": sig}
                        if fake.networks is not None:
                            hello["networks"] = copy.deepcopy(fake.networks)
                        self._send({"id": req.get("id"), "ok": True, "result": hello})
                        continue
                    fake.requests.append(req)
                    if req.get("op") == "cia309":
                        if fake.cia309 is None:  # an older plugin
                            self._send({"id": req.get("id"), "ok": False, "error": "unknown op 'cia309'"})
                            continue
                        if fake.cia309 == "off":
                            self._send({"id": req.get("id"), "ok": False, "error": "cia309 gateway not configured"})
                            continue
                        if fake.cia309_sessions >= fake.cia309_max:
                            self._send({"id": req.get("id"), "ok": False, "error": "too many gateway clients"})
                            continue
                        self._send({"id": req.get("id"), "ok": True, "result": copy.deepcopy(fake.cia309)})
                        fake.cia309_sessions += 1
                        try:
                            self._gateway()
                        finally:
                            fake.cia309_sessions -= 1
                        return
                    if fake.delay and req.get("op") in ("sdo_read", "sdo_write"):
                        time.sleep(fake.delay)
                    self._send(dict(fake.answer(req, self), id=req.get("id")))
                # The plugin ends a client's cyclic jobs when it disconnects.
                for j in fake.jobs.values():
                    if j["conn"] is self and not j["reason"]:
                        fake._end_job(j, "client disconnected")

            def _send(self, obj):
                try:
                    self.wfile.write(json.dumps(obj).encode() + b"\n")
                except OSError:
                    pass

            def _gateway(self):
                # CiA 309-3 lines from here on (the cia309 op): each "[seq]
                # text" is answered from fake.cia309_answers (default "OK").
                for raw in self.rfile:
                    line = raw.decode("utf-8", "replace").strip()
                    fake.cia309_lines.append(line)
                    m = re.match(r"^\[(\d+)\]\s*(.*)$", line)
                    if not m:
                        continue
                    answer = fake.cia309_answers.get(m.group(2), "OK")
                    try:
                        for n in fake.cia309_notifications:
                            self.wfile.write(n.encode() + b"\r\n")
                        fake.cia309_notifications = []
                        self.wfile.write(("[%s] %s\r\n" % (m.group(1), answer)).encode())
                    except OSError:
                        return

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

    def outage(self):
        """The runtime goes away: no new connections, and every open one is
        cut. Serve again on the same port with `restart()`."""
        self.server.shutdown()
        self.server.server_close()
        for h in list(self.conns):
            try:
                h.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def restart(self):
        """Serves again on the same port after `outage()`."""
        self.server = type(self.server)(("127.0.0.1", self.port), self.server.RequestHandlerClass)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self.server

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

    # -- raw frames --------------------------------------------------------
    def _job_sent(self, j):
        if not j["reason"] and self.job_failure:
            j["sent"], j["reason"] = 1, self.job_failure
        if j["reason"]:
            return j["sent"]
        n = int((time.monotonic() - j["started"]) * 1000 // j["period_ms"]) + 1
        if j["count"] and n >= j["count"]:
            j["sent"] = j["count"]
            j["reason"] = "count reached"
            return j["sent"]
        return n

    def _running(self, j):
        self._job_sent(j)
        return not j["reason"]

    def _end_job(self, j, reason):
        if not j["reason"]:
            j["sent"] = self._job_sent(j)
            j["reason"] = j["reason"] or reason

    def _job_row(self, j):
        return {"job": j["job"], "id": j["id"], "ext": j["ext"], "period_ms": j["period_ms"], "sent": self._job_sent(j),
                "count": j["count"], "peer": j["peer"]}

    def _send_frame(self, req, ok, err, conn, net):
        if not self.send_supported:
            return err("unknown op '%s'" % req["op"])
        if not self.allow_changes:
            return err("changes not allowed")
        if req["op"] == "send_frame_stop":
            stopped = []
            for j in self.jobs.values():
                if j["conn"] is conn and j["net"] is net and req.get("job") in (None, j["job"]) and not j.get("collected"):
                    self._end_job(j, "stopped")
                    j["collected"] = True
                    stopped.append(dict(self._job_row(j), reason=j["reason"]))
            return ok({"stopped": stopped})
        ext, rtr = bool(req.get("ext")), bool(req.get("rtr"))
        try:
            can_id = req["can_id"] if isinstance(req.get("can_id"), int) else int(str(req.get("can_id")), 0)
        except ValueError:
            return err("field 'can_id' must be a number")
        if not 0 <= can_id <= (0x1FFFFFFF if ext else 0x7FF):
            return err("field 'can_id' must be 0x0-0x%X" % (0x1FFFFFFF if ext else 0x7FF))
        if rtr and "data" in req:
            return err("a remote frame has no data")
        data = diag.parse_hex(req["data"]) if req.get("data") else b""
        if len(data) > 8:
            return err("data must be 0-8 bytes")
        period = req.get("period_ms") or 0
        if period and not 10 <= period <= 60000:
            return err("period_ms must be 10-60000")
        if not req.get("force"):
            if can_id in self.cob_ids and not ext:
                return err("0x%X is %s; force needed" % (can_id, self.cob_ids[can_id]))
            if self.operational:
                return err("node %d is OPERATIONAL; force needed" % self.operational)
        frame = {"id": can_id, "ext": ext, "rtr": rtr, "dlc": req.get("dlc") if rtr else len(data),
                 "data": diag.hex_bytes(data), "forced": bool(req.get("force")), "network": req.get("network")}
        if not period:
            self.sent.append(frame)
            return ok({"sent": True})
        if sum(1 for j in self.jobs.values() if j["net"] is net and self._running(j)) >= 8:
            return err("too many jobs")
        job = self.next_job
        self.next_job += 1
        self.jobs[job] = {"job": job, "id": can_id, "ext": ext, "period_ms": period, "count": req.get("count"),
                          "sent": 0, "peer": "127.0.0.1", "conn": conn, "net": net, "started": time.monotonic(),
                          "reason": None, "frame": frame}
        return ok({"job": job, "period_ms": period, "count": req.get("count")})

    # -- bit rate detection -------------------------------------------------
    def _sweep_result(self):
        sw = self.sweep
        if sw is None:
            return {"running": False, "verdict": None}
        done = min(sw["total"], sw["polls"] * self.sweep_step)
        results = [dict({"bitrate_kbit": r, "frames": 0, "error_frames": 0, "ids": []}, **self.sweep_hears.get(r, {}))
                   for r in sw["rates"][:done]]
        n = len(sw["rates"])
        res = {"running": done < sw["total"], "rate_kbit": sw["rates"][done % n] if done < sw["total"] else None,
               "round": min(done // n + 1, sw["total"] // n), "done": done, "total": sw["total"], "results": results}
        if res["running"]:
            return res
        heard = [r for r in results if r["frames"]]
        matches = [r["bitrate_kbit"] for r in heard if r["error_frames"] * 100 <= r["frames"]]
        res.update(configured_kbit=self.configured_kbit, finished_at="2026-10-07T12:00:00Z", bitrate_kbit=None)
        if len(matches) == 1:
            res.update(verdict="detected", bitrate_kbit=matches[0], matches_config=matches[0] == self.configured_kbit)
        elif heard:
            best = matches or [max(heard, key=lambda r: r["frames"])["bitrate_kbit"]]
            res.update(verdict="ambiguous", candidates=best)
        else:
            res.update(verdict="silent")
        return res

    def _detect(self, req, ok, err, net):
        if not self.detect_supported:
            return err("unknown op '%s'" % req["op"])
        if req["op"] == "detect_bitrate_status":
            if self.sweep:
                self.sweep["polls"] += 1
            return ok(self._sweep_result())
        if not self.allow_changes:
            return err("changes not allowed")
        if self.sweep and self._sweep_result()["running"]:
            return ok(self._sweep_result())
        if self.detect_refusal:
            return err(self.detect_refusal)
        if self.operational and not req.get("force"):
            name = req.get("network") or (self.networks[0]["name"] if self.networks else "can0")
            return err("node %d is OPERATIONAL; CANopen on network %s would stop for the sweep; force needed"
                       % (self.operational, name))
        rates = req.get("rates") or list(diag.DETECT_RATES)
        self.sweeps.append(req)
        self.sweep = {"rates": rates, "total": len(rates) * (req.get("rounds") or 1), "polls": 0}
        return ok(self._sweep_result())

    def answer(self, req, conn=None):
        op = req.get("op")
        ok = lambda result: {"ok": True, "result": result}  # noqa: E731
        err = lambda why: {"ok": False, "error": why}  # noqa: E731
        net, why = self._pick(req)
        if why:
            return err(why)
        if op in ("trace_start", "trace_fetch", "trace_stop"):
            return self._trace(req, ok, err, net)
        if op in ("send_frame", "send_frame_stop"):
            return self._send_frame(req, ok, err, conn, net)
        if op in ("detect_bitrate", "detect_bitrate_status"):
            return self._detect(req, ok, err, net)
        info = net.info if net is not self else (self.networks[0] if self.networks else {})
        if info.get("role") == "slave":
            # A slave network serves its status and its own dictionary only.
            if op not in ("status", "sdo_read", "sdo_write"):
                return err("network \"%s\" is a slave network; %s needs a master network" % (info["name"], op))
            if op != "status" and req.get("node") != info["node_id"]:
                return err("node %s is not this slave (node ID %d); a slave network reads and writes only its own "
                           "dictionary" % (req.get("node"), info["node_id"]))
        sim = self.sim if net is self else None
        if isinstance(op, str) and op.startswith("sim_"):
            if sim is None:
                return err("nothing simulated")
            return sim.handle(req, allow_changes=self.allow_changes)
        if op == "status":
            st = copy.deepcopy(net.status)
            if sim is not None:
                st["simulated_network"] = sim.simulated_network
                conflicts = {d["node"] for d in sim.devices if d["node"] and d.get("conflict")}
                simulated = {d["node"] for d in sim.devices if d["node"]} - conflicts
                for n in st["nodes"]:
                    n["simulated"] = n["node_id"] in simulated
                    n["sim_conflict"] = n["node_id"] in conflicts
            if self.send_supported:
                st["send_jobs"] = [self._job_row(j) for j in self.jobs.values() if j["net"] is net and self._running(j)]
            if self.detect_supported:
                st["bitrate_sweep"] = {"running": bool(self.sweep and self._sweep_result()["running"])}
            return ok(st)
        if op == "emcy":
            return ok({"node_id": req["node"], "emcy": net.emcy.get(req["node"], [])})
        if op in ("sdo_write", "nmt") and not self.allow_changes:
            return err("changes not allowed")
        if req.get("force"):
            self.forced.append((op, req.get("node")))
        running = [n["node_id"] for n in net.status.get("nodes") or [] if n.get("state") == 5]
        if self.force_running and not req.get("force"):
            if (op == "sdo_write" or op == "nmt" and req.get("command") != "start") and req.get("node") in running:
                return err("node %d is OPERATIONAL; %s; force needed" % (req["node"], (
                    "an SDO write changes it while the program drives it" if op == "sdo_write" else
                    "an NMT command takes it out of the program's control")))
            if op == "scan" and running:
                return err("node %d is OPERATIONAL; a scan sends SDO requests to every node ID; force needed"
                           % running[0])
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
