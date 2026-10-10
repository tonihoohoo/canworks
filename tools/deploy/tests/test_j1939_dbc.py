"""J1939 DBC import and export (canworks.j1939.dbc, j1939-pc-tools): the
messages and problems of a DBC with 29-bit and 11-bit messages, config
entries from imported messages, and the export of a J1939 network that
cantools loads in strict mode."""

import contextlib
import copy
import io
import json
import os
import shutil
import tempfile
import unittest

from canworks import cli, contract, dbcexport
from canworks.j1939 import dbc

from .test_contract import FIXTURES, REPO, load_cases

try:
    import cantools
except ImportError:  # a dependency of the tools; a shard without it skips these
    cantools = None

DATA = os.path.join(os.path.dirname(__file__), "data", "j1939")
PUMP_DBC = os.path.join(DATA, "pump.dbc")
MACHINE_DBC = os.path.join(REPO, "examples", "j1939", "machine.dbc")
MACHINE_CONFIG = os.path.join(REPO, "examples", "j1939", "canworks.json")


def machine_config():
    with open(MACHINE_CONFIG, encoding="utf-8") as f:
        return json.load(f)


def j1939_cases_base():
    """The shared fixtures' config: CANopen network io and J1939 network machine."""
    return copy.deepcopy(load_cases("cases-j1939.json")["base"])


class Identifiers(unittest.TestCase):
    def test_split_pdu2(self):
        self.assertEqual(dbc.split_id(0x18FF0000), (6, 0xFF00, None, 0))

    def test_split_pdu1_takes_the_destination_out(self):
        self.assertEqual(dbc.split_id(0x18EF0080), (6, 0xEF00, 0, 0x80))

    def test_join_is_split_backwards(self):
        for frame_id in (0x18FF0180, 0x0CEF8005, 0x18EFFF80):
            p, pgn, dest, sa = dbc.split_id(frame_id)
            self.assertEqual(dbc.join_id(p, pgn, sa, dest), frame_id)

    def test_join_pdu1_defaults_to_global(self):
        self.assertEqual(dbc.join_id(6, 0xEF00, 0x80), 0x18EFFF80)


@unittest.skipIf(cantools is None, "cantools is not installed")
class Import(unittest.TestCase):
    def test_machine_dbc(self):
        # Spec scenario "Import a machine DBC".
        imported = dbc.load(MACHINE_DBC)
        self.assertEqual(imported.problems, [])
        self.assertEqual([m["pgn"] for m in imported.messages], [65280, 65281, 65282, 61184])
        p = imported.find(65280)[0]
        self.assertEqual((p["name"], p["priority"], p["source"], p["length"], p["cycle_ms"], p["sender"]),
                         ("Pressures", 6, 0, 8, 100, "Engine"))
        self.assertEqual([s["name"] for s in p["signals"]], ["Pressure", "Temp", "Level", "PumpOn"])
        self.assertEqual(p["signals"][0], {
            "name": "Pressure", "start_bit": 0, "length": 16, "byte_order": "little", "signed": False,
            "scale": 0.1, "offset": 0, "unit": "bar", "minimum": 0, "maximum": 6425.5, "comment": ""})
        self.assertTrue(p["signals"][1]["signed"])
        command = imported.find(61184)[0]
        self.assertEqual((command["destination"], command["source"], command["cycle_ms"]), (0, 128, None))

    def test_29_and_11_bit_messages(self):
        imported = dbc.load(PUMP_DBC)
        self.assertEqual([m["name"] for m in imported.messages], ["Status", "Request", "Counters", "Muxed", "Mixed"])
        status = imported.messages[0]
        self.assertEqual((status["pgn"], status["priority"], status["source"], status["cycle_ms"]),
                         (0xFF10, 6, 5, 50))
        self.assertEqual((status["signals"][0]["scale"], status["signals"][0]["offset"],
                          status["signals"][0]["unit"]), (0.5, -100, "l/min"))
        self.assertEqual(status["signals"][3]["length"], 12)
        counters = imported.messages[2]
        self.assertEqual(counters["priority"], 3)
        self.assertEqual(counters["signals"][0]["byte_order"], "big")
        self.assertEqual(counters["signals"][0]["start_bit"], 7)  # as in the DBC: the most significant bit
        text = "\n".join(imported.problems)
        self.assertIn("message Legacy (ID 0x700) has an 11-bit identifier", text)
        # Spec scenario "Import a multiplexed PGN": switch and pages, no problem.
        self.assertNotIn("Muxed", text)
        muxed = {sg["name"]: sg for sg in imported.messages[3]["signals"]}
        self.assertTrue(muxed["Sel"]["multiplexer"])
        self.assertEqual((muxed["A"]["mux"], muxed["B"]["mux"]), ({"values": [0]}, {"values": [1]}))
        self.assertIn("message Mixed (ID 0x18FF1305): signal Temperature is a float signal", text)
        self.assertIn("message Counters (ID 0xCFF1105): signal Wide has 72 bits", text)
        self.assertIn("attribute SPN is not used by the import", text)
        self.assertEqual(len(imported.problems), 4)

    def test_not_a_dbc(self):
        with self.assertRaises(dbc.ImportFailed):
            dbc.load(text="this is not a DBC file")

    def test_non_strict_file_is_imported_with_a_problem(self):
        with open(PUMP_DBC, encoding="utf-8") as f:
            text = f.read()
        # Two signals on the same bits: only a non-strict load takes it.
        text = text.replace(' SG_ Code : 0|8@1+ (1,0) [0|255] "" PLC',
                            ' SG_ Code : 0|8@1+ (1,0) [0|255] "" PLC\n SG_ Code2 : 4|8@1+ (1,0) [0|255] "" PLC')
        imported = dbc.load(text=text)
        self.assertIn("does not load in strict mode", imported.problems[0])
        self.assertEqual(len(imported.find(61184)[0]["signals"]), 2)


@unittest.skipIf(cantools is None, "cantools is not installed")
class ConfigEntries(unittest.TestCase):
    def test_receive_a_message(self):
        # Spec scenario "Receive a message": timeout 3 x cycle, free %I locations.
        cfg = machine_config()
        msg = dbc.load(MACHINE_DBC).find(65280)[0]
        used = dbc.free_locations(cfg)
        entry = dbc.config_entry(msg, "rx", used, start=200)
        self.assertEqual(entry["timeout_ms"], 300)
        self.assertNotIn("source", entry)
        locations = [s["iec_location"] for s in entry["signals"]]
        # %IW210, %IB204..206 are the example's own; the suggestions skip them.
        self.assertEqual(locations, ["%IW200", "%IB202", "%IB203", "%IB207"])
        self.assertEqual(entry["signals"][0], {"name": "Pressure", "start_bit": 0, "length": 16, "scale": 0.1,
                                               "unit": "bar", "iec_location": "%IW200"})
        self.assertTrue(entry["signals"][1]["signed"])
        self.assertIn(("I", "B", 207), used)

    def test_send_a_message(self):
        imported = dbc.load(MACHINE_DBC)
        used = set()
        tx = dbc.config_entry(imported.find(65281)[0], "tx", used)
        self.assertEqual((tx["priority"], tx["period_ms"]), (6, 100))
        self.assertNotIn("destination", tx)
        self.assertNotIn("length", tx)
        self.assertEqual([s["iec_location"] for s in tx["signals"]], ["%QW100", "%QB100"])
        command = dbc.config_entry(imported.find(61184)[0], "tx", used)
        self.assertEqual((command["destination"], command["period_ms"]), (0, 0))
        info = dbc.config_entry(imported.find(65282)[0], "tx", used)
        self.assertEqual(info["length"], 40)  # the DBC's, more than the signals need

    def test_one_bit_and_wide_signals(self):
        imported = dbc.load(PUMP_DBC)
        status = dbc.config_entry(imported.messages[0], "rx", set())
        self.assertEqual([s["iec_location"] for s in status["signals"]], ["%IW100", "%IX100.0", "%IB100", "%IW101"])
        self.assertEqual(status["signals"][0]["offset"], -100)
        self.assertTrue(status["signals"][3]["signed"])
        counters = dbc.config_entry(imported.messages[2], "rx", set())
        self.assertEqual(counters["signals"][0]["byte_order"], "big")
        self.assertEqual(counters["signals"][0]["iec_location"], "%ID100")
        self.assertEqual(counters["timeout_ms"], 3000)

    def test_network_from_the_dbc_passes_the_checks(self):
        # Every message of both DBCs as rx or tx of one network: the checks accept it.
        cfg = {"schema_version": 2, "networks": [{
            "name": "machine", "protocol": "j1939", "adapter": {"type": "socketcan", "interface": "vcan1",
                                                              "bitrate": 250000},
            "j1939": {"ecu": {"name": {"identity_number": 7}, "address": 128}, "dbc": "machine.dbc",
                      "rx": [], "tx": []}}]}
        used = dbc.free_locations(cfg)
        j = cfg["networks"][0]["j1939"]
        for m in dbc.load(MACHINE_DBC).messages:
            key = "tx" if m["sender"] == "PLC" else "rx"
            j[key].append(dbc.config_entry(m, key, used))
        for m in dbc.load(PUMP_DBC).messages:
            j["rx"].append(dbc.config_entry(m, "rx", used))
        self.assertEqual((len(j["rx"]), len(j["tx"])), (7, 2))
        r = contract.check_config(cfg, "canworks.json")
        self.assertEqual(r.errors, [])
        self.assertEqual(r.warnings, [])


@unittest.skipIf(cantools is None, "cantools is not installed")
class Export(unittest.TestCase):
    def export_machine(self):
        cfg = machine_config()
        files, warnings = dbcexport.export_networks(cfg, MACHINE_CONFIG)
        self.assertEqual(warnings, [])
        self.assertEqual([name for name, _ in files], ["machine"])
        return files[0][1]

    def test_round_trip(self):
        # Spec scenario "Round trip": same PGNs and signal layouts as the DBC the network came from.
        db = cantools.database.load_string(self.export_machine(), "dbc", strict=True)
        source = cantools.database.load_file(MACHINE_DBC, strict=True)

        def layout(d):
            out = {}
            for m in d.messages:
                _, pgn, _, _ = dbc.split_id(m.frame_id)
                out[pgn] = [(s.name, s.start, s.length, s.byte_order, s.is_signed, s.scale, s.offset, s.unit or "")
                            for s in m.signals]
            return out

        self.assertEqual(layout(db), layout(source))
        self.assertEqual({m.frame_id for m in db.messages}, {m.frame_id for m in source.messages})
        for m in db.messages:
            self.assertTrue(m.is_extended_frame)
            self.assertEqual(m.dbc.attributes["VFrameFormat"].value, 3)
        self.assertEqual(db.get_message_by_name("Setpoints").cycle_time, 100)
        self.assertEqual(db.get_message_by_name("Pressures").cycle_time, 100)  # timeout 300 / 3
        self.assertEqual(db.get_message_by_name("Setpoints").senders, ["PLC"])
        self.assertEqual(db.get_message_by_name("Pressures").senders, ["ECU0"])
        self.assertEqual(db.dbc.attributes["ProtocolType"].value, "J1939")

    def test_import_of_the_export(self):
        exported = self.export_machine()
        imported = dbc.load(text=exported)
        self.assertEqual(imported.problems, [])
        self.assertEqual(sorted(m["pgn"] for m in imported.messages), [61184, 65280, 65281, 65282])
        self.assertEqual(imported.find(65281)[0]["source"], 128)

    def test_unfiltered_rx_uses_the_null_address(self):
        cfg = machine_config()
        rx = cfg["networks"][0]["j1939"]["rx"][0]
        del rx["source"]
        rx["source_name"] = "0x00000000000004D2"
        files, _ = dbcexport.export_networks(cfg, MACHINE_CONFIG)
        db = cantools.database.load_string(files[0][1], "dbc", strict=True)
        self.assertEqual(db.get_message_by_name("Pressures").frame_id, 0x18FF00FE)
        self.assertIn("NAME 0x00000000000004D2", db.get_message_by_name("Pressures").comment)

    def test_pdu1_tx_and_own_address(self):
        cfg = machine_config()
        cfg["networks"][0]["j1939"]["ecu"]["address"] = 130
        files, _ = dbcexport.export_networks(cfg, MACHINE_CONFIG)
        db = cantools.database.load_string(files[0][1], "dbc", strict=True)
        self.assertEqual(db.get_message_by_name("Command").frame_id, 0x18EF0082)
        self.assertEqual(db.get_message_by_name("Setpoints").frame_id, 0x18FF0182)

    def test_big_endian_and_offset(self):
        cfg = machine_config()
        sig = cfg["networks"][0]["j1939"]["tx"][0]["signals"][0]
        sig.update(byte_order="big", start_bit=7, offset=-40, scale=0.5, signed=True)
        files, _ = dbcexport.export_networks(cfg, MACHINE_CONFIG)
        db = cantools.database.load_string(files[0][1], "dbc", strict=True)
        s = db.get_message_by_name("Setpoints").get_signal_by_name("Setpoint")
        self.assertEqual((s.start, s.byte_order, s.scale, s.offset, s.is_signed), (7, "big_endian", 0.5, -40, True))
        self.assertEqual((s.minimum, s.maximum), (-16424, 16343.5))

    def test_cli_writes_one_file_per_network(self):
        # A CANopen and a J1939 network: bus_io.dbc and bus_machine.dbc.
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        cfg = j1939_cases_base()
        path = os.path.join(tmp, "canworks.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        shutil.copy(os.path.join(FIXTURES, "eds", "cpp-slave.eds"), tmp)
        out = os.path.join(tmp, "bus.dbc")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["--config", path, "--export-dbc", out]), 0)
        db = cantools.database.load_file(os.path.join(tmp, "bus_machine.dbc"), strict=True)
        self.assertEqual(sorted(m.frame_id for m in db.messages), [0x18FF0000, 0x18FF0180])
        self.assertTrue(os.path.isfile(os.path.join(tmp, "bus_io.dbc")))
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["--config", path, "--export-dbc", out, "--network", "machine"]), 0)
        cantools.database.load_file(out, strict=True)

    def test_dcf_export_of_a_j1939_network(self):
        from canworks import dcfexport
        with self.assertRaises(dcfexport.ExportFailed) as e:
            dcfexport.export(j1939_cases_base(), os.path.join(FIXTURES, "eds", "canworks.json"), network="machine")
        self.assertIn("network 'machine' is a J1939 network; it has no CANopen nodes to export as DCF files",
                      str(e.exception))

if __name__ == "__main__":
    unittest.main()
