"""Diagnostic messages in J1939 traces (add-j1939-diagnostics, task 6.1):
DM1/DM2 with lamps and codes (single frame and by BAM), Requests for
DM1/DM2/DM3/DM11 and their ACK/NACK, DM13, DM22, Component and Software
ID, SPN names from the DBC's SPN attribute, and the frame inspector's
explanation of a code's four bytes."""

import json
import os
import shutil
import tempfile
import unittest

from canworks.bustrace.decode import Decoder, decode_all
from canworks.bustrace.explain import explain, format_text, parse_frame
from canworks.bustrace.j1939 import J1939Decoder
from canworks.bustrace.model import Frame
from canworks.j1939 import dm

from .test_j1939_dm_diag import DM_DBC

FMI3 = "FMI 3 (voltage above normal or shorted high)"


def bam(source, pgn, data, t=0):
    """The frames of a BAM of `data` from `source`."""
    packets = (len(data) + 6) // 7
    cm = bytes([32, len(data) & 0xFF, len(data) >> 8, packets, 0xFF, pgn & 0xFF, (pgn >> 8) & 0xFF, pgn >> 16])
    out = [Frame(t, 0x1CECFF00 | source, cm, ext=True)]
    for k in range(packets):
        part = bytes(data[k * 7:k * 7 + 7]).ljust(7, b"\xff")
        out.append(Frame(t + 50000 * (k + 1), 0x1CEBFF00 | source, bytes([k + 1]) + part, ext=True))
    return out


def frame(can_id, data):
    return Frame(0, can_id, bytes(data), ext=True)


def decoder(spn_names=None):
    d = J1939Decoder()
    d.address_names = {0: "Engine", 128: "PLC"}
    d.spn_names = dict(spn_names or {})
    return d


class Decoding(unittest.TestCase):
    def test_dm1_with_two_codes(self):
        """A DM1 BAM from 0 with amber on and two codes: one row."""
        data = dm.build_dm(0x04, 0xFF, [dm.Dtc(520192, 3, 2), dm.Dtc(520193, 1, 1)])
        frames = bam(0, dm.PGN_DM1, data)
        rows = decode_all(decoder(), frames)
        last = rows[-1]
        self.assertEqual((last.kind, last.node, last.name), ("pgn", 0, "DM1"))
        self.assertIn("PGN 65226 from 0 (Engine) (10 bytes by BAM in 2 packets; this row is its last TP.DT, "
                      "packet 2): DM1 (active DTCs), MIL off, red stop off, amber warning on, protect off; ", last.text)
        self.assertIn("SPN 520192 %s OC 2; SPN 520193 FMI 1 (below normal, most severe) OC 1" % FMI3, last.text)
        self.assertEqual([r.name for r in rows[:-1]], ["TP.CM BAM", "TP.DT"])
        self.assertIn("BAM for PGN 65226 (DM1)", rows[0].text)

    def test_dm1_single_frame_lamps_and_flash(self):
        d = decoder().decode(frame(0x18FECA00, dm.build_dm(0x44, 0x3F, [dm.Dtc(520192, 3, 2, cm=True)])))
        self.assertEqual(d.name, "DM1")
        self.assertIn("MIL on (slow flash), red stop off, amber warning on, protect off", d.text)
        self.assertIn("OC 2 [older SPN format]", d.text)

    def test_no_codes(self):
        d1 = decoder().decode(frame(0x18FECA00, dm.build_dm(0, 0xFF, [])))
        self.assertTrue(d1.text.endswith("DM1 (active DTCs), MIL off, red stop off, amber warning off, protect off; "
                                         "no active codes"), d1.text)
        d2 = decoder().decode(frame(0x18FECB00, dm.build_dm(0xFF, 0xFF, [])))
        self.assertEqual(d2.name, "DM2")
        self.assertTrue(d2.text.endswith("DM2 (previously active DTCs), lamps n/a; no previously active codes"))

    def test_clear_and_acknowledgement(self):
        """A Request for DM11 from 249 to 128 and the ACK from 128."""
        dec = decoder()
        req = dec.decode(frame(0x18EA80F9, [0xD3, 0xFE, 0x00]))
        ack = dec.decode(frame(0x18E8FF80, [0, 0xFF, 0xFF, 0xFF, 249, 0xD3, 0xFE, 0x00]))
        self.assertEqual((req.kind, req.name), ("request", "Request DM11"))
        self.assertTrue(req.text.startswith("Request DM11 (clear active DTCs)"), req.text)
        self.assertIn("from 249 to 128 (PLC)", req.text)
        self.assertEqual((ack.kind, ack.name), ("ack", "ACK DM11"))
        self.assertTrue(ack.text.startswith("ACK DM11"), ack.text)
        nack = dec.decode(frame(0x18E8FF80, [1, 0xFF, 0xFF, 0xFF, 249, 0xCC, 0xFE, 0x00]))
        self.assertEqual(nack.name, "NACK DM3")
        for pgn, name in ((dm.PGN_DM1, "Request DM1"), (dm.PGN_DM2, "Request DM2"), (dm.PGN_DM3, "Request DM3")):
            r = dec.decode(frame(0x18EA00F9, [pgn & 0xFF, pgn >> 8, 0]))
            self.assertEqual(r.name, name)
        other = dec.decode(frame(0x18EA00F9, [0x00, 0xFF, 0x00]))
        self.assertEqual(other.name, "Request")

    def test_dm13(self):
        d = decoder().decode(frame(0x18DFFFF9, [0x3F, 0xFF, 0xFF, 0x0F, 0xFF, 0xFF, 0xFF, 0xFF]))
        self.assertEqual(d.name, "DM13")
        self.assertIn("DM13 (stop/start broadcast), current data link stop; suspend signal 0, hold signal 15", d.text)
        d = decoder().decode(frame(0x18DFFFF9, [0x7F, 0xFF, 0xFF, 0xFF, 0x3C, 0x00, 0xFF, 0xFF]))
        self.assertIn("current data link start", d.text)
        self.assertIn("suspend duration 60 s", d.text)

    def test_dm22(self):
        d = decoder({520192: "CoolantLevel"}).decode(
            frame(0x18C300F9, [0x11, 0xFF, 0xFF, 0xFF, 0xFF, 0x00, 0xF0, 0xE3]))
        self.assertEqual(d.name, "DM22")
        self.assertIn("clear active DTC, SPN 520192 CoolantLevel %s" % FMI3, d.text)
        d = decoder().decode(frame(0x18C3F900, [0x13, 0x04, 0xFF, 0xFF, 0xFF, 0x00, 0xF0, 0xE3]))
        self.assertIn("NACK clear active DTC", d.text)
        self.assertIn("reason: DTC no longer active", d.text)

    def test_component_and_software_id(self):
        rows = decode_all(decoder(), bam(0, dm.PGN_COMPONENT_ID, b"MAKER*PX-7*000123*Unit 1*"))
        self.assertEqual(rows[-1].name, "Component ID")
        self.assertIn("make 'MAKER', model 'PX-7', serial number '000123', unit number 'Unit 1'", rows[-1].text)
        rows = decode_all(decoder(), bam(0, dm.PGN_SOFTWARE_ID, b"\x02v1.2*boot 3*"))
        self.assertEqual(rows[-1].name, "Software ID")
        self.assertIn("2 fields: 'v1.2', 'boot 3'", rows[-1].text)

    def test_spn_names_from_the_network_dbc(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        with open(os.path.join(tmp, "dm.dbc"), "w") as f:
            f.write(DM_DBC)
        cfg = {"schema_version": 2, "networks": [{"name": "machine", "interface": "vcan0", "protocol": "j1939",
                                                  "j1939": {"dbc": "dm.dbc", "ecu": {"name": {}}}}]}
        path = os.path.join(tmp, "canworks.json")
        with open(path, "w") as f:
            json.dump(cfg, f)
        dec = Decoder.from_config(cfg, path, network="machine")
        self.assertEqual(dec.spn_names, {520192: "CoolantLevel", 1234: "FirstSpn"})
        d = dec.decode(frame(0x18FECA00, dm.build_dm(0x04, 0xFF, [dm.Dtc(520192, 3, 2)])))
        self.assertEqual(d.name, "DM1")  # decoded as DM1 although the DBC defines PGN 65226
        self.assertIn("SPN 520192 CoolantLevel %s OC 2" % FMI3, d.text)


class Explain(unittest.TestCase):
    def test_the_four_bytes_of_a_code(self):
        data = dm.build_dm(0x04, 0xFF, [dm.Dtc(520192, 3, 2)])
        m = explain(parse_frame("18FECA00#" + data.hex()), decoder({520192: "CoolantLevel"}))
        self.assertEqual((m["kind"], m["title"]), ("dm", "DM1 (active DTCs) from 0 (Engine)"))
        f = {x["name"]: x for x in m["fields"]}
        self.assertEqual(f["amber warning lamp"]["value"], "01 = on")
        self.assertEqual(f["MIL flash"]["value"], "11 = no flash")
        self.assertEqual((f["Code 1 SPN, low 16 bits"]["start"], f["Code 1 SPN, low 16 bits"]["value"]),
                         (16, str(520192 & 0xFFFF)))
        self.assertEqual((f["Code 1 FMI"]["start"], f["Code 1 FMI"]["length"], f["Code 1 FMI"]["value"]),
                         (32, 5, "3 = voltage above normal or shorted high"))
        self.assertEqual((f["Code 1 SPN, top 3 bits"]["start"], f["Code 1 SPN, top 3 bits"]["value"]), (37, "7"))
        self.assertIn("SPN = 61440 + 7 * 65536 = 520192 (CoolantLevel)", f["Code 1 SPN, top 3 bits"]["text"])
        self.assertEqual((f["Code 1 Occurrence count"]["start"], f["Code 1 Occurrence count"]["value"]), (40, "2"))
        self.assertEqual((f["Code 1 CM"]["start"], f["Code 1 CM"]["value"]), (47, "0"))
        self.assertEqual(sum(x["length"] for x in m["fields"]), 64)
        self.assertIn("The PLC sees each code as one UDINT: SPN + FMI * 2**19 + OC * 2**24 + CM * 2**31 (here %d)."
                      % dm.to_value(520192, 3, 2), m["notes"])
        self.assertIn("J1939-73 diagnostic messages", format_text(m))

    def test_no_code_and_other_dms(self):
        m = explain(parse_frame("18FECB00#00FF00000000FFFF"), decoder())
        self.assertIn("No code", [x["name"] for x in m["fields"]])
        m = explain(parse_frame("18DFFFF9#3FFFFFFFFFFFFFFF"), decoder())
        self.assertEqual(m["kind"], "dm")
        self.assertIn("current data link stop", m["meaning"])
        m = explain(parse_frame("18EA80F9#D3FE00"), decoder())
        self.assertIn("PGN 65235 (DM11)", m["meaning"])


if __name__ == "__main__":
    unittest.main()
