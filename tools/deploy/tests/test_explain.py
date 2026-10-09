"""Frame explanation (canopen-frame-explain): the four layers for every
frame kind, the wire reconstruction, the frame builder, the sequence views
of canopen-bus-trace and `canworks-diag explain`."""

import contextlib
import copy
import io
import json
import os
import shutil
import tempfile
import unittest

from canworks import diag
from canworks.bustrace import explain_texts, formats, framebuild, sequences
from canworks.bustrace.decode import Decoder
from canworks.bustrace.explain import (candump_text, context_for, explain, format_text, parse_frame)
from canworks.bustrace.model import Frame, Trace
from canworks.bustrace.recorder import Session
from canworks.bustrace.wire import crc15, crc15_bytes, unstuff, wire

from .test_contract import REPO

RTD = os.path.join(REPO, "config", "rtd-sensor", "canopen_config.json")
GOLDEN = os.path.join(os.path.dirname(__file__), "data", "explain")


def rtd_config():
    with open(RTD, encoding="utf-8") as f:
        return json.load(f)


def rtd_decoder(cfg=None):
    return Decoder.from_config(cfg or rtd_config(), RTD)


def ex(text, dec=None, bitrate=None, context=None):
    return explain(parse_frame(text), dec or rtd_decoder(), bitrate, context)


def field(m, name):
    for f in m["fields"]:
        if f["name"] == name:
            return f
    raise AssertionError("no field %r in %s" % (name, [f["name"] for f in m["fields"]]))


def bit_of(data, n):
    return int.from_bytes(bytes(data).ljust(8, b"\0"), "little") >> n & 1


# Frames of every kind the explanation knows.
FRAMES = [
    "000#0105", "000#8100", "080#", "080#07", "100#00E0C1031E2A", "085#1023030000000000", "085#0000000000000000",
    "705#00", "705#05", "705#7F", "705#85", "705#R", "605#4018100100000000", "585#4318100178563412",
    "605#2B171000E8030000", "585#6017100000000000", "585#8000100002000106", "605#2108100012000000",
    "605#0030313233343536", "585#4108100012000000", "585#004F70656E504C43", "605#6000000000000000",
    "605#C2081000000000", "585#C4081000120000", "605#A4081000127F0000", "605#A3000000000000",
    "605#A2050F0000000000", "605#A1000000000000", "585#A0171000000000", "585#A20510", "185#EA00FFFF10002000",
    "285#25000000", "185#R", "190#0102", "7E5#1105", "7E4#1100", "7E5#130002", "7E5#4078563412", "7E4#5E05",
    "7E5#5100000000800000", "18FF0017#0102", "123#AA",
]


class Wire(unittest.TestCase):
    def test_crc_check_value(self):
        self.assertEqual(crc15_bytes(b"123456789"), 0x059E)

    def test_spec_example_at_500k(self):
        w = wire(0x185, data=bytes.fromhex("2500EA00"), bitrate=500000)
        self.assertEqual(w["stuff_bits"], 3)
        self.assertEqual(w["frame_bits"], 79)
        self.assertEqual(w["frame_bits"] - w["stuff_bits"], 76)
        self.assertAlmostEqual(w["duration_us"], 158.0)
        self.assertFalse(w["bitrate_assumed"])

    def test_stuffing_rules(self):
        for text in FRAMES:
            f = parse_frame(text)
            w = wire(f.can_id, f.ext, f.rtr, f.data, f.dlc)
            bits = w["bits"]
            end = max(k for k, b in enumerate(bits) if b["field"] in ("crc", "stuff") and b["ref"] != "crcdel")
            run, last = 0, None
            for b in bits[:end + 1]:
                run = run + 1 if b["v"] == last else 1
                last = b["v"]
                self.assertLess(run, 6, text)
            for k, b in enumerate(bits):
                if b["field"] == "stuff":
                    prev = [x["v"] for x in bits[k - 5:k]]
                    self.assertEqual(len(set(prev)), 1, text)
                    self.assertNotEqual(b["v"], prev[0], text)
            raw = unstuff(bits)
            sof_to_data = [b for b in bits if b["field"] not in ("stuff", "crc", "crcdel", "ack", "ackdel", "eof",
                                                                    "ifs")]
            crc_bits = [b["v"] for b in bits if b["field"] == "crc" and b["ref"] != "crcdel"]
            self.assertEqual(crc15([b["v"] for b in sof_to_data]),
                             int("".join(map(str, crc_bits)), 2), text)
            self.assertEqual(len(raw), len(bits) - w["stuff_bits"])

    def test_extended_and_remote(self):
        w = wire(0x18FF0017, ext=True, data=b"\x01\x02")
        refs = [b["ref"] for b in w["bits"] if b["field"] != "stuff"]
        self.assertEqual(refs[:13], ["sof"] + ["id.%d" % n for n in range(28, 17, -1)] + ["srr"])
        self.assertEqual(refs[13], "ide")
        self.assertEqual(refs[14:32], ["id.%d" % n for n in range(17, -1, -1)])
        self.assertEqual(refs[32:35], ["rtr", "r1", "r0"])
        self.assertTrue(w["bitrate_assumed"])
        self.assertEqual(w["bitrate"], 500000)
        r = wire(0x705, rtr=True, dlc=1)
        rtr = next(b for b in r["bits"] if b["ref"] == "rtr")
        self.assertEqual(rtr["v"], 1)
        self.assertFalse(any(b["field"] == "data" for b in r["bits"]))
        self.assertEqual(r["data_share"], 0)

    def test_classic_can_only(self):
        with self.assertRaises(ValueError):
            wire(0x185, data=bytes(9))


class Layers(unittest.TestCase):
    def test_every_bit_in_one_field(self):
        dec = rtd_decoder()
        for text in FRAMES:
            m = ex(text, dec)
            n = len(m["frame"]["data"].split()) * 8
            owners = [0] * n
            for f in m["fields"]:
                for b in range(f["start"], f["start"] + f["length"]):
                    owners[b] += 1
            self.assertEqual(owners, [1] * n, text)
            self.assertTrue(m["meaning"].endswith("."), text)
            self.assertTrue(m["about"], text)
            for f in m["fields"]:
                self.assertTrue(f["text"], (text, f["name"]))

    def test_sdo_answer_meaning(self):
        m = ex("585#4318100178563412")
        self.assertIn("1018h:01", m["meaning"])
        self.assertIn("Vendor-ID", m["meaning"])
        self.assertIn("305419896 (0x12345678)", m["meaning"])
        self.assertEqual(m["identifier"]["function_code"], 11)
        self.assertEqual(m["identifier"]["node"], 5)

    def test_sdo_command_byte(self):
        m = ex("605#2B171000E8030000")
        self.assertEqual(field(m, "Client command specifier")["value"], "1 = initiate download")
        self.assertEqual(field(m, "n: bytes without data")["value"], "2 (2 data bytes)")
        self.assertEqual(field(m, "e: expedited")["value"], "1")
        self.assertEqual(field(m, "s: size indicated")["value"], "1")
        data = field(m, "Data")
        self.assertEqual((data["start"], data["length"]), (32, 16))
        self.assertTrue(data["value"].startswith("1000"))
        self.assertIn("E8 03", data["how"])
        self.assertEqual(field(m, "Padding")["start"], 48)
        self.assertIn("1017h:00", m["meaning"])

    def test_little_endian_working(self):
        m = ex("185#0000EA0010002000")
        f = next(f for f in m["fields"] if f["start"] == 16)
        self.assertEqual(f["how"], "bytes 2-3 = EA 00, low byte first, so read backwards: 0x00EA")
        self.assertTrue(f["value"].startswith("234"))
        self.assertEqual(f["location"], "%IW101")

    def test_signed_value(self):
        m = ex("185#FFFF000000000000")
        self.assertTrue(m["fields"][0]["value"].startswith("-1 "))

    def test_byte_object_bits(self):
        m = ex("285#25000000")
        f = m["fields"][0]
        self.assertEqual((f["start"], f["length"], f["location"], f["type"]), (0, 8, "%IB100", "UNSIGNED8"))
        on = [k for k in range(8) if bit_of(bytes.fromhex("25"), k)]
        self.assertEqual(on, [0, 2, 5])

    def test_emcy_register_bits(self):
        m = ex("085#1023030000000000")
        reg = field(m, "Error register (1001h)")
        self.assertEqual(reg["start"], 16)
        self.assertEqual(len(reg["bits"]), 8)
        self.assertEqual(reg["bits"][0]["name"], "generic error")
        self.assertEqual(reg["bits"][1]["name"], "current")
        self.assertEqual([k for k in range(8) if bit_of(bytes.fromhex("1023030000000000"), 16 + k)], [0, 1])
        self.assertIn("0x2310", m["meaning"])

    def test_heartbeat_and_guarding(self):
        self.assertIn("booted", ex("705#00")["meaning"])
        self.assertIn("OPERATIONAL", ex("705#05")["meaning"])
        g = ex("705#R")
        self.assertIn("node guarding", g["meaning"])
        self.assertEqual(g["fields"], [])
        self.assertIn("toggle 1", ex("705#85")["meaning"])

    def test_configured_cob_id(self):
        cfg = rtd_config()
        cfg["nodes"][0]["tx_pdos"][1]["cob_id"] = "0x1A0"
        dec = rtd_decoder(cfg)
        m = ex("1A0#01020304", dec)
        self.assertEqual(m["kind"], "pdo")
        self.assertEqual(m["identifier"]["message"], "TPDO2")
        self.assertTrue(m["identifier"]["configured"])
        self.assertIn("configuration", m["identifier"]["configured_text"])
        self.assertFalse(ex("185#00", dec)["identifier"]["configured"])

    def test_no_configuration(self):
        m = ex("185#2500EA00", Decoder())
        self.assertEqual(m["kind"], "pdo")
        self.assertIn("mapping is unknown", m["meaning"])
        self.assertEqual(field(m, "Process data")["value"], "25 00 EA 00")
        self.assertEqual(ex("705#05", Decoder())["title"], "Heartbeat of node 5")

    def test_error_frame(self):
        f = Frame(0, 0x044, bytes([0, 0x10, 0, 0, 0, 0, 130, 10]), err=True)
        m = explain(f, rtd_decoder())
        self.assertEqual(m["kind"], "error")
        self.assertIsNone(m["wire"])
        self.assertIn("controller problem", m["meaning"])
        self.assertIn("bus-off", m["meaning"])
        self.assertEqual(field(m, "TX error counter")["value"], "130")
        self.assertTrue(m["error_classes"]["bits"][6]["set"])

    def test_lss_and_extended(self):
        self.assertIn("configure node-ID 5", ex("7E5#1105")["meaning"])
        self.assertIsNone(ex("7E5#1105")["identifier"]["node"])
        e = ex("18FF0017#0102")
        self.assertEqual(e["kind"], "ext")
        self.assertEqual(e["identifier"]["width"], 29)

    def test_segment_with_context(self):
        dec = rtd_decoder()
        frames = framebuild.sdo(dec, 5, 0x1008, 0, "read", "eighteen bytes ok!", type_name="VISIBLE_STRING")
        t = Trace()
        for k, x in enumerate(frames):
            x["frame"].time_us = 1000 * k
            t.append(x["frame"])
        self.assertEqual(len(t), 8)  # request, answer, 3 x (segment request, segment)
        m = explain(t.frame(7), dec, None, context_for(t, 7, dec))
        self.assertIn("Segment 3 of the read of 1008h:00", m["meaning"])
        self.assertIn("eighteen bytes ok!", m["meaning"])
        alone = explain(t.frame(7), dec)
        self.assertTrue(any("frames before it" in n for n in alone["notes"]))

    def test_toggle_error_noted(self):
        dec = rtd_decoder()
        frames = framebuild.sdo(dec, 5, 0x1008, 0, "read", "eighteen bytes ok!", type_name="VISIBLE_STRING")
        t = Trace()
        for k, x in enumerate(frames):
            f = x["frame"]
            if k == 5:  # the second segment with the wrong toggle bit
                f = Frame(0, f.can_id, bytes([f.data[0] ^ 0x10]) + f.data[1:])
            f.time_us = 1000 * k
            t.append(f)
        m = explain(t.frame(5), dec, None, context_for(t, 5, dec))
        self.assertTrue(any("toggle bit should be 1" in n for n in m["notes"]))

    def test_parse_frame(self):
        self.assertEqual(candump_text(parse_frame("705#r1")), "705#R1")
        self.assertTrue(parse_frame("18FF0017#01").ext)
        for bad, why in (("185#2500E", "whole bytes"), ("185", "ID#DATA"), ("800#00", "11 bits"),
                         ("185#00010203040506070809", "8 data bytes"), ("1G5#00", "hexadecimal")):
            with self.assertRaises(ValueError) as cm:
                parse_frame(bad)
            self.assertIn(why, str(cm.exception))

    def test_golden_text(self):
        dec = rtd_decoder()
        got = "\n".join(format_text(ex(t, dec, 125000)) for t in FRAMES)
        path = os.path.join(GOLDEN, "rtd-sensor.txt")
        if os.environ.get("CANWORKS_UPDATE_GOLDEN"):
            os.makedirs(GOLDEN, exist_ok=True)
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(got)
        with open(path, encoding="utf-8", newline="") as f:
            self.assertEqual(got, f.read())

    def test_texts_complete(self):
        for table in (explain_texts.NMT_COMMANDS, explain_texts.NMT_STATES, explain_texts.SDO_CLIENT,
                      explain_texts.SDO_SERVER):
            for v in table.values():
                self.assertTrue(all(v))
        for k, v in explain_texts.WIRE.items():
            self.assertEqual(len(v), 2, k)
        self.assertEqual(len(explain_texts.ERROR_REGISTER), 8)
        self.assertTrue(all(explain_texts.SDO_BITS.values()))


class Builder(unittest.TestCase):
    def test_sdo_write(self):
        frames = framebuild.sdo(rtd_decoder(), 5, 0x1017, 0, "write", "1000")
        self.assertEqual([candump_text(x["frame"]) for x in frames], ["605#2B171000E8030000", "585#6017100000000000"])

    def test_sdo_read_default(self):
        frames = framebuild.sdo(rtd_decoder(), 5, 0x1018, 1, "read", type_name="UNSIGNED32")
        self.assertEqual(candump_text(frames[0]["frame"]), "605#4018100100000000")
        self.assertTrue(candump_text(frames[1]["frame"]).startswith("585#43181001"))

    def test_segmented_write_round_trip(self):
        dec = rtd_decoder()
        frames = framebuild.sdo(dec, 5, 0x1008, 0, "write", "0123456789ABCDEF", type_name="VISIBLE_STRING")
        self.assertEqual(len(frames), 2 + 2 * 3)
        t = Trace()
        for k, x in enumerate(frames):
            x["frame"].time_us = k
            t.append(x["frame"])
        s = Session(dec, trace=t)
        conv = sequences.sdo_conversations(t, s.analysis.kinds, dec)
        self.assertEqual(len(conv), 1)
        self.assertEqual(conv[0]["result"], "done")
        self.assertEqual(bytes.fromhex(conv[0]["data"].replace(" ", "")), b"0123456789ABCDEF")

    def test_pdo_values_and_range(self):
        dec = rtd_decoder()
        f = framebuild.pdo(dec, 0x185, {"%IW100": -1, "%IW101": 234})[0]["frame"]
        self.assertEqual(f.data.hex(), "ffffea0000000000")
        m = explain(f, dec)
        self.assertTrue(m["fields"][1]["value"].startswith("234"))
        with self.assertRaises(framebuild.BuildError) as cm:
            framebuild.pdo(dec, 0x285, {"%IB100": 300})
        self.assertIn("out of range 0 to 255", str(cm.exception))
        with self.assertRaises(framebuild.BuildError):
            framebuild.pdo(dec, 0x285, {"nonsense": 1})
        with self.assertRaises(framebuild.BuildError):
            framebuild.pdo(dec, 0x385, {})

    def test_other_builders(self):
        self.assertEqual(candump_text(framebuild.nmt("start", 0)[0]["frame"]), "000#0100")
        self.assertEqual(candump_text(framebuild.heartbeat(5, "preop")[0]["frame"]), "705#7F")
        self.assertEqual(candump_text(framebuild.emcy(5, 0x2310, 3)[0]["frame"]), "085#1023030000000000")
        with self.assertRaises(framebuild.BuildError):
            framebuild.heartbeat(200)

    def test_examples_from_config(self):
        dec = rtd_decoder()
        ex_ = framebuild.examples(dec)
        labels = [(e["group"], e["label"]) for e in ex_]
        self.assertIn(("node 5 (rtd)", "Boot-up"), labels)
        self.assertIn(("node 5 (rtd)", "TPDO1"), labels)
        self.assertIn(("node 5 (rtd)", "SDO read of 1018h:01 (vendor-ID)"), labels)
        for e in ex_:
            for x in e["frames"]:
                explain(x["frame"], dec)  # every example explains


def boot_trace(dec, expected, refuse=None, late_us=None):
    """A boot of node 5 as the master makes it: boot-up, the configuration's
    writes (one refused when `refuse` names its position), NMT start, then
    three SYNC periods of 10 ms with TPDO1 300 us (or late_us) after SYNC."""
    t = Trace()
    now = [1_000_000]

    def add(f, dt=500):
        f.time_us = now[0]
        now[0] += dt
        t.append(f)

    add(framebuild.heartbeat(5, "boot-up")[0]["frame"])
    for k, (index, sub, data, _src) in enumerate(expected[5]):
        if k == refuse:
            add(Frame(0, 0x605, bytes([0x23 | (4 - len(data)) << 2]) + index.to_bytes(2, "little") + bytes([sub])
                      + data.ljust(4, b"\0")))
            add(Frame(0, 0x585, bytes([0x80]) + index.to_bytes(2, "little") + bytes([sub])
                      + (0x06010002).to_bytes(4, "little")))
            continue
        for x in framebuild.sdo(dec, 5, index, sub, "write", data.hex(), type_name="OCTET_STRING"):
            add(x["frame"])
    add(framebuild.nmt("start", 0)[0]["frame"])
    for c in range(3):
        add(Frame(0, 0x080, b""), late_us if (late_us and c == 1) else 300)
        add(framebuild.pdo(dec, 0x185, {"%IW100": c})[0]["frame"], 300)
        add(framebuild.heartbeat(5)[0]["frame"], 10000 - 600 - ((late_us - 300) if (late_us and c == 1) else 0))
    return t


class Sequences(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = rtd_config()
        cls.dec = rtd_decoder(cls.cfg)
        cls.expected = sequences.expected_writes(cls.cfg, RTD)

    def session(self, t):
        return Session(self.dec, trace=t)

    def test_conversations_and_abort(self):
        t = boot_trace(self.dec, self.expected, refuse=3)
        s = self.session(t)
        convs = sequences.sdo_conversations(t, s.analysis.kinds, self.dec)
        self.assertEqual(len(convs), len(self.expected[5]))
        aborted = [c for c in convs if c["result"] == "aborted"]
        self.assertEqual(len(aborted), 1)
        self.assertEqual(aborted[0]["abort_text"], "attempt to write a read only object")
        self.assertEqual([st["from"] for st in aborted[0]["steps"]], ["PLC", "node"])
        self.assertEqual(sequences.conversation_at(convs, aborted[0]["steps"][1]["seq"]), aborted[0])

    def test_segmented_upload_conversation(self):
        frames = framebuild.sdo(self.dec, 5, 0x1008, 0, "read", "eighteen bytes ok!", type_name="VISIBLE_STRING")
        t = Trace()
        for k, x in enumerate(frames):
            x["frame"].time_us = 100 * k
            t.append(x["frame"])
        s = self.session(t)
        c = sequences.sdo_conversations(t, s.analysis.kinds, self.dec)[0]
        self.assertEqual((c["mode"], c["result"], c["frames"], c["size"]), ("segmented", "done", 8, 18))
        self.assertIn("t=1", c["steps"][5]["text"])

    def test_block_download_conversation(self):
        n = 5
        data = bytes(range(20))
        req, ans = 0x600 + n, 0x580 + n
        frames = [
            Frame(0, req, bytes([0xC6, 0x08, 0x10, 0x00]) + len(data).to_bytes(4, "little")),
            Frame(0, ans, bytes([0xA4, 0x08, 0x10, 0x00, 127, 0, 0, 0])),
            Frame(0, req, bytes([0x01]) + data[0:7]),
            Frame(0, req, bytes([0x02]) + data[7:14]),
            Frame(0, req, bytes([0x83]) + data[14:20] + b"\0"),
            Frame(0, ans, bytes([0xA2, 3, 127, 0, 0, 0, 0, 0])),
            Frame(0, req, bytes([0xC1 | (1 << 2), 0, 0, 0, 0, 0, 0, 0])),
            Frame(0, ans, bytes([0xA1, 0, 0, 0, 0, 0, 0, 0])),
        ]
        t = Trace()
        for k, f in enumerate(frames):
            f.time_us = k
            t.append(f)
        s = self.session(t)
        c = sequences.sdo_conversations(t, s.analysis.kinds, self.dec)
        self.assertEqual(len(c), 1)
        self.assertEqual((c[0]["mode"], c[0]["result"]), ("block", "done"))
        self.assertEqual(bytes.fromhex(c[0]["data"].replace(" ", "")), data)
        m = explain(t.frame(3), self.dec, None, context_for(t, 3, self.dec))
        self.assertIn("Block segment 2", m["meaning"])

    def test_sync_cycles_and_window(self):
        cfg = copy.deepcopy(self.cfg)
        cfg["master"]["sync_window_us"] = 2000
        dec = rtd_decoder(cfg)
        t = boot_trace(dec, self.expected, late_us=2600)
        s = Session(dec, trace=t)
        cycles = sequences.sync_cycles(t, s.analysis.kinds, dec)
        self.assertEqual(len(cycles), 3)
        self.assertEqual(cycles[0]["period_us"], 10000)
        slow = sequences.slowest_cycle(cycles)
        self.assertEqual((slow["n"], slow["last_sync_pdo_us"], slow["late"]), (1, 2600, 1))
        cyc = sequences.sync_cycle(t, s.analysis.kinds, dec, 1)
        tp = next(r for r in cyc["frames"] if r["group"] == "sync_pdo")
        self.assertEqual((tp["offset_us"], tp["transmission"], tp["in_window"]), (2600, 1, False))
        self.assertTrue(sequences.sync_cycle(t, s.analysis.kinds, dec, 0)["frames"][1]["in_window"])

    def test_boot_story(self):
        t = boot_trace(self.dec, self.expected)
        s = self.session(t)
        stories = sequences.boot_stories(t, s.analysis.kinds, self.dec, self.expected)
        self.assertEqual(len(stories), 1)
        st = stories[0]
        self.assertEqual((st["node"], st["how"], st["result"]), (5, "boot-up", "running"))
        self.assertEqual(st["summary"], {"ok": len(self.expected[5])})
        whats = [x["what"] for x in st["steps"]]
        self.assertEqual(whats[0], "boot-up")
        self.assertEqual(whats[-3:], ["nmt", "pdo", "heartbeat"])

    def test_boot_story_refused_write(self):
        t = boot_trace(self.dec, self.expected, refuse=2)
        s = self.session(t)
        st = sequences.boot_stories(t, s.analysis.kinds, self.dec, self.expected)[0]
        refused = [w for w in st["writes"] if w["status"] == "refused"]
        self.assertEqual(len(refused), 1)
        self.assertEqual(refused[0]["abort_text"], "attempt to write a read only object")
        self.assertEqual(refused[0]["object"], "%04Xh:%02X" % self.expected[5][2][:2])

    def test_boot_story_missing_and_different(self):
        exp = {5: list(self.expected[5])}
        index, sub, data, src = exp[5][0]
        exp[5][0] = (index, sub, b"\x99\x00", src)
        exp[5].append((0x2000, 1, b"\x01", "startup_sdo"))
        t = boot_trace(self.dec, self.expected)
        s = self.session(t)
        st = sequences.boot_stories(t, s.analysis.kinds, self.dec, exp)[0]
        status = {w["object"]: w["status"] for w in st["writes"]}
        self.assertEqual(status["%04Xh:%02X" % (index, sub)], "different")
        self.assertEqual(status["2000h:01"], "missing")

    def test_boot_story_without_pdos_ends_at_operational(self):
        """A node without PDOs: the boot ends at its first OPERATIONAL
        heartbeat; an SDO variable write after the NMT start is a step but
        not compared, and later periodic SDO reads are not part of the boot."""
        t = Trace()
        now = [1_000_000]

        def add(f, dt=500):
            f.time_us = now[0]
            now[0] += dt
            t.append(f)

        add(framebuild.heartbeat(5, "boot-up")[0]["frame"])
        for index, sub, data, _src in self.expected[5]:
            for x in framebuild.sdo(self.dec, 5, index, sub, "write", data.hex(), type_name="OCTET_STRING"):
                add(x["frame"])
        add(framebuild.nmt("start", 0)[0]["frame"])
        for x in framebuild.sdo(self.dec, 5, 0x2054, 1, "write", "01", type_name="OCTET_STRING"):
            add(x["frame"])
        add(framebuild.heartbeat(5)[0]["frame"], 1_000_000)
        for _ in range(20):
            for x in framebuild.sdo(self.dec, 5, 0x1018, 4, "read"):
                add(x["frame"], 1_000_000)
        s = self.session(t)
        st = sequences.boot_stories(t, s.analysis.kinds, self.dec, self.expected)[0]
        self.assertEqual(st["result"], "operational")
        self.assertEqual(st["steps"][-1]["what"], "heartbeat")
        self.assertLess(st["duration_us"], 1_000_000)
        self.assertEqual(st["summary"], {"ok": len(self.expected[5])})
        self.assertIn("2054h:01", " ".join(x["text"] for x in st["steps"]))
        self.assertNotIn("1018h:04", " ".join(x["text"] for x in st["steps"]))


class Cli(unittest.TestCase):
    def run_cli(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = diag.main(argv)
        return rc, out.getvalue(), err.getvalue()

    def test_text(self):
        rc, out, _ = self.run_cli(["explain", "705#05"])
        self.assertEqual(rc, 0)
        self.assertIn("Node 5 is OPERATIONAL.", out)
        self.assertIn("function code 1110 = 14   node ID 0000101 = 5", out)
        self.assertIn("NMT state (bits 0-6)", out)
        self.assertIn("On the wire at 500 kbit/s (assumed)", out)

    def test_json_with_config(self):
        rc, out, _ = self.run_cli(["explain", "--config", RTD, "--format", "json", "185#EA00", "705#00"])
        self.assertEqual(rc, 0)
        models = json.loads(out)
        self.assertEqual(len(models), 2)
        self.assertEqual(models[0]["wire"]["bitrate"], 125000)
        self.assertIn("rtd", models[1]["meaning"])

    def test_trace_file(self):
        dec = rtd_decoder()
        frames = framebuild.sdo(dec, 5, 0x1008, 0, "read", "eighteen bytes ok!", type_name="VISIBLE_STRING")
        t = Trace()
        for k, x in enumerate(frames):
            x["frame"].time_us = 1_000_000 + 100 * k
            t.append(x["frame"])
        t.meta["bitrate"] = 250000
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        path = os.path.join(d, "run.pcapng")
        formats.write_file(t, path, "pcapng")
        rc, out, _ = self.run_cli(["explain", "--trace", path, "--index", "7", "--config", RTD])
        self.assertEqual(rc, 0)
        self.assertIn("Segment 3 of the read of 1008h:00", out)
        self.assertIn("at 125 kbit/s", out)  # the config's bit rate wins
        rc, out, _ = self.run_cli(["explain", "--trace", path, "--index", "7"])
        self.assertIn("at 250 kbit/s", out)

    def test_errors(self):
        for argv, why in ((["explain", "185#2500E"], "whole bytes"),
                          (["explain", "185#000102030405060708090A0B"], "up to 8 data bytes"),
                          (["explain"], "give frames"),
                          (["explain", "--trace", "x.log"], "--index"),
                          (["explain", "--index", "3", "705#05"], "--trace")):
            rc, _, err = self.run_cli(argv)
            self.assertEqual(rc, 2, argv)
            self.assertIn(why, err, argv)


if __name__ == "__main__":
    unittest.main()
