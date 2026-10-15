"""PDO layouts without a configuration and DBC files in a trace
(canopen-bus-trace: "PDO decoding without a configuration", "DBC files in a
trace")."""

import os
import struct
import unittest

from canworks.bustrace import explain as explain_mod
from canworks.bustrace.decode import Decoder
from canworks.bustrace.model import Frame
from canworks.bustrace.recorder import Session
from canworks.eds import Eds
from canworks.raw import dbc as dbc_mod

from .test_contract import REPO

SERVO = os.path.join(REPO, "config", "cia402-drive", "servo402.eds")
PINGPONG_DBC = os.path.join(os.path.dirname(__file__), "data", "dbc", "pingpong.dbc")
T0 = 1_000_000


def write(nid, index, sub, value, size, t):
    """An expedited SDO download of `value` and the server's confirmation."""
    cmd = {1: 0x2F, 2: 0x2B, 4: 0x23}[size]
    req = bytes([cmd]) + struct.pack("<HB", index, sub) + value.to_bytes(size, "little").ljust(4, b"\0")
    ans = bytes([0x60]) + struct.pack("<HB", index, sub) + b"\0\0\0\0"
    return [Frame(t, 0x600 + nid, req, tx=True), Frame(t + 100, 0x580 + nid, ans)]


def remap_tpdo1(nid, t):
    """A master's boot writes: TPDO1 off, mapping 0x6064:0 (32 bit) alone, on."""
    out = []
    for i, (index, sub, value, size) in enumerate([
            (0x1800, 1, 0x80000180 + nid, 4), (0x1A00, 0, 0, 1), (0x1A00, 1, 0x60640020, 4), (0x1A00, 0, 1, 1),
            (0x1800, 1, 0x180 + nid, 4)]):
        out += write(nid, index, sub, value, size, t + i * 1000)
    return out


def servo_decoder():
    d = Decoder()
    d.set_node_eds(5, Eds.read(SERVO))
    d.node_names[5] = ""
    return d


class EdsDefaults(unittest.TestCase):
    def test_tpdo_with_eds_defaults(self):
        d = servo_decoder()
        out = d.decode(Frame(T0, 0x185, bytes([0x37, 0x02, 0x08])))
        self.assertEqual(out.kind, "pdo")
        self.assertEqual(out.name, "TPDO1")
        self.assertEqual(out.source, "eds")
        self.assertIn("node 5", out.text)
        self.assertIn("=567", out.text)  # 0x0237
        self.assertIn("=8", out.text)
        self.assertEqual(len(out.signals), 2)

    def test_signal_keys_for_graphs(self):
        keys = [k for k, _, _ in servo_decoder().signal_keys()]
        self.assertTrue(any(k.startswith("node5.TPDO1.") for k in keys))

    def test_nothing_known_stays_raw(self):
        d = Decoder()
        out = d.decode(Frame(T0, 0x1B2, bytes(8)))
        self.assertEqual(out.name, "TPDO1")
        self.assertIsNone(out.source)
        self.assertEqual(out.text, "node 50 00 00 00 00 00 00 00 00")

    def test_inspector_layout_line(self):
        d = servo_decoder()
        m = explain_mod.explain(Frame(T0, 0x185, bytes([0x37, 0x02, 0x08])), d)
        self.assertEqual(m["kind"], "pdo")
        self.assertEqual(m["layout"]["source"], "eds")
        self.assertIn("EDS defaults", m["layout"]["text"])
        raw = explain_mod.explain(Frame(T0, 0x1B2, bytes(8)), d)
        self.assertIsNone(raw["layout"]["source"])
        self.assertEqual(raw["layout"]["node"], 50)


class LearnedOnTheBus(unittest.TestCase):
    def frames(self):
        before = Frame(T0, 0x185, bytes([0x37, 0x02, 0x08]))
        boot = remap_tpdo1(5, T0 + 10_000)
        after = Frame(T0 + 50_000, 0x185, (1200).to_bytes(4, "little"))
        return before, boot, after

    def test_before_and_after_the_master_remaps(self):
        before, boot, after = self.frames()
        s = Session(servo_decoder())
        s.feed([before] + boot + [after])
        dec = s.decoder.clone()
        old = dec.decode(before)
        new = dec.decode(after)
        self.assertEqual(old.source, "eds")
        self.assertEqual(len(old.signals), 2)
        self.assertEqual(new.source, "bus")
        self.assertEqual([v for _, v in new.signals], [1200])
        m = explain_mod.explain(after, s.decoder)
        self.assertEqual(m["layout"]["source"], "bus")
        self.assertEqual(m["layout"]["since_us"], boot[-1].time_us)

    def test_learned_without_eds(self):
        boot = remap_tpdo1(49, T0)
        d = Decoder()
        for f in boot:
            d.decode(f)
        out = d.decode(Frame(T0 + 50_000, 0x180 + 49, (7).to_bytes(4, "little")))
        self.assertEqual(out.source, "bus")
        self.assertIn("=7", out.text)
        # 0x6064 is in the CiA 402 notes only: named from them
        self.assertIn("Position actual value", out.text)

    def test_unconfirmed_write_is_not_learned(self):
        d = Decoder()
        for f in remap_tpdo1(49, T0):
            if f.can_id != 0x580 + 49:
                d.decode(f)
        self.assertIsNone(d.decode(Frame(T0 + 50_000, 0x180 + 49, bytes(4))).source)

    def test_disabled_pdo_stops_decoding(self):
        d = servo_decoder()
        for f in write(5, 0x1800, 1, 0x80000185, 4, T0):
            d.decode(f)
        self.assertIsNone(d.decode(Frame(T0 + 5000, 0x185, bytes(3))).source)

    def test_clones_do_not_learn(self):
        d = Decoder()
        c = d.clone()
        for f in remap_tpdo1(49, T0):
            c.decode(f)
        self.assertEqual(d.cob_versions, {})

    def test_series_of_learned_signals(self):
        s = Session(Decoder())
        s.feed(remap_tpdo1(49, T0) + [Frame(T0 + 50_000, 0x180 + 49, (7).to_bytes(4, "little"))])
        keys = [k for k in s.analysis.series if k.startswith("node49.TPDO1.")]
        self.assertEqual(len(keys), 1)

    def test_device_read(self):
        d = Decoder()
        d.add_device_values(49, {(0x1800, 1): 0x1B1, (0x1A00, 0): 1, (0x1A00, 1): 0x60000108}, 2 * T0)
        self.assertIsNone(d.decode(Frame(T0, 0x1B1, b"\x05")).source)
        out = d.decode(Frame(3 * T0, 0x1B1, b"\x05"))
        self.assertEqual(out.source, "device")
        self.assertEqual([v for _, v in out.signals], [5])


class DbcFiles(unittest.TestCase):
    def dbc(self):
        return ("pingpong.dbc", dbc_mod.read_dbc(PINGPONG_DBC), [])

    def test_dbc_over_inferred_layout(self):
        d = Decoder()
        d.set_node_eds(2, Eds.read(os.path.join(REPO, "config", "pingpong", "cpp-slave.eds")))
        d.attach_dbc([self.dbc()])
        out = d.decode(Frame(T0, 0x182, bytes([1, 0, 0, 0])))
        self.assertEqual(out.source, "dbc")
        self.assertTrue(out.name.startswith("pingpong_TPDO1"))
        self.assertEqual(d.dbc_files[0]["used"], d.dbc_files[0]["total"])

    def test_heartbeat_keeps_canopen_text(self):
        d = Decoder()
        d.attach_dbc([self.dbc()])
        out = d.decode(Frame(T0, 0x702, b"\x05"))
        self.assertEqual(out.kind, "heartbeat")
        self.assertIn("OPERATIONAL", out.text)
        self.assertIn("pingpong_Heartbeat", out.text)
        m = explain_mod.explain(Frame(T0, 0x702, b"\x05"), d)
        self.assertTrue(any("DBC file" in n for n in m["notes"]))

    def test_second_file_on_same_identifier_not_used(self):
        d = Decoder()
        d.attach_dbc([self.dbc(), ("copy.dbc", dbc_mod.read_dbc(PINGPONG_DBC), [])])
        self.assertEqual(d.dbc_files[1]["used"], 0)
        self.assertTrue(all("pingpong.dbc" in u for u in d.dbc_files[1]["unused"]))

    def test_configuration_wins(self):
        from .test_bustrace import PINGPONG
        import json
        with open(PINGPONG) as f:
            cfg = json.load(f)
        d = Decoder.from_config(cfg, PINGPONG)
        d.attach_dbc([self.dbc()])
        out = d.decode(Frame(T0, 0x182, bytes([1, 0, 0, 0])))
        self.assertIsNone(out.source)
        self.assertTrue(any("configuration's pingpong_TPDO1" in u for u in d.dbc_files[0]["unused"]))

    def test_inspector_shows_dbc_message(self):
        d = Decoder()
        d.attach_dbc([self.dbc()])
        m = explain_mod.explain(Frame(T0, 0x182, bytes([1, 0, 0, 0])), d)
        self.assertEqual(m["kind"], "raw")
        self.assertIn("DBC message", m["meaning"])

    def test_multiplexed_message_on_extended_identifier(self):
        import tempfile
        text = (
            'VERSION ""\n\nNS_ :\n\nBS_:\n\nBU_: Sensor\n\n'
            'BO_ 2147484416 Status: 3 Sensor\n'  # extended 0x300
            ' SG_ Page M : 0|8@1+ (1,0) [0|255] "" Vector__XXX\n'
            ' SG_ Temp m1 : 8|16@1- (0.1,0) [0|0] "degC" Vector__XXX\n'
            ' SG_ Press m2 : 8|16@1+ (1,0) [0|0] "kPa" Vector__XXX\n')
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "mux.dbc")
            with open(path, "w") as f:
                f.write(text)
            d = Decoder()
            d.attach_dbc([("mux.dbc", dbc_mod.read_dbc(path), [])])
        out = d.decode(Frame(T0, 0x300, bytes([2, 0x10, 0x00]), ext=True))
        self.assertEqual(out.source, "dbc")
        self.assertIn("Press=16", out.text)
        self.assertNotIn("Temp", out.text)
        # The same number as a standard identifier is not this message.
        self.assertNotEqual(d.decode(Frame(T0, 0x300, bytes([2, 0x10, 0x00]))).source, "dbc")

    def test_plain_network(self):
        from canworks.bustrace.decode import PlainDecoder
        d = PlainDecoder()
        d.attach_dbc([self.dbc()])
        self.assertEqual(d.decode(Frame(T0, 0x182, bytes(4))).source, "dbc")


if __name__ == "__main__":
    unittest.main()


# -- the configurator's routes ----------------------------------------------------

from .test_configurator_trace import Trace, b64  # noqa: E402
from .fake_diag import FakePlugin  # noqa: E402


class DecodingRoutes(Trace):
    def test_add_remove_and_remembered(self):
        self.open_sample()
        view = self.ok("GET", "/api/trace/decoding")
        self.assertEqual(view["dbc"], [])
        with open(PINGPONG_DBC, "rb") as f:
            data = f.read()
        view = self.ok("POST", "/api/trace/decoding", {"action": "add", "name": "pingpong.dbc", "data": b64(data)})
        self.assertEqual(len(view["dbc"]), 1)
        row = view["dbc"][0]
        self.assertEqual((row["name"], row["used"], row["total"]), ("pingpong.dbc", 6, 6))
        self.assertFalse(row["path"].startswith(self.project))
        rows = self.ok("POST", "/api/trace/frames", {"offset": 0, "count": 50})["rows"]
        tpdo = [r for r in rows if r["id"] == "182"]
        self.assertTrue(tpdo and tpdo[0]["source"] == "dbc" and tpdo[0]["name"] == "pingpong_TPDO1")
        # Remembered: a newly opened trace decodes with it too.
        self.open_sample()
        rows = self.ok("POST", "/api/trace/frames", {"offset": 0, "count": 50})["rows"]
        self.assertEqual([r for r in rows if r["id"] == "182"][0]["source"], "dbc")
        view = self.ok("POST", "/api/trace/decoding", {"action": "remove", "path": row["path"]})
        self.assertEqual(view["dbc"], [])
        rows = self.ok("POST", "/api/trace/frames", {"offset": 0, "count": 50})["rows"]
        self.assertIsNone([r for r in rows if r["id"] == "182"][0]["source"])

    def test_missing_and_bad_files(self):
        status, data, _ = self.request("POST", "/api/trace/decoding", {"action": "add", "path": "/no/such.dbc"})
        self.assertEqual(status, 422, data)
        status, data, _ = self.request("POST", "/api/trace/decoding",
                                       {"action": "add", "name": "x.dbc", "data": b64(b"not a dbc at all {")})
        self.assertEqual(status, 422, data)
        path = os.path.join(self.dir, "gone.dbc")
        with open(PINGPONG_DBC, "rb") as src, open(path, "wb") as dst:
            dst.write(src.read())
        self.ok("POST", "/api/trace/decoding", {"action": "add", "path": path})
        os.remove(path)
        view = self.ok("GET", "/api/trace/decoding")
        self.assertTrue(view["dbc"][0]["missing"])

    def test_pdo_layout_read_from_the_device(self):
        fake = FakePlugin()
        fake.__enter__()
        self.addCleanup(fake.__exit__)
        self.connect(fake)
        self.save(self.pingpong())
        fake.objects.update({(2, 0x1000, 0): (0x191).to_bytes(4, "little"),
                        (2, 0x1800, 1): (0x182).to_bytes(4, "little"), (2, 0x1800, 2): b"\xff",
                        (2, 0x1A00, 0): b"\x01", (2, 0x1A00, 1): (0x60000108).to_bytes(4, "little")})
        r = self.ok("POST", "/api/online/pdo_layout", {"node": 2})
        self.assertEqual(r["pdos"], [{"name": "TPDO1", "cob_id": 0x182}])
        self.assertEqual(r["device_type"], 0x191)


class CommandLine(unittest.TestCase):
    def test_convert_with_dbc(self):
        import contextlib
        import io
        import tempfile
        from canworks import diag
        with tempfile.TemporaryDirectory() as d:
            log = os.path.join(d, "in.log")
            with open(log, "w") as f:
                f.write("(0.0) vcan0 182#01000000\n(0.1) vcan0 702#05\n")
            out = os.path.join(d, "out.csv")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(diag.main(["convert", log, out, "--dbc", PINGPONG_DBC]), 0)
            with open(out) as f:
                text = f.read()
        self.assertIn("pingpong_TPDO1 UNSIGNED32_sent_from_slave=1", text)
        self.assertIn("node 2 OPERATIONAL; pingpong_Heartbeat", text)
