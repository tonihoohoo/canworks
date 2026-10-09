"""Raw CAN messages in the PC tools (spec can-raw-messages): the shared
config fixtures, signal packing against the shared vectors, declarations,
DBC export/import and trace decoding."""

import json
import os
import unittest

from canworks import contract as _contract  # noqa: F401 - import order of the package
from canworks.configurator.declare import identifier
from canworks.raw import contract, declare, signals
from canworks.raw.decode import RawDecoder

try:
    import cantools  # noqa: F401
    from canworks.raw import dbc
except ImportError:
    dbc = None

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "..", "..", "test", "fixtures")


def load(name):
    with open(os.path.join(FIXTURES, name)) as f:
        return json.load(f)


class SharedCases(unittest.TestCase):
    def test_cases(self):
        cases = load(os.path.join("config", "cases-raw.json"))["cases"]
        self.assertGreaterEqual(len(cases), 20)
        for case in cases:
            with self.subTest(case["name"]):
                ids = case.get("protocol_ids") or {}

                def use(ident, ext, ids=ids):
                    return "" if ext else ids.get("0x%X" % ident, "")

                errors, warnings, _ = contract.check_raw(case["raw"], "networks[0].raw", case.get("listen_only", False),
                                                         use if ids else None)
                for key, got in (("errors", errors), ("warnings", warnings)):
                    if key not in case:
                        continue
                    want = case[key]
                    self.assertEqual(len(got), len(want), "%s: %r" % (key, got))
                    for w, g in zip(want, got):
                        self.assertIn(w, g)


class Signals(unittest.TestCase):
    def test_vectors(self):
        for c in load("can_signals.json")["cases"]:
            data = bytes.fromhex(c["data"])
            self.assertEqual(signals.unpack(data, c["start_bit"], c["length"], c["big_endian"], c["signed"]), c["value"])
            packed = signals.pack(bytearray(8), c["start_bit"], c["length"], c["value"], c["big_endian"])
            self.assertEqual(bytes(packed).hex(), c["packed"])

    def test_tx_dlc(self):
        self.assertEqual(contract.tx_dlc({"signals": [{"start_bit": 7, "length": 16, "byte_order": "big"}]}), 2)
        self.assertEqual(contract.tx_dlc({"rtr": True}), 0)
        self.assertEqual(contract.tx_dlc({"data_location": "%QL1"}), 8)


CAB = {
    "rx": [{"name": "Joystick", "id": 291, "dlc": 8, "timeout_ms": 300, "status_location": "%IX300.0",
            "signals": [{"name": "X", "start_bit": 0, "length": 12, "signed": True, "scale": 0.1, "unit": "%",
                         "iec_location": "%IW304"}]}],
    "tx": [{"name": "Lamps", "id": 1281, "period_ms": 100,
            "signals": [{"name": "Red", "start_bit": 0, "length": 1, "iec_location": "%QX300.1"},
                        {"name": "Level", "start_bit": 15, "length": 16, "byte_order": "big",
                         "iec_location": "%QW300"}]},
           {"name": "Wake", "id": 0x18FF0080, "extended": True, "on_change": True,
            "signals": [{"name": "V", "start_bit": 0, "length": 8, "iec_location": "%QB1"}]}],
}


class Declarations(unittest.TestCase):
    def test_names_types_comments(self):
        names = set()

        def unique(n):
            names.add(n.lower())
            return n

        decls = declare.declarations(CAB, "", "", "", unique, identifier, {})
        by_name = {d["name"]: d for d in decls}
        self.assertEqual(by_name["Joystick_X"]["type"], "INT")
        self.assertEqual(by_name["Joystick_X"]["location"], "%IW304")
        self.assertIn("scale 0.1, offset 0, unit %", by_name["Joystick_X"]["description"])
        self.assertEqual(by_name["Joystick_status"]["type"], "BOOL")
        self.assertEqual(by_name["Lamps_Level"]["type"], "UINT")
        self.assertEqual(by_name["Wake_V"]["type"], "USINT")


class Decode(unittest.TestCase):
    def test_joystick_row(self):
        d = RawDecoder(CAB)
        self.assertEqual(d.text(0x123, False, bytes([0xFF, 0x0F, 0, 0, 0, 0, 0, 0])), "Joystick X=-1 (-0.1 %)")
        self.assertEqual(d.text(0x124, False, bytes(8)), "")
        self.assertEqual(d.text(0x18FF0080, True, bytes([7])), "Wake V=7")
        self.assertEqual(d.text(0x18FF0080, False, bytes([7])), "")


@unittest.skipIf(dbc is None, "cantools not installed")
class Dbc(unittest.TestCase):
    def test_round_trip(self):
        text = dbc.export_dbc(CAB, "cab")
        messages = {m["name"]: m for m in dbc.read_dbc(text)}
        self.assertEqual(set(messages), {"Joystick", "Lamps", "Wake"})
        self.assertEqual(messages["Lamps"]["senders"], ["PLC"])
        self.assertEqual(messages["Joystick"]["senders"], [])
        joy = dbc.to_entry(messages["Joystick"], "receive")
        self.assertEqual(joy["timeout_ms"], 300)
        self.assertEqual(joy["signals"], [{"name": "X", "start_bit": 0, "length": 12, "byte_order": "little",
                                           "signed": True, "scale": 0.1, "unit": "%"}])
        lamps = dbc.to_entry(messages["Lamps"], "send")
        self.assertEqual(lamps["period_ms"], 100)
        self.assertEqual(lamps["dlc"], 3)
        got = sorted((s["name"], s["start_bit"], s["length"], s["byte_order"]) for s in lamps["signals"])
        self.assertEqual(got, [("Level", 15, 16, "big"), ("Red", 0, 1, "little")])
        wake = dbc.to_entry(messages["Wake"], "send")
        self.assertTrue(wake["extended"])
        self.assertEqual(wake["id"], 0x18FF0080)
        self.assertTrue(wake["on_change"])

    def test_multiplexed_listed(self):
        text = (
            'VERSION ""\nBU_: A\nBO_ 100 M: 8 A\n SG_ Mux M : 0|8@1+ (1,0) [0|0] "" Vector__XXX\n'
            ' SG_ Val m1 : 8|8@1+ (1,0) [0|0] "" Vector__XXX\n SG_ Plain : 16|8@1+ (1,0) [0|0] "" Vector__XXX\n')
        (m,) = dbc.read_dbc(text)
        self.assertTrue(m["multiplexed"])
        self.assertEqual([s["name"] for s in m["signals"]], ["Plain"])


if __name__ == "__main__":
    unittest.main()
