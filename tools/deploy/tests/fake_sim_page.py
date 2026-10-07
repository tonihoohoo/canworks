"""A small stand-in for the simulator's control requests (docs/simulator.md,
"Control protocol") for the configurator's Simulation view tests: either the
plugin's diagnostics channel with its simulated devices (hello with
allow_changes) or a standalone openplc-canopen-sim (hello with simulator:
true). With a token it speaks TLS and the SCRAM login (fake_tls.py), without
one plain lines, on 127.0.0.1, and records every request."""

import copy
import json
import socketserver
import threading

from . import fake_tls

TOKEN = "test-token"
CHANGE_OPS = ("sim_set", "sim_override", "sim_release", "sim_source", "sim_fault", "sim_clear", "sim_scenario_start",
              "sim_scenario_stop")


class FakeSim:
    def __init__(self, token=TOKEN, allow_changes=True, standalone=False, simulated_network=False, interface="can0"):
        self.token = token
        self.allow_changes = allow_changes
        self.standalone = standalone
        self.simulated_network = simulated_network
        self.interface = interface
        self.requests = []
        self.lock = threading.Lock()
        # Devices by reference (node ID, or name for one without node ID).
        self.devices = {
            5: {"node": 5, "name": "rtd", "eds": "rtd8.eds", "profile": 404, "power": "on", "nmt": "operational",
                "conflict": False, "faults": [], "sources": {}, "overrides": {}},
        }
        # (device, object) -> (value, type); the PDO objects per device.
        self.values = {(5, "0x7130:1"): (215, "INTEGER16"), (5, "0x7130:2"): (220, "INTEGER16"),
                       (5, "0x6150:1"): (0, "UNSIGNED8"), (5, "0x2000:0"): (0, "BOOLEAN")}
        self.pdo = {5: ["0x7130:1", "0x7130:2", "0x6150:1"]}
        self.scenarios = {}  # name -> {"name", "state", "step", "message"}
        fake = self

        class Handler(socketserver.StreamRequestHandler):
            def setup(self):
                self.mode = fake_tls.accept(self)
                super().setup()

            def handle(self):
                if self.mode is None or (fake.token and self.mode != "tls"):
                    return
                login = fake_tls.Login(fake.token) if fake.token else None
                authed = False
                for raw in self.rfile:
                    try:
                        req = json.loads(raw)
                    except ValueError:
                        continue
                    if not authed:
                        hello = {"protocol": 1, "version": "v-test"}
                        if login:
                            if login.snonce is None:
                                first = login.hello(req)
                                if first is None:
                                    return
                                self._send({"id": req.get("id"), "ok": True, "result": first})
                                continue
                            sig = login.login(req)
                            if sig is None:
                                return
                            hello = {"protocol": 2, "version": "v-test", "signature": sig}
                        elif req.get("op") != "hello":
                            return
                        authed = True
                        if fake.standalone:
                            hello["simulator"] = True
                        else:
                            hello.update(allow_changes=fake.allow_changes, master_node_id=1)
                        self._send({"id": req.get("id"), "ok": True, "result": hello})
                        continue
                    with fake.lock:
                        fake.requests.append(req)
                        answer = fake.answer(req)
                    self._send(dict(answer, id=req.get("id")))

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

    def sent(self, op):
        """The requests of one op, in order."""
        with self.lock:
            return [r for r in self.requests if r.get("op") == op]

    def set_value(self, node, obj, value):
        with self.lock:
            self.values[(node, obj)] = (value, self.values[(node, obj)][1])

    def finish(self, name, state, message="", step=None):
        with self.lock:
            self.scenarios[name].update(state=state, message=message)
            if step is not None:
                self.scenarios[name]["step"] = step

    def _get(self, node, obj):
        if (node, obj) not in self.values:
            return {"node": node, "object": obj, "error": "object does not exist"}
        dev = self.devices[node]
        value, typ = self.values[(node, obj)]
        if obj in dev["overrides"]:
            value = dev["overrides"][obj]
        return {"node": node, "object": obj, "value": value, "type": typ}

    def answer(self, req):
        op = req.get("op")
        ok = lambda result=None: {"ok": True, "result": result or {}}  # noqa: E731
        err = lambda why: {"ok": False, "error": why}  # noqa: E731
        if not op.startswith("sim_"):
            return err("unknown op '%s'" % op)
        if op in CHANGE_OPS and not self.standalone and not self.allow_changes:
            return err("changes not allowed")
        node = req.get("node")
        if op not in ("sim_status", "sim_scenario_list", "sim_scenario_start", "sim_scenario_stop") \
                and "items" not in req and node not in self.devices:
            return err("node %s is not simulated" % node)
        if op == "sim_status":
            return ok({"simulated_network": self.simulated_network, "interface": self.interface,
                       "devices": copy.deepcopy(list(self.devices.values())),
                       "scenarios": copy.deepcopy(list(self.scenarios.values()))})
        if op == "sim_scenario_list":
            return ok({"scenarios": copy.deepcopy(list(self.scenarios.values()))})
        if op == "sim_get":
            if req.get("pdo"):
                return ok({"values": [self._get(node, o) for o in self.pdo.get(node, [])]})
            return ok({"values": [self._get(i["node"], i["object"]) for i in req.get("items", [])]})
        dev = self.devices.get(node)
        if op == "sim_set":
            for o, v in req["values"].items():
                self.values[(node, o)] = (v, self.values.get((node, o), (0, "INTEGER32"))[1])
            return ok()
        if op == "sim_override":
            dev["overrides"].update(req["values"])
            return ok()
        if op == "sim_release":
            if req["objects"] == "all":
                dev["overrides"].clear()
            for o in req["objects"] if isinstance(req["objects"], list) else []:
                dev["overrides"].pop(o, None)
            return ok()
        if op == "sim_source":
            if req.get("source") is None:
                dev["sources"].pop(req["object"], None)
            else:
                dev["sources"][req["object"]] = req["source"]
            return ok()
        if op == "sim_fault":
            dev["faults"].append(req["fault"])
            return ok()
        if op == "sim_clear":
            name = req["fault"]
            dev["faults"] = [] if name == "all" else [f for f in dev["faults"] if name not in f]
            return ok()
        if op == "sim_check_expr":
            expr = req.get("expr", "")
            if "foo" in expr:
                return ok({"error": "unknown name 'foo'", "position": expr.index("foo")})
            return ok({"ok": True})
        if op == "sim_scenario_start":
            name = req["name"]
            self.scenarios[name] = {"name": name, "state": "running", "step": 1, "message": ""}
            return ok()
        if op == "sim_scenario_stop":
            if req["name"] in self.scenarios:
                self.scenarios[req["name"]]["state"] = "stopped"
            return ok()
        return err("unknown op '%s'" % op)
