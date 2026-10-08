"""The configurator's machine endpoints (add-machine-sim task 3.2): the
machine file of a network's section for the Machine view offline, the live
sim_machine answer over the kept-open connection, machine faults through
/api/sim/request, and machine file problems with the simulation file's."""

import json
import os
import shutil
import unittest

from openplc_canopen_deploy.configurator import simulation

from . import fake_sim_page
from .fake_diag import TOKEN, FakePlugin
from .fake_machine import FakeMachine
from .fake_sim import FakeSim
from .helpers import REPO
from .test_configurator_server import Running

EXAMPLE = os.path.join(REPO, "examples", "gantry-cell", "canopen")
SIM = {"schema_version": 2, "networks": {"motion": {"machine": "machine.json"}}}


class Machine(Running):
    """The project holds the gantry-cell example's config, EDS and machine files."""

    def setUp(self):
        super().setUp()
        self.open_project()
        self.canopen = os.path.join(self.project, "canopen")
        shutil.rmtree(self.canopen, ignore_errors=True)
        shutil.copytree(EXAMPLE, self.canopen)
        self.sim_path = os.path.join(self.canopen, "simulation.json")
        if os.path.exists(self.sim_path):
            os.remove(self.sim_path)
        with open(os.path.join(EXAMPLE, "machine.json"), encoding="utf-8") as f:
            self.machine = json.load(f)
        self.ok("POST", "/api/reload")

    def write(self, name, doc):
        with open(os.path.join(self.canopen, name), "w", encoding="utf-8") as f:
            json.dump(doc, f)

    def use(self, fake, standalone=False):
        if standalone:
            self.ok("POST", "/api/sim/settings", {"target": "simulator", "address": fake.address})
        else:
            self.ok("POST", "/api/online/settings", {"host": fake.address if hasattr(fake, "address") else
                                                     fake.runtime})
            self.ok("POST", "/api/online/token", {"action": "set", "token": TOKEN})


class Offline(Machine):
    def test_machine_file_of_the_section(self):
        self.write("simulation.json", SIM)
        r = self.ok("GET", "/api/sim/machine?network=motion")
        self.assertEqual(r, {"network": "motion", "file": "machine.json", "machine": self.machine, "problems": []})

    def test_no_machine(self):
        r = self.ok("GET", "/api/sim/machine?network=motion")
        self.assertEqual(r, {"network": "motion", "file": None, "machine": None, "problems": []})
        self.write("simulation.json", {"schema_version": 1, "tick_ms": 5})
        self.assertIsNone(self.ok("GET", "/api/sim/machine?network=motion")["machine"])
        self.write("simulation.json", {"schema_version": 2, "networks": {"motion": {"nodes": {}}}})
        r = self.ok("GET", "/api/sim/machine?network=motion")
        self.assertEqual((r["file"], r["machine"]), (None, None))
        self.write("simulation.json", SIM)
        self.assertIsNone(self.ok("GET", "/api/sim/machine?network=other")["machine"])

    def test_problems(self):
        self.machine["joints"]["x"]["node"] = 10
        self.write("machine.json", self.machine)
        self.write("simulation.json", SIM)
        r = self.ok("GET", "/api/sim/machine?network=motion")
        self.assertEqual(r["machine"]["joints"]["x"]["node"], 10)  # drawn anyway
        self.assertEqual([p["path"] for p in r["problems"]], ["networks.motion.machine"])
        self.assertIn("joint x: node 10 (io) has no `axis`", r["problems"][0]["message"])
        self.assertNotIn(self.sim_path, r["problems"][0]["message"])

    def test_missing_or_broken_file(self):
        self.write("simulation.json", {"schema_version": 2, "networks": {"motion": {"machine": "cell.json"}}})
        r = self.ok("GET", "/api/sim/machine?network=motion")
        self.assertEqual((r["file"], r["machine"]), ("cell.json", None))
        self.assertIn("network motion: machine cell.json: machine file", r["problems"][0]["message"])
        self.assertIn("not found", r["problems"][0]["message"])
        with open(os.path.join(self.canopen, "cell.json"), "w") as f:
            f.write("{no")
        r = self.ok("GET", "/api/sim/machine?network=motion")
        self.assertIsNone(r["machine"])
        self.assertIn("not valid JSON", r["problems"][0]["message"])

    def test_problems_with_the_simulation_file_problems(self):
        doc = {"schema_version": 2, "networks": {"motion": {"machine": "cell.json", "scenarios": {"t": {"steps": [
            {"machine": "z", "fault": {"jam": True}}]}}}}}
        problems = self.ok("POST", "/api/sim/check", {"doc": doc})["problems"]
        self.assertEqual([p["path"] for p in problems], ["networks.motion.machine"])
        self.assertIn("cell.json", problems[0]["message"])
        doc["networks"]["motion"]["machine"] = "machine.json"
        doc["networks"]["motion"]["scenarios"]["t"]["steps"].append({"wait": {"machine": "plcaed", "ge": 1}})
        problems = self.ok("POST", "/api/sim/check", {"doc": doc})["problems"]
        self.assertEqual([p["path"] for p in problems], ["networks.motion.scenarios.t.steps[1].wait.machine"])
        self.assertIn("the machine has no value \"plcaed\"", problems[0]["message"])
        # Schema problems first; the machine is checked once the file passes the schema.
        doc["networks"]["motion"]["machine"] = 3
        self.assertEqual(self.ok("POST", "/api/sim/check", {"doc": doc})["problems"], simulation.check(doc))

    def test_saved_section_keeps_machine_first(self):
        doc = {"schema_version": 2, "networks": {"motion": {"scenarios": {"t": {"steps": [{"log": "x"}]}},
                                                            "machine": "machine.json"}}}
        self.ok("POST", "/api/sim/save", {"doc": doc})
        with open(self.sim_path, encoding="utf-8") as f:
            self.assertEqual(list(json.load(f)["networks"]["motion"]), ["machine", "scenarios"])

    def test_sim_machine_is_a_page_request(self):
        self.assertIn("sim_machine", simulation.OPS)


class Live(Machine):
    def test_answer_over_the_kept_open_connection(self):
        sim = FakeSim.example()
        sim.set_machine(self.machine)
        with FakePlugin(allow_changes=False, sim=sim) as fp:
            self.use(fp)
            first = self.ok("POST", "/api/sim/machine", {"network": "motion"})
            self.assertEqual((first["target"], first["standalone"], first["allow_changes"]),
                             ("runtime", False, False))
            self.assertIn("hello", first)
            self.assertEqual(set(first["machine"]["joints"]), {"x", "y", "z"})
            seqs = [self.ok("POST", "/api/sim/machine", {"network": "motion"})["machine"]["seq"] for _ in range(5)]
            self.assertEqual(seqs, sorted(seqs))
            self.assertEqual(fp.connections, 1)
            self.ok("POST", "/api/sim/poll", {})
            self.assertEqual(fp.connections, 1)  # the poll shares it

    def test_runtime_without_a_machine(self):
        with FakePlugin(sim=FakeSim.example()) as fp:
            self.use(fp)
            status, data, _ = self.request("POST", "/api/sim/machine", {"network": "motion"})
            self.assertEqual(status, 422)
            self.assertIn("no machine", data["error"])

    def test_machine_faults_through_request(self):
        machine = FakeMachine(self.machine)
        with fake_sim_page.FakeSim(machine=machine) as fake:
            self.use(fake)
            fault = {"op": "sim_fault", "machine": "z", "fault": {"jam": True}, "network": "motion"}
            self.ok("POST", "/api/sim/request", fault)
            sent = fake.sent("sim_fault")[0]
            self.assertEqual((sent["machine"], sent["fault"]), ("z", {"jam": True}))
            self.assertEqual(self.ok("POST", "/api/sim/machine", {})["machine"]["joints"]["z"]["state"], "fault")
            status, data, _ = self.request("POST", "/api/sim/request",
                                           {"op": "sim_fault", "machine": "part_at_pick", "fault": {"jam": True}})
            self.assertEqual(status, 422)
            self.assertIn("is a fault of a joint", data["error"])
            self.ok("POST", "/api/sim/request", {"op": "sim_clear", "machine": "z", "fault": "jam"})
            self.assertEqual(fake.sent("sim_clear")[0]["fault"], "jam")
            self.assertFalse(self.ok("POST", "/api/sim/machine", {})["machine"]["joints"]["z"]["fault"])

    def test_read_only_runtime_refuses_machine_faults(self):
        with fake_sim_page.FakeSim(allow_changes=False, machine=FakeMachine(self.machine)) as fake:
            self.use(fake)
            r = self.ok("POST", "/api/sim/machine", {})
            self.assertFalse(r["allow_changes"])
            status, data, _ = self.request("POST", "/api/sim/request",
                                           {"op": "sim_fault", "machine": "z", "fault": {"jam": True}})
            self.assertEqual(status, 422)
            self.assertIn("changes not allowed", data["error"])
            self.assertFalse(self.ok("POST", "/api/sim/machine", {})["machine"]["joints"]["z"]["fault"])

    def test_standalone_simulator(self):
        with fake_sim_page.FakeSim(token="", standalone=True, machine=FakeMachine(self.machine)) as fake:
            self.use(fake, standalone=True)
            r = self.ok("POST", "/api/sim/machine", {"network": "motion"})
            self.assertEqual((r["target"], r["standalone"], r["allow_changes"]), ("simulator", True, True))
            self.assertEqual(r["machine"]["network"], "motion")


if __name__ == "__main__":
    unittest.main()
