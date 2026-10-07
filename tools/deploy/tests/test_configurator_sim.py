"""The configurator's simulation endpoints (/api/sim/*, add-device-simulator
tasks 8.5-8.7): the simulation file, the simulator address kept on this PC,
the proxy to the simulated devices, and expression checking."""

import json
import os
import shutil
import unittest
from unittest import mock

from openplc_canopen_deploy.configurator import simulation

from .fake_sim_page import TOKEN, FakeSim
from .test_configurator_server import RTD, Running, read, rtd_node


def sim_config(**adapter):
    adapter = dict({"type": "socketcan", "interface": "can0", "bitrate": 125000}, **adapter)
    return {"schema_version": 1, "adapter": adapter,
            "master": {"node_id": 1}, "nodes": [rtd_node()]}


class Sim(Running):
    def setUp(self):
        super().setUp()
        self.open_project()
        self.canopen = os.path.join(self.project, "canopen")
        os.makedirs(self.canopen)
        shutil.copy(os.path.join(RTD, "rtd8.eds"), self.canopen)
        self.sim_path = os.path.join(self.canopen, "simulation.json")

    def write_sim(self, doc):
        with open(self.sim_path, "w", encoding="utf-8") as f:
            json.dump(doc, f)


class File(Sim):
    def test_config_with_simulate_fields_saves(self):
        cfg = sim_config(simulate=True)
        cfg["nodes"][0]["simulate"] = False
        out = self.ok("POST", "/api/save", {"config": cfg})
        self.assertEqual(out["check"]["errors"], 0, out["check"]["items"])
        saved = json.loads(read(os.path.join(self.canopen, "canopen.json"), "r"))
        self.assertEqual(list(saved["adapter"]), ["type", "simulate", "interface", "bitrate"])
        self.assertIs(saved["nodes"][0]["simulate"], False)
        self.assertEqual(list(saved["nodes"][0])[:4], ["node_id", "name", "eds", "simulate"])

    def test_state_reads_the_simulation_file(self):
        st = self.ok("GET", "/api/state")["simulation"]
        self.assertEqual((st["exists"], st["doc"], st["error"]), (False, {"schema_version": 1}, None))
        doc = {"schema_version": 1, "nodes": {"5": {"sources": {"0x7130:1": {"constant": 3}}}}}
        self.write_sim(doc)
        st = self.ok("POST", "/api/reload")["simulation"]
        self.assertEqual((st["exists"], st["doc"]), (True, doc))
        with open(self.sim_path, "w") as f:
            f.write("{broken")
        self.assertIn("cannot be read", self.ok("POST", "/api/reload")["simulation"]["error"])

    def test_save_checks_the_schema_and_writes_only_canopen(self):
        bad = {"schema_version": 1, "nodes": {"5": {"sources": {"0x7130:1": {"sine": {"min": 1}}}}}}
        status, data, _ = self.request("POST", "/api/sim/save", {"doc": bad})
        self.assertEqual(status, 422)
        self.assertIn("nothing was saved", data["error"])
        self.assertTrue(any(p["path"].startswith("nodes.5.sources") for p in data["problems"]), data["problems"])
        self.assertFalse(os.path.exists(self.sim_path))
        doc = {"scenarios": {"a": {"steps": [{"log": "hi"}]}}, "schema_version": 1,
               "nodes": {"7": {"default_behaviour": False}, "5": {"faults": [{"heartbeat": "stop"}]}}}
        out = self.ok("POST", "/api/sim/save", {"doc": doc})
        self.assertEqual(out["written"], [self.sim_path])
        saved = json.loads(read(self.sim_path, "r"))
        self.assertEqual(list(saved), ["schema_version", "nodes", "scenarios"])
        self.assertEqual(list(saved["nodes"]), ["5", "7"])
        self.assertTrue(out["state"]["simulation"]["exists"])

    def test_save_refuses_a_file_changed_on_disk(self):
        self.ok("POST", "/api/sim/save", {"doc": {"schema_version": 1}})
        self.write_sim({"schema_version": 1, "tick_ms": 5})
        status, data, _ = self.request("POST", "/api/sim/save", {"doc": {"schema_version": 1, "tick_ms": 20}})
        self.assertEqual(status, 409)
        self.assertTrue(data["changed_on_disk"])
        self.ok("POST", "/api/sim/save", {"doc": {"schema_version": 1, "tick_ms": 20}, "overwrite": True})
        self.assertEqual(json.loads(read(self.sim_path, "r"))["tick_ms"], 20)

    def test_extra_device_eds_is_written_with_the_file(self):
        status, data, _ = self.eds(os.path.join(RTD, "rtd8.eds"), name="spare.eds")
        self.assertEqual(status, 200, data)
        self.assertIn("spare.eds", self.ok("GET", "/api/state")["sim_eds"])
        doc = {"schema_version": 1, "extra_devices": [{"node": 40, "name": "spare", "eds": "spare.eds"}]}
        out = self.ok("POST", "/api/sim/save", {"doc": doc})
        self.assertEqual(out["written"], [os.path.join(self.canopen, "spare.eds"), self.sim_path])
        state = out["state"]
        self.assertNotIn("spare.eds", state["unused_eds"])
        self.assertIn("spare.eds", state["eds"])

    def test_check(self):
        self.assertEqual(self.ok("POST", "/api/sim/check", {"doc": {"schema_version": 1}})["problems"], [])
        doc = {"scenarios": {"s": {"steps": [{"wait": {"node": 5, "object": "0x6200:1"}}, {"bogus": 1}]}}}
        problems = self.ok("POST", "/api/sim/check", {"doc": doc})["problems"]
        self.assertTrue(problems)
        self.assertTrue(all(p["path"].startswith("scenarios.s.steps[") for p in problems), problems)
        self.assertEqual(simulation.check({"schema_version": 2})[0]["path"], "schema_version")


class Settings(Sim):
    def test_address_token_and_pins_stay_on_this_pc(self):
        view = self.ok("GET", "/api/sim/settings")
        self.assertEqual(view, {"target": "runtime", "address": "127.0.0.1:7532", "token_set": False, "pins": {}})
        self.assertEqual(self.request("POST", "/api/sim/settings", {"address": "pi:x"})[0], 422)
        self.assertEqual(self.request("POST", "/api/sim/settings", {"target": "elsewhere"})[0], 422)
        self.assertEqual(self.request("POST", "/api/sim/settings", {"pins": {"5": ["nope"]}})[0], 422)
        view = self.ok("POST", "/api/sim/settings", {"target": "simulator", "address": "bench:7600", "token": "s3cret",
                                                     "pins": {"5": ["0x2000", "0x2000:0", "0x6150:2"]}})
        self.assertEqual(view, {"target": "simulator", "address": "bench:7600", "token_set": True,
                                "pins": {"5": ["0x2000:0", "0x6150:2"]}})
        settings = json.loads(read(os.path.join(self.dir, "cfg", "online.json"), "r"))["projects"][self.project]
        self.assertEqual(settings["sim_token"], "s3cret")
        for root, _, names in os.walk(self.project):
            for name in names:
                self.assertNotIn(b"s3cret", read(os.path.join(root, name)), name)
        self.assertFalse(self.ok("POST", "/api/sim/settings", {"token": ""})["token_set"])


class Live(Sim):
    def use(self, fake, standalone=False):
        if standalone:
            self.ok("POST", "/api/sim/settings", {"target": "simulator", "address": fake.address})
        else:
            self.ok("POST", "/api/online/settings", {"host": fake.address})
            self.ok("POST", "/api/online/token", {"action": "set", "token": TOKEN})

    def test_runtime_needs_online_access_settings(self):
        status, data, _ = self.request("POST", "/api/sim/poll", {})
        self.assertEqual((status, data["need"]), (409, "host"))

    def test_poll_reads_status_pdo_and_extra_objects(self):
        with FakeSim(allow_changes=False) as fake:
            self.use(fake)
            r = self.ok("POST", "/api/sim/poll", {"node": 5, "objects": ["0x2000:0", "0x7130:1"]})
            self.assertEqual((r["target"], r["standalone"], r["allow_changes"]), ("runtime", False, False))
            self.assertEqual([v["object"] for v in r["values"]], ["0x7130:1", "0x7130:2", "0x6150:1", "0x2000:0"])
            gets = fake.sent("sim_get")
            self.assertEqual(gets[0], dict(gets[0], node=5, pdo=True))
            self.assertEqual(gets[1]["items"], [{"node": 5, "object": "0x2000:0"}])
            # Without changes allowed the runtime refuses; the page shows why.
            status, data, _ = self.request("POST", "/api/sim/request",
                                           {"op": "sim_override", "node": 5, "values": {"0x7130:1": 900}})
            self.assertEqual(status, 422)
            self.assertIn("changes not allowed", data["error"])

    def test_standalone_simulator_and_requests(self):
        with FakeSim(token="", standalone=True) as fake:
            self.use(fake, standalone=True)
            r = self.ok("POST", "/api/sim/poll", {})
            self.assertEqual((r["target"], r["standalone"], r["allow_changes"]), ("simulator", True, True))
            self.assertEqual(r["values"], [])
            self.ok("POST", "/api/sim/request", {"op": "sim_fault", "node": 5, "fault": {"emcy": {"code": "0x5000"}}})
            self.assertEqual(fake.sent("sim_fault")[0]["fault"], {"emcy": {"code": "0x5000"}})
            self.assertNotIn("port", fake.sent("sim_fault")[0])
            self.assertEqual(self.request("POST", "/api/sim/request", {"op": "status"})[0], 400)

    def test_expression_checked_by_the_simulator_when_connected(self):
        with FakeSim(token="", standalone=True) as fake:
            self.use(fake, standalone=True)
            r = self.ok("POST", "/api/sim/check_expr", {"node": 5, "expr": "1 + foo", "online": True})
            self.assertEqual(r, {"checked": True, "ok": False, "error": "unknown name 'foo'", "position": 4,
                                 "by": "simulator"})
            r = self.ok("POST", "/api/sim/check_expr", {"node": 5, "expr": "1 + 2", "online": True})
            self.assertEqual((r["checked"], r["ok"]), (True, True))
        self.assertEqual(self.request("POST", "/api/sim/check_expr", {"expr": ""})[0], 400)


class Offline(Sim):
    def test_without_the_checker_module_nothing_is_claimed(self):
        with mock.patch.dict("sys.modules", {"openplc_canopen_deploy.simfile": None}):
            r = self.ok("POST", "/api/sim/check_expr", {"node": 5, "expr": "1 + foo"})
        self.assertEqual(r, {"checked": False})

    def test_with_the_checker_module(self):
        seen = []

        class Checker:
            @staticmethod
            def check_expression(text, known_devices, has_object):
                seen.append((5 in known_devices, has_object(None, "0x7130:1"), has_object(5, "0x7999:1")))
                return (4, "unknown name 'foo'") if "foo" in text else None

        self.ok("POST", "/api/save", {"config": sim_config()})
        with mock.patch.dict("sys.modules", {"openplc_canopen_deploy.simfile": Checker}):
            import openplc_canopen_deploy
            with mock.patch.object(openplc_canopen_deploy, "simfile", Checker, create=True):
                bad = self.ok("POST", "/api/sim/check_expr", {"node": 5, "expr": "1 + foo"})
                good = self.ok("POST", "/api/sim/check_expr", {"node": 5, "expr": "[0x7130:1] * 2"})
        self.assertEqual(bad, {"checked": True, "ok": False, "position": 4, "error": "unknown name 'foo'",
                               "by": "configurator"})
        self.assertEqual(good, {"checked": True, "ok": True, "by": "configurator"})
        self.assertEqual(seen[0], (True, True, False))


if __name__ == "__main__":
    unittest.main()
