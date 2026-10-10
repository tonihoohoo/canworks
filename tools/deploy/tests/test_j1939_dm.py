"""The J1939 diagnostic message codec (canworks.j1939.dm) against the byte
fixtures the plugin's codec is tested with (test/fixtures/j1939-dm)."""

import json
import os
import unittest

from canworks.j1939 import dm

from .test_contract import REPO

CASES = os.path.join(REPO, "test", "fixtures", "j1939-dm", "cases.json")


def load():
    with open(CASES) as f:
        return json.load(f)["cases"]


class Fixtures(unittest.TestCase):
    def test_dm_lists(self):
        for c in (c for c in load() if c["kind"] == "dm"):
            with self.subTest(c["name"]):
                data = bytes.fromhex(c["data"])
                p = dm.parse_dm(data)
                self.assertEqual((p.lamps, p.flash), (c["lamps"], c["flash"]))
                self.assertEqual([d.as_dict() for d in p.dtcs],
                                 [{k: d[k] for k in ("spn", "fmi", "oc", "cm")} for d in c["dtcs"]])
                self.assertEqual([d.value for d in p.dtcs], [d["value"] for d in c["dtcs"]])
                self.assertEqual([dm.from_value(d["value"]) for d in c["dtcs"]], p.dtcs)
                self.assertEqual(p.lamps_text(), c["lamps_text"])
                if c["name"] != "lamps not available":
                    self.assertEqual(dm.build_dm(p.lamps, p.flash, p.dtcs), data)

    def test_own_dm1(self):
        for c in (c for c in load() if c["kind"] == "own"):
            with self.subTest(c["name"]):
                lamps = c["lamps_output"]
                for a in c["active"]:
                    lamps |= dm.lamp_byte(a["lamps"])
                flash = dm.flash_byte([(a["lamps"], a["flash"]) for a in c["active"]])
                codes = [dm.Dtc(a["spn"], a["fmi"], a["oc"]) for a in c["active"]]
                self.assertEqual(dm.build_dm(lamps, flash, codes), bytes.fromhex(c["data"]))

    def test_dm13(self):
        for c in (c for c in load() if c["kind"] == "dm13"):
            with self.subTest(c["name"]):
                self.assertEqual(dm.dm13_command(bytes.fromhex(c["data"])), c["command"])

    def test_dm22(self):
        for c in (c for c in load() if c["kind"] == "dm22"):
            with self.subTest(c["name"]):
                ctl, reason, d = dm.parse_dm22(bytes.fromhex(c["data"]))
                self.assertEqual((ctl, reason, d.spn, d.fmi), (c["control"], c["reason"], c["spn"], c["fmi"]))

    def test_id_text(self):
        for c in (c for c in load() if c["kind"] == "id"):
            with self.subTest(c["name"]):
                self.assertEqual(dm.parse_id_text(bytes.fromhex(c["data"]), c["pgn"]), c["fields"])


class Codec(unittest.TestCase):
    def test_value_of_spec_scenario(self):
        # j1939-diagnostics "Trouble code value in the PLC".
        self.assertEqual(dm.to_value(520192, 3, 2), 0x021FF000)
        self.assertEqual(dm.from_value(0x021FF000), dm.Dtc(520192, 3, 2))

    def test_fmi_texts(self):
        self.assertEqual(len(dm.FMI_TEXT), 32)
        self.assertEqual(dm.fmi_text(3), "voltage above normal or shorted high")

    def test_dm_pgns(self):
        self.assertEqual(sorted(dm.DM_PGNS), [49920, 57088, 65226, 65227, 65228, 65235])


if __name__ == "__main__":
    unittest.main()
