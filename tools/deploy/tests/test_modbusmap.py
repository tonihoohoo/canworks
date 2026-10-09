"""Modbus register map of bridge configs (canworks.modbusmap): the register
rule, byte checks, channel suggestion, the CSV/JSON/ST writers, Pack for
Modbus and the command-line export."""

import contextlib
import copy
import csv
import io
import json
import os
import tempfile
import unittest

from canworks import cli, modbusmap

from .test_contract import REPO

DATA = os.path.join(os.path.dirname(__file__), "data", "modbus")
BRIDGE = os.path.join(DATA, "bridge.json")
VIRTUAL_PLANT = os.path.join(REPO, "examples", "virtual-plant", "canworks", "canworks.json")


def load(path=BRIDGE):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def by_name(rows):
    return {r["name"]: r for r in rows}


class RegisterRule(unittest.TestCase):
    def test_rule(self):
        rows = by_name(modbusmap.register_map(load()))
        r = rows["sensor.0x6000:1"]
        self.assertEqual((r["table"], r["address"], r["count"]), ("input register", 2, 2))
        self.assertEqual(r["word_order"], "high_first")
        r = rows["sensor.0x6000:2"]
        self.assertEqual((r["table"], r["address"], r["count"]), ("input register", 4, 1))
        r = rows["sensor.0x6000:3"]
        self.assertEqual((r["address"], r["byte_in_register"]), (5, "high"))
        r = rows["sensor.0x6000:4"]
        self.assertEqual((r["table"], r["address"]), ("discrete input", 91))
        r = rows["sensor.0x6200:2"]
        self.assertEqual((r["table"], r["address"]), ("coil", 801))
        r = rows["sensor.0x6200:3"]
        self.assertEqual((r["table"], r["address"], r["count"], r["type"]),
                         ("holding register", 2, 2, "REAL32"))
        r = rows["field.state"]
        self.assertEqual((r["address"], r["byte_in_register"]), (20, "high"))
        r = rows["sensor.state"]
        self.assertEqual((r["address"], r["byte_in_register"]), (20, "low"))
        r = rows["sensor.TPDO1.timeout"]
        self.assertEqual((r["table"], r["address"]), ("discrete input", 337))

    def test_bridge_blocks(self):
        rows = by_name(modbusmap.register_map(load()))
        self.assertEqual((rows["bridge.status"]["address"], rows["bridge.status"]["count"]), (24, 4))
        self.assertEqual((rows["bridge.control"]["table"], rows["bridge.control"]["count"]),
                         ("holding register", 3))
        self.assertEqual(rows["bridge.live_list.field"]["count"], 8)

    def test_image_sizes(self):
        self.assertEqual(modbusmap.image_sizes(modbusmap.register_map(load())), (72, 102))

    def test_low_first(self):
        cfg = load()
        cfg["bridge"]["word_order"] = "low_first"
        rows = by_name(modbusmap.register_map(cfg))
        self.assertEqual(rows["sensor.0x6000:1"]["word_order"], "low_first")
        self.assertEqual(rows["sensor.0x6000:2"]["word_order"], "")

    def test_not_a_bridge_config(self):
        cfg = load()
        del cfg["bridge"]
        with self.assertRaisesRegex(modbusmap.MapError, "not a bridge config"):
            modbusmap.register_map(cfg)


class ByteChecks(unittest.TestCase):
    def test_odd_word(self):
        cfg = load()
        cfg["networks"][0]["nodes"][0]["tx_pdos"][0]["entries"][1]["iec_location"] = "%IW3"
        with self.assertRaisesRegex(modbusmap.MapError, "%IW3 must start at an even byte"):
            modbusmap.register_map(cfg)

    def test_overlap(self):
        cfg = load()
        cfg["networks"][0]["nodes"][0]["tx_pdos"][0]["entries"][1]["iec_location"] = "%IW6"
        with self.assertRaisesRegex(modbusmap.MapError,
                                    r"sensor.0x6000:1 \(%ID4\) and sensor.0x6000:2 \(%IW6\) "
                                    r"overlap in input bytes 6 and 7"):
            modbusmap.register_map(cfg)

    def test_bits_share_a_byte(self):
        cfg = load()
        cfg["networks"][0]["nodes"][0]["status_location"] = "%IX11.4"
        modbusmap.register_map(cfg)
        cfg["networks"][0]["nodes"][0]["status_location"] = "%IX11.3"
        with self.assertRaisesRegex(modbusmap.MapError, "both map to"):
            modbusmap.register_map(cfg)

    def test_bit_in_a_byte_location(self):
        cfg = load()
        cfg["networks"][0]["nodes"][0]["status_location"] = "%IX10.0"
        with self.assertRaisesRegex(modbusmap.MapError, "overlap in input byte 10"):
            modbusmap.register_map(cfg)

    def test_block_inside_data(self):
        cfg = load()
        cfg["bridge"]["status_location"] = "%IB6"
        with self.assertRaisesRegex(modbusmap.MapError, "bridge.status"):
            modbusmap.register_map(cfg)

    def test_block_must_be_a_byte(self):
        cfg = load()
        cfg["bridge"]["status_location"] = "%IW48"
        with self.assertRaisesRegex(modbusmap.MapError, "must be a byte location"):
            modbusmap.register_map(cfg)


class Channels(unittest.TestCase):
    def test_spec_example(self):
        rows = [{"table": "input register", "address": a, "count": 1, "direction": "input",
                 "byte": 2 * a} for a in range(150)]
        rows += [{"table": "holding register", "address": a, "count": 1, "direction": "output",
                  "byte": 2 * a} for a in range(20)]
        self.assertEqual(modbusmap.suggest_channels(rows),
                         [(4, 0, 125, "input"), (4, 125, 25, "input"), (16, 0, 20, "output")])

    def test_bits_need_their_register(self):
        rows = [{"table": "coil", "address": 801, "count": 1, "direction": "output", "byte": 100}]
        self.assertEqual(modbusmap.suggest_channels(rows), [(16, 50, 1, "output")])


class Writers(unittest.TestCase):
    def test_csv(self):
        rows = modbusmap.register_map(load())
        parsed = list(csv.DictReader(io.StringIO(modbusmap.to_csv(rows))))
        self.assertEqual(len(parsed), len(rows))
        first = parsed[0]
        self.assertEqual((first["table"], first["address"]), ("input register", "2"))

    def test_json(self):
        cfg = load()
        doc = json.loads(modbusmap.to_json(cfg, modbusmap.register_map(cfg)))
        self.assertEqual((doc["input_bytes"], doc["output_bytes"]), (72, 102))
        self.assertEqual(doc["channels"][0], {"function": 4, "start": 2, "count": 34,
                                              "direction": "input"})

    def test_st(self):
        cfg = load()
        text = modbusmap.to_st(cfg, modbusmap.register_map(cfg))
        self.assertIn("VAR_GLOBAL", text)
        self.assertIn("sensor_0x6000_1 : UDINT; (* input register 2..3, field sensor 0x6000:1 *)", text)
        self.assertIn("sensor_0x6200_3 : REAL; (* holding register 2..3", text)
        self.assertIn("bridge_status : ARRAY[0..3] OF WORD;", text)
        self.assertIn("Suggested client channels", text)
        self.assertTrue(text.rstrip().endswith("*)"))


class Pack(unittest.TestCase):
    def test_pack_bridge_fixture(self):
        cfg = load()
        packed = modbusmap.pack(cfg)
        self.assertEqual(cfg, load(), "pack must not change its input")
        rows = by_name(modbusmap.register_map(packed))
        self.assertEqual(rows["sensor.0x6000:1"]["location"], "%ID0")
        self.assertEqual(rows["sensor.0x6000:2"]["location"], "%IW4")
        self.assertEqual(rows["sensor.0x6000:3"]["location"], "%IB6")
        self.assertEqual(rows["sensor.0x6000:4"]["location"], "%IX7.0")
        self.assertEqual(rows["sensor.0x6200:1"]["location"], "%QW0")
        self.assertEqual(rows["sensor.0x6200:2"]["location"], "%QX2.0")
        self.assertEqual(rows["sensor.0x6200:3"]["location"], "%QD4")
        # Status after data, bridge blocks last and word-aligned.
        self.assertEqual(rows["field.state"]["location"], "%IB8")
        self.assertEqual(rows["bridge.status"]["location"], "%IB12")
        self.assertEqual(rows["bridge.control"]["location"], "%QB8")

    def test_pack_mixed_config_is_dense_and_clean(self):
        cfg = load(VIRTUAL_PLANT)
        cfg["bridge"] = {"listen": "0.0.0.0:502", "status_location": "%IB0",
                         "control_location": "%QB0"}
        packed = modbusmap.pack(cfg)
        rows = modbusmap.register_map(packed)
        used = set()
        for r in rows:
            if r["direction"] != "input":
                continue
            n = 1 if r["table"] == "discrete input" else r["count"] * 2
            used.update(range(r["byte"], r["byte"] + n))
        inputs, _ = modbusmap.image_sizes(rows)
        gaps = [b for b in range(inputs) if b not in used]
        # Only alignment gaps: never two free bytes in a row.
        self.assertFalse([b for b in gaps if b + 1 in gaps], gaps)


class SharedMap(unittest.TestCase):
    def test_example_map_fixture_is_current(self):
        # test/bridge/bridge_host_tests.cpp checks this map against the bridge.
        cfg = load(os.path.join(REPO, "examples", "modbus-bridge", "canworks.json"))
        with open(os.path.join(REPO, "test", "fixtures", "modbus", "example-map.json"), encoding="utf-8") as f:
            self.assertEqual(f.read(), modbusmap.to_json(cfg, modbusmap.register_map(cfg)),
                             "regenerate test/fixtures/modbus/example-map.json with modbusmap.to_json")


class Export(unittest.TestCase):
    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = cli.main(list(argv))
            except SystemExit as e:
                code = e.code
        return code, out.getvalue(), err.getvalue()

    def test_export_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            for ext in ("csv", "json", "st"):
                path = os.path.join(tmp, "map." + ext)
                code, out, err = self.run_cli("--config", BRIDGE, "--export-modbus-map", path)
                self.assertEqual(code, 0, err)
                self.assertTrue(os.path.getsize(path) > 0)
                self.assertIn(path, out)

    def test_export_refuses_plain_config(self):
        cfg = load()
        del cfg["bridge"]
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "plain.json")
            with open(src, "w") as f:
                json.dump(cfg, f)
            code, out, err = self.run_cli("--config", src, "--export-modbus-map",
                                          os.path.join(tmp, "m.csv"))
            self.assertNotEqual(code, 0)
            self.assertIn("not a bridge config", err)

    def test_unknown_format(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, out, err = self.run_cli("--config", BRIDGE, "--export-modbus-map",
                                          os.path.join(tmp, "m.txt"))
            self.assertNotEqual(code, 0)
            self.assertIn("use .csv, .json or .st", err)


if __name__ == "__main__":
    unittest.main()
