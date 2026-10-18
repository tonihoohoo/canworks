"""The machine file (add-machine-sim: canopen-config-contract "Machine file
contract", "Machine file checks"): its schema, the checks the schema cannot
express, the simulation file's machine steps and conditions, the bundle and
editor project carrying it, and the test doubles that answer sim_machine."""

import copy
import filecmp
import json
import os
import shutil
import unittest

import jsonschema

from canworks import bundle, project, simfile, simmachine

from .fake_sim_machine import FakeMachine, FakeMachineError
from .fake_sim import FakeSim
from .helpers import REPO, editor_bundle, tmpdir, zip_contents
from .test_deploy import deploy

EXAMPLE = os.path.join(REPO, "examples", "gantry-cell", "canworks")
SCHEMAS = ("canworks-sim-machine.v1.schema.json", "canworks-sim.v2.schema.json")


def example_machine():
    with open(os.path.join(EXAMPLE, "machine.json"), encoding="utf-8") as f:
        return json.load(f)


def write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return path


class Gantry:
    """The gantry-cell example's config, its EDS files and machine file in a
    temp folder, with a version 2 simulation file whose `motion` section
    names the machine."""

    def setUp(self):
        self.dir = tmpdir(self)
        self.canopen = os.path.join(self.dir, "canworks")
        shutil.copytree(EXAMPLE, self.canopen)
        for name in ("simulation.json",):
            if os.path.exists(os.path.join(self.canopen, name)):
                os.remove(os.path.join(self.canopen, name))
        self.config = os.path.join(self.canopen, "canworks.json")
        with open(self.config, encoding="utf-8") as f:
            self.cfg = json.load(f)
        self.machine = example_machine()
        self.sim = {"schema_version": 2, "networks": {"motion": {"machine": "machine.json"}}}

    def check(self, machine_file=None, sim=None, cfg=None):
        """(ok, errors text, warnings text) of the simulation file check."""
        write_json(os.path.join(self.canopen, "machine.json"), machine_file or self.machine)
        path = write_json(os.path.join(self.canopen, "simulation.json"), sim or self.sim)
        cfg = cfg or self.cfg
        _, r = simfile.check_file(path, cfg, self.config, eds_paths=bundle.eds_files(cfg, self.config))
        return r.ok, "\n".join(r.errors), "\n".join(r.warnings)

    def assertFails(self, *parts, **kw):
        ok, errors, _ = self.check(**kw)
        self.assertFalse(ok)
        for p in parts:
            self.assertIn(p, errors)
        return errors


class Schema(unittest.TestCase):
    def setUp(self):
        self.v = jsonschema.Draft202012Validator(simmachine.schema())

    def test_schema_copies_match(self):
        # The package ships a copy of schema/; it must not drift.
        for name in SCHEMAS:
            self.assertTrue(filecmp.cmp(os.path.join(REPO, "schema", name),
                                        os.path.join(REPO, "tools", "deploy", "canworks", "schema",
                                                     name), shallow=False), name)

    def test_schemas_are_valid_draft_2020_12(self):
        for name in SCHEMAS:
            with open(os.path.join(REPO, "schema", name), encoding="utf-8") as f:
                jsonschema.Draft202012Validator.check_schema(json.load(f))

    def test_example_machine_is_valid(self):
        self.assertEqual(simmachine.schema_problems(example_machine()), [])
        self.assertEqual(simmachine.structure_problems(example_machine()), [])

    def test_refused(self):
        def bad(change):
            m = example_machine()
            change(m)
            return simmachine.schema_problems(m)

        cases = {
            "unknown key": lambda m: m.update(colour="red"),
            "kind": lambda m: m.update(kind="robot_arm"),
            "units": lambda m: m.update(units="inch"),
            "tick_ms": lambda m: m.update(tick_ms=0),
            "joint missing": lambda m: m["joints"].pop("z"),
            "joint name": lambda m: m["joints"].update(w=m["joints"]["x"]),
            "joint without travel": lambda m: m["joints"]["x"].pop("travel"),
            "direction": lambda m: m["joints"]["x"].update(direction=2),
            "node": lambda m: m["joints"]["x"].update(node=128),
            "bit": lambda m: m["tool"]["close"].update(bit=64),
            "object": lambda m: m["tool"]["close"].update(object="6200:1"),
            "bit key": lambda m: m["tool"]["close"].update(mask=1),
            "tool type": lambda m: m["tool"].update(type="vacuum"),
            "part size": lambda m: m["parts"]["box"].update(size=[80, 60]),
            "conveyor run": lambda m: m["conveyors"][0].pop("run"),
            "sensor detects": lambda m: m["sensors"][0].update(detects="light"),
            "slot count": lambda m: m["fixtures"][0]["slots"].update(count=[3, 0]),
            "change ready": lambda m: m["fixtures"][0]["change"].pop("ready"),
            "colour": lambda m: m["visual"]["colors"].update(frame="grey"),
            "table height": lambda m: m["visual"]["table"].update(height="high"),
            "schema_version": lambda m: m.update(schema_version=2),
        }
        for name, change in cases.items():
            with self.subTest(name):
                self.assertTrue(bad(change), name)

    def test_visual_allows_other_keys(self):
        m = example_machine()
        m["visual"]["lamps"] = {"brightness": 2}
        m["visual"]["table"]["legs"] = 4
        self.assertEqual(simmachine.schema_problems(m), [])
        m.pop("visual")
        self.assertEqual(simmachine.schema_problems(m), [])

    def test_simulation_file_v2_machine_keys(self):
        v = jsonschema.Draft202012Validator(simfile.schema(2))

        def valid(steps, section=None):
            sec = dict(section or {}, scenarios={"s": {"steps": steps}})
            return v.is_valid({"schema_version": 2, "networks": {"motion": sec}})

        self.assertTrue(valid([{"log": "x"}], {"machine": "machine.json"}))
        self.assertFalse(valid([{"log": "x"}], {"machine": ""}))
        for f in ({"jam": True}, {"stuck": "on"}, {"stuck": "off"}, {"slip": True}, {"feeder": "stop"},
                  {"feeder": "empty"}, {"misaligned_mm": -1000}, {"misaligned_mm": 12.5}):
            self.assertTrue(valid([{"machine": "z", "fault": f}]), f)
        for f in ({"jam": False}, {"stuck": "maybe"}, {"feeder": "go"}, {"misaligned_mm": 1001}, {},
                  {"jam": True, "slip": True}, {"emcy": {"code": 1}}):
            self.assertFalse(valid([{"machine": "z", "fault": f}]), f)
        for c in ("jam", "stuck", "feeder", "misaligned_mm", "all"):
            self.assertTrue(valid([{"machine": "z", "clear": c}]), c)
            self.assertEqual(valid([{"node": 4, "clear": c}]), c == "all", c)
        self.assertFalse(valid([{"machine": "z", "clear": "emcy"}]))
        self.assertFalse(valid([{"machine": "z", "node": 4, "clear": "all"}]))
        self.assertFalse(valid([{"machine": "z", "set": {"0x6200:1": 1}}]))
        self.assertFalse(valid([{"node": 4, "fault": {"jam": True}}]))
        self.assertTrue(valid([{"node": 4, "fault": {"emcy": {"code": 1}}}]))
        for op in ("eq", "ne", "lt", "le", "gt", "ge"):
            self.assertTrue(valid([{"wait": {"machine": "placed", op: 9}}]), op)
        self.assertTrue(valid([{"expect": {"machine": "dropped", "eq": 0}, "for_ms": 1000}]))
        self.assertFalse(valid([{"wait": {"machine": "placed"}}]))
        self.assertFalse(valid([{"wait": {"machine": "placed", "eq": "nine"}}]))
        self.assertFalse(valid([{"wait": {"machine": "placed", "ge": 9, "le": 10}}]))
        self.assertFalse(valid([{"wait": {"machine": "placed", "node": 10, "ge": 9}}]))
        self.assertFalse(valid([{"wait": {"machine": "placed", "expr": "1", "ge": 9}}]))
        # Version 1 has no machine.
        self.assertFalse(jsonschema.Draft202012Validator(simfile.schema(1)).is_valid(
            {"schema_version": 1, "scenarios": {"s": {"steps": [{"wait": {"machine": "placed", "ge": 1}}]}}}))


class Structure(unittest.TestCase):
    def problems(self, change):
        m = example_machine()
        change(m)
        self.assertEqual(simmachine.schema_problems(m), [])
        return "\n".join("%s: %s" % p for p in simmachine.structure_problems(m))

    def test_travel_limits_and_hard_stops_in_order(self):
        self.assertIn("joints.x.travel: must be [low, high] with low < high",
                      self.problems(lambda m: m["joints"]["x"].update(travel=[900, 0])))
        self.assertIn("joints.y.limits: must be [low, high] with low < high",
                      self.problems(lambda m: m["joints"]["y"].update(limits=[605, -5])))
        self.assertIn("joints.y.hard_stops: must lie outside the limit switches (-5, 605)",
                      self.problems(lambda m: m["joints"]["y"].update(hard_stops=[-12, 600])))
        self.assertIn("joints.z.hard_stops: must lie outside the travel (0, 300)",
                      self.problems(lambda m: m["joints"]["z"].update(limits=[10, 20], hard_stops=[5, 25])))

    def test_part_kinds_and_names(self):
        self.assertIn("conveyors[0].feed.part: part kind \"crate\" is not defined in \"parts\" (box)",
                      self.problems(lambda m: m["conveyors"][0]["feed"].update(part="crate")))
        self.assertIn("conveyors[0].feed.every_s: must be [shortest, longest]",
                      self.problems(lambda m: m["conveyors"][0]["feed"].update(every_s=[4, 2])))
        self.assertIn("fixtures[0].name: the name \"pallet\" is used by another element (sensor pallet)",
                      self.problems(lambda m: m["sensors"][0].update(name="pallet")))
        self.assertIn("the name \"x\" is used by another element (the joint)",
                      self.problems(lambda m: m["conveyors"][0].update(name="x")))
        self.assertIn("a conveyor runs along x or y",
                      self.problems(lambda m: m["conveyors"][0].update(to=[120, 300])))
        self.assertIn("tool.closed_mm: must be smaller than open_mm",
                      self.problems(lambda m: m["tool"].update(closed_mm=96)))
        self.assertIn("joints.y: node 4 drives another joint too (joint x)",
                      self.problems(lambda m: m["joints"]["y"].update(node=4)))

    def test_input_bits_bound_once(self):
        def twice(m):
            m["sensors"].append({"name": "spare", "at": [0, 0, 0], "size": [1, 1, 1],
                                 "output": {"node": 10, "object": "0x6000:1", "bit": 3}})
        self.assertIn("sensors[1].output: node 10 0x6000:1 bit 3 is bound twice: sensor part_at_pick and sensor spare",
                      self.problems(twice))
        self.assertIn("node 10 0x6000:1 bit 4 is both an output (conveyor infeed run) and an input (tool.gripped)",
                      self.problems(lambda m: m["conveyors"][0]["run"].update(object="0x6000:1", bit=4)))

    def test_fault_shapes(self):
        m = example_machine()
        for f in ({"jam": True}, {"stuck": "off"}, {"slip": True}, {"feeder": "empty"}, {"misaligned_mm": 8}):
            self.assertIsNone(simmachine.fault_problem(f), f)
        self.assertIn("one of jam", simmachine.fault_problem({"jam": True, "slip": True}))
        self.assertIn("unknown machine fault \"melt\"", simmachine.fault_problem({"melt": True}))
        self.assertEqual(simmachine.fault_element_problem(m, "z", {"jam": True}), None)
        self.assertEqual(simmachine.fault_element_problem(m, "part_at_pick", {"jam": True}),
                         "\"jam\" is a fault of a joint, not of part_at_pick")
        self.assertEqual(simmachine.fault_element_problem(m, "infeed", {"feeder": "stop"}), None)
        self.assertEqual(simmachine.fault_element_problem(m, "w", {"jam": True}), "the machine has no element \"w\"")
        self.assertIsNone(simmachine.clear_element_problem(m, "all", "all"))
        self.assertIn("not a machine fault", simmachine.clear_element_problem(m, "z", "slip"))


class Checks(Gantry, unittest.TestCase):
    def test_example_passes(self):
        ok, errors, warnings = self.check()
        self.assertTrue(ok, errors)
        self.assertEqual(warnings, "")

    def test_joint_on_a_node_without_an_axis(self):
        self.machine["joints"]["x"]["node"] = 10
        errors = self.assertFails("network motion", "joint x", "node 10", "has no `axis`")
        self.assertIn("networks.motion.machine", errors)

    def test_input_written_by_the_master(self):
        self.machine["sensors"][0]["output"] = {"node": 10, "object": "0x6200:1", "bit": 3}
        self.assertFails("network motion", "sensor part_at_pick", "the master writes 0x6200:1 of node 10",
                         "RPDO 1", "an input must be an object the device sends")

    def test_output_not_written_by_the_master(self):
        self.machine["conveyors"][0]["run"] = {"node": 10, "object": "0x6000:1", "bit": 2}
        self.assertFails("conveyor infeed run", "the master does not write 0x6000:1 of node 10",
                         "an output must be an object the master writes (an RPDO)")

    def test_node_not_simulated(self):
        cfg = copy.deepcopy(self.cfg)
        cfg["networks"][0]["nodes"][2]["simulate"] = False
        self.assertFails("network motion", "joint z", "node 6", "is not simulated", cfg=cfg)

    def test_node_not_in_the_network(self):
        self.machine["fixtures"][0]["change"]["ready"]["node"] = 33
        self.assertFails("fixture pallet ready", "node 33 is neither a node of the network nor an extra device")

    def test_object_not_in_the_eds(self):
        self.machine["tool"]["gripped"]["object"] = "0x6ABC:1"
        self.assertFails("tool.gripped", "has no object 0x6ABC:1 in dio16.eds")

    def test_bit_beyond_the_data_type(self):
        self.machine["sensors"][0]["output"]["bit"] = 9
        self.assertFails("sensor part_at_pick", "bit 9 does not fit object 0x6000:1 of node 10", "(8 bits)")

    def test_input_bound_twice(self):
        self.machine["tool"]["gripped"] = {"node": 10, "object": "0x6000:1", "bit": 3}
        self.assertFails("network motion", "node 10 0x6000:1 bit 3 is bound twice: tool.gripped and sensor "
                                           "part_at_pick")

    def test_travel_order_and_part_kinds(self):
        self.machine["joints"]["x"]["travel"] = [900, 0]
        self.machine["conveyors"][0]["feed"]["part"] = "crate"
        self.assertFails("network motion", "joints.x.travel: must be [low, high] with low < high",
                         "part kind \"crate\" is not defined")

    def test_schema_problem_names_the_network_and_path(self):
        self.machine["joints"]["z"]["load"]["hold_permille"] = 9000
        self.assertFails("network motion: machine machine.json: joints.z.load.hold_permille")

    def test_machine_file_missing(self):
        write_json(os.path.join(self.canopen, "simulation.json"),
                   {"schema_version": 2, "networks": {"motion": {"machine": "cell.json"}}})
        _, r = simfile.check_file(os.path.join(self.canopen, "simulation.json"), self.cfg, self.config,
                                  eds_paths=bundle.eds_files(self.cfg, self.config))
        self.assertFalse(r.ok)
        text = "\n".join(r.errors)
        self.assertIn("network motion", text)
        self.assertIn("machine file %s not found" % os.path.join(self.canopen, "cell.json"), text)
        self.assertIn("cell.json", text)

    def test_machine_file_not_json(self):
        with open(os.path.join(self.canopen, "broken.json"), "w") as f:
            f.write("{nope")
        sim = {"schema_version": 2, "networks": {"motion": {"machine": "broken.json"}}}
        self.assertFails("network motion", "not valid JSON", sim=sim)

    def test_machine_on_a_real_network_is_a_warning(self):
        cfg = copy.deepcopy(self.cfg)
        cfg["networks"][0]["adapter"]["simulate"] = False
        for n in cfg["networks"][0]["nodes"]:
            n.pop("simulate", None)
        ok, errors, warnings = self.check(cfg=cfg)
        self.assertTrue(ok, errors)
        self.assertIn("network motion: machine machine.json is not used: a machine only runs on a simulated "
                      "network", warnings)

    def test_unknown_network(self):
        sim = {"schema_version": 2, "networks": {"motoin": {"machine": "machine.json"}}}
        self.assertFails("there is no network 'motoin'", "networks: motion", sim=sim)

    def test_machine_steps_and_conditions(self):
        steps = [{"machine": "z", "fault": {"jam": True}}, {"machine": "z", "clear": "jam"},
                 {"machine": "part_at_pick", "fault": {"stuck": "off"}}, {"machine": "all", "clear": "all"},
                 {"machine": "infeed", "fault": {"misaligned_mm": 20}},
                 {"wait": {"machine": "placed", "ge": 9}, "timeout_ms": 60000},
                 {"expect": {"machine": "dropped", "eq": 0}, "for_ms": 1000},
                 {"wait": {"machine": "part_at_pick", "eq": 1}}, {"wait": {"machine": "pallet", "ge": 9}}]
        self.sim["networks"]["motion"]["scenarios"] = {"t": {"test": True, "steps": steps}}
        ok, errors, _ = self.check()
        self.assertTrue(ok, errors)
        steps[:] = [{"machine": "w", "fault": {"jam": True}}, {"machine": "part_at_pick", "fault": {"jam": True}},
                    {"machine": "tool", "fault": {"feeder": "stop"}}, {"wait": {"machine": "plcaed", "ge": 9}}]
        errors = self.assertFails(
            "steps[0].machine: the machine has no element \"w\"",
            "steps[1].machine: \"jam\" is a fault of a joint, not of part_at_pick",
            "steps[2].machine: \"feeder\" is a fault of a conveyor with a feeder, not of tool",
            "steps[3].wait.machine: the machine has no value \"plcaed\" (fed, picked, placed, misplaced, dropped, "
            "pallets, x, y, z, part_at_pick, pallet, relay, manual, jog_x_plus, ", "auto_lamp, scanner.warning, "
            "scanner.protective)")
        self.assertIn("networks.motion.scenarios.t", errors)

    def test_machine_step_without_a_machine(self):
        sim = {"schema_version": 2, "networks": {"motion": {"scenarios": {"t": {"steps": [
            {"machine": "z", "fault": {"jam": True}}, {"wait": {"machine": "placed", "ge": 1}}]}}}}}
        errors = self.assertFails("network motion has no machine (its section names no machine file)", sim=sim)
        self.assertIn("steps[1].wait.machine", errors)

    def test_referenced_files_and_rewrite(self):
        path = os.path.join(self.canopen, "simulation.json")
        files = simfile.referenced_files(self.sim, path)
        self.assertEqual(files["machine"], {"machine.json": os.path.join(self.canopen, "machine.json")})
        out = simfile.rewrite(self.sim, path, os.path.basename, os.path.basename, lambda v, p: "m/" + v)
        self.assertEqual(out["networks"]["motion"]["machine"], "m/machine.json")
        self.assertEqual(simfile.rewrite(self.sim, path, os.path.basename, os.path.basename), self.sim)


class Bundle(Gantry, unittest.TestCase):
    def deploy(self, sim):
        write_json(os.path.join(self.canopen, "simulation.json"), sim)
        src = os.path.join(self.dir, "src")
        if not os.path.isdir(src):
            editor_bundle(src)
        out_zip = os.path.join(self.dir, "program.zip")
        code, out, err = deploy("--bundle", src, "--config", self.config, "--check-only", "--output", out_zip)
        self.assertEqual(code, 0, err)
        return zip_contents(out_zip), out

    def test_machine_file_next_to_the_simulation_file(self):
        files, out = self.deploy(self.sim)
        self.assertIn("conf/canworks/simulation.json, conf/canworks/machine.json", out)
        self.assertEqual(json.loads(files["conf/canworks/simulation.json"])["networks"]["motion"]["machine"],
                         "machine.json")
        with open(os.path.join(EXAMPLE, "machine.json"), "rb") as f:
            self.assertEqual(files["conf/canworks/machine.json"], f.read())

    def test_relative_name_kept_and_unsafe_names_flattened(self):
        os.makedirs(os.path.join(self.canopen, "cells"))
        shutil.copy(os.path.join(EXAMPLE, "machine.json"), os.path.join(self.canopen, "cells", "gantry.json"))
        files, _ = self.deploy({"schema_version": 2, "networks": {"motion": {"machine": "cells/gantry.json"}}})
        self.assertIn("conf/canworks/cells/gantry.json", files)
        self.assertEqual(json.loads(files["conf/canworks/simulation.json"])["networks"]["motion"]["machine"],
                         "cells/gantry.json")
        shutil.copy(os.path.join(EXAMPLE, "machine.json"), os.path.join(self.dir, "outside.json"))
        files, _ = self.deploy({"schema_version": 2, "networks": {"motion": {"machine": "../outside.json"}}})
        self.assertIn("conf/canworks/outside.json", files)
        self.assertEqual(json.loads(files["conf/canworks/simulation.json"])["networks"]["motion"]["machine"],
                         "outside.json")
        self.assertEqual(bundle.machine_name("eds/m.json", "/x/eds/m.json"), "m.json")

    def test_check_fails_before_the_bundle(self):
        self.machine["joints"]["x"]["node"] = 10
        write_json(os.path.join(self.canopen, "machine.json"), self.machine)
        write_json(os.path.join(self.canopen, "simulation.json"), self.sim)
        code, _, err = deploy("--bundle", editor_bundle(os.path.join(self.dir, "src")), "--config", self.config,
                              "--check-only")
        self.assertNotEqual(code, 0)
        self.assertIn("joint x: node 10 (io) has no `axis`", err)

    def test_into_project(self):
        proj = os.path.join(self.dir, "proj")
        os.makedirs(os.path.join(proj, "cells"))
        write_json(os.path.join(proj, "project.json"), {})
        os.makedirs(os.path.join(self.canopen, "cells"))
        shutil.copy(os.path.join(EXAMPLE, "machine.json"), os.path.join(self.canopen, "cells", "gantry.json"))
        sim = write_json(os.path.join(self.canopen, "simulation.json"),
                         {"schema_version": 2, "networks": {"motion": {"machine": "cells/gantry.json"}}})
        written, _ = project.write(self.cfg, self.config, proj, sim_path=sim)
        target = os.path.join(proj, "canworks")
        self.assertIn(os.path.join(target, "gantry.json"), written)
        with open(os.path.join(target, "simulation.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["networks"]["motion"]["machine"], "gantry.json")
        self.assertTrue(filecmp.cmp(os.path.join(target, "gantry.json"), os.path.join(EXAMPLE, "machine.json"),
                                    shallow=False))


class Doubles(unittest.TestCase):
    def test_snapshot_shape(self):
        m = FakeMachine.example()
        s = m.snapshot(1.0)
        self.assertEqual(set(s), {"name", "kind", "joints", "tool", "parts", "sensors", "conveyors", "fixtures",
                                  "counters", "faults", "t_us", "seq", "network", "step_us", "step_max_us", "panel",
                                  "safety"})
        self.assertEqual((s["t_us"], s["seq"], s["network"]), (1000000, 1, "motion"))
        self.assertEqual(set(s["joints"]), {"x", "y", "z"})
        self.assertEqual(set(s["joints"]["x"]), {"node", "position", "velocity", "demand", "actual_counts", "state",
                                                 "mode", "statusword", "fault", "torque", "sto"})
        self.assertEqual([s["joints"][j]["node"] for j in "xyz"], [4, 5, 6])
        self.assertEqual(set(s["tool"]), {"position", "opening", "closed", "holding"})
        self.assertEqual(set(s["parts"][0]), {"id", "kind", "position", "yaw", "state"})
        self.assertEqual(set(s["conveyors"]["infeed"]), {"running", "travel"})
        self.assertEqual(set(s["fixtures"]["pallet"]), {"offset", "ready", "changing", "filled"})
        self.assertEqual(set(s["counters"]), set(simmachine.COUNTERS))
        self.assertEqual(m.snapshot(1.1)["seq"], 2)
        self.assertLess(len(json.dumps(m.snapshot(100))), 16 * 1024)

    def test_pick_and_place_cycle(self):
        m = FakeMachine.example()
        held = [m.snapshot(t / 10.0) for t in range(0, 81)]
        self.assertTrue(any(s["tool"]["holding"] for s in held))
        self.assertTrue(any(p["state"] == "belt" for s in held for p in s["parts"]))
        after = m.snapshot(8.0)
        self.assertEqual(after["counters"]["placed"], 1)
        self.assertEqual(after["fixtures"]["pallet"]["filled"], 1)
        # Smooth: no jump larger than the speed allows between 10 ms steps.
        prev = None
        for i in range(0, 1600):
            s = m.snapshot(i / 100.0)
            pos = [s["joints"][j]["position"] for j in "xyz"]
            if prev:
                self.assertLess(max(abs(a - b) for a, b in zip(pos, prev)), 15, i)
            prev = pos

    def test_jam_stops_the_joint_and_clear_resumes(self):
        m = FakeMachine.example()
        before = m.snapshot(2.0)["joints"]["z"]
        m.fault("z", {"jam": True})
        s = m.snapshot(3.0)
        self.assertEqual(s["joints"]["z"]["state"], "fault")
        self.assertTrue(s["joints"]["z"]["fault"])
        self.assertEqual(s["joints"]["z"]["position"], before["position"])
        self.assertEqual(s["joints"]["x"]["state"], "operation_enabled")
        self.assertEqual(s["faults"], [{"machine": "z", "fault": {"jam": True}}])
        m.clear("z", "jam")
        s = m.snapshot(3.01)
        self.assertEqual(s["joints"]["z"]["state"], "operation_enabled")
        self.assertLess(abs(s["joints"]["z"]["position"] - before["position"]), 5)
        self.assertEqual(s["faults"], [])

    def test_sensor_feeder_slip_and_refusals(self):
        m = FakeMachine.example()
        self.assertTrue(m.snapshot(0.5)["sensors"]["part_at_pick"])
        m.fault("part_at_pick", {"stuck": "off"})
        self.assertFalse(m.snapshot(0.6)["sensors"]["part_at_pick"])
        m.fault("infeed", {"feeder": "stop"})
        m.fault("infeed", {"misaligned_mm": 15})
        self.assertEqual(len(m.snapshot(0.7)["faults"]), 3)
        m.clear("all", "all")
        self.assertEqual(m.snapshot(0.8)["faults"], [])
        m.snapshot(3.0)
        m.fault("tool", {"slip": True})
        s = m.snapshot(3.1)
        self.assertEqual(s["counters"]["dropped"], 1)
        self.assertIn("table", [p["state"] for p in s["parts"]])
        with self.assertRaises(FakeMachineError) as e:
            m.fault("part_at_pick", {"jam": True})
        self.assertIn("is a fault of a joint", str(e.exception))
        with self.assertRaises(FakeMachineError):
            m.clear("z", "slip")

    def test_fake_sim_answers_sim_machine(self):
        sim = FakeSim.example()
        r = sim.handle({"op": "sim_machine"}, allow_changes=False)
        self.assertEqual(r, {"ok": False, "error": "no machine"})
        sim.set_machine(example_machine())
        sim.clock = lambda: 2.5
        r = sim.handle({"op": "sim_machine"}, allow_changes=False)
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["result"]["t_us"], 2500000)
        r = sim.handle({"op": "sim_fault", "machine": "z", "fault": {"jam": True}}, allow_changes=False)
        self.assertEqual(r, {"ok": False, "error": "changes not allowed"})
        self.assertTrue(sim.handle({"op": "sim_fault", "machine": "z", "fault": {"jam": True}})["ok"])
        self.assertEqual(sim.handle({"op": "sim_status"})["result"]["machine"]["faults"],
                         [{"machine": "z", "fault": {"jam": True}}])
        r = sim.handle({"op": "sim_clear", "machine": "z", "fault": "slip"})
        self.assertIn("is not a machine fault", r["error"])
        self.assertTrue(sim.handle({"op": "sim_clear", "machine": "z", "fault": "jam"})["ok"])


def button(m, name):
    return next(b for b in m["panel"]["buttons"] if b["name"] == name)


class PanelAndSafety(unittest.TestCase):
    """add-gantry-manual-mode: the machine file's panel, safety and brake
    (canopen-config-contract "Machine file checks")."""

    def problems(self, change):
        m = example_machine()
        change(m)
        self.assertEqual(simmachine.schema_problems(m), [])
        return "\n".join("%s: %s" % p for p in simmachine.structure_problems(m))

    def test_example_has_every_new_key(self):
        m = example_machine()
        self.assertTrue(m["joints"]["z"]["brake"])
        self.assertEqual(simmachine.schema_problems(m), [])
        self.assertEqual(simmachine.structure_problems(m), [])
        els = simmachine.elements(m)
        self.assertEqual((els["estop"], els["manual_lamp"], els["scanner"]), ("button", "lamp", "scanner"))

    def test_schema_refuses(self):
        def bad(change):
            m = example_machine()
            change(m)
            return simmachine.schema_problems(m)

        cases = {
            "kind toggle": lambda m: button(m, "manual").update(kind="toggle"),
            "key Tab": lambda m: button(m, "manual").update(key="Tab"),
            "key Escape": lambda m: button(m, "manual").update(key="Escape"),
            "key lower case": lambda m: button(m, "manual").update(key="m"),
            "key F13": lambda m: button(m, "manual").update(key="F13"),
            "button without input": lambda m: button(m, "manual").pop("input"),
            "lamp without output": lambda m: m["panel"]["lamps"][0].pop("output"),
            "panel key": lambda m: m["panel"].update(switches=[]),
            "safety without relay": lambda m: m["safety"].pop("relay"),
            "relay without inputs": lambda m: m["safety"]["relay"].update(inputs=[]),
            "stop delay": lambda m: m["safety"]["relay"].update(stop_delay_ms=10001),
            "box size": lambda m: m["safety"]["scanners"][0]["warning"][0].update(size=[0, 100]),
            "no protective box": lambda m: m["safety"]["scanners"][0].update(protective=[]),
            "scanner at": lambda m: m["safety"]["scanners"][0].update(at=[1, 2, 3]),
            "brake": lambda m: m["joints"]["z"].update(brake="yes"),
        }
        for name, change in cases.items():
            with self.subTest(name):
                self.assertTrue(bad(change), name)
        m = example_machine()
        for b in m["panel"]["buttons"]:
            b.pop("kind")
            b.pop("label")
        for k in ("stop_delay_ms", "joints", "conveyors", "feedback"):
            m["safety"]["relay"].pop(k)
        self.assertEqual(simmachine.schema_problems(m), [])

    def test_names_unique(self):
        self.assertIn("panel.buttons[8].name: the name \"part_at_pick\" is used by another element (sensor part_at_pick)",
                      self.problems(lambda m: button(m, "gripper").update(name="part_at_pick")))
        self.assertIn("panel.lamps[0].name: the name \"manual\" is used by another element (button manual)",
                      self.problems(lambda m: m["panel"]["lamps"][0].update(name="manual")))
        self.assertIn("safety.scanners[0].name: the name \"x\" is used by another element (the joint)",
                      self.problems(lambda m: m["safety"]["scanners"][0].update(name="x")))

    def test_key_used_twice(self):
        self.assertIn("panel.buttons[9].key: key \"G\" is used by button gripper too",
                      self.problems(lambda m: button(m, "conveyor").update(key="G")))

    def test_relay_inputs_and_reset(self):
        def inputs(*names):
            return lambda m: m["safety"]["relay"].update(inputs=list(names))
        self.assertIn("safety.relay.inputs: \"foo\" is not a panel button or a scanner", self.problems(inputs("foo")))
        self.assertIn("safety.relay.inputs: button \"stop\" is momentary: an emergency stop must be latching",
                      self.problems(inputs("estop", "stop")))
        self.assertIn("safety.relay.inputs: button \"manual\" is a switch: an emergency stop must be latching",
                      self.problems(inputs("manual")))
        self.assertIn("safety.relay.inputs: \"auto_lamp\" is not a panel button or a scanner", self.problems(inputs("auto_lamp")))
        self.assertEqual(self.problems(inputs("scanner")), "")
        for reset in ("estop", "manual", "nothing"):
            self.assertIn("safety.relay.reset: \"%s\" must name a momentary panel button" % reset,
                          self.problems(lambda m: m["safety"]["relay"].update(reset=reset)))

    def test_relay_joints_and_conveyors(self):
        self.assertIn("safety.relay.joints: the machine has no joint \"q\"",
                      self.problems(lambda m: m["safety"]["relay"].update(joints=["x", "q"])))
        self.assertIn("safety.relay.conveyors: the machine has no conveyor \"q\"",
                      self.problems(lambda m: m["safety"]["relay"].update(conveyors=["q"])))

    def test_protective_inside_a_warning_box(self):
        self.assertIn("safety.scanners[0].protective[1]: must lie inside one of the scanner's warning boxes",
                      self.problems(lambda m: m["safety"]["scanners"][0]["protective"][1].update(size=[600, 2300])))
        # Inside the union of two boxes but in neither is outside.
        self.assertIn("safety.scanners[0].protective[0]",
                      self.problems(lambda m: m["safety"]["scanners"][0]["protective"][0].update(origin=[-700, -700],
                                                                                                    size=[1900, 1700])))

    def test_input_bits(self):
        def feedback_on_estop(m):
            m["safety"]["relay"]["feedback"] = dict(button(m, "estop")["input"])
        self.assertIn("safety.relay.feedback: node 11 0x6000:2 bit 7 is bound twice: panel button estop and safety relay "
                      "feedback", self.problems(feedback_on_estop))

        def warning_on_sensor(m):
            m["safety"]["scanners"][0]["warning_output"]["bit"] = 3
        self.assertIn("node 10 0x6000:1 bit 3 is bound twice: sensor part_at_pick and scanner scanner warning",
                      self.problems(warning_on_sensor))

        def lamp_on_button(m):
            m["panel"]["lamps"][0]["output"] = dict(button(m, "manual")["input"])
        self.assertIn("panel.lamps[0].output: node 11 0x6000:1 bit 0 is both an output (panel lamp manual_lamp) and an "
                      "input (panel button manual)", self.problems(lamp_on_button))

    def test_value_names(self):
        names = simmachine.value_names(example_machine())
        for n in ("relay", "jog_x_plus", "estop", "fault_lamp", "scanner.warning", "scanner.protective"):
            self.assertIn(n, names)
        m = example_machine()
        m.pop("safety")
        m.pop("panel")
        self.assertNotIn("relay", simmachine.value_names(m))
        self.assertEqual(simmachine.value_names(m)[-1], "pallet")

    def test_panel_and_person_problems(self):
        m = example_machine()
        self.assertIsNone(simmachine.panel_problem(m, "estop"))
        self.assertTrue(simmachine.panel_problem(m, "jog").startswith(
            "the machine has no panel button \"jog\" (manual, jog_x_plus, "))
        self.assertIsNone(simmachine.person_step_problem(m))
        m.pop("panel")
        m.pop("safety")
        self.assertEqual(simmachine.panel_problem(m, "estop"), "the machine has no panel")
        self.assertEqual(simmachine.person_step_problem(m), "the machine has no safety scanner")


class PanelChecks(Gantry, unittest.TestCase):
    def test_button_written_by_the_master(self):
        button(self.machine, "estop")["input"] = {"node": 11, "object": "0x6200:1", "bit": 7}
        self.assertFails("network motion", "panel button estop: the master writes 0x6200:1 of node 11",
                         "an input must be an object the device sends")

    def test_lamp_not_written_by_the_master(self):
        self.machine["panel"]["lamps"][1]["output"] = {"node": 10, "object": "0x6000:1", "bit": 0}
        self.assertFails("panel lamp homed_lamp: the master does not write 0x6000:1 of node 10")

    def test_feedback_beyond_the_data_type(self):
        self.machine["safety"]["relay"]["feedback"]["bit"] = 8
        self.assertFails("safety relay feedback: bit 8 does not fit object 0x6000:1 of node 10")

    def test_panel_node_missing(self):
        cfg = copy.deepcopy(self.cfg)
        cfg["networks"][0]["nodes"] = [n for n in cfg["networks"][0]["nodes"] if n["node_id"] != 11]
        self.assertFails("panel button manual: node 11 is neither a node of the network nor an extra device", cfg=cfg)

    def test_panel_and_person_steps(self):
        steps = [{"panel": {"manual": True, "jog_x_plus": True}}, {"panel": {"jog_x_plus": False}, "after_ms": 2000},
                 {"person": [300, 1200]}, {"person": None, "at_ms": 9000},
                 {"wait": {"machine": "relay", "eq": 2}, "timeout_ms": 1000},
                 {"expect": {"machine": "manual_lamp", "eq": 1}},
                 {"wait": {"machine": "scanner.warning", "eq": 1}},
                 {"expect": {"machine": "scanner.protective", "eq": 0}, "for_ms": 100},
                 {"wait": {"machine": "estop", "eq": 0}}]
        self.sim["networks"]["motion"]["scenarios"] = {"t": {"test": True, "steps": steps}}
        ok, errors, _ = self.check()
        self.assertTrue(ok, errors)
        steps[:] = [{"panel": {"jog": True}}, {"wait": {"machine": "scanner.muted", "eq": 1}},
                    {"wait": {"machine": "relays", "eq": 1}}]
        self.assertFails("steps[0].panel: the machine has no panel button \"jog\" (manual, jog_x_plus, ",
                         "steps[1].wait.machine: the machine has no value \"scanner.muted\"",
                         "steps[2].wait.machine: the machine has no value \"relays\"")

    def test_steps_without_panel_or_scanner(self):
        self.machine.pop("panel")
        self.machine.pop("safety")
        self.sim["networks"]["motion"]["scenarios"] = {"t": {"steps": [{"panel": {"estop": True}},
                                                                       {"person": [0, 0]}]}}
        self.assertFails("steps[0].panel: the machine has no panel", "steps[1].person: the machine has no safety scanner")

    def test_steps_without_a_machine(self):
        sim = {"schema_version": 2, "networks": {"motion": {"scenarios": {"t": {"steps": [
            {"panel": {"estop": True}}, {"person": None}]}}}}}
        errors = self.assertFails("steps[0].panel: network motion has no machine", sim=sim)
        self.assertIn("steps[1].person: network motion has no machine", errors)

    def test_step_schema(self):
        v = jsonschema.Draft202012Validator(simfile.schema(2))

        def valid(step):
            return v.is_valid({"schema_version": 2, "networks": {"motion": {"scenarios": {"s": {"steps": [step]}}}}})

        for step in ({"panel": {"a": True}}, {"panel": {"a": False, "b": True}, "at_ms": 10}, {"person": [1.5, -2]},
                     {"person": None, "after_ms": 5}):
            self.assertTrue(valid(step), step)
        for step in ({"panel": {}}, {"panel": {"a": 1}}, {"panel": ["a"]}, {"person": [1]}, {"person": "here"},
                     {"panel": {"a": True}, "node": 11}, {"person": None, "machine": "z"},
                     {"panel": {"a": True}, "device": "d"}, {"panel": {"a": True}, "log": "x"},
                     {"panel": {"a": True}, "person": None}):
            self.assertFalse(valid(step), step)


class PanelDoubles(unittest.TestCase):
    """FakeMachine's panel, relay and person follow the simulator's rules."""

    def test_momentary_lease_and_switch(self):
        m = FakeMachine.example()
        m.snapshot(1.0)
        m.panel("jog_x_plus", True, 1.0)
        m.panel("manual", True, 1.0)
        self.assertTrue(m.snapshot(1.4)["panel"]["buttons"]["jog_x_plus"])
        self.assertFalse(m.snapshot(1.5)["panel"]["buttons"]["jog_x_plus"])  # 500 ms without a repeat
        for t in (2.0, 2.2, 2.4, 2.6):
            m.panel("jog_x_plus", True, t)
        self.assertTrue(m.snapshot(3.0)["panel"]["buttons"]["jog_x_plus"])
        m.panel("jog_x_plus", False, 3.0)
        s = m.snapshot(3.0)
        self.assertFalse(s["panel"]["buttons"]["jog_x_plus"])
        self.assertTrue(s["panel"]["buttons"]["manual"])  # a switch keeps its position
        self.assertEqual(set(s["panel"]["lamps"]), {"manual_lamp", "homed_lamp", "fault_lamp", "auto_lamp"})
        with self.assertRaises(FakeMachineError) as e:
            m.panel("jog", True)
        self.assertIn("the machine has no panel button \"jog\"", str(e.exception))
        with self.assertRaises(FakeMachineError) as e:
            m.panel("estop", 1)
        self.assertEqual(str(e.exception), "\"pressed\" must be true or false")

    def test_emergency_stop_and_reset(self):
        m = FakeMachine.example()
        s = m.snapshot(1.0)
        self.assertEqual(s["safety"], {"relay": "closed", "reset_ready": False,
                                       "scanners": {"scanner": {"warning": False, "protective": False}}, "person": None})
        self.assertFalse(any(j["sto"] for j in s["joints"].values()))
        m.panel("estop", True, 1.0)
        self.assertEqual(m.snapshot(1.1)["safety"]["relay"], "stopping")
        s = m.snapshot(1.4)
        self.assertEqual((s["safety"]["relay"], s["safety"]["reset_ready"]), ("open", False))
        self.assertTrue(all(j["sto"] and j["state"] == "switch_on_disabled" for j in s["joints"].values()))
        m.panel("reset", True, 1.5)
        self.assertEqual(m.snapshot(1.6)["safety"]["relay"], "open")  # still latched
        m.panel("reset", False, 1.6)
        m.panel("estop", False, 1.7)
        self.assertTrue(m.snapshot(1.8)["safety"]["reset_ready"])
        m.panel("reset", True, 1.9)
        s = m.snapshot(2.0)
        self.assertEqual((s["safety"]["relay"], s["safety"]["reset_ready"]), ("closed", False))
        self.assertFalse(s["joints"]["x"]["sto"])

    def test_person_in_the_fields(self):
        m = FakeMachine.example()
        m.snapshot(1.0)
        m.person([300, 1900], 1.0)  # in front of the fence, outside the warning field
        self.assertEqual(m.snapshot(1.1)["safety"]["scanners"]["scanner"], {"warning": False, "protective": False})
        m.person([300, 1300], 1.1)
        s = m.snapshot(1.2)
        self.assertEqual(s["safety"]["scanners"]["scanner"], {"warning": True, "protective": False})
        self.assertEqual((s["safety"]["relay"], s["safety"]["person"]), ("closed", [300.0, 1300.0]))
        m.person([300, 1000], 1.2)
        self.assertEqual(m.snapshot(1.3)["safety"]["scanners"]["scanner"], {"warning": True, "protective": True})
        self.assertEqual(m.snapshot(1.6)["safety"]["relay"], "open")
        m.person(None, 1.6)
        s = m.snapshot(1.7)
        self.assertEqual((s["safety"]["relay"], s["safety"]["reset_ready"], s["safety"]["person"]), ("open", True, None))
        with self.assertRaises(FakeMachineError) as e:
            m.person([1, 2, 3])
        self.assertEqual(str(e.exception), "\"at\" must be [x, y] in mm, or null")

    def test_fake_sim_answers_panel_and_person(self):
        sim = FakeSim.example()
        self.assertEqual(sim.handle({"op": "sim_panel", "button": "estop", "pressed": True}),
                         {"ok": False, "error": "this network has no machine"})
        sim.set_machine(example_machine())
        sim.clock = lambda: 1.0
        self.assertEqual(sim.handle({"op": "sim_panel", "button": "estop", "pressed": True}, allow_changes=False),
                         {"ok": False, "error": "changes not allowed"})
        self.assertEqual(sim.handle({"op": "sim_person", "at": [0, 0]}, allow_changes=False),
                         {"ok": False, "error": "changes not allowed"})
        self.assertTrue(sim.handle({"op": "sim_panel", "button": "estop", "pressed": True})["ok"])
        self.assertTrue(sim.handle({"op": "sim_person", "at": [300, 1300]})["ok"])
        r = sim.handle({"op": "sim_machine"}, allow_changes=False)["result"]
        self.assertTrue(r["panel"]["buttons"]["estop"])
        self.assertEqual(r["safety"]["person"], [300.0, 1300.0])
        self.assertIn("the machine has no panel button \"jog\"",
                      sim.handle({"op": "sim_panel", "button": "jog", "pressed": True})["error"])
        m = example_machine()
        m.pop("panel")
        m.pop("safety")
        sim.set_machine(m)
        self.assertEqual(sim.handle({"op": "sim_panel", "button": "estop", "pressed": True})["error"],
                         "the machine has no panel")
        self.assertEqual(sim.handle({"op": "sim_person", "at": None})["error"], "the machine has no safety scanner")
        s = sim.handle({"op": "sim_machine"})["result"]
        self.assertNotIn("panel", s)
        self.assertNotIn("safety", s)


if __name__ == "__main__":
    unittest.main()
