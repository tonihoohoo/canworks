"""A stand-in for simulated devices (docs/simulator.md, "Control protocol"):
FakeSim keeps the devices' state and answers the sim_ requests; FakePlugin
(fake_diag.py) routes them to it, and FakeSimServer serves it as a standalone
canworks-sim on 127.0.0.1. For the CLI and configurator tests.

    sim = FakeSim.example()            # nodes 5 and 7, extra device "spare"
    with FakePlugin(allow_changes=True, sim=sim) as fp: ...
    with FakeSimServer(sim) as srv: ...  # srv.address -> "127.0.0.1:PORT"

Scenarios move on by polls: every sim_status or sim_scenario_list moves each
running scenario one poll closer to its outcome (FakeSim.add_scenario).

With a machine (FakeSim(machine=FakeMachine(...)), fake_machine.py, or
sim.set_machine(machine file dict)) sim_machine answers its snapshot at the
sim's clock (seconds since it was made, or sim.clock = lambda: t), and
sim_fault / sim_clear with "machine" reach it; without one sim_machine
answers "no machine"."""

import copy
import json
import socketserver
import threading
import time

from canworks import simfile
from canworks.simclient import READ_OPS

from . import fake_machine
from . import fake_tls

FAULT_KINDS = ("emcy", "heartbeat", "power", "reset", "nmt_state", "sdo_abort", "sdo_delay",
               "refuse_write_operational", "tpdo_stop", "identity", "device_type", "forget_node_id", "drive_input")
CLEARABLE = ("emcy", "heartbeat", "power", "sdo_abort", "sdo_delay", "refuse_write_operational", "tpdo_stop",
             "identity", "device_type", "drive_input")
SOURCE_KINDS = ("constant", "sine", "triangle", "sawtooth", "square", "ramp", "steps", "random_walk", "counter",
                "csv", "expr")
INT_TYPES = ("BOOLEAN", "INTEGER8", "INTEGER16", "INTEGER32", "INTEGER64", "UNSIGNED8", "UNSIGNED16", "UNSIGNED32",
             "UNSIGNED64")


class SimRefused(Exception):
    pass


class FakeSim:
    def __init__(self, simulated_network=True, interface="simulated", machine=None):
        self.simulated_network = simulated_network
        self.interface = interface
        self.machine = machine  # a fake_machine.FakeMachine, or None
        self.machine_file = "machine.json"
        start = time.monotonic()
        self.clock = lambda: time.monotonic() - start
        self.devices = []  # dicts, see add_device
        self.scenarios = {}  # name -> dict
        self.requests = []
        self.lock = threading.Lock()

    # -- set-up -------------------------------------------------------------
    def add_device(self, node, name="", eds="", profile=0, objects=None, pdo=None, master_written=None):
        """objects: {"0xIIII:S": (value, type)}; pdo: the objects of its
        active PDOs (default: all); master_written: {"0xIIII:S": writer}."""
        d = {"node": node, "name": name, "eds": eds, "profile": profile, "power": "on", "nmt": "operational",
             "conflict": None, "faults": [], "sources": {}, "overrides": {},
             "objects": {k: {"value": v[0], "type": v[1]} for k, v in (objects or {}).items()},
             "pdo": list(pdo) if pdo is not None else list((objects or {}).keys()),
             "master_written": dict(master_written or {})}
        self.devices.append(d)
        return d

    def add_scenario(self, name, outcome="passed", message="", polls=1, steps=None, test=False, autostart=False):
        """outcome: passed, failed, or never (keeps running); polls: how many
        polls it runs before it ends."""
        self.scenarios[name] = {"name": name, "state": "idle", "step": None, "message": "", "steps": steps or [],
                                "test": test, "autostart": autostart, "outcome": outcome,
                                "outcome_message": message, "polls": polls, "left": 0}
        return self.scenarios[name]

    def set_machine(self, machine, network="motion", file="machine.json", **kw):
        """Runs a FakeMachine of a machine file (a dict) on this sim."""
        self.machine = fake_machine.FakeMachine(machine, network, **kw)
        self.machine_file = file
        return self.machine

    @classmethod
    def example(cls, simulated_network=True):
        """Node 5 (a CiA 404 sensor), node 7 (CiA 401 I/O, 0x6200:1 written
        by RPDO 1) and the extra device "spare" without a node ID; scenarios
        sensor-break (passes after 2 polls), alarm (fails) and endless."""
        sim = cls(simulated_network, "simulated" if simulated_network else "vcan0")
        sim.add_device(5, "rtd", "rtd8.eds", 404, {
            "0x7130:1": (230, "INTEGER16"), "0x7130:2": (240, "INTEGER16"), "0x6150:1": (0, "UNSIGNED8"),
            "0x1008:0": ("RTD8", "VISIBLE_STRING"), "0x2000:1": (0, "UNSIGNED32")},
            pdo=["0x7130:1", "0x7130:2", "0x6150:1"])
        sim.add_device(7, "io", "io.eds", 401, {
            "0x6200:1": (0, "UNSIGNED8"), "0x6000:1": (0, "UNSIGNED8"), "0x6411:1": (0, "INTEGER16"),
            "0x6401:1": (100, "INTEGER16")},
            pdo=["0x6200:1", "0x6000:1", "0x6401:1", "0x6411:1"],
            master_written={"0x6200:1": "RPDO 1", "0x6411:1": "RPDO 2"})
        spare = sim.add_device(0, "spare", "lss-slave.eds", 0, {"0x2000:0": (9, "UNSIGNED32")})
        spare["nmt"] = "bootup"
        sim.add_scenario("sensor-break", "passed", polls=2, test=True, steps=[{"node": 5, "set": {"0x7130:1": 900}}])
        sim.add_scenario("alarm", "failed", "step 2: expect node 7 0x6200:1 bit 2 eq 1 within 500 ms: value seen 0",
                         polls=1, test=True)
        sim.add_scenario("endless", "never")
        return sim

    # -- lookups ------------------------------------------------------------
    def device(self, node):
        for d in self.devices:
            if (isinstance(node, int) and not isinstance(node, bool) and node and d["node"] == node) or \
                    (isinstance(node, str) and d["name"] == node):
                return d
        if isinstance(node, str):
            raise SimRefused("no simulated device is named %s" % node)
        raise SimRefused("node %s is not simulated" % node)

    def value(self, node, obj):
        d = self.device(node)
        o = d["objects"].get(_key(obj))
        if _key(obj) in d["overrides"]:
            return d["overrides"][_key(obj)]
        return o["value"] if o else None

    def _object(self, d, obj):
        key = _key(obj)
        if key not in d["objects"]:
            raise SimRefused("%s has no object %s" % (_label(d), obj))
        return key, d["objects"][key]

    # -- the protocol -------------------------------------------------------
    def handle(self, req, allow_changes=True):
        """The answer to one request: {"ok": True, "result": ...} or
        {"ok": False, "error": ...}."""
        with self.lock:
            self.requests.append(req)
            op = req.get("op")
            if op not in READ_OPS and not allow_changes:
                return {"ok": False, "error": "changes not allowed"}
            fn = getattr(self, "_" + op, None) if isinstance(op, str) and op.startswith("sim_") else None
            if fn is None:
                return {"ok": False, "error": "unknown op '%s'" % op}
            try:
                return {"ok": True, "result": fn(req)}
            except SimRefused as e:
                return {"ok": False, "error": str(e)}
            except (KeyError, TypeError, ValueError, AttributeError) as e:
                return {"ok": False, "error": "bad request: %s" % e}

    def _tick(self):
        for s in self.scenarios.values():
            if s["state"] == "running" and s["outcome"] != "never":
                s["left"] -= 1
                s["step"] = (s["step"] or 0) + 1
                if s["left"] <= 0:
                    s["state"], s["message"], s["step"] = s["outcome"], s["outcome_message"], None

    def _scenario_list(self):
        return [{k: s[k] for k in ("name", "state", "step", "message")} for s in self.scenarios.values()]

    def _public(self, d):
        out = {k: copy.deepcopy(d[k]) for k in ("node", "name", "eds", "profile", "power", "nmt", "conflict",
                                                "faults", "sources", "overrides")}
        return out

    def _sim_status(self, req):
        self._tick()
        res = {"simulated_network": self.simulated_network, "interface": self.interface,
               "devices": [self._public(d) for d in self.devices], "scenarios": self._scenario_list()}
        if self.machine is not None:
            res["machine"] = {"name": self.machine.m.get("name", ""), "file": self.machine_file,
                              "faults": self.machine.faults()}
        return res

    def _sim_machine(self, req):
        if self.machine is None:
            raise SimRefused("no machine")
        return self.machine.snapshot(self.clock())

    def _machine_request(self, req, op):
        """sim_fault / sim_clear on a machine element (sim_engine.cpp)."""
        el = req["machine"]
        if not isinstance(el, str) or not el:
            raise SimRefused("\"machine\" must name a machine element")
        if self.machine is None:
            raise SimRefused("this network has no machine")
        try:
            if op == "fault":
                self.machine.fault(el, req.get("fault"), self.clock())
            else:
                if not isinstance(req.get("fault"), str):
                    raise SimRefused("\"fault\" must be a machine fault name or \"all\"")
                self.machine.clear(el, req["fault"], self.clock())
        except fake_machine.FakeMachineError as e:
            raise SimRefused(str(e))
        return {}

    def _sim_scenario_list(self, req):
        self._tick()
        return {"scenarios": self._scenario_list()}

    def _sim_get(self, req):
        values = []
        if req.get("pdo"):
            d = self.device(req["node"])
            items = [{"node": req["node"], "object": o} for o in d["pdo"]]
        else:
            items = req["items"]
        for it in items:
            try:
                d = self.device(it["node"])
                key, o = self._object(d, it["object"])
                v = d["overrides"].get(key, o["value"])
                values.append({"node": it["node"], "object": it["object"], "value": v, "type": o["type"]})
            except SimRefused as e:
                values.append({"node": it["node"], "object": it["object"], "error": str(e)})
        return {"values": values}

    def _check_values(self, d, values):
        if not isinstance(values, dict) or not values:
            raise SimRefused("values: give object -> value")
        out = {}
        for obj, v in values.items():
            key, o = self._object(d, obj)
            if o["type"] == "VISIBLE_STRING" and not isinstance(v, str):
                raise SimRefused("%s %s is a VISIBLE_STRING; give a string" % (_label(d), obj))
            if o["type"] != "VISIBLE_STRING" and isinstance(v, str):
                raise SimRefused("%s %s takes a number, not %r" % (_label(d), obj, v))
            if o["type"] in INT_TYPES and isinstance(v, float):
                v = int(round(v))
            out[key] = v
        return out

    def _sim_set(self, req):
        d = self.device(req["node"])
        for key, v in self._check_values(d, req["values"]).items():
            d["objects"][key]["value"] = v
        return {}

    def _sim_override(self, req):
        d = self.device(req["node"])
        d["overrides"].update(self._check_values(d, req["values"]))
        return {}

    def _sim_release(self, req):
        d = self.device(req["node"])
        objects = req["objects"]
        if objects == "all":
            d["overrides"].clear()
        else:
            for obj in objects:
                d["overrides"].pop(self._object(d, obj)[0], None)
        return {}

    def _sim_source(self, req):
        d = self.device(req["node"])
        key, o = self._object(d, req["object"])
        src = req.get("source")
        if src is None:
            d["sources"].pop(key, None)
            return {}
        if not isinstance(src, dict):
            raise SimRefused("a source is an object with one type key")
        kinds = [k for k in src if k in SOURCE_KINDS]
        if len(kinds) != 1 or set(src) - set(SOURCE_KINDS) - {"noise", "tick_ms"}:
            raise SimRefused("a source has exactly one of %s" % ", ".join(SOURCE_KINDS))
        if key in d["master_written"]:
            raise SimRefused("%s %s is written by the master (%s); use an override" % (_label(d), key,
                                                                                    d["master_written"][key]))
        if o["type"] == "VISIBLE_STRING" and kinds[0] != "constant":
            raise SimRefused("%s %s is a VISIBLE_STRING, which takes only a constant" % (_label(d), key))
        if kinds[0] == "expr":
            res = self._check(d, src["expr"])
            if not res["ok"]:
                raise SimRefused("expression, position %d: %s" % (res["position"], res["error"]))
        d["sources"][key] = src
        return {}

    def _sim_fault(self, req):
        if "machine" in req:
            return self._machine_request(req, "fault")
        d = self.device(req["node"])
        f = req["fault"]
        kinds = [k for k in f if k in FAULT_KINDS] if isinstance(f, dict) else []
        if len(kinds) != 1 or set(f) - set(FAULT_KINDS) - {"off_ms"}:
            raise SimRefused("a fault has exactly one of %s" % ", ".join(FAULT_KINDS))
        kind = kinds[0]
        if kind == "power":
            d["power"] = "off" if f["power"] == "off" else "on"
            if f["power"] == "off":
                d["faults"].append(copy.deepcopy(f))
            return {}
        if kind == "nmt_state":
            d["nmt"] = f["nmt_state"]
            return {}
        if kind == "reset":
            d["nmt"] = "preop"
            return {}
        if kind in ("sdo_abort", "sdo_delay") and isinstance(f[kind], dict) and "object" in f[kind]:
            self._object(d, f[kind]["object"])
        d["faults"].append(copy.deepcopy(f))
        return {}

    def _sim_clear(self, req):
        if "machine" in req:
            return self._machine_request(req, "clear")
        d = self.device(req["node"])
        kind = req["fault"]
        if kind == "all":
            d["faults"] = []
            d["power"] = "on"
            return {}
        if kind not in CLEARABLE:
            raise SimRefused("%s cannot be cleared (clearable: all, %s)" % (kind, ", ".join(CLEARABLE)))

        def keep(f):
            if kind not in f:
                return True
            if kind == "sdo_abort" and req.get("object") is not None:
                return _key(f["sdo_abort"].get("object", "")) != _key(req["object"])
            if kind == "tpdo_stop" and req.get("tpdo") is not None:
                return f["tpdo_stop"] != req["tpdo"]
            return False

        d["faults"] = [f for f in d["faults"] if keep(f)]
        if kind == "power":
            d["power"] = "on"
        return {}

    def _sim_scenario_start(self, req):
        name = req["name"]
        if req.get("scenario") is not None:
            self.add_scenario(name, "passed", steps=req["scenario"].get("steps"))
        s = self.scenarios.get(name)
        if s is None:
            raise SimRefused("no scenario %s" % name)
        if s["state"] == "running":
            raise SimRefused("scenario %s is already running" % name)
        s.update(state="running", step=0, message="", left=s["polls"])
        return {}

    def _sim_scenario_stop(self, req):
        s = self.scenarios.get(req["name"])
        if s is None:
            raise SimRefused("no scenario %s" % req["name"])
        if s["state"] == "running":
            s.update(state="stopped", step=None, message="stopped")
        return {}

    def _check(self, own, text):
        def resolve(dev, index, sub):
            if dev is None:
                d = own
            else:
                try:
                    d = self.device(dev)
                except SimRefused:
                    return "unknown device %s" % dev
            if simfile.object_key(index, sub) not in d["objects"]:
                return "%s: object %s is not in its EDS" % (_label(d), simfile.object_key(index, sub))
            return None
        try:
            simfile.parse(text, resolve)
        except simfile.ExprError as e:
            return {"ok": False, "error": e.message, "position": e.position}
        return {"ok": True}

    def _sim_check_expr(self, req):
        return self._check(self.device(req["node"]), req["expr"])


def _key(obj):
    return simfile.object_key(*simfile.parse_object(obj))


def _label(d):
    return "node %d" % d["node"] if d["node"] else "device %s" % d["name"]


class FakeSimServer:
    """FakeSim as a standalone simulator's control channel: the hello is
    needed only with a token, and changes need no allow_changes."""

    def __init__(self, sim, token=None):
        self.sim = sim
        self.token = token
        fake = self

        class Handler(socketserver.StreamRequestHandler):
            def setup(self):
                self.mode = fake_tls.accept(self)
                super().setup()

            def handle(self):
                # With a token: TLS and the SCRAM login; without: plain.
                if self.mode is None:
                    return
                if fake.token and self.mode != "tls":
                    self._send({"ok": False, "error": "this simulator needs an encrypted connection; "
                                                      "update canworks-diag"})
                    return
                login = fake_tls.Login(fake.token) if fake.token else None
                authed = not fake.token
                for raw in self.rfile:
                    try:
                        req = json.loads(raw)
                    except ValueError:
                        self._send({"ok": False, "error": "not a JSON object"})
                        continue
                    if not authed:
                        if login.snonce is None:
                            first = login.hello(req)
                            if first is None:
                                return
                            self._send({"id": req.get("id"), "ok": True, "result": first})
                            continue
                        sig = login.login(req)
                        if sig is None:
                            return
                        authed = True
                        self._send({"id": req.get("id"), "ok": True,
                                    "result": {"protocol": 2, "version": "v-test", "simulator": True,
                                               "signature": sig}})
                        continue
                    if req.get("op") == "hello":
                        self._send({"id": req.get("id"), "ok": True,
                                    "result": {"protocol": 1, "version": "v-test", "simulator": True}})
                        continue
                    self._send(dict(fake.sim.handle(req, allow_changes=True), id=req.get("id")))

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

    @property
    def address(self):
        return "127.0.0.1:%d" % self.port
