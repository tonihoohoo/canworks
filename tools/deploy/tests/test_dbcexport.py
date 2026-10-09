"""DBC export (canworks.dbcexport): messages and signals from the
config and the EDS files, names, the SDO option, the DBC text (golden files),
and a strict load in cantools when it is installed."""

import contextlib
import copy
import io
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from canworks import cli, dbcexport, notes

from .test_contract import FIXTURES, REPO, load_cases

try:
    import cantools
except ImportError:  # CI installs it; locally the cantools test is skipped
    cantools = None

EDS_DIR = os.path.join(FIXTURES, "eds")
FIXTURE_CONFIG = os.path.join(EDS_DIR, "canworks.json")
GOLDEN = os.path.join(os.path.dirname(__file__), "data", "dbc")
RTD = os.path.join(REPO, "config", "rtd-sensor", "canopen_config.json")
PINGPONG = os.path.join(REPO, "config", "pingpong", "canopen_config.json")
EDITOR_PROJECT = os.path.join(FIXTURES, "editor-project")


def base_config():
    return copy.deepcopy(load_cases()["base"])


def fixed_io_config():
    """The fixture config on fixed-io.eds: both PDOs keep the device mapping
    (TPDO 0x6000:1-2, RPDO 0x6200:1-2), the config names one object of each."""
    cfg = base_config()
    n = cfg["nodes"][0]
    n["eds"] = "fixed-io.eds"
    n["tx_pdos"] = [{"entries": [{"index": "0x6000", "subindex": 2, "type": "UNSIGNED8", "iec_location": "%IB40"}]}]
    n["rx_pdos"] = [{"entries": [{"index": "0x6200", "subindex": 1, "type": "UNSIGNED8", "iec_location": "%QB40"}]}]
    return cfg


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def model(cfg, path=FIXTURE_CONFIG, **kw):
    return dbcexport.build(cfg, path, **kw)


def message(m, name):
    return next(x for x in m.messages if x.name == name)


def signal(msg, name):
    return next(s for s in msg.signals if s.name == name)


class Names(unittest.TestCase):
    def test_identifier(self):
        self.assertEqual(dbcexport.identifier("AI Sensor Type"), "AI_Sensor_Type")
        self.assertEqual(dbcexport.identifier("  Temp. (°C) "), "Temp_C")
        self.assertEqual(dbcexport.identifier("1st Binary Data"), "_1st_Binary_Data")
        self.assertEqual(dbcexport.identifier("--"), "")

    def test_node_without_name(self):
        cfg = base_config()
        del cfg["nodes"][0]["name"]
        self.assertEqual(model(cfg).nodes, ["Master", "node2"])

    def test_non_ascii_and_duplicate_node_names(self):
        cfg = base_config()
        cfg["nodes"][0]["name"] = "Pumppu ä"
        second = copy.deepcopy(cfg["nodes"][0])
        second["node_id"] = 3
        second["status_location"] = "%IX10.1"
        second["tx_pdos"][0]["entries"][0]["iec_location"] = "%ID101"
        second["rx_pdos"][0]["entries"][0]["iec_location"] = "%QD101"
        cfg["nodes"].append(second)
        self.assertEqual(model(cfg).nodes, ["Master", "Pumppu", "Pumppu_3"])

    def test_node_named_master(self):
        cfg = base_config()
        cfg["nodes"][0]["name"] = "master"
        self.assertEqual(model(cfg).nodes, ["Master", "master_2"])

    def test_var_uses_its_own_name(self):
        m = model(base_config())
        self.assertEqual([s.name for s in message(m, "pingpong_TPDO1").signals], ["UNSIGNED32_sent_from_slave"])

    def test_sub_object_gets_parent_prefix(self):
        m = model(fixed_io_config())
        self.assertEqual([s.name for s in message(m, "pingpong_TPDO1").signals],
                         ["Read_inputs_8_bit_Read_inputs_0x1", "Read_inputs_8_bit_Read_inputs_0x2"])

    def test_parent_prefix_not_repeated(self):
        m = model(load(RTD), RTD)
        self.assertEqual(signal(message(m, "rtd_TPDO1"), "AI_Input_PV_AI0_Input_PV").start, 0)
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        with open(os.path.join(EDS_DIR, "fixed-io.eds"), encoding="utf-8") as f:
            text = f.read().replace("ParameterName=Read inputs 0x1", "ParameterName=Read inputs 8-bit 1")
        with open(os.path.join(tmp, "fixed-io.eds"), "w", encoding="utf-8") as f:
            f.write(text)
        m = model(fixed_io_config(), os.path.join(tmp, "canworks.json"))
        self.assertEqual(message(m, "pingpong_TPDO1").signals[0].name, "Read_inputs_8_bit_1")

    def test_plc_variable_name(self):
        cfg = fixed_io_config()
        names = {"%IB40": ["door_byte"], "%QB40": ["lamp", "Lamp"]}
        m = model(cfg, names=names)
        tpdo = message(m, "pingpong_TPDO1")
        self.assertEqual(tpdo.signals[1].name, "door_byte")
        self.assertIn("%IB40 (door_byte)", tpdo.signals[1].comment)
        # Two different names on one location keep the OD name; plc_names
        # folds names that differ only in case.
        m = model(cfg, names={"%QB40": ["lamp", "valve"]})
        rpdo = message(m, "pingpong_RPDO1")
        self.assertEqual(rpdo.signals[0].name, "Write_outputs_8_bit_Write_outputs_0x1")
        self.assertIn("(lamp, valve)", rpdo.signals[0].comment)

    def test_plc_names_from_editor_project(self):
        from canworks.configurator import scan
        uses, _ = scan.scan(EDITOR_PROJECT)
        self.assertEqual(dbcexport.plc_names(uses).get("%IX10.1"), ["door_ok"])

    def test_project_detection(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        project = os.path.join(tmp, "proj")
        shutil.copytree(EDITOR_PROJECT, project)
        os.makedirs(os.path.join(project, "canworks"))
        self.assertEqual(dbcexport.project_names(os.path.join(project, "canworks", "canworks.json"))["%IX10.1"],
                         ["door_ok"])
        self.assertIsNone(dbcexport.project_names(os.path.join(project, "canworks.json")))
        os.remove(os.path.join(project, "project.json"))
        self.assertIsNone(dbcexport.project_names(os.path.join(project, "canworks", "canworks.json")))


class Pdos(unittest.TestCase):
    def test_cob_ids_and_directions(self):
        m = model(base_config())
        tpdo, rpdo = message(m, "pingpong_TPDO1"), message(m, "pingpong_RPDO1")
        self.assertEqual((tpdo.cob_id, tpdo.length, tpdo.sender), (0x182, 4, "pingpong"))
        self.assertEqual(tpdo.signals[0].receivers, ["Master"])
        self.assertEqual((rpdo.cob_id, rpdo.sender), (0x202, "Master"))
        self.assertEqual(rpdo.signals[0].receivers, ["pingpong"])

    def test_auto_cob_id_above_pdo_4(self):
        cfg = {"nodes": [{"node_id": 2, "tx_pdos": [{"number": 5, "cob_id": "auto"}]},
                         {"node_id": 3, "tx_pdos": [{"number": 1}]}]}
        self.assertEqual(dbcexport._normalized_pdos(cfg)[0]["tx_pdos"][0]["cob_id"], 0x57F)

    def test_four_int16_inputs(self):
        m = model(load(RTD), RTD)
        tpdo = message(m, "rtd_TPDO1")
        self.assertEqual((tpdo.cob_id, tpdo.length), (0x185, 8))
        self.assertEqual([(s.start, s.length, s.signed) for s in tpdo.signals],
                         [(0, 16, True), (16, 16, True), (32, 16, True), (48, 16, True)])
        self.assertEqual(tpdo.signals[0].comment, "0x7130:1 INTEGER16 -> %IW100")
        self.assertEqual((message(m, "rtd_TPDO2").cob_id, message(m, "rtd_TPDO2").length), (0x285, 4))

    def test_device_mapping_with_unused_objects(self):
        m = model(fixed_io_config())
        tpdo, rpdo = message(m, "pingpong_TPDO1"), message(m, "pingpong_RPDO1")
        self.assertEqual([(s.start, s.length) for s in tpdo.signals], [(0, 8), (8, 8)])
        self.assertIn("(not used by the PLC)", tpdo.signals[0].comment)
        self.assertIn("-> %IB40", tpdo.signals[1].comment)
        self.assertIn("sent as 0 by the master", rpdo.signals[1].comment)

    def test_dummy_entry_is_a_gap(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        with open(os.path.join(EDS_DIR, "fixed-io.eds"), encoding="utf-8") as f:
            text = f.read().replace("DefaultValue=0x60000108", "DefaultValue=0x00050008", 1)
        with open(os.path.join(tmp, "fixed-io.eds"), "w", encoding="utf-8") as f:
            f.write(text)
        m = model(fixed_io_config(), os.path.join(tmp, "canworks.json"))
        tpdo = message(m, "pingpong_TPDO1")
        self.assertEqual([(s.start, s.length) for s in tpdo.signals], [(8, 8)])
        self.assertEqual(tpdo.length, 2)

    def test_cycle_time_and_transmission(self):
        m = model(load(RTD), RTD)
        tpdo = message(m, "rtd_TPDO1")
        self.assertEqual(tpdo.cycle_ms, 100)
        self.assertEqual(tpdo.comment, "node 5 TPDO 1, transmission 1")
        m = model(base_config())
        self.assertIn("from EDS", message(m, "pingpong_TPDO1").comment)

    def test_startup_sdo_override_warns(self):
        cfg = base_config()
        cfg["nodes"][0]["sdo"].append({"index": "0x1800", "subindex": 1, "type": "UNSIGNED32", "value": "0x190"})
        m = model(cfg)
        self.assertTrue(any("may not match the bus" in w and "TPDO 1" in w for w in m.warnings))
        self.assertEqual(message(m, "pingpong_TPDO1").cob_id, 0x182)

    def test_config_with_error(self):
        cfg = base_config()
        cfg["nodes"][0]["tx_pdos"][0]["number"] = 2
        with self.assertRaises(dbcexport.ExportFailed) as e:
            model(cfg)
        self.assertIn("TPDO 2", str(e.exception))

    def test_gateway_routed_entry(self):
        # Virtual-plant io: a gateway route feeds node 6's 0x6411:1, which
        # has no PLC location in the version 2 config.
        path = os.path.join(REPO, "examples", "virtual-plant", "canworks", "canworks.json")
        files, _ = dbcexport.export_networks(load(path), path, network="io")
        lines = [ln for ln in files[0][1].splitlines() if ln.startswith("CM_ SG_ 518 ")]
        self.assertTrue(any('"0x6411:1 INTEGER16 (gateway route, no PLC location)"' in ln for ln in lines), lines)
        self.assertTrue(any('"0x6411:2 INTEGER16 -> %QW110"' in ln for ln in lines), lines)


class Notes(unittest.TestCase):
    """Units, scales, value names and note texts of the merged notes
    (canopen-device-notes, canopen-dbc-export)."""

    def notes(self, objects):
        doc = {"format": notes.FORMAT, "objects": objects}
        return lambda value, eds: notes.Notes(eds, value, None, doc)

    def test_scaled_signal_with_values_and_text(self):
        m = model(load(RTD), RTD, notes=self.notes({
            "0x7130": {"text": "Pressure", "unit": "bar", "scale": 0.01},
            "0x7130:2": {"values": {"-32768": "open circuit"}}}))
        tpdo = message(m, "rtd_TPDO1")
        first, second = tpdo.signals[0], tpdo.signals[1]
        self.assertEqual((first.unit, first.scale, first.values), ("bar", 0.01, []))
        self.assertEqual(first.comment, "0x7130:1 INTEGER16 -> %IW100; Pressure")
        self.assertEqual(second.values, [(-32768, "open circuit")])
        text = dbcexport.write(m)
        self.assertRegex(text, r'SG_ \w+ : 0\|16@1- \(0\.01,0\) \[[^]]*\] "bar"')
        self.assertRegex(text, r'VAL_ 389 \w+ -32768 "open circuit" ;')

    def test_sdo_signals(self):
        # Notes also reach the SDO frames' signals (here the startup SDO 0x1017).
        m = model(base_config(), sdo="config", notes=self.notes({"0x1017": {"values": {"0": "off"}}}))
        sig = signal(message(m, "pingpong_SDO_Rx"), "Producer_heartbeat_time")
        self.assertEqual((sig.unit, sig.values), ("ms", [(0, "off")]))
        self.assertIn("startup SDO, value 100; Producer heartbeat time", sig.comment)

    def test_unchanged_without_notes(self):
        plain = model(load(RTD), RTD, notes=self.notes({}))
        tpdo = message(plain, "rtd_TPDO1")
        self.assertEqual([(s.unit, s.scale, s.values) for s in tpdo.signals], [("", 1, [])] * 4)
        self.assertEqual(tpdo.signals[0].comment, "0x7130:1 INTEGER16 -> %IW100")


class FixedFrames(unittest.TestCase):
    def test_heartbeat_emcy_nmt_sync(self):
        m = model(base_config())
        hb = message(m, "pingpong_Heartbeat")
        self.assertEqual((hb.cob_id, hb.length), (0x702, 1))
        self.assertIn((5, "Operational"), hb.signals[0].values)
        em = message(m, "pingpong_EMCY")
        self.assertEqual([(s.name, s.start, s.length) for s in em.signals],
                         [("Error_Code", 0, 16), ("Error_Register", 16, 8), ("Manufacturer_Data", 24, 40)])
        nmt = message(m, "NMT")
        self.assertEqual((nmt.cob_id, nmt.sender), (0, "Master"))
        self.assertIn((129, "Reset node"), nmt.signals[0].values)
        self.assertEqual((message(m, "SYNC").cob_id, message(m, "SYNC").length), (0x80, 0))

    def test_no_sync_message_without_sync_period(self):
        cfg = base_config()
        del cfg["master"]["sync_period_us"]
        cfg["nodes"][0]["tx_pdos"][0]["transmission"] = 255
        cfg["nodes"][0]["rx_pdos"][0]["transmission"] = 255
        m = model(cfg)
        self.assertFalse([x for x in m.messages if x.cob_id == 0x80])

    def test_plc_cycle_sync(self):
        cfg = base_config()
        del cfg["master"]["sync_period_us"]
        cfg["master"]["sync_source"] = "plc_cycle"
        cfg["master"]["sync_cycles"] = 2
        cfg["nodes"][0]["tx_pdos"][0]["transmission"] = 1
        m = model(cfg)
        self.assertEqual(message(m, "SYNC").cob_id, 0x80)
        tpdo = message(m, "pingpong_TPDO1")
        self.assertIsNone(tpdo.cycle_ms)
        self.assertIn("sent at every SYNC, one SYNC every 2 PLC cycles", tpdo.comment)


class Sdo(unittest.TestCase):
    def test_default_without_sdo(self):
        m = model(base_config())
        self.assertFalse([x for x in m.messages if 0x580 <= x.cob_id <= 0x67F])

    def test_config_option(self):
        cfg = base_config()
        cfg["nodes"][0]["sdo_variables"] = [
            {"name": "ping value", "index": "0x4001", "subindex": 0, "type": "UNSIGNED32", "direction": "read",
             "iec_location": "%ID200"}]
        m = model(cfg, sdo="config")
        rx, tx = message(m, "pingpong_SDO_Rx"), message(m, "pingpong_SDO_Tx")
        self.assertEqual((rx.cob_id, rx.sender, tx.cob_id, tx.sender), (0x602, "Master", 0x582, "pingpong"))
        obj = signal(rx, "Object")
        self.assertTrue(obj.multiplexer)
        self.assertEqual((obj.start, obj.length), (8, 24))
        self.assertEqual(obj.values, [(0x4001, "0x4001:0 ping_value"), (0x1017, "0x1017:0 Producer_heartbeat_time")])
        var = signal(rx, "ping_value")
        self.assertEqual((var.mux, var.start, var.length), (0x4001, 32, 32))
        self.assertIn("SDO variable, read -> %ID200", var.comment)
        self.assertIn("startup SDO, value 100", signal(rx, "Producer_heartbeat_time").comment)
        self.assertIn((0x2B, "Download 2 bytes"), signal(rx, "Command").values)
        self.assertIn((0x4B, "Upload 2 bytes"), signal(tx, "Command").values)
        self.assertIn("abort code", signal(rx, "Command").comment)

    def test_all_option_skips_large_and_string_objects(self):
        m = model(load(RTD), RTD, sdo="all")
        rx = message(m, "rtd_SDO_Rx")
        values = {v for v, _ in signal(rx, "Object").values}
        self.assertIn(0x1017, values)
        self.assertNotIn(0x1008, values)  # VISIBLE_STRING
        self.assertIn(0x6110 + (1 << 16), values)

    def test_unknown_option(self):
        with self.assertRaises(ValueError):
            model(base_config(), sdo="some")


class Writer(unittest.TestCase):
    CASES = [
        ("pingpong.dbc", PINGPONG, None, "none"),
        ("rtd-sensor.dbc", RTD, None, "none"),
        ("rtd-sensor-sdo-config.dbc", RTD, None, "config"),
        ("fixed-io-sdo-all.dbc", FIXTURE_CONFIG, fixed_io_config, "all"),
    ]

    def export(self, path, make, sdo):
        cfg = make() if make else load(path)
        with mock.patch.object(dbcexport, "__version__", "TEST"):
            text, _ = dbcexport.export(cfg, path, sdo=sdo)
        return text

    def test_golden_files(self):
        for name, path, make, sdo in self.CASES:
            with self.subTest(name=name):
                text = self.export(path, make, sdo)
                golden = os.path.join(GOLDEN, name)
                if os.environ.get("UPDATE_GOLDEN"):
                    with open(golden, "w", encoding="ascii", newline="") as f:
                        f.write(text)
                with open(golden, encoding="ascii", newline="") as f:
                    self.assertEqual(text, f.read())

    def test_ascii_crlf(self):
        text = self.export(RTD, None, "config")
        text.encode("ascii")
        self.assertNotIn("\n", text.replace("\r\n", ""))

    def test_float_signal(self):
        m = dbcexport.Model(["Master", "n"], [dbcexport.Message(0x181, "n_TPDO1", 4, "n")], "c", [])
        m.messages[0].signals.append(dbcexport.Signal("Temp", 0, 32, False, 1, ["Master"]))
        text = dbcexport.write(m)
        self.assertIn("SIG_VALTYPE_ 385 Temp : 1;", text)
        self.assertIn(" SG_ Temp : 0|32@1+ (1,0) [0|0] \"\" Master", text)

    def test_write_file_replaces(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        path = os.path.join(tmp, "bus.dbc")
        dbcexport.write_file("A\r\n", path)
        dbcexport.write_file("B\r\n", path)
        self.assertEqual(os.listdir(tmp), ["bus.dbc"])
        with open(path, newline="") as f:
            self.assertEqual(f.read(), "B\r\n")


class Cli(unittest.TestCase):
    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def config_in(self, cfg):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        shutil.copytree(EDS_DIR, os.path.join(tmp, "eds"))
        path = os.path.join(tmp, "eds", "canworks.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        return tmp, path

    def test_export(self):
        tmp, path = self.config_in(base_config())
        out_file = os.path.join(tmp, "bus.dbc")
        code, out, err = self.run_cli("--config", path, "--export-dbc", out_file)
        self.assertEqual(code, 0, err)
        self.assertIn("wrote " + out_file, out)
        with open(out_file, encoding="ascii") as f:
            text = f.read()
        self.assertIn("BO_ 386 pingpong_TPDO1: 4 pingpong", text)
        self.assertNotIn("SDO_Rx", text)

    def test_export_with_sdo(self):
        tmp, path = self.config_in(base_config())
        out_file = os.path.join(tmp, "bus.dbc")
        code, _, err = self.run_cli("--config", path, "--export-dbc", out_file, "--dbc-sdo", "all")
        self.assertEqual(code, 0, err)
        with open(out_file, encoding="ascii") as f:
            self.assertIn("BO_ 1538 pingpong_SDO_Rx: 8 Master", f.read())

    def test_project_names(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        project = os.path.join(tmp, "proj")
        shutil.copytree(EDITOR_PROJECT, project)
        shutil.copytree(EDS_DIR, os.path.join(project, "canworks"))
        cfg = base_config()
        cfg["nodes"][0]["tx_pdos"] = [{"entries": [
            {"index": "0x4001", "subindex": 0, "type": "UNSIGNED32", "iec_location": "%ID10"}]}]
        with open(os.path.join(project, "pous", "programs", "main.st"), "a", encoding="utf-8") as f:
            f.write("\nPROGRAM other\n  VAR\n    ping AT %ID10 : UDINT;\n  END_VAR\nEND_PROGRAM\n")
        path = os.path.join(project, "canworks", "canworks.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        out_file = os.path.join(tmp, "bus.dbc")
        code, _, err = self.run_cli("--config", path, "--export-dbc", out_file)
        self.assertEqual(code, 0, err)
        with open(out_file, encoding="ascii") as f:
            self.assertIn(" SG_ ping : 0|32@1+", f.read())

    def test_failure_leaves_file(self):
        cfg = base_config()
        cfg["nodes"][0]["tx_pdos"][0]["number"] = 2
        tmp, path = self.config_in(cfg)
        out_file = os.path.join(tmp, "bus.dbc")
        with open(out_file, "w") as f:
            f.write("old")
        code, _, err = self.run_cli("--config", path, "--export-dbc", out_file)
        self.assertEqual(code, 1)
        self.assertIn("TPDO 2", err)
        with open(out_file) as f:
            self.assertEqual(f.read(), "old")

    def test_refuses_upload_options(self):
        tmp, path = self.config_in(base_config())
        code, _, err = self.run_cli("--config", path, "--export-dbc", os.path.join(tmp, "b.dbc"),
                                    "--runtime", "plc.local")
        self.assertEqual(code, 1)
        self.assertIn("--export-dbc only writes a DBC file", err)

    def test_dbc_sdo_needs_export(self):
        tmp, path = self.config_in(base_config())
        code, _, err = self.run_cli("--config", path, "--check-only", "--dbc-sdo", "all", "--bundle", tmp)
        self.assertEqual(code, 1)
        self.assertIn("--dbc-sdo needs --export-dbc", err)

    def test_excludes_other_sources(self):
        tmp, path = self.config_in(base_config())
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            cli.main(["--config", path, "--export-dbc", "b.dbc", "--export-dcf", tmp])


@unittest.skipIf(cantools is None, "cantools is not installed")
class CantoolsStrict(unittest.TestCase):
    def test_every_golden_file_loads_strict(self):
        for name in sorted(os.listdir(GOLDEN)):
            with self.subTest(name=name):
                cantools.database.load_file(os.path.join(GOLDEN, name), strict=True)

    def test_pdo_round_trip(self):
        db = cantools.database.load_file(os.path.join(GOLDEN, "rtd-sensor.dbc"), strict=True)
        msg = db.get_message_by_frame_id(0x185)
        data = msg.encode({s.name: v for s, v in zip(msg.signals, (1, -2, 3, -4))})
        self.assertEqual(data.hex(), "0100feff0300fcff")
        self.assertEqual(list(msg.decode(data).values()), [1, -2, 3, -4])

    def test_sdo_decode(self):
        db = cantools.database.load_file(os.path.join(GOLDEN, "rtd-sensor-sdo-config.dbc"), strict=True)
        msg = db.get_message_by_frame_id(0x605)
        decoded = msg.decode(bytes.fromhex("2B1061011E000000"))
        self.assertEqual(str(decoded["Command"]), "Download 2 bytes")
        self.assertEqual(str(decoded["Object"]), "0x6110:1 AI_Sensor_Type_AI0_Sensor_Type")
        self.assertEqual(decoded["AI_Sensor_Type_AI0_Sensor_Type"], 30)
        hb = db.get_message_by_frame_id(0x705)
        self.assertEqual(str(hb.decode(b"\x05")["NMT_State"]), "Operational")

    def test_all_option_loads_strict_on_drive_eds(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        shutil.copy(os.path.join(EDS_DIR, "drives", "servo-drive.eds"), os.path.join(tmp, "servo.eds"))
        cfg = {"schema_version": 1, "adapter": {"type": "socketcan", "interface": "vcan0", "bitrate": 500000},
               "master": {"node_id": 1, "sync_period_us": 10000},
               "nodes": [{"node_id": 3, "name": "servo", "eds": "servo.eds",
                          "tx_pdos": [{"number": 1, "mapping": "device", "transmission": 1, "entries": [
                              {"index": "0x6041", "subindex": 0, "type": "UNSIGNED16", "iec_location": "%IW10"}]}],
                          "rx_pdos": [{"number": 1, "entries": [
                              {"index": "0x6040", "subindex": 0, "type": "UNSIGNED16", "iec_location": "%QW10"}]}]}]}
        text, _ = dbcexport.export(cfg, os.path.join(tmp, "canworks.json"), sdo="all")
        db = cantools.database.load_string(text, strict=True)
        self.assertGreater(len(db.get_message_by_frame_id(0x603).signals), 100)


if __name__ == "__main__":
    unittest.main()
