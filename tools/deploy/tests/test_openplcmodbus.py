"""OpenPLC through its Modbus master (canworks.openplcmodbus and the map hash
of canworks.modbusmap): the hash both sides compute, the editor's remote
device file, the generated programs and the project changes. The ST of the
programs is compiled and run by test/plc_modbus/run.sh."""

import copy
import json
import os
import shutil
import tempfile
import unittest
import zlib

from canworks import editorproject, modbusmap, openplcmodbus

from .test_contract import REPO

EXAMPLE = os.path.join(REPO, "examples", "openplc-modbus", "canworks.json")
HASH_TEXT = os.path.join(REPO, "test", "fixtures", "modbus", "openplc-hash.txt")
EDITOR_PROJECT = os.path.join(REPO, "test", "fixtures", "editor-project")


def load(path=EXAMPLE):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def decls(cfg, path=EXAMPLE):
    return editorproject.declarations(cfg, path)


class MapHash(unittest.TestCase):
    def test_crc_vector(self):
        self.assertEqual(zlib.crc32(b"123456789"), 0xCBF43926)

    def test_text_shared_with_the_bridge(self):
        # test/bridge/bridge_host_tests.cpp (map_hash_vectors) checks the same text.
        with open(HASH_TEXT, encoding="utf-8") as f:
            self.assertEqual(modbusmap.map_hash_text(load()), f.read())
        self.assertEqual(modbusmap.map_hash(load()), 0xD4FDFC35)

    def test_rename_keeps_and_move_changes_it(self):
        cfg = load()
        h = modbusmap.map_hash(cfg)
        renamed = copy.deepcopy(cfg)
        renamed["networks"][0]["nodes"][0]["name"] = "temps"
        self.assertEqual(modbusmap.map_hash(renamed), h)
        moved = copy.deepcopy(cfg)
        entry = moved["networks"][0]["nodes"][0]["tx_pdos"][0]["entries"][3]
        self.assertEqual(entry["iec_location"], "%IW18")
        moved["bridge"]["live_lists"][0]["location"] = "%IB54"
        moved["bridge"]["sdo_bridge_location"]["response"] = "%IB70"
        self.assertNotEqual(modbusmap.map_hash(moved), h)

    def test_openplc_blocks_in_the_map(self):
        rows = {r["name"]: r for r in modbusmap.register_map(load())}
        self.assertEqual((rows["bridge.map_hash"]["address"], rows["bridge.map_hash"]["count"]), (0, 2))
        self.assertEqual((rows["bridge.status"]["address"], rows["bridge.status"]["count"]), (2, 4))
        self.assertEqual(rows["bridge.plc_link"]["table"], "holding register")
        self.assertEqual((rows["bridge.plc_link"]["address"], rows["bridge.plc_link"]["count"]), (0, 3))

    def test_exports_carry_it(self):
        cfg = load()
        rows = modbusmap.register_map(cfg)
        self.assertEqual(json.loads(modbusmap.to_json(cfg, rows))["map_hash"], "0xd4fdfc35")
        self.assertIn("map hash 0xd4fdfc35", modbusmap.to_st(cfg, rows))

    def test_pack_keeps_the_header_free(self):
        cfg = load()
        bridge = cfg["bridge"]
        bridge["control_location"] = "%QB0"
        bridge["live_lists"][0]["location"] = "%IB0"
        packed = modbusmap.pack(cfg)
        uses = modbusmap.map_hash_text(packed).splitlines()
        self.assertEqual(uses[:2], ["I 0 4 -", "I 4 8 -"])
        self.assertIn("Q 0 6 -", uses)
        self.assertEqual([u for u in uses if u.startswith("Q ")][1].split()[1], "6")
        modbusmap.register_map(packed)


class RemoteDevice(unittest.TestCase):
    def setUp(self):
        self.cfg = load()
        self.dev = openplcmodbus.remote_device(self.cfg, decls(self.cfg))
        self.groups = self.dev["modbusTcpConfig"]["ioGroups"]

    def test_device(self):
        self.assertEqual(self.dev["name"], "canworks")
        self.assertEqual(self.dev["protocol"], "modbus-tcp")
        tcp = self.dev["modbusTcpConfig"]
        self.assertEqual((tcp["host"], tcp["port"], tcp["slaveId"], tcp["timeout"]), ("127.0.0.1", 1502, 1, 1000))

    def test_header_first(self):
        g = self.groups[0]
        self.assertEqual((g["functionCode"], g["offset"], g["length"]), ("16", "0", 3))

    def test_groups(self):
        got = [(g["functionCode"], int(g["offset"]), g["length"], g["errorHandling"]) for g in self.groups]
        self.assertEqual(got, [
            ("16", 0, 3, "keep-last-value"),
            ("4", 0, 6, "set-to-zero"),      # hash and status
            ("4", 6, 12, "keep-last-value"),  # every PDO and diagnostic, contiguous
            ("4", 18, 15, "set-to-zero"),    # live list and SDO response
            ("16", 3, 13, "keep-last-value"),  # outputs, control block, SDO request
        ])
        self.assertTrue(all(g["cycleTime"] == 10 for g in self.groups))
        self.assertEqual(openplcmodbus.request_count(openplcmodbus.layout(self.cfg, decls(self.cfg))[0]), 5)

    def test_points(self):
        points = [p for g in self.groups for p in g["ioPoints"]]
        inputs = [p["iecLocation"] for p in points if p["iecLocation"].startswith("%IW")]
        outputs = [p["iecLocation"] for p in points if p["iecLocation"].startswith("%QW")]
        self.assertEqual(inputs, ["%%IW%d" % (100 + k) for k in range(33)])
        self.assertEqual(sorted(outputs, key=lambda x: int(x[3:])), ["%%QW%d" % (100 + k) for k in range(16)])
        aliases = {p["iecLocation"]: p["alias"] for p in points}
        self.assertEqual(aliases["%IW106"], "rtd_AI0_Input_PV")
        self.assertEqual(aliases["%IW101"], "cw_map_hash_w1")
        self.assertEqual(aliases["%QW100"], "cw_plc_link")
        self.assertTrue(all(p["type"] == "Analog Input (Input Register)" for g in self.groups
                            if g["functionCode"] == "4" for p in g["ioPoints"]))

    def test_iec_base_and_settings(self):
        cfg = load()
        cfg["bridge"]["openplc"] = {"poll_ms": 20, "remote_device": "can_bus", "iec_base": 300}
        cfg["bridge"]["listen"] = "127.0.0.1:1600"
        dev = openplcmodbus.remote_device(cfg, decls(cfg), iec_base=300)
        self.assertEqual(dev["name"], "can_bus")
        self.assertEqual(dev["modbusTcpConfig"]["port"], 1600)
        self.assertEqual(dev["modbusTcpConfig"]["ioGroups"][0]["ioPoints"][0]["iecLocation"], "%QW300")
        self.assertEqual({g["cycleTime"] for g in dev["modbusTcpConfig"]["ioGroups"]}, {20})

    def test_stable_ids(self):
        again = openplcmodbus.remote_device(self.cfg, decls(self.cfg))
        self.assertEqual(again, self.dev)

    def test_long_runs_are_cut_between_values(self):
        saved = modbusmap.MAX_READ_REGISTERS
        modbusmap.MAX_READ_REGISTERS = 5
        try:
            groups, _ = openplcmodbus.layout(self.cfg, decls(self.cfg))
        finally:
            modbusmap.MAX_READ_REGISTERS = saved
        data = [(g.first, g.count) for g in groups if g.area == "I" and g.key == "data"]
        self.assertEqual(data, [(6, 5), (11, 5), (16, 2)])
        bridge = [(g.first, g.count) for g in groups if g.area == "I" and g.key == "bridge"]
        # a 16-byte live list (8 registers) is longer than one request: cut
        self.assertEqual(bridge, [(0, 2), (2, 4), (18, 5), (23, 3), (26, 5), (31, 2)])

    def test_budget_warning(self):
        many = [openplcmodbus.Group("I", "data", k * 2, "data") for k in range(41)]
        self.assertIn("41 Modbus requests per poll", openplcmodbus.budget_warning(many))
        self.assertIsNone(openplcmodbus.budget_warning(many[:40]))

    def test_not_openplc(self):
        cfg = load()
        del cfg["bridge"]["openplc"]
        with self.assertRaises(openplcmodbus.OpenplcError):
            openplcmodbus.remote_device(cfg, [])


class Programs(unittest.TestCase):
    def setUp(self):
        self.cfg = load()
        self.decls = decls(self.cfg)
        self.in_st, self.out_st = openplcmodbus.programs(self.cfg, self.decls)

    def test_shapes(self):
        self.assertTrue(self.in_st.startswith("PROGRAM canworks_in\n"))
        self.assertTrue(self.out_st.startswith("PROGRAM canworks_out\n"))
        self.assertIn("i6  : WORD AT %IW106;", self.in_st)
        self.assertIn("canworks.rtd_AI0_Input_PV := WORD_TO_INT(i6);", self.in_st)
        self.assertIn("canworks.ok := i0 = 16#D4FD AND i1 = 16#FC35 AND NOT stale.Q;", self.in_st)

    def test_header_written_last(self):
        lines = self.out_st.rstrip().splitlines()
        self.assertEqual(lines[-3:], ["q0 := 1;", "", "END_PROGRAM"])
        self.assertIn("q1 := 16#D4FD;", self.out_st)
        self.assertIn("q2 := 16#FC35;", self.out_st)

    def test_link_words(self):
        self.assertIn("canworks.link[21] := 16#0106 OR BOOL_TO_WORD(canworks.ok);", self.in_st)
        self.assertIn("canworks.link[25] := i18;", self.in_st)
        self.assertIn("q6 := canworks.link[4];", self.out_st)
        self.assertIn("q15 := canworks.link[13];", self.out_st)

    def test_shared_register(self):
        self.assertIn("q3 := SHL((USINT_TO_WORD(canworks.dio_Write_output_8_bit_1) AND 16#00FF), 8) OR "
                      "(USINT_TO_WORD(canworks.dio_Write_output_8_bit_2) AND 16#00FF);", self.out_st)

    def test_global_list(self):
        lst = openplcmodbus.global_list(self.decls)
        self.assertEqual(lst["name"], "canworks")
        names = [v["name"] for v in lst["variables"]]
        self.assertEqual(names[:2], ["ok", "link"])
        self.assertIn("rtd_AI0_Input_PV", names)
        link = lst["variables"][1]["type"]
        self.assertEqual(link["definition"], "array")
        self.assertEqual(link["data"]["dimensions"], [{"dimension": "0..88"}])
        self.assertTrue(all(v["location"] == "" for v in lst["variables"]))

    def test_instances(self):
        resource = {"tasks": [{"name": "main_task"}],
                    "instances": [{"name": "main_instance", "task": "main_task", "program": "main"},
                                  {"name": "old", "task": "main_task", "program": "canworks_out"}]}
        self.assertEqual([i["program"] for i in openplcmodbus.instances(resource)],
                         ["canworks_in", "main", "canworks_out"])
        self.assertTrue(all(i["task"] == "main_task" for i in openplcmodbus.instances(resource)))


class SyncProject(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.project = os.path.join(self.dir, "p")
        shutil.copytree(EDITOR_PROJECT, self.project)
        self.cfg = load()
        self.decls = decls(self.cfg)

    def tearDown(self):
        shutil.rmtree(self.dir)

    def data(self):
        with open(os.path.join(self.project, "project.json"), encoding="utf-8") as f:
            return json.load(f)["data"]

    def test_writes_everything(self):
        r = openplcmodbus.sync_project(self.project, self.cfg, self.decls)
        self.assertEqual(r["requests"], 5)
        self.assertEqual(r["iec_base"], 100)
        data = self.data()
        self.assertEqual([l["name"] for l in data["globalVariableLists"]], ["canworks"])
        self.assertEqual([i["program"] for i in data["configuration"]["resource"]["instances"]],
                         ["canworks_in", "main", "canworks_out"])
        # the user's own globals stay
        self.assertEqual([v["name"] for v in data["configuration"]["resource"]["globalVariables"]],
                         ["ai_spare", "run_lamp"])
        for name in ("canworks_in", "canworks_out"):
            self.assertTrue(os.path.isfile(os.path.join(self.project, "pous", "programs", name + ".st")))
        remote = os.path.join(self.project, "devices", "remote")
        self.assertEqual(sorted(os.listdir(remote)), ["canworks.json", "ecat-bus.json", "io-rack.json"])
        with open(os.path.join(remote, "canworks.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f), openplcmodbus.remote_device(self.cfg, self.decls, 100))
        # again: still one list and one instance each, nothing reported as changed
        openplcmodbus.sync_project(self.project, self.cfg, self.decls)
        data = self.data()
        self.assertEqual(len(data["globalVariableLists"]), 1)
        self.assertEqual(len(data["configuration"]["resource"]["instances"]), 3)

    def test_changed_file_needs_force(self):
        openplcmodbus.sync_project(self.project, self.cfg, self.decls)
        path = os.path.join(self.project, "pous", "programs", "canworks_out.st")
        with open(path, "a", encoding="utf-8") as f:
            f.write("(* edited *)\n")
        cfg = copy.deepcopy(self.cfg)
        cfg["bridge"]["openplc"]["poll_ms"] = 20
        with self.assertRaises(openplcmodbus.ChangedFiles) as e:
            openplcmodbus.sync_project(self.project, cfg, self.decls)
        self.assertEqual(e.exception.files, ["pous/programs/canworks_out.st"])
        openplcmodbus.sync_project(self.project, cfg, self.decls, force=True)
        with open(path, encoding="utf-8") as f:
            self.assertNotIn("edited", f.read())

    def test_free_base(self):
        from canworks.configurator import scan
        uses, _ = scan.scan(self.project)
        # the fixture's ai_spare takes %IW120: 33 input words from 100 would cross it
        self.assertEqual(openplcmodbus.free_iec_base(self.cfg, self.decls, uses), 121)
        cfg = copy.deepcopy(self.cfg)
        cfg["bridge"]["openplc"]["iec_base"] = 500
        r = openplcmodbus.sync_project(self.project, cfg, self.decls, uses)
        self.assertEqual(r["iec_base"], 500)


if __name__ == "__main__":
    unittest.main()
