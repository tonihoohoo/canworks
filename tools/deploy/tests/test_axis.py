"""CiA 402 axes (add-cia402-drive-support): the axis checks, the generated
axis and bridge lines, and the configurator's "Map CiA 402 objects"."""

import copy
import json
import os
import re
import unittest

from canworks import axis, contract, editorproject
from canworks.configurator import cia402map, layout, server
from canworks.eds import Eds

from .helpers import REPO

EXAMPLE = os.path.join(REPO, "config", "cia402-drive")
CONFIG = os.path.join(EXAMPLE, "canopen_config.json")
DRIVES = os.path.join(REPO, "test", "fixtures", "eds", "drives")


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def run_check(cfg):
    errors, warnings = [], []
    axis.check(cfg, lambda w, m, p: errors.append((m, p)), lambda w, m, p: warnings.append((m, p)))
    return [m for m, _ in errors], [m for m, _ in warnings]


def entry(cfg, index):
    for key in ("tx_pdos", "rx_pdos"):
        for p in cfg["nodes"][0][key]:
            for e in p["entries"]:
                if e["index"] == index:
                    return e
    raise KeyError(index)


def drop(cfg, index):
    for key in ("tx_pdos", "rx_pdos"):
        for p in cfg["nodes"][0][key]:
            p["entries"] = [e for e in p["entries"] if e["index"] != index]


class Check(unittest.TestCase):
    def setUp(self):
        self.cfg = load(CONFIG)

    def test_example_is_clean(self):
        r = contract.check_config(self.cfg, CONFIG)
        self.assertEqual((r.errors, r.warnings), ([], []))

    def test_needs_status_bit(self):
        del self.cfg["nodes"][0]["status_location"]
        errors, _ = run_check(self.cfg)
        self.assertEqual(errors, ["node 4 (drive): a CiA 402 axis needs 'status_location': the axis goes into error "
                                  "stop when the drive is lost"])

    def test_wrong_direction(self):
        e = entry(self.cfg, "0x6064")
        self.cfg["nodes"][0]["rx_pdos"][2]["entries"].append(dict(e, iec_location="%QD103"))
        drop_tx = self.cfg["nodes"][0]["tx_pdos"][1]
        drop_tx["entries"] = []
        errors, _ = run_check(self.cfg)
        self.assertEqual(errors, ["node 4 (drive): CiA 402 axis: 0x6064 (position actual value) must be mapped in a "
                                  "TPDO, not an RPDO"])

    def test_wrong_type(self):
        entry(self.cfg, "0x6040")["type"] = "INTEGER32"
        errors, _ = run_check(self.cfg)
        self.assertEqual(errors, ["node 4 (drive): CiA 402 axis: 0x6040 (controlword) needs type UNSIGNED16 (UINT), "
                                  "not INTEGER32"])

    def test_mapped_twice(self):
        self.cfg["nodes"][0]["tx_pdos"][2]["entries"].append(dict(entry(self.cfg, "0x6064"), iec_location="%ID102"))
        errors, _ = run_check(self.cfg)
        self.assertEqual(errors, ["node 4 (drive): CiA 402 axis: 0x6064 (position actual value) is mapped 2 times; "
                                  "map it once"])

    def test_needs_controlword_and_statusword(self):
        drop(self.cfg, "0x6040")
        del entry(self.cfg, "0x6041")["iec_location"]
        errors, _ = run_check(self.cfg)
        self.assertEqual(errors, [
            "node 4 (drive): a CiA 402 axis needs the statusword 0x6041 in a TPDO with a location",
            "node 4 (drive): a CiA 402 axis needs the controlword 0x6040 in an RPDO with a location"])

    def test_target_without_modes_warns(self):
        drop(self.cfg, "0x6060")
        errors, warnings = run_check(self.cfg)
        self.assertEqual(errors, [])
        self.assertEqual(len(warnings), 1)
        self.assertIn("0x607A (target position) is mapped without 0x6060", warnings[0])

    def test_no_axis_no_checks(self):
        del self.cfg["nodes"][0]["axis"]
        del self.cfg["nodes"][0]["status_location"]
        self.assertEqual(run_check(self.cfg), ([], []))

    def test_device_type_warning(self):
        cfg = copy.deepcopy(self.cfg)
        cfg["nodes"][0]["eds"] = os.path.join(REPO, "test", "fixtures", "eds", "cpp-slave.eds")
        node = cfg["nodes"][0]
        self.assertIsNone(axis.device_type_warning(node, Eds.read(os.path.join(EXAMPLE, "servo402.eds"))))
        msg = axis.device_type_warning(node, Eds.read(node["eds"]))
        self.assertRegex(msg, r"^node 4 \(drive\): CiA 402 axis: its EDS device type \(0x1000\) is 0x[0-9A-F]{8}, "
                              r"not device profile 402")
        del node["axis"]
        self.assertIsNone(axis.device_type_warning(node, Eds.read(node["eds"])))


class Glue(unittest.TestCase):
    def test_example_program(self):
        cfg = load(CONFIG)
        main = editorproject.program(cfg, CONFIG)
        decl = main.split("END_VAR")[0]
        self.assertIn("    drive_Target_velocity            : DINT AT %QD102;", decl)
        # The axis and the bridge follow the node's located variables.
        self.assertTrue(re.search(r"drive_Target_velocity .*\n    drive {28}: AXIS_REF_SM3; \(\* node drive \(4\): "
                                  r"CiA 402 axis \*\)\n    drive_bridge {21}: SM_Drive_GenericDS402;", decl), decl)
        body = main.split("END_VAR\n\n", 1)[1]
        self.assertTrue(body.startswith(axis.BODY_HEAD + "\ndrive.iRatioTechUnitsNum := DINT#1;\n"
                                        "drive.dwRatioTechUnitsDenom := DWORD#1;\ndrive.fScalefactor := LREAL#1.0;\n"
                                        "drive_bridge(Axis := drive,\n"
                                        "             wStatusWord := drive_Statusword,\n"), body)
        self.assertIn("             bOnline := drive_ok,\n             wControlWord => drive_Controlword,\n", body)
        self.assertIn("diTargetVelocity => drive_Target_velocity);\n\n" + editorproject.BODY, body)
        # Pins of objects that are not mapped (torques) are left out.
        self.assertNotIn("Torque", body)

    def test_velocity_only_drive(self):
        cfg = load(CONFIG)
        node = cfg["nodes"][0]
        node["rx_pdos"] = [{"number": 1, "entries": [
            {"index": "0x6040", "subindex": 0, "type": "UNSIGNED16", "iec_location": "%QW100"},
            {"index": "0x6060", "subindex": 0, "type": "INTEGER8", "iec_location": "%QB100"},
            {"index": "0x60FF", "subindex": 0, "type": "INTEGER32", "iec_location": "%QD100"}]}]
        node["tx_pdos"] = [{"number": 1, "entries": [
            {"index": "0x6041", "subindex": 0, "type": "UNSIGNED16", "iec_location": "%IW100"},
            {"index": "0x6061", "subindex": 0, "type": "INTEGER8", "iec_location": "%IB100"},
            {"index": "0x606C", "subindex": 0, "type": "INTEGER32", "iec_location": "%ID100"}]}]
        r = contract.check_config(cfg, CONFIG)
        self.assertEqual((r.errors, r.warnings), ([], []))
        _, body = axis.glue(cfg, editorproject.declarations(cfg, CONFIG))
        pins = re.findall(r"(\w+) (?::=|=>) ", body[-1])
        self.assertEqual(pins, ["Axis", "wStatusWord", "siModesDisplay", "diActualVelocity", "bOnline", "wControlWord",
                                "siModes", "diTargetVelocity"])

    def test_scaling_literals(self):
        cfg = load(CONFIG)
        cfg["nodes"][0]["axis"] = {"scale_numerator": -4096, "scale_denominator": 360, "scale_factor": 2}
        _, body = axis.glue(cfg, [])
        self.assertEqual(body[1:4], ["drive.iRatioTechUnitsNum := DINT#-4096;",
                                     "drive.dwRatioTechUnitsDenom := DWORD#360;", "drive.fScalefactor := LREAL#2.0;"])

    def test_without_status_bit_online_is_true(self):
        cfg = load(CONFIG)
        del cfg["nodes"][0]["status_location"]
        _, body = axis.glue(cfg, editorproject.declarations(cfg, CONFIG))
        self.assertIn("bOnline := TRUE", body[-1])

    def test_unnamed_node(self):
        cfg = load(CONFIG)
        del cfg["nodes"][0]["name"]
        axes, body = axis.glue(cfg, [])
        self.assertEqual([a["name"] for a in axes], ["node4", "node4_bridge"])
        self.assertTrue(body[-1].startswith("node4_bridge(Axis := node4,\n"))

    def test_no_axis_program_unchanged(self):
        cfg = load(CONFIG)
        del cfg["nodes"][0]["axis"]
        decls = editorproject.declarations(cfg, CONFIG)
        self.assertEqual(editorproject.program(cfg, CONFIG), editorproject.main_st(decls))
        self.assertNotIn("AXIS_REF_SM3", editorproject.program(cfg, CONFIG))
        self.assertEqual(axis.text_block(cfg, decls), "")

    def test_demo_has_the_generated_lines(self):
        """drive_demo.st holds the generator's output for the example; it
        goes stale when the generator or the example changes."""
        cfg = load(CONFIG)
        main = editorproject.program(cfg, CONFIG)
        demo = read(os.path.join(EXAMPLE, "drive_demo.st"))
        for line in main.split("END_VAR")[0].splitlines()[2:]:
            self.assertIn(line.strip(), demo)
        _, body = axis.glue(cfg, editorproject.declarations(cfg, CONFIG))
        for line in body:
            self.assertIn(line, demo)

    def test_text_block(self):
        cfg = load(CONFIG)
        text = axis.text_block(cfg, editorproject.declarations(cfg, CONFIG))
        self.assertTrue(text.startswith("VAR\n  drive        : AXIS_REF_SM3; (* node drive (4): CiA 402 axis *)\n"
                                        "  drive_bridge : SM_Drive_GenericDS402;"), text)
        self.assertIn("END_VAR\n\n(* First lines of the program body: *)\n" + axis.BODY_HEAD, text)


class MapObjects(unittest.TestCase):
    def info(self, path):
        return server.eds_summary(Eds.read(path))

    def test_example_layout(self):
        node = {"node_id": 4, "name": "drive", "eds": "servo402.eds", "axis": {}}
        new, mapped, missing = cia402map.map_objects(node, self.info(os.path.join(EXAMPLE, "servo402.eds")), set())
        layout_of = {k: [(p["number"], [e["index"] for e in p["entries"]]) for p in new[k]] for k in ("tx_pdos", "rx_pdos")}
        self.assertEqual(layout_of, {
            "tx_pdos": [(1, ["0x6041", "0x6061"]), (2, ["0x6064"]), (3, ["0x606C"]), (4, ["0x6077"])],
            "rx_pdos": [(1, ["0x6040", "0x6060"]), (2, ["0x607A", "0x6081"]), (3, ["0x60FF"]), (4, ["0x6071"])]})
        self.assertEqual(new["tx_pdos"][0]["entries"][0],
                         {"index": "0x6041", "subindex": 0, "type": "UNSIGNED16", "iec_location": "%IW100"})
        self.assertEqual(new["status_location"], "%IX100.0")
        self.assertEqual(missing, [])
        self.assertEqual(len(mapped), 12)
        self.assertNotIn("transmission", json.dumps(new))  # the EDS's own values stay
        self.assertNotIn("tx_pdos", node)  # the input is left alone
        # Again: nothing new.
        again, mapped, missing = cia402map.map_objects(new, self.info(os.path.join(EXAMPLE, "servo402.eds")), set())
        self.assertEqual((again, mapped, missing), (new, [], []))

    def test_keeps_existing_entries_and_locations(self):
        node = {"node_id": 4, "eds": "x.eds", "axis": {}, "status_location": "%IX10.0",
                "tx_pdos": [{"number": 1, "entries": [{"index": "0x6041", "subindex": 0, "type": "UNSIGNED16",
                                                       "iec_location": "%IW100"}]}]}
        used = layout.taken({"nodes": [node]}, [])
        new, mapped, _ = cia402map.map_objects(node, self.info(os.path.join(EXAMPLE, "servo402.eds")), used)
        self.assertEqual(new["tx_pdos"][0]["entries"][1]["iec_location"], "%IB100")
        self.assertEqual(new["tx_pdos"][1]["entries"][0]["iec_location"], "%ID100")
        self.assertNotIn("0x6041", [m["index"] for m in mapped])
        self.assertEqual(new["status_location"], "%IX10.0")

    def test_cyclic_layout(self):
        node = {"node_id": 4, "name": "drive", "eds": "servo402.eds", "axis": {"cyclic": True}, "heartbeat_ms": 100}
        changes = []
        new, _, missing = cia402map.map_objects(node, self.info(os.path.join(EXAMPLE, "servo402.eds")), set(),
                                                changes=changes)
        layout_of = {k: [(p["number"], p.get("transmission"), [e["index"] for e in p["entries"]]) for p in new[k]]
                     for k in ("tx_pdos", "rx_pdos")}
        self.assertEqual(layout_of, {
            "tx_pdos": [(1, 1, ["0x6041", "0x6061", "0x6064"]), (2, 1, ["0x606C", "0x6077"])],
            "rx_pdos": [(1, 1, ["0x6040", "0x6060", "0x607A"]), (2, 1, ["0x60FF", "0x6071"]), (3, 1, ["0x6081"])]})
        self.assertEqual(missing, [])
        self.assertEqual(sorted(c["pdo"] for c in changes), ["RPDO1", "RPDO2", "RPDO3", "TPDO1", "TPDO2"])
        cfg = load(CYCLIC)
        cfg["nodes"] = [new]
        self.assertEqual(contract_messages(cfg), ([], []))
        # A PDO already synchronous in the config is not changed again.
        changes = []
        again, mapped, _ = cia402map.map_objects(new, self.info(os.path.join(EXAMPLE, "servo402.eds")), set(),
                                                 changes=changes)
        self.assertEqual((again, mapped, changes), (new, [], []))

    def test_fixed_mapping_device(self):
        node = {"node_id": 4, "eds": "fixed-drive.eds", "axis": {}}
        new, _, missing = cia402map.map_objects(node, self.info(os.path.join(DRIVES, "fixed-drive.eds")), set())
        self.assertEqual([(p["number"], [e["index"] for e in p["entries"]]) for p in new["rx_pdos"]],
                         [(1, ["0x6040"]), (3, ["0x607A"])])
        self.assertTrue(all("mapping" not in p for p in new["rx_pdos"] + new["tx_pdos"]))
        why = {m["index"]: m["reason"] for m in missing}
        self.assertEqual(why["0x60FF"], "no RPDO's fixed mapping has it")
        self.assertEqual(why["0x6081"], "not in the EDS")
        self.assertEqual(why["0x6061"], "the EDS does not let it be mapped in a TPDO")
        # The result passes the contract check apart from what is missing.
        cfg = {"schema_version": 1, "adapter": {"type": "socketcan", "interface": "can0", "bitrate": 500000},
               "master": {"node_id": 1}, "nodes": [dict(new, eds=os.path.join(DRIVES, "fixed-drive.eds"))]}
        r = contract.check_config(cfg, os.path.join(DRIVES, "x.json"))
        self.assertEqual(r.errors, [])


if __name__ == "__main__":
    unittest.main()


CYCLIC = os.path.join(EXAMPLE, "canopen_config_cyclic.json")


def contract_messages(cfg, path=CYCLIC):
    r = contract.check_config(cfg, path)
    return [m for m in r.errors], [m for m in r.warnings]


class Cyclic(unittest.TestCase):
    """Cyclic synchronous axes (add-cia402-cyclic-modes)."""

    def setUp(self):
        self.cfg = load(CYCLIC)

    def test_example_is_clean(self):
        self.assertEqual(contract_messages(self.cfg), ([], []))

    def test_interpolation_code(self):
        self.assertEqual(axis.interpolation_code(10000), (10, -3))
        self.assertEqual(axis.interpolation_code(2500), (25, -4))
        self.assertEqual(axis.interpolation_code(1000), (1, -3))
        self.assertEqual(axis.interpolation_code(125), (125, -6))
        self.assertIsNone(axis.interpolation_code(333))
        self.assertIsNone(axis.interpolation_code(0))

    def test_needs_plc_cycle_sync(self):
        self.cfg["master"]["sync_source"] = "timer"
        self.cfg["master"]["sync_period_us"] = 10000
        errors, _ = run_check(self.cfg)
        self.assertEqual(len(errors), 1)
        self.assertIn("needs SYNC from the PLC cycle", errors[0])
        del self.cfg["master"]["sync_source"]
        errors, _ = run_check(self.cfg)
        self.assertIn("needs SYNC from the PLC cycle", errors[0])

    def test_needs_one_sync_per_cycle(self):
        self.cfg["master"]["sync_cycles"] = 2
        errors, _ = run_check(self.cfg)
        self.assertEqual(len(errors), 1)
        self.assertIn("'sync_cycles' 1, not 2", errors[0])

    def test_needs_mode_and_set_point(self):
        drop(self.cfg, "0x6060")
        errors, _ = run_check(self.cfg)
        self.assertTrue(any("needs 0x6060 (modes of operation) in an RPDO" in e for e in errors), errors)
        cfg = load(CYCLIC)
        for index in ("0x607A", "0x60FF", "0x6071"):
            drop(cfg, index)
        errors, _ = run_check(cfg)
        self.assertTrue(any("needs a set-point in an RPDO" in e for e in errors), errors)

    def test_bad_interpolation_period(self):
        self.cfg["nodes"][0]["axis"]["interpolation_period_us"] = 333
        errors, _ = run_check(self.cfg)
        self.assertEqual(len(errors), 1)
        self.assertIn("'interpolation_period_us' 333 cannot be written to 0x60C2", errors[0])
        self.cfg["nodes"][0]["axis"]["interpolation_period_us"] = 2500
        self.assertEqual(run_check(self.cfg), ([], []))

    def test_schema_range(self):
        for bad in (50, 255001):
            cfg = load(CYCLIC)
            cfg["nodes"][0]["axis"]["interpolation_period_us"] = bad
            errors, _ = contract_messages(cfg)
            self.assertTrue(errors, bad)

    def test_rpdo_must_be_synchronous(self):
        self.cfg["nodes"][0]["rx_pdos"][1]["transmission"] = 255
        errors, _ = contract_messages(self.cfg)
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("RPDO 2 (0x60FF, 0x6071) has transmission type 255", errors[0])

    def test_tpdo_feedback_warning(self):
        self.cfg["nodes"][0]["tx_pdos"][0]["transmission"] = 255
        errors, warnings = contract_messages(self.cfg)
        self.assertEqual(errors, [])
        self.assertEqual(len(warnings), 1, warnings)
        self.assertIn("TPDO 1 (0x6064) has transmission type 255", warnings[0])

    def test_eds_warnings(self):
        # servo402.eds has 0x60C2, 0x6065 and every mode; the wrapper below
        # takes 0x60C2 and 0x6065 away and lists only modes 1, 3 and 6.
        eds = Eds.read(os.path.join(EXAMPLE, "servo402.eds"))
        cfg_node = self.cfg["nodes"][0]
        parsed = {"node_id": 4, "rx_pdos": [], "tx_pdos": []}
        self.assertEqual(axis.cyclic_eds_check(cfg_node, parsed, eds), ([], []))

        class Without:
            def __init__(self, eds, gone, modes=None):
                self.eds, self.gone, self.modes = eds, gone, modes

            def has(self, index, sub=None):
                return index not in self.gone and self.eds.has(index)

            def find(self, index, sub):
                if index == 0x6502 and self.modes is not None:
                    class O:
                        def value(_, node_id):
                            return self.modes
                    return O()
                return None if index in self.gone else self.eds.find(index, sub)

        _, warnings = axis.cyclic_eds_check(cfg_node, parsed, Without(eds, (0x60C2, 0x6065), 0x25))
        text = " | ".join(m for m, _ in warnings)
        self.assertIn("no 0x60C2 (interpolation time period)", text)
        self.assertIn("no 0x6065 (following error window)", text)
        self.assertIn("does not list cyclic synchronous position (mode 8)", text)
        self.assertIn("does not list cyclic synchronous torque (mode 10)", text)

    def test_not_cyclic_no_checks(self):
        del self.cfg["nodes"][0]["axis"]["cyclic"]
        self.cfg["master"]["sync_source"] = "timer"
        self.cfg["master"]["sync_period_us"] = 10000
        self.assertEqual(run_check(self.cfg), ([], []))

    def test_two_networks(self):
        drive = load(CYCLIC)
        io = load(CYCLIC)
        del io["nodes"][0]["axis"]["cyclic"]
        io["master"] = {"node_id": 1, "sync_period_us": 10000}
        cfg = {"schema_version": 2,
               "networks": [dict(name="io", adapter=dict(io["adapter"], interface="can1"), master=io["master"],
                                 nodes=io["nodes"]),
                            dict(name="drives", adapter=drive["adapter"], master=drive["master"],
                                 nodes=drive["nodes"])]}
        for n in cfg["networks"][0]["nodes"]:
            for key in ("status_location",):
                n[key] = "%IX20.0"
            for p in n["tx_pdos"] + n["rx_pdos"]:
                for e in p["entries"]:
                    e["iec_location"] = e["iec_location"].replace("10", "20", 1)
        errors, _ = contract_messages(cfg)
        self.assertEqual(errors, [])
        # The cyclic axis on the timer network is refused there.
        cfg["networks"][0]["nodes"][0]["axis"]["cyclic"] = True
        errors, _ = contract_messages(cfg)
        self.assertEqual(len(errors), 1, errors)
        self.assertIn(": networks[0]: nodes[0]: ", errors[0])
        self.assertIn("needs SYNC from the PLC cycle", errors[0])


class CyclicGlue(unittest.TestCase):
    def test_cycle_time_from_the_interval(self):
        cfg = load(CYCLIC)
        _, body = editorproject.with_axes(cfg, editorproject.declarations(cfg, CYCLIC), "T#2ms")
        self.assertIn("drive.fCycleTime := LREAL#0.002; (* the task interval: change it with the interval *)", body)
        _, body = editorproject.with_axes(cfg, editorproject.declarations(cfg, CYCLIC), "T#10ms")
        self.assertIn("drive.fCycleTime := LREAL#0.01; (* the task interval: change it with the interval *)", body)

    def test_profile_axis_has_no_cycle_time(self):
        cfg = load(CONFIG)
        _, body = editorproject.with_axes(cfg, editorproject.declarations(cfg, CONFIG), "T#2ms")
        self.assertFalse(any("fCycleTime" in b for b in body))

    def test_uses_library(self):
        self.assertTrue(editorproject.uses_library(load(CYCLIC)))
        self.assertFalse(editorproject.uses_library(load(CONFIG)))
