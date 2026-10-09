"""canworks-diag sim against the fake plugin and the fake standalone
simulator (canopen-online-diagnostics: simulator commands)."""

import contextlib
import io
import json
import os
import unittest
import xml.etree.ElementTree as ET
from unittest import mock

from canworks import diag, simcli

from .fake_diag import TOKEN, FakePlugin, closed_port
from .fake_sim import FakeSim, FakeSimServer
from .helpers import tmpdir


def run(*argv, token=TOKEN):
    """diag.main as the command runs it: (exit code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    env = {diag.TOKEN_ENV: token} if token else {}
    with mock.patch.dict(os.environ, env), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
            mock.patch.object(simcli, "POLL_S", 0.01):
        if not token:
            os.environ.pop(diag.TOKEN_ENV, None)
        code = diag.main(list(argv))
    return code, out.getvalue(), err.getvalue()


def parse(*argv):
    return diag.parser().parse_args(["sim"] + list(argv))


class Arguments(unittest.TestCase):
    def fault(self, *argv):
        return simcli.fault_object(parse("fault", "5", *argv))

    def test_fault_kinds(self):
        self.assertEqual(self.fault("emcy", "0x5000", "--register", "1", "--msef", "0100000000", "--period-ms", "500"),
                         {"emcy": {"code": 0x5000, "register": 1, "msef": "0100000000", "period_ms": 500}})
        self.assertEqual(self.fault("emcy", "0x8130"), {"emcy": {"code": 0x8130}})
        self.assertEqual(self.fault("heartbeat-stop"), {"heartbeat": "stop"})
        self.assertEqual(self.fault("power", "off"), {"power": "off"})
        self.assertEqual(self.fault("power", "cycle", "--off-ms", "2000"), {"power": "cycle", "off_ms": 2000})
        self.assertEqual(self.fault("reset", "comm"), {"reset": "comm"})
        self.assertEqual(self.fault("nmt", "preop"), {"nmt_state": "preop"})
        self.assertEqual(self.fault("sdo-abort", "0x2000:1", "0x08000020", "--on", "write", "--count", "1"),
                         {"sdo_abort": {"object": "0x2000:1", "code": 0x08000020, "on": "write", "count": 1}})
        self.assertEqual(self.fault("sdo-delay", "1500", "--object", "0x1008"),
                         {"sdo_delay": {"ms": 1500, "object": "0x1008:0"}})
        self.assertEqual(self.fault("refuse-write-operational"), {"refuse_write_operational": True})
        self.assertEqual(self.fault("tpdo-stop", "2"), {"tpdo_stop": 2})
        self.assertEqual(self.fault("identity", "--product-code", "0x99", "--serial-number", "7"),
                         {"identity": {"product_code": 0x99, "serial_number": 7}})
        self.assertEqual(self.fault("device-type", "0x20192"), {"device_type": 0x20192})
        self.assertEqual(self.fault("forget-node-id"), {"forget_node_id": True})
        self.assertEqual(self.fault("drive-input", "--blocked", "--no-home-switch"),
                         {"drive_input": {"blocked": True, "home_switch": False}})
        self.assertEqual(self.fault("json", '{"heartbeat": "stop"}'), {"heartbeat": "stop"})

    def test_fault_usage_errors(self):
        for argv in (("identity",), ("drive-input",), ("power", "on", "--off-ms", "10"),
                     ("emcy", "0x5000", "--register", "0x100"), ("emcy", "1", "--period-ms", "5")):
            with self.assertRaises(diag.DiagError, msg=argv) as cm:
                self.fault(*argv)
            self.assertEqual(cm.exception.kind, "usage")
        err = io.StringIO()
        for argv in (("emcy", "0x5000", "--msef", "01"), ("tpdo-stop", "513"), ("json", "[1]"), ("power", "half")):
            with contextlib.redirect_stderr(err), self.assertRaises(SystemExit, msg=argv):
                self.fault(*argv)

    def test_values_devices_objects(self):
        self.assertEqual(simcli.value("450"), 450)
        self.assertEqual(simcli.value("0x1F"), 31)
        self.assertEqual(simcli.value("-3.5"), -3.5)
        self.assertEqual(simcli.value("010"), 10)
        self.assertEqual(simcli.value("true"), 1)
        self.assertEqual(simcli.value("RTD8"), "RTD8")
        self.assertEqual(simcli.device("5"), 5)
        self.assertEqual(simcli.device("spare"), "spare")
        self.assertEqual(simcli.obj("6200:1"), "0x6200:1")
        self.assertEqual(simcli.obj("0x1008"), "0x1008:0")
        args = parse("set", "5", "0x7130:1", "450", "--runtime", "plc.local", "--json")
        self.assertEqual((args.runtime, args.json, args.value), ("plc.local", True, 450))
        args = diag.parser().parse_args(["--runtime", "plc.local", "sim", "status"])
        self.assertEqual(args.runtime, "plc.local")


class Runtime(unittest.TestCase):
    def test_status_and_get(self):
        with FakePlugin(sim=FakeSim.example()) as fp:
            code, out, err = run("sim", "status", "--runtime", fp.runtime)
            self.assertEqual(code, 0, err)
            self.assertIn("simulated network: no CAN interface is used", out)
            self.assertIn("rtd", out)
            self.assertIn("sensor-break", out)
            code, out, err = run("--runtime", fp.runtime, "sim", "get", "5", "0x7130:1", "0x6999:1")
            self.assertEqual(code, 0, err)
            self.assertIn("node 5 0x7130:1 = 230 (INTEGER16)", out)
            self.assertIn("node 5 0x6999:1: node 5 has no object 0x6999:1", out)
            code, out, err = run("--runtime", fp.runtime, "--json", "sim", "get", "5", "--pdo")
            self.assertEqual([v["object"] for v in json.loads(out)["values"]], ["0x7130:1", "0x7130:2", "0x6150:1"])
            code, out, err = run("--runtime", fp.runtime, "sim", "get", "spare", "0x2000")
            self.assertIn("node spare 0x2000:0 = 9", out)
            # The plugin's own status names what is simulated.
            code, out, err = run("--runtime", fp.runtime, "status")
            self.assertIn("simulated network: no CAN interface is used; no node is simulated", out)

    def test_status_of_a_mixed_network(self):
        sim = FakeSim(simulated_network=False, interface="vcan0")
        sim.add_device(2, "pingpong", "cpp-slave.eds", 0, {"0x2000:0": (0, "UNSIGNED32")})
        with FakePlugin(sim=sim) as fp:
            code, out, err = run("--runtime", fp.runtime, "status")
            self.assertIn("simulated devices on this network: node 2", out)
            code, out, err = run("--runtime", fp.runtime, "--json", "status")
            nodes = {n["node_id"]: n["simulated"] for n in json.loads(out)["nodes"]}
            self.assertEqual(nodes, {2: True, 23: False})

    def test_status_with_a_node_id_conflict(self):
        # Node 23 is marked simulated, but a real node 23 is on the bus.
        sim = FakeSim(simulated_network=False, interface="vcan0")
        sim.add_device(23, "io", "cpp-slave.eds", 0, {"0x2000:0": (0, "UNSIGNED32")})
        sim.devices[-1]["conflict"] = True
        with FakePlugin(sim=sim) as fp:
            code, out, err = run("--runtime", fp.runtime, "status")
            self.assertIn("node 23: marked simulated, but a device on the bus already uses node ID 23", out)
            code, out, err = run("--runtime", fp.runtime, "--json", "status")
            n23 = [n for n in json.loads(out)["nodes"] if n["node_id"] == 23][0]
            self.assertEqual((n23["simulated"], n23["sim_conflict"]), (False, True))

    def test_several_networks(self):
        # The fake simulates on its first network, io; drives simulates nothing.
        nets = [{"name": "io", "interface": "can0", "bitrate": 250000, "master_node_id": 1},
                {"name": "drives", "interface": "can1", "bitrate": 500000, "master_node_id": 1}]
        with FakePlugin(networks=nets, sim=FakeSim.example()) as fp:
            code, out, err = run("sim", "status", "--runtime", fp.runtime)
            self.assertEqual(code, 1)
            self.assertIn("give --network NAME", err)
            self.assertIn("io, drives", err)
            code, out, err = run("sim", "status", "--runtime", fp.runtime, "--network", "io")
            self.assertEqual(code, 0, err)
            self.assertIn("rtd", out)
            self.assertEqual(fp.requests[-1].get("network"), "io")
            code, out, err = run("sim", "status", "--runtime", fp.runtime, "--network", "drives")
            self.assertEqual(code, 1)
            self.assertIn("nothing simulated", err)
            code, out, err = run("sim", "status", "--runtime", fp.runtime, "--network", "axes")
            self.assertEqual(code, 1)
            self.assertIn("no network 'axes'", err)

    def test_nothing_simulated(self):
        with FakePlugin() as fp:
            code, out, err = run("sim", "status", "--runtime", fp.runtime)
            self.assertEqual(code, 1)
            self.assertIn("nothing simulated", err)

    def test_changes_need_allow_changes(self):
        with FakePlugin(sim=FakeSim.example()) as fp:
            code, out, err = run("sim", "get", "5", "0x7130:1", "--runtime", fp.runtime)
            self.assertEqual(code, 0, err)
            code, out, err = run("sim", "fault", "5", "emcy", "0x5000", "--runtime", fp.runtime)
            self.assertEqual(code, 1)
            self.assertIn("changes not allowed", err)

    def test_changes(self):
        sim = FakeSim.example()
        with FakePlugin(allow_changes=True, sim=sim) as fp:
            rt = ("--runtime", fp.runtime)
            code, out, err = run("sim", "fault", "5", "emcy", "0x5000", "--register", "1", *rt)
            self.assertEqual(code, 0, err)
            self.assertEqual(out, "node 5: fault emcy 0x5000 register 1\n")
            self.assertEqual(fp.requests[-1], {"op": "sim_fault", "id": fp.requests[-1]["id"], "node": 5,
                                               "fault": {"emcy": {"code": 0x5000, "register": 1}}})
            code, out, err = run("sim", "set", "5", "0x7130:1", "450", *rt)
            self.assertEqual((code, out), (0, "node 5 0x7130:1 set to 450\n"), err)
            self.assertEqual(sim.value(5, "0x7130:1"), 450)
            code, out, err = run("sim", "override", "5", "0x7130:1", "1500", *rt)
            self.assertEqual(sim.value(5, "0x7130:1"), 1500)
            code, out, err = run("sim", "release", "5", *rt)
            self.assertEqual(out, "node 5: all overrides released\n")
            self.assertEqual(fp.requests[-1]["objects"], "all")
            self.assertEqual(sim.value(5, "0x7130:1"), 450)
            code, out, err = run("sim", "fault", "5", "sdo-abort", "0x2000:1", "0x08000020", *rt)
            code, out, err = run("sim", "clear", "5", "sdo-abort", "--object", "0x2000:1", *rt)
            self.assertEqual((code, out), (0, "node 5: sdo-abort 0x2000:1 cleared\n"), err)
            self.assertEqual(fp.requests[-1]["fault"], "sdo_abort")
            self.assertEqual(fp.requests[-1]["object"], "0x2000:1")
            self.assertEqual([list(f) for f in sim.devices[0]["faults"]], [["emcy"]])
            code, out, err = run("sim", "clear", "5", "all", *rt)
            self.assertEqual(sim.devices[0]["faults"], [])
            # A value source on an object the master writes is refused, naming the writer.
            code, out, err = run("sim", "source", "7", "0x6200:1", '{"constant": 1}', *rt)
            self.assertEqual(code, 1)
            self.assertIn("RPDO 1", err)
            code, out, err = run("sim", "source", "7", "0x6000:1", '{"expr": "[0x6200:1] + [5/0x7130:1]"}', *rt)
            self.assertEqual(code, 0, err)
            code, out, err = run("sim", "source", "7", "0x6401:1", '{"expr": "[0x6999:1]"}', *rt)
            self.assertIn("position 0", err)
            code, out, err = run("sim", "source", "7", "0x6000:1", "none", *rt)
            self.assertEqual(out, "node 7 0x6000:1: value source removed\n")
            self.assertIsNone(fp.requests[-1]["source"])
            code, out, err = run("sim", "fault", "9", "power", "off", *rt)
            self.assertIn("node 9 is not simulated", err)


class Standalone(unittest.TestCase):
    def test_commands_on_a_standalone_simulator(self):
        sim = FakeSim.example()
        with FakeSimServer(sim) as srv:
            code, out, err = run("sim", "--sim", srv.address, "fault", "5", "power", "cycle", "--off-ms", "2000",
                                 token=None)
            self.assertEqual((code, out), (0, "node 5: fault power cycle off-ms 2000\n"), err)
            code, out, err = run("sim", "scenario", "list", "--sim", srv.address, token=None)
            self.assertIn("sensor-break", out)
            self.assertIn("idle", out)
            code, out, err = run("sim", "scenario", "start", "endless", "--sim", srv.address, token=None)
            self.assertEqual((code, out), (0, "scenario endless started\n"), err)
            code, out, err = run("sim", "scenario", "stop", "endless", "--sim", srv.address, token=None)
            self.assertEqual(sim.scenarios["endless"]["state"], "stopped")
            code, out, err = run("sim", "scenario", "start", "nope", "--sim", srv.address, token=None)
            self.assertEqual(code, 1)
            self.assertIn("no scenario nope", err)

    def test_token_file(self):
        d = tmpdir(self)
        path = os.path.join(d, "token")
        with open(path, "w") as f:
            f.write("sim-secret\n")
        with FakeSimServer(FakeSim.example(), token="sim-secret") as srv:
            code, out, err = run("sim", "status", "--sim", srv.address, "--token-file", path, token=None)
            self.assertEqual(code, 0, err)
            code, out, err = run("sim", "status", "--sim", srv.address, token=None)
            self.assertEqual(code, 1)

    def test_runtime_and_sim_together(self):
        code, out, err = run("sim", "status", "--sim", "127.0.0.1", "--runtime", "127.0.0.1", token=None)
        self.assertEqual(code, 2)
        self.assertIn("not both", err)

    def test_no_simulator(self):
        code, out, err = run("sim", "status", "--sim", "127.0.0.1:%d" % closed_port(), token=None)
        self.assertEqual(code, 1)
        self.assertIn("no simulator listens", err)


class Test(unittest.TestCase):
    def setUp(self):
        self.dir = tmpdir(self)
        self.junit = os.path.join(self.dir, "results.xml")

    def test_passing_scenario(self):
        with FakePlugin(allow_changes=True, sim=FakeSim.example()) as fp:
            code, out, err = run("sim", "test", "--scenario", "sensor-break", "--junit", self.junit,
                                 "--runtime", fp.runtime)
        self.assertEqual(code, 0, err)
        self.assertRegex(out, r"PASS    sensor-break \(\d+\.\d s\)\n1 of 1 scenario passed\n")
        suite = ET.parse(self.junit).getroot().find("testsuite")
        self.assertEqual((suite.get("tests"), suite.get("failures")), ("1", "0"))
        self.assertEqual(suite.find("testcase").get("name"), "sensor-break")

    def test_failing_and_timed_out_scenarios(self):
        with FakeSimServer(FakeSim.example()) as srv:
            code, out, err = run("sim", "test", "--all", "--timeout", "0.5", "--junit", self.junit,
                                 "--sim", srv.address, token=None)
        self.assertEqual(code, 1, err)
        lines = out.splitlines()
        self.assertTrue(lines[0].startswith("PASS    sensor-break"), out)
        self.assertTrue(lines[1].startswith("FAIL    alarm"), out)
        self.assertIn("value seen 0", lines[1])
        self.assertTrue(lines[2].startswith("TIMEOUT endless"), out)
        self.assertEqual(lines[3], "1 of 3 scenarios passed")
        root = ET.parse(self.junit).getroot()
        suite = root.find("testsuite")
        self.assertEqual((suite.get("tests"), suite.get("failures"), suite.get("skipped")), ("3", "2", "0"))
        cases = {c.get("name"): c for c in suite.findall("testcase")}
        self.assertIsNone(cases["sensor-break"].find("failure"))
        self.assertIn("value seen 0", cases["alarm"].find("failure").get("message"))
        self.assertEqual(cases["endless"].find("failure").get("type"), "timeout")

    def test_parallel_and_json(self):
        with FakeSimServer(FakeSim.example()) as srv:
            code, out, err = run("--json", "sim", "test", "--parallel", "--scenario", "sensor-break",
                                 "--scenario", "alarm", "--sim", srv.address, token=None)
        self.assertEqual(code, 1, err)
        res = json.loads(out)
        self.assertEqual((res["passed"], res["total"]), (1, 2))
        self.assertEqual([s["state"] for s in res["scenarios"]], ["passed", "failed"])

    def test_usage_and_connection_errors_exit_2(self):
        with FakeSimServer(FakeSim.example()) as srv:
            code, out, err = run("sim", "test", "--sim", srv.address, token=None)
            self.assertEqual(code, 2)
            self.assertIn("--scenario NAME", err)
            code, out, err = run("sim", "test", "--scenario", "nope", "--sim", srv.address, token=None)
            self.assertEqual(code, 2)
            self.assertIn("no scenario nope; the simulation has: sensor-break, alarm, endless", err)
        code, out, err = run("sim", "test", "--all", "--sim", "127.0.0.1:%d" % closed_port(), token=None)
        self.assertEqual(code, 2)
        with FakePlugin(sim=FakeSim.example()) as fp:  # read-only token: the scenario cannot start
            code, out, err = run("sim", "test", "--all", "--runtime", fp.runtime)
            self.assertEqual(code, 2)
            self.assertIn("changes not allowed", err)


if __name__ == "__main__":
    unittest.main()
