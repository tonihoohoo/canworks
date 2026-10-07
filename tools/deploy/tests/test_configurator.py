"""The configurator's shared pieces: EDS metadata, error paths, the project
location scan, address suggestion, PDO packing and declarations
(add-canopen-configurator tasks 2.1-2.5)."""

import copy
import json
import os
import unittest

from openplc_canopen_deploy import contract
from openplc_canopen_deploy.configurator import declare, layout, scan
from openplc_canopen_deploy.eds import Eds

from .helpers import PINGPONG, REPO, pingpong_config, tmpdir

RTD = os.path.join(REPO, "config", "rtd-sensor")
FIXTURE = os.path.join(REPO, "test", "fixtures", "editor-project")


def rtd_config():
    with open(os.path.join(RTD, "canopen_config.json"), encoding="utf-8") as f:
        return json.load(f)


class EdsMetadata(unittest.TestCase):
    def test_rtd_input(self):
        eds = Eds.read(os.path.join(RTD, "rtd8.eds"))
        o = eds.find(0x7130, 1)
        self.assertEqual(o.name, "AI0_Input_PV")
        self.assertEqual(o.type_name, "INTEGER16")
        self.assertEqual(o.directions, ("input",))
        self.assertIn((0x7130, 1, o), eds.mappable())
        self.assertEqual(eds.pdo_count("input"), 4)
        self.assertEqual(eds.pdo_count("output"), 0)

    def test_rtd_writable_sensor_type(self):
        o = Eds.read(os.path.join(RTD, "rtd8.eds")).find(0x6110, 1)
        self.assertEqual((o.name, o.type_name, o.access, o.default), ("AI0_Sensor_Type", "UNSIGNED16", "rw", "0x1E"))
        self.assertTrue(o.writable)

    def test_pingpong_directions(self):
        eds = Eds.read(os.path.join(PINGPONG, "cpp-slave.eds"))
        by = {(i, s): o for i, s, o in eds.mappable()}
        self.assertEqual(by[(0x4000, 0)].directions, ("output",))
        self.assertEqual(by[(0x4001, 0)].directions, ("input",))
        self.assertEqual(eds.find(0x4001, 0).name, "UNSIGNED32 sent from slave")
        # 0x1018 is not PDO-mappable: never offered.
        self.assertNotIn(0x1018, {i for i, _, _ in eds.mappable()})

    def test_direction_rules(self):
        from openplc_canopen_deploy.eds import SubObject
        self.assertEqual(SubObject(7, "rw", True).directions, ("input", "output"))
        self.assertEqual(SubObject(7, "rwr", True).directions, ("input",))
        self.assertEqual(SubObject(7, "rww", True).directions, ("output",))
        self.assertEqual(SubObject(7, "wo", True).directions, ("output",))
        self.assertEqual(SubObject(7, "const", True).directions, ())
        self.assertEqual(SubObject(7, "ro", False).directions, ())


class ErrorPaths(unittest.TestCase):
    def setUp(self):
        self.dir = tmpdir(self)
        self.path = pingpong_config(self.dir)
        with open(self.path, encoding="utf-8") as f:
            self.cfg = json.load(f)

    def paths(self, cfg):
        r = contract.check_config(cfg, self.path)
        self.assertEqual(r.errors, [i["message"] for i in r.items if i["level"] == "error"])
        return [(i["message"], i["paths"]) for i in r.items if i["level"] == "error"]

    def test_type_mismatch(self):
        self.cfg["nodes"][0]["tx_pdos"][0]["entries"][0]["iec_location"] = "%IW100"
        [(msg, paths)] = self.paths(self.cfg)
        self.assertIn("does not fit location %IW100", msg)
        self.assertEqual(paths, ["nodes[0].tx_pdos[0].entries[0].iec_location"])

    def test_duplicate_node_id(self):
        second = copy.deepcopy(self.cfg["nodes"][0])
        second["tx_pdos"][0]["entries"][0]["iec_location"] = "%ID101"
        second["rx_pdos"][0]["entries"][0]["iec_location"] = "%QD101"
        second["status_location"] = "%IX10.1"
        self.cfg["nodes"].append(second)
        found = self.paths(self.cfg)
        dup = [p for m, p in found if "used by more than one slave" in m]
        self.assertEqual(dup, [["nodes[0].node_id", "nodes[1].node_id"]])

    def test_sdo_range(self):
        self.cfg["nodes"][0]["sdo"] = [{"index": "0x1017", "subindex": 0, "type": "UNSIGNED8", "value": 300}]
        [(msg, paths)] = self.paths(self.cfg)
        self.assertIn("does not fit UNSIGNED8", msg)
        self.assertEqual(paths, ["nodes[0].sdo[0].value"])

    def test_eds_errors_point_at_the_entry(self):
        self.cfg["nodes"][0]["sdo"] = [{"index": "0x1018", "subindex": 1, "type": "UNSIGNED32", "value": 1}]
        [(msg, paths)] = self.paths(self.cfg)
        self.assertIn("startup SDO needs a writable object", msg)
        self.assertEqual(paths, ["nodes[0].sdo[0]"])

    def test_schema_error_path(self):
        self.cfg["adapter"]["bitrate"] = 300000
        found = self.paths(self.cfg)
        self.assertEqual(found[0][1], ["adapter.bitrate"])


class ProjectScan(unittest.TestCase):
    def test_fixture(self):
        uses, problems = scan.scan(FIXTURE)
        self.assertEqual(problems, [])
        got = {(u.file, str(u.loc), u.kind, u.name) for u in uses}
        self.assertEqual(got, {
            ("project.json", "%IW120", "variable", "ai_spare"),
            ("devices/pin-mapping.json", "%IX0.0", "device", None),
            ("devices/pin-mapping.json", "%QX0.0", "device", None),
            ("devices/remote/ecat-bus.json", "%ID100", "device", "drive1"),
            ("devices/remote/ecat-bus.json", "%QD100", "device", "drive1"),
            ("devices/remote/io-rack.json", "%IW200", "device", "ai0"),
            ("devices/remote/io-rack.json", "%IW201", "device", "ai1"),
            ("devices/remote/io-rack.json", "%QX20.0", "device", "do0"),
            ("pous/programs/main.st", "%IX10.1", "variable", "door_ok"),
        })
        # The alias-bound variable run_lamp ("lamp") is not a location.
        self.assertNotIn("run_lamp", {u.name for u in uses})

    def test_skips_canopen_and_build(self):
        d = tmpdir(self)
        for sub in ("canopen", "build"):
            os.makedirs(os.path.join(d, sub))
            with open(os.path.join(d, sub, "x.json"), "w") as f:
                json.dump({"iec_location": "%IW1"}, f)
        self.assertEqual(scan.scan(d)[0], [])

    def test_editor_style_declaration(self):
        d = tmpdir(self)
        os.makedirs(os.path.join(d, "pous", "programs"))
        with open(os.path.join(d, "pous", "programs", "main.st"), "w") as f:
            f.write("PROGRAM main\n  VAR\n    rtd1 : INT AT %IW100;\n    s : STRING(8) AT %MD4; (* text *)\n"
                    "    old AT %IX1.0 : BOOL;\n  END_VAR\nEND_PROGRAM\n")
        got = {(str(u.loc), u.name) for u in scan.scan(d)[0]}
        self.assertEqual(got, {("%IW100", "rtd1"), ("%MD4", "s"), ("%IX1.0", "old")})
        cfg = rtd_config()
        _, declared = layout.project_checks(cfg, scan.scan(d)[0], False)
        self.assertEqual(declared["nodes[0].tx_pdos[0].entries[0].iec_location"], "rtd1")

    def test_unreadable_json_is_reported(self):
        d = tmpdir(self)
        with open(os.path.join(d, "project.json"), "w") as f:
            f.write("{nope")
        uses, problems = scan.scan(d)
        self.assertEqual(uses, [])
        self.assertIn("project.json: not readable JSON", problems[0])

    def test_empty_json_is_skipped_quietly(self):
        d = tmpdir(self)
        for name, text in (("empty.json", ""), ("blank.json", " \n")):
            with open(os.path.join(d, name), "w") as f:
                f.write(text)
        self.assertEqual(scan.scan(d), ([], []))


class Layout(unittest.TestCase):
    def test_next_free_word_skips_project_and_config(self):
        uses, _ = scan.scan(FIXTURE)
        cfg = {"nodes": [{"tx_pdos": [{"entries": [{"type": "INTEGER16", "iec_location": "%IW100"}]}]}]}
        used = layout.taken(cfg, uses)
        self.assertEqual(layout.suggest("I", "W", used), "%IW101")
        self.assertEqual(layout.suggest("I", "W", used, start=200), "%IW202")
        self.assertEqual(layout.suggest("I", "W", used, start=120), "%IW121")

    def test_tables_are_independent(self):
        uses, _ = scan.scan(FIXTURE)
        used = layout.taken({"nodes": []}, uses)
        # %ID100 (EtherCAT) does not take %IW100.
        self.assertEqual(layout.suggest("I", "W", used), "%IW100")
        self.assertEqual(layout.suggest("I", "D", used), "%ID101")
        self.assertEqual(layout.suggest("I", "X", used, start=10), "%IX10.0")
        used.add(("I", "X", 80))
        self.assertEqual(layout.suggest("I", "X", used, start=10), "%IX10.2")

    def test_pack(self):
        entry = {"type": "UNSIGNED8"}
        self.assertEqual(layout.pack([], "INTEGER16", 4), (0, None))
        self.assertEqual(layout.pack([{"entries": [entry] * 7}], "UNSIGNED8", 4), (0, None))
        self.assertEqual(layout.pack([{"entries": [entry] * 8}], "UNSIGNED8", 4), (1, None))
        self.assertEqual(layout.pack([{"entries": [{"type": "UNSIGNED32"}]}], "UNSIGNED64", 4), (1, None))
        full = [{"entries": [{"type": "UNSIGNED64"}]}] * 4
        pdo, reason = layout.pack(full, "BOOLEAN", 4)
        self.assertIsNone(pdo)
        self.assertIn("all 4 PDOs", reason)
        self.assertIn("no PDO", layout.pack([], "BOOLEAN", 0)[1])

    def test_project_checks(self):
        uses, _ = scan.scan(FIXTURE)
        cfg = {"nodes": [{"status_location": "%IX10.1", "tx_pdos": [{"entries": [
            {"type": "INTEGER32", "iec_location": "%ID100"}, {"type": "INTEGER16", "iec_location": "%IW120"}]}]}]}
        items, declared = layout.project_checks(cfg, uses)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["level"], "error")
        self.assertEqual(items[0]["paths"], ["nodes[0].tx_pdos[0].entries[0].iec_location"])
        self.assertIn("devices/remote/ecat-bus.json", items[0]["message"])
        self.assertEqual(declared, {"nodes[0].status_location": "door_ok",
                                    "nodes[0].tx_pdos[0].entries[1].iec_location": "ai_spare"})
        items, _ = layout.project_checks(cfg, uses, allow_overlap=True)
        self.assertEqual(items[0]["level"], "warning")


class Declarations(unittest.TestCase):
    def test_rtd(self):
        cfg = rtd_config()
        eds = Eds.read(os.path.join(RTD, "rtd8.eds"))

        def name(i, index, sub):
            o = eds.find(index, sub)
            return o.name if o else None

        decls = declare.declarations(cfg, name, {})
        got = [(d["location"], d["type"]) for d in decls]
        self.assertEqual(got, [("%IX10.0", "BOOL")] + [("%%IW%d" % n, "INT") for n in range(100, 104)]
                         + [("%%IB%d" % n, "USINT") for n in range(100, 104)])
        self.assertEqual(decls[1]["name"], "rtd_AI0_Input_PV")
        self.assertEqual(len({d["name"] for d in decls}), len(decls))
        block = declare.st_block(decls)
        self.assertTrue(block.startswith("VAR\n"))
        self.assertIn("rtd_AI0_Input_PV AT %IW100 : INT;", block)

    def test_state_byte(self):
        cfg = rtd_config()
        cfg["nodes"][0]["state_location"] = "%IB20"
        decls = declare.declarations(cfg, lambda *a: None, {})
        self.assertIn(("rtd_state", "%IB20", "USINT"), [(d["name"], d["location"], d["type"]) for d in decls])
        uses = {path: str(loc) for path, loc in layout.canopen_uses(cfg)}
        self.assertEqual(uses["nodes[0].state_location"], "%IB20")

    def test_boot_error_and_master_state(self):
        cfg = rtd_config()
        cfg["nodes"][0]["boot_error_location"] = "%IB21"
        cfg["master"]["state_location"] = "%IB22"
        decls = declare.declarations(cfg, lambda *a: None, {})
        rows = [(d["name"], d["location"], d["type"]) for d in decls]
        self.assertIn(("rtd_boot_err", "%IB21", "USINT"), rows)
        self.assertIn(("can_master_state", "%IB22", "USINT"), rows)
        uses = {path: str(loc) for path, loc in layout.canopen_uses(cfg)}
        self.assertEqual(uses["nodes[0].boot_error_location"], "%IB21")
        self.assertEqual(uses["master.state_location"], "%IB22")

    def test_bus_diagnostics(self):
        cfg = rtd_config()
        cfg["master"].update(bus_state_location="%IB120", tx_error_count_location="%IB121",
                             rx_error_count_location="%IB122", bus_off_count_location="%IW120")
        decls = declare.declarations(cfg, lambda *a: None, {"master.rx_error_count_location": "rxe"})
        rows = [(d["name"], d["location"], d["type"], d["declared_as"]) for d in decls[:4]]
        self.assertEqual(rows, [("can_bus_state", "%IB120", "USINT", None), ("can_tx_errors", "%IB121", "USINT", None),
                                ("can_rx_errors", "%IB122", "USINT", "rxe"), ("can_bus_offs", "%IW120", "UINT", None)])
        uses = {path: str(loc) for path, loc in layout.canopen_uses(cfg)}
        self.assertEqual(uses["master.bus_state_location"], "%IB120")
        self.assertEqual(uses["master.bus_off_count_location"], "%IW120")
        self.assertIn(("I", "B", 120), layout.taken(cfg, []))

    def test_emcy_inputs(self):
        cfg = rtd_config()
        cfg["nodes"][0]["emcy_code_location"] = "%IW30"
        cfg["nodes"][0]["error_register_location"] = "%IB31"
        decls = declare.declarations(cfg, lambda *a: None, {})
        rows = [(d["name"], d["location"], d["type"]) for d in decls]
        self.assertIn(("rtd_emcy", "%IW30", "WORD"), rows)
        self.assertIn(("rtd_errreg", "%IB31", "BYTE"), rows)
        uses = {path: str(loc) for path, loc in layout.canopen_uses(cfg)}
        self.assertEqual((uses["nodes[0].emcy_code_location"], uses["nodes[0].error_register_location"]),
                         ("%IW30", "%IB31"))

    def test_sdo_variables_and_nmt(self):
        cfg = rtd_config()
        cfg["nodes"][0]["nmt_command_location"] = "%QB20"
        cfg["nodes"][0]["sdo_variables"] = [
            {"name": "sensor type", "index": "0x6110", "subindex": 1, "type": "UNSIGNED16", "direction": "write",
             "iec_location": "%QW20", "trigger_location": "%QX21.0", "status_location": "%IB21",
             "abort_code_location": "%ID21"},
            {"index": "0x1018", "subindex": 1, "type": "UNSIGNED32", "direction": "read", "iec_location": "%ID22"}]
        decls = declare.declarations(cfg, lambda i, index, sub: "Vendor-ID" if index == 0x1018 else None,
                                     {"nodes[0].sdo_variables[0].status_location": "st"})
        rows = [(d["name"], d["location"], d["type"], d["declared_as"]) for d in decls]
        self.assertIn(("rtd_nmt", "%QB20", "USINT", None), rows)
        self.assertEqual(rows[-5:], [("rtd_sensor_type", "%QW20", "UINT", None),
                                     ("rtd_sensor_type_trig", "%QX21.0", "BOOL", None),
                                     ("rtd_sensor_type_status", "%IB21", "USINT", "st"),
                                     ("rtd_sensor_type_abort", "%ID21", "UDINT", None),
                                     ("rtd_Vendor_ID", "%ID22", "UDINT", None)])
        uses = {path: str(loc) for path, loc in layout.canopen_uses(cfg)}
        self.assertEqual(uses["nodes[0].nmt_command_location"], "%QB20")
        self.assertEqual(uses["nodes[0].sdo_variables[0].trigger_location"], "%QX21.0")
        self.assertEqual(uses["nodes[0].sdo_variables[1].iec_location"], "%ID22")
        self.assertIn(("Q", "X", 168), layout.taken(cfg, []))

    def test_declared_entries_left_out(self):
        cfg = rtd_config()
        decls = declare.declarations(cfg, lambda *a: None, {"nodes[0].tx_pdos[0].entries[0].iec_location": "t1"})
        self.assertEqual(decls[1]["declared_as"], "t1")
        self.assertNotIn("%IW100", declare.st_block(decls))

    def test_program_order_and_descriptions(self):
        cfg = rtd_config()
        cfg["master"]["bus_state_location"] = "%IB120"
        cfg["nodes"][0]["nmt_command_location"] = "%QB20"
        cfg["nodes"][0]["sdo_variables"] = [
            {"name": "sensor type", "index": "0x6110", "subindex": 1, "type": "UNSIGNED16", "direction": "write",
             "iec_location": "%QW20", "status_location": "%IB21"}]
        cfg["nodes"].append({"node_id": 23, "name": "valve", "eds": "x.eds", "status_location": "%IX10.1",
                             "rx_pdos": [{"number": 1, "entries": [
                                 {"index": "0x6200", "subindex": 1, "type": "UNSIGNED8", "iec_location": "%QB30"}]}],
                             "tx_pdos": [{"number": 1, "entries": [
                                 {"index": "0x6000", "subindex": 1, "type": "UNSIGNED8", "iec_location": "%IB30"}]}]})
        eds = Eds.read(os.path.join(RTD, "rtd8.eds"))

        def name(i, index, sub):
            if i == 1:
                return "Out (1)" if index == 0x6200 else None
            o = eds.find(index, sub)
            return o.name if o else None

        decls = declare.program_order(declare.declarations(cfg, name, {}))
        self.assertEqual([d["location"] for d in decls], [
            "%IB120", "%IX10.0", "%IW100", "%IW101", "%IW102", "%IW103", "%IB100", "%IB101", "%IB102", "%IB103",
            "%IB21", "%QW20", "%QB20", "%IX10.1", "%IB30", "%QB30"])
        by = {d["location"]: d["description"] for d in decls}
        self.assertEqual(by["%IB120"], "CAN bus state")
        self.assertEqual(by["%IX10.0"], "node rtd (5): operational")
        self.assertEqual(by["%IW100"], "node rtd (5) TPDO1 0x7130:1 %s" % eds.find(0x7130, 1).name)
        self.assertEqual(by["%QB30"], "node valve (23) RPDO1 0x6200:1 Out (1)")
        self.assertEqual(by["%IB30"], "node valve (23) TPDO1 0x6000:1")
        self.assertEqual(by["%QW20"], "node rtd (5) SDO write 0x6110:1 AI0_Sensor_Type")
        self.assertEqual(by["%IB21"], "node rtd (5) SDO write 0x6110:1 AI0_Sensor_Type, status")
        self.assertEqual(by["%QB20"], "node rtd (5): NMT command")
        block = declare.editor_block(decls)
        self.assertIn("\n    rtd_ok", block)
        self.assertTrue(block.startswith("  VAR\n") and block.endswith("\n  END_VAR"))
        self.assertIn(" : USINT AT %QB30; (* node valve (23) RPDO1 0x6200:1 Out (1) *)", block)
        self.assertEqual(declare.editor_block([]), "  VAR\n  END_VAR")
        self.assertEqual(declare.comment_text("a *) b\n(* c"), "a * ) b ( * c")

    def test_identifiers(self):
        self.assertEqual(declare.identifier("AI0 Input (PV)"), "AI0_Input_PV")
        self.assertEqual(declare.identifier("9lives"), "n9lives")
        self.assertEqual(declare.identifier("a__b"), "a_b")
        decls = declare.declarations({"nodes": [{"node_id": 3, "tx_pdos": [{"entries": [
            {"index": "0x6000", "subindex": 1, "type": "BOOLEAN", "iec_location": "%IX1.0"},
            {"index": "0x6000", "subindex": 2, "type": "BOOLEAN", "iec_location": "%IX1.1"}]}]}]},
            lambda *a: "In", {})
        self.assertEqual([d["name"] for d in decls], ["node3_In", "node3_In_2"])


if __name__ == "__main__":
    unittest.main()
