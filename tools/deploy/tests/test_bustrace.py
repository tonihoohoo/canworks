"""Bus traces (canworks.bustrace, canopen-bus-trace spec): file
formats (golden files, round trips, python-can and Wireshark when installed),
CANopen decoding, statistics, triggers, the recorder against the fake
diagnostics channel, and `canworks-diag trace` / `convert`."""

import contextlib
import copy
import io
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import unittest

from canworks import __version__, diag
from canworks.bustrace import formats, triggers
from canworks.bustrace.decode import Decoder, decode_all, signal_value
from canworks.bustrace.model import RECORD_SIZE, Frame, Trace
from canworks.bustrace.recorder import Recorder, Session
from canworks.bustrace.stats import Analysis, frame_bits

from .fake_diag import TOKEN, TWO_NETWORKS, FakePlugin
from .test_contract import FIXTURES, REPO, load_cases

try:
    import can
except ImportError:  # CI installs python-can; locally the read-back tests are skipped
    can = None

GOLDEN = os.path.join(os.path.dirname(__file__), "data", "trace")
PINGPONG = os.path.join(REPO, "config", "pingpong", "canopen_config.json")
EDITOR_PROJECT = os.path.join(FIXTURES, "editor-project")
T0 = 1791181200_000000  # 2026-10-05 06:20:00 UTC


def sample_trace():
    """Node 2 of the ping-pong: NMT start, SYNC/RPDO/TPDO, heartbeat, an SDO
    upload, a segmented upload, an EMCY, an extended frame, an RTR, an error
    frame and a gap."""
    t = Trace()
    t.append(Frame(T0, 0, bytes([1, 2]), tx=True))
    for k in range(5):
        b = T0 + 10000 + k * 10000
        t.append(Frame(b, 0x080, b"", tx=True))
        t.append(Frame(b + 400, 0x202, bytes([k, 0, 0, 0]), tx=True))
        t.append(Frame(b + 1100, 0x182, bytes([k + 1, 0, 0, 0])))
    t.append(Frame(T0 + 55000, 0x702, bytes([5])))
    t.append(Frame(T0 + 60000, 0, gap=True))
    t.append(Frame(T0 + 250000, 0x602, bytes.fromhex("4018100400000000"), tx=True))
    t.append(Frame(T0 + 251200, 0x582, bytes.fromhex("4318100478563412")))
    t.append(Frame(T0 + 260000, 0x602, bytes.fromhex("4000100000000000"), tx=True))
    t.append(Frame(T0 + 261000, 0x582, bytes.fromhex("8000100002000106")))
    t.append(Frame(T0 + 300000, 0x082, bytes.fromhex("1050010000000000")))
    t.append(Frame(T0 + 310000, 0x18FF0017, bytes([1, 2]), ext=True))
    t.append(Frame(T0 + 320000, 0x702, b"", rtr=True, tx=True, dlc=1))
    t.append(Frame(T0 + 330000, 0x020, bytes(8), err=True))
    t.meta.update({"interface": "can0", "bitrate": 125000})
    t.add_marker(T0 + 300000, "trigger: EMCY", "trigger")
    return t


def pingpong_decoder():
    with open(PINGPONG, encoding="utf-8") as f:
        cfg = json.load(f)
    return Decoder.from_config(cfg, PINGPONG)


def two_network_config(folder):
    """Node 2 on two networks: the ping-pong slave on io, a drive with its
    statusword and position in TPDO1 on drives."""
    shutil.copy(os.path.join(REPO, "config", "pingpong", "cpp-slave.eds"), folder)
    shutil.copy(os.path.join(FIXTURES, "eds", "drives", "servo-drive.eds"), folder)
    with open(PINGPONG, encoding="utf-8") as f:
        pp = json.load(f)
    drive = {"node_id": 2, "name": "drive", "eds": "servo-drive.eds", "tx_pdos": [{"entries": [
        {"index": "0x6041", "subindex": 0, "type": "UNSIGNED16", "iec_location": "%IW200"},
        {"index": "0x6064", "subindex": 0, "type": "INTEGER32", "iec_location": "%ID201"}]}]}
    cfg = {"schema_version": 2, "networks": [
        {"name": "io", "adapter": pp["adapter"], "master": pp["master"], "nodes": pp["nodes"]},
        {"name": "drives", "adapter": {"type": "socketcan", "interface": "vcan1", "bitrate": 500000},
         "master": {"node_id": 1}, "nodes": [drive]}]}
    path = os.path.join(folder, "canworks.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f)
    return cfg, path


# TPDO1 of node 2: 0x0237, then 0xFFFFFFFF.
NODE2_TPDO1 = bytes([0x37, 0x02, 0xFF, 0xFF, 0xFF, 0xFF])


def written(trace, fmt, decoder=None):
    out = io.BytesIO()
    formats.write(trace, out, fmt, decoder)
    return out.getvalue()


class Formats(unittest.TestCase):
    def tmp(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        return d

    def test_golden_text_formats(self):
        t = sample_trace()
        dec = pingpong_decoder()
        for fmt, name in (("candump", "sample.log"), ("asc", "sample.asc"), ("trc", "sample.trc"),
                          ("csv", "sample.csv")):
            got = written(t, fmt, dec).decode("utf-8").replace(__version__, "VERSION")
            path = os.path.join(GOLDEN, name)
            if os.environ.get("CANWORKS_UPDATE_GOLDEN"):
                with open(path, "w", encoding="utf-8", newline="") as f:
                    f.write(got)
            with open(path, encoding="utf-8", newline="") as f:
                self.assertEqual(got, f.read(), name)

    def test_gap_only_in_pcapng(self):
        t = sample_trace()
        self.assertNotIn(b"060000", written(t, "candump"))
        back = formats.read(written(t, "pcapng"))
        self.assertEqual([f.time_us for f in back if f.gap], [T0 + 60000])

    def test_pcapng_round_trip_with_metadata(self):
        t = sample_trace()
        t.lost.append((T0 + 100, 7))
        t.kernel_drops = 3
        back = formats.read(written(t, "pcapng"))
        self.assertEqual(list(back), list(t))
        self.assertEqual(back.markers, t.markers)
        self.assertEqual(back.lost, [(T0 + 100, 7)])
        self.assertEqual(back.kernel_drops, 3)
        self.assertEqual(back.meta["bitrate"], 125000)
        self.assertEqual(back.meta["interface"], "can0")

    def test_candump_and_asc_round_trip(self):
        t = sample_trace()
        frames = [f for f in t if not f.gap]
        self.assertEqual(list(formats.read(written(t, "candump"))), frames)
        back = list(formats.read(written(t, "asc")))
        self.assertEqual(len(back), len(frames))
        for a, b in zip(back, frames):
            if b.err:  # ASC ErrorFrame lines carry no class or data
                self.assertTrue(a.err)
                continue
            self.assertEqual(a, b)

    def test_read_classic_pcap_and_candump_without_direction(self):
        import struct
        pkt = struct.pack(">I", 0x182) + bytes([2, 0, 0, 0]) + b"\x05\x06" + bytes(6)
        data = struct.pack("<IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 227)
        data += struct.pack("<IIII", 1791181200, 5, len(pkt), len(pkt)) + pkt
        t = formats.read(data)
        self.assertEqual(list(t), [Frame(T0 + 5, 0x182, b"\x05\x06")])
        t = formats.read(b"(1791181200.000100) can0 123#1122\n(1791181200.000200) can0 18FF0017#R\n")
        self.assertEqual(list(t), [Frame(T0 + 100, 0x123, b"\x11\x22"),
                                   Frame(T0 + 200, 0x18FF0017, b"", ext=True, rtr=True)])

    def test_format_by_extension_and_errors(self):
        self.assertEqual(formats.format_of("a.LOG"), "candump")
        self.assertEqual(formats.format_of("a.x", "blf"), "blf")
        with self.assertRaises(formats.FormatError):
            formats.format_of("a.txt")
        with self.assertRaises(formats.FormatError):
            formats.read(b"LOGG" + bytes(200))
        with self.assertRaises(formats.FormatError):
            formats.read(b"hello\n", "x.txt")

    def test_write_file_is_atomic(self):
        d = self.tmp()
        path = os.path.join(d, "a.blf")
        formats.write_file(sample_trace(), path)
        self.assertEqual(os.listdir(d), ["a.blf"])

    def test_blf_containers_split(self):
        t = Trace()
        t.extend(Frame(T0 + i, 0x181, bytes(8)) for i in range(5000))  # > 128 KiB of objects
        data = written(t, "blf")
        self.assertGreater(data.count(b"LOBJ"), 1)

    def test_signals_csv(self):
        out = io.StringIO()
        formats.write_signals_csv([("a", [(T0, 1), (T0 + 1000, 2)]), ("b", [(T0 + 500, 1.5)])], out)
        self.assertEqual(out.getvalue().splitlines(), [
            "time_s,utc,a,b",
            "0.000000,2026-10-05T06:20:00.000000+00:00,1,",
            "0.000500,2026-10-05T06:20:00.000500+00:00,1,1.5",
            "0.001000,2026-10-05T06:20:00.001000+00:00,2,1.5"])
        # A point that repeats its series' value (the next frame of the PDO) writes no row.
        out = io.StringIO()
        formats.write_signals_csv([("a", [(T0, 1), (T0 + 1000, 1), (T0 + 2000, 1), (T0 + 3000, 2)])], out)
        self.assertEqual([ln.split(",")[0] for ln in out.getvalue().splitlines()[1:]], ["0.000000", "0.003000"])

    @unittest.skipIf(can is None, "python-can is not installed")
    def test_python_can_reads_every_format(self):
        d = self.tmp()
        t = sample_trace()
        frames = [f for f in t if not f.gap]
        for ext in ("log", "asc", "blf", "trc"):
            path = os.path.join(d, "x." + ext)
            formats.write_file(t, path)
            msgs = list(can.LogReader(path))
            # python-can reads candump error frames of other classes than "bus
            # error" as extended data frames and TRC skips them: compare the
            # data frames there.
            want = [f for f in frames if not (f.err and ext in ("log", "trc"))]
            if ext == "log":
                self.assertEqual((msgs[-1].arbitration_id, msgs[-1].is_extended_id), (0x20, True))
                msgs = msgs[:-1]
            self.assertEqual(len(msgs), len(want), ext)
            offset = want[0].t if ext == "asc" else 0  # python-can's ASC times count from the start
            for m, f in zip(msgs, want):
                self.assertEqual(m.is_error_frame, f.err, (ext, f))
                self.assertAlmostEqual(m.timestamp, f.t - offset, places=5, msg=(ext, f))
                if f.err:
                    continue
                self.assertEqual((m.arbitration_id, m.is_extended_id, m.is_remote_frame),
                                 (f.can_id, f.ext, f.rtr), (ext, f))
                self.assertEqual(bytes(m.data), f.data, (ext, f))
                self.assertEqual(not m.is_rx, f.tx, (ext, f))

    def test_wireshark_decodes_canopen(self):
        if not shutil.which("tshark"):
            if os.environ.get("CANWORKS_REQUIRE_TSHARK") == "1":
                self.fail("tshark is not installed (CANWORKS_REQUIRE_TSHARK=1)")
            self.skipTest("tshark is not installed")
        d = self.tmp()
        path = os.path.join(d, "x.pcapng")
        formats.write_file(sample_trace(), path)
        out = subprocess.run(["tshark", "-r", path, "-d", "can.subdissector,canopen"], capture_output=True,
                             text=True, check=True).stdout
        for want in ("NMT", "SYNC", "Default-SDO", "EMCY", "PDO"):
            self.assertIn(want, out)


class Decoding(unittest.TestCase):
    def test_pingpong(self):
        dec = pingpong_decoder()
        self.assertEqual(dec.warnings, [])
        ds = decode_all(dec, sample_trace())
        by = [(d.kind, d.node, d.name, d.text) for d in ds]
        self.assertEqual(by[0], ("nmt", 2, "NMT", "start node 2 (pingpong)"))
        self.assertEqual(by[1][:3], ("sync", None, "SYNC"))
        self.assertEqual(by[2], ("pdo", 2, "pingpong_RPDO1", "UNSIGNED32_received_by_slave=0"))
        self.assertEqual(by[3], ("pdo", 2, "pingpong_TPDO1", "UNSIGNED32_sent_from_slave=1"))
        self.assertEqual(ds[3].signals, [("pingpong_TPDO1.UNSIGNED32_sent_from_slave", 1)])
        self.assertEqual(by[16], ("heartbeat", 2, "Heartbeat", "node 2 (pingpong) OPERATIONAL"))
        self.assertEqual(by[17][0], "gap")
        self.assertEqual(by[18][3], "node 2 (pingpong) read 0x1018:4 Identity object / Serial number")
        self.assertEqual(by[19][3], "node 2 (pingpong) read 0x1018:4 Identity object / Serial number = "
                                    "305419896 (0x12345678)")
        self.assertIn("abort 0x1000:0", by[21][3])
        self.assertIn("0x06010002 attempt to write a read only object", by[21][3])
        self.assertEqual(by[22], ("emcy", 2, "EMCY",
                                  "node 2 (pingpong) 0x5010 device hardware, register 0x01 (generic)"))
        self.assertEqual(by[23][0], "other")
        self.assertEqual(by[24][:3], ("heartbeat", 2, "Node guarding"))
        self.assertEqual(by[25], ("error", None, "error frame", "no acknowledgement"))

    def test_segmented_transfers_join(self):
        dec = pingpong_decoder()
        frames = [Frame(0, 0x602, bytes.fromhex("4008100000000000")),
                  Frame(1, 0x582, bytes.fromhex("4108100009000000")),
                  Frame(2, 0x602, bytes.fromhex("6000000000000000")),
                  Frame(3, 0x582, bytes.fromhex("004C656C7920736C")),
                  Frame(4, 0x602, bytes.fromhex("7000000000000000")),
                  Frame(5, 0x582, bytes.fromhex("1B61766500000000")),
                  Frame(6, 0x602, bytes.fromhex("2100200004000000")),
                  Frame(7, 0x602, bytes.fromhex("0B01020304000000"))]
        ds = decode_all(dec, frames)
        self.assertIn("9 bytes (segmented)", ds[1].text)
        self.assertTrue(ds[5].text.endswith("= 4C 65 6C 79 20 73 6C 61 76 (segmented, done)"), ds[5].text)
        self.assertIn("write 0x2000:0", ds[6].text)
        self.assertTrue(ds[7].text.endswith("(segmented, done)"), ds[7].text)

    def test_block_transfers_join(self):
        dec = pingpong_decoder()
        H = bytes.fromhex
        frames = [  # block download, 9 bytes to 0x2000:0
                  Frame(0, 0x602, H("C600200009000000")),
                  Frame(1, 0x582, H("A000200004000000")),
                  Frame(2, 0x602, H("0101020304050607")),
                  Frame(3, 0x602, H("8208090000000000")),
                  Frame(4, 0x582, H("A202040000000000")),
                  Frame(5, 0x602, H("D500000000000000")),
                  Frame(6, 0x582, H("A100000000000000")),
                  # block upload of 0x1008:0, the second segment is lost once
                  Frame(7, 0x602, H("A40810007F000000")),
                  Frame(8, 0x582, H("C608100009000000")),
                  Frame(9, 0x602, H("A300000000000000")),
                  Frame(10, 0x582, H("014C656C7920736C")),
                  Frame(11, 0x582, H("8261766500000000")),
                  Frame(12, 0x602, H("A2017F0000000000")),
                  Frame(13, 0x582, H("8161766500000000")),
                  Frame(14, 0x602, H("A2017F0000000000")),
                  Frame(15, 0x582, H("D500000000000000")),
                  Frame(16, 0x602, H("A100000000000000")),
                  Frame(17, 0x582, H("4300100000000000"))]
        ds = decode_all(dec, frames)
        self.assertIn("9 bytes (block)", ds[0].text, ds[0].text)
        self.assertIn("block segment 2, last", ds[3].text)
        self.assertTrue(ds[5].text.endswith("= 01 02 03 04 05 06 07 08 09 (block, done)"), ds[5].text)
        self.assertIn("confirmed (block)", ds[6].text)
        self.assertIn("9 bytes (block)", ds[8].text)
        self.assertTrue(ds[15].text.endswith("= 4C 65 6C 79 20 73 6C 61 76 (block, done)"), ds[15].text)
        self.assertIn("finished", ds[16].text)
        self.assertNotIn("block", ds[17].text)  # back to normal decoding

    def test_without_config(self):
        dec = Decoder()
        d = dec.decode(Frame(0, 0x185, b"\x01"))
        self.assertEqual((d.kind, d.node, d.name), ("pdo", 5, "TPDO1"))
        d = dec.decode(Frame(0, 0x7E5, bytes([0x11, 40, 0, 0, 0, 0, 0, 0])))
        self.assertEqual(d.text, "request configure node ID 40")

    def test_bad_config_falls_back(self):
        cfg = copy.deepcopy(load_cases()["base"])
        cfg["nodes"][0]["eds"] = "missing.eds"
        dec = Decoder.from_config(cfg, os.path.join(FIXTURES, "eds", "canworks.json"))
        self.assertTrue(dec.warnings)
        self.assertEqual(dec.decode(Frame(0, 0x702, b"\x05")).text, "node 2 (pingpong) OPERATIONAL")

    def test_bad_config_note_names_the_problem(self):
        cfg = copy.deepcopy(load_cases()["base"])
        cfg["nodes"][0]["eds"] = "missing.eds"
        path = os.path.join(FIXTURES, "eds", "canworks.json")
        dec = Decoder.from_config(cfg, path)
        self.assertEqual(dec.warnings, ["decoding without the config's PDOs: node 2: the EDS file missing.eds "
                                        "is missing"])

    def test_gateway_routed_entries_decode(self):
        # Virtual-plant io: node 6's RPDO 1 carries 0x6411:1 for a gateway
        # route, without a PLC location; the version 2 config passes its check.
        path = os.path.join(REPO, "examples", "virtual-plant", "canworks", "canworks.json")
        with open(path, encoding="utf-8") as f:
            cfg = json.load(f)
        dec = Decoder.from_config(cfg, path, network="io")
        self.assertEqual(dec.warnings, [])
        d = dec.decode(Frame(T0, 0x185, bytes(8)))
        self.assertEqual((d.kind, d.node), ("pdo", 5))
        self.assertTrue(d.name.endswith("_TPDO1"), d.name)
        self.assertTrue(d.signals)
        self.assertTrue(any(node == 5 and "_TPDO1 " in label for _, label, node in dec.signal_keys()))
        self.assertIn(0x206, dec.pdos)
        # The slave network cell: the PLC (node 20) with its own EDS's PDOs.
        dec = Decoder.from_config(cfg, path, network="cell")
        self.assertEqual(dec.warnings, [])
        self.assertEqual(sorted(dec.pdos), [0x194, 0x214, 0x294, 0x394, 0x494])
        d = dec.decode(Frame(T0, 0x194, bytes([1, 7, 0, 0, 0])))
        self.assertEqual((d.kind, d.node, d.name), ("pdo", 20, "cell_TPDO1"))
        self.assertEqual(dict(d.signals)["cell_TPDO1.BOOLEAN_to_master_alarm"], 1)
        self.assertEqual(dec.pdos[0x194].info[0]["location"], "%QX300.0")

    def test_plc_variable_names(self):
        from canworks import dbcexport
        cfg = copy.deepcopy(load_cases()["base"])
        cfg["nodes"][0]["tx_pdos"] = [{"entries": [
            {"index": "0x4001", "subindex": 0, "type": "UNSIGNED32", "iec_location": "%ID10"}]}]
        dec = Decoder.from_config(cfg, os.path.join(FIXTURES, "eds", "canworks.json"),
                                  names={"%ID10": ["valve_status"]})
        d = dec.decode(Frame(0, 0x182, (7).to_bytes(4, "little")))
        self.assertEqual(d.text, "valve_status=7")
        self.assertEqual(dbcexport.identifier("valve_status"), "valve_status")

    def test_network_picks_the_nodes(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        cfg, path = two_network_config(tmp)
        frame = Frame(T0, 0x182, NODE2_TPDO1)
        io_dec = Decoder.from_config(cfg, path, network="io")
        self.assertEqual(io_dec.warnings, [])
        d = io_dec.decode(frame)
        self.assertEqual((d.name, d.text), ("pingpong_TPDO1", "UNSIGNED32_sent_from_slave=4294902327"))
        self.assertEqual(io_dec.decode(Frame(T0, 0x702, bytes([5]))).text, "node 2 (pingpong) OPERATIONAL")
        drives_dec = Decoder.from_config(cfg, path, network="drives")
        d = drives_dec.decode(frame)
        self.assertEqual((d.name, d.text), ("drive_TPDO1", "Statusword=567, Position_actual_value=-1"))
        self.assertEqual(drives_dec.decode(Frame(T0, 0x702, bytes([5]))).text, "node 2 (drive) OPERATIONAL")
        # Without a network a config with several decodes like no config, and says why.
        dec = Decoder.from_config(cfg, path)
        self.assertEqual(dec.warnings, ["decoding without the config's nodes: the config has 2 networks "
                                        "(io, drives); name one"])
        self.assertEqual(dec.decode(frame).name, "TPDO1")

    def test_signal_values(self):
        self.assertEqual(signal_value(b"\xff\xff", 0, 16, True, 0), -1)
        self.assertEqual(signal_value(b"\x00\x00\x80\x3f", 0, 32, False, 1), 1.0)
        self.assertEqual(signal_value(b"\x10", 4, 1, False, 0), 1)


class Statistics(unittest.TestCase):
    def test_cycle_times_and_load(self):
        a = Analysis(pingpong_decoder(), 125000)
        for i in range(1000):
            a.feed(Frame(T0 + i * 10000, 0x182, bytes(4)))
        row = [r for r in a.id_table() if r["id"] == 0x182][0]
        self.assertEqual(row["count"], 1000)
        self.assertAlmostEqual(row["cycle_avg_ms"], 10.0)
        self.assertEqual((row["cycle_min_ms"], row["cycle_max_ms"]), (10.0, 10.0))
        s = a.summary()
        self.assertAlmostEqual(s["rate"], 100.0)
        self.assertAlmostEqual(s["load"], 100.0 * 100 * frame_bits(Frame(0, 0x182, bytes(4))) / 125000)
        ts, rate, load = a.rate_series()
        self.assertEqual(len(ts), 100)
        series = a.series["pingpong_TPDO1.UNSIGNED32_sent_from_slave"]
        self.assertEqual(len(series.times), 1000)
        t, v = series.range(points=50)
        self.assertLess(len(t), 300)

    def test_frame_bits(self):
        self.assertEqual(frame_bits(Frame(0, 0x80, b"")), 47 + 33 // 4 // 2)
        self.assertGreater(frame_bits(Frame(0, 0x80, bytes(8), ext=True)), frame_bits(Frame(0, 0x80, bytes(8))))

    def test_trace_limit_drops_oldest(self):
        s = Session(Decoder(), limit=100)
        s.feed([Frame(T0 + i, 0x181, b"") for i in range(150)])
        self.assertLessEqual(len(s.trace), 100)
        self.assertEqual(len(s.analysis.kinds), len(s.trace))
        self.assertEqual(s.trace.dropped + len(s.trace), 150)
        self.assertEqual(s.trace[0].time_us, T0 + s.trace.dropped)


class Triggers(unittest.TestCase):
    def run_frames(self, spec, frames, decoder=None):
        dec = decoder or pingpong_decoder()
        dec.reset()
        e = triggers.Engine(spec)
        return [f.time_us for f in frames if e.frame(f, dec.decode(f))], e

    def test_conditions(self):
        f = Frame
        frames = [f(1, 0x182, b"\x01\x00\x00\x00"), f(2, 0x182, b"\x05\x00\x00\x00"), f(3, 0x182, b"\x02\x00\x00\x00"),
                  f(4, 0x82, bytes.fromhex("1050010000000000")), f(5, 0x82, bytes(8)),
                  f(6, 0x702, b"\x05"), f(7, 0x702, b"\x04"), f(8, 0x702, b"\x04"), f(9, 0x702, b"\x00"),
                  f(10, 0x582, bytes.fromhex("8000100002000106")), f(11, 0x20, bytes(8), err=True),
                  f(12, 0x202, b"\x09\x00\x00\x00", tx=True)]
        key = "pingpong_TPDO1.UNSIGNED32_sent_from_slave"
        cases = [
            ("frame id=0x182", [1, 2, 3]),
            ("frame id=0x182 data=05", [2]),
            ("frame id=0x200 mask=0x780 dir=tx", [12]),
            ("frame id=0x182 dir=tx", []),
            ("emcy", [4]),
            ("emcy node=2 code=0x5010", [4]),
            ("emcy node=3", []),
            ("state node=2 state=stopped", [7]),
            ("state node=2 state=bootup", [9]),
            ("state state=any", [6, 7, 9]),
            ("sdo-abort node=2", [10]),
            ("error-frame", [11]),
            ("signal %s>4" % key, [2]),
            ("signal key=%s op=cross_up value=3" % key, [2]),
            ("signal key=%s op=cross_down value=3" % key, [3]),
        ]
        for text, want in cases:
            got, _ = self.run_frames(triggers.parse(text), frames)
            self.assertEqual(got, want, text)

    def test_combine_and_count(self):
        frames = [Frame(1000, 0x82, bytes.fromhex("1050010000000000")), Frame(50000, 0x702, b"\x04"),
                  Frame(500000, 0x702, b"\x05"), Frame(600000, 0x82, bytes.fromhex("1050010000000000"))]
        got, _ = self.run_frames(triggers.parse("emcy && state node=2 state=stopped", window_ms=100), frames)
        self.assertEqual(got, [50000])
        got, _ = self.run_frames(triggers.parse("emcy && state node=2 state=stopped", window_ms=10), frames)
        self.assertEqual(got, [])
        got, _ = self.run_frames(triggers.parse("state node=2 state=stopped -> emcy", window_ms=0), frames)
        self.assertEqual(got, [600000])
        aborts = [Frame(i, 0x582, bytes.fromhex("8000100002000106")) for i in range(7)]
        got, _ = self.run_frames(triggers.parse("sdo-abort", count=3), aborts)
        self.assertEqual(got, [2, 5])

    def test_status_conditions(self):
        e = triggers.Engine(triggers.parse("heartbeat-lost node=2"))
        st = {"nodes": [{"node_id": 2, "status": True}], "bus": {"state": 1}}
        self.assertFalse(e.status(1, st))
        st["nodes"][0]["status"] = False
        self.assertTrue(e.status(2, st))
        e = triggers.Engine(triggers.parse("bus state=passive"))
        self.assertFalse(e.status(1, {"bus": {"state": 2}}))
        self.assertTrue(e.status(2, {"bus": {"state": 4}}))
        self.assertFalse(e.status(3, {"bus": {"state": 4}}))
        e = triggers.Engine(triggers.parse("boot-error"))
        self.assertTrue(e.status(1, {"nodes": [{"node_id": 23, "boot_error": "J"}]}))
        self.assertFalse(e.status(2, {"nodes": [{"node_id": 23, "boot_error": "J"}]}))

    def test_checks(self):
        for bad in ({"conditions": []}, {"conditions": [{"type": "nope"}]},
                    {"conditions": [{"type": "frame"}]}, {"conditions": [{"type": "emcy"}], "post_s": 601},
                    {"conditions": [{"type": "signal", "key": "a", "op": ">"}]},
                    {"conditions": [{"type": "emcy", "node": 200}]}):
            with self.assertRaises(triggers.TriggerError):
                triggers.check(bad)
        self.assertEqual(triggers.describe(triggers.parse("frame id=0x197 data=10 dir=rx", count=2)),
                         "frame 0x197 data 10 Rx, every 2")

    def test_signal_names_resolve(self):
        keys = [("pdo_A.speed", "", 2), ("pdo_A.bit1", "", 2), ("pdo_B.bit1", "", 3)]
        spec = triggers.resolve_signals(triggers.parse("signal speed>3"), keys)
        self.assertEqual(spec["conditions"][0]["key"], "pdo_A.speed")
        spec = triggers.resolve_signals(triggers.parse("signal key=pdo_B.bit1 op=rising"), keys)
        self.assertEqual(spec["conditions"][0]["key"], "pdo_B.bit1")
        with self.assertRaisesRegex(triggers.TriggerError, "more than one signal 'bit1'; use one of: pdo_A.bit1"):
            triggers.resolve_signals(triggers.parse("signal bit1>0"), keys)
        with self.assertRaisesRegex(triggers.TriggerError, "no signal 'nope'; the config's signals are: pdo_A.speed"):
            triggers.resolve_signals(triggers.parse("signal nope>0"), keys)
        with self.assertRaisesRegex(triggers.TriggerError, "--config"):
            triggers.resolve_signals(triggers.parse("signal nope>0"), [])
        self.assertEqual(triggers.resolve_signals(triggers.parse("emcy"), [])["conditions"][0]["type"], "emcy")


class Recording(unittest.TestCase):
    def setUp(self):
        self.fake = FakePlugin()
        self.fake.__enter__()
        self.addCleanup(self.fake.__exit__)

    def connect(self):
        c = diag.Client("127.0.0.1", self.fake.port, TOKEN, 2.0)
        c.connect()
        return c

    def recorder(self, **kw):
        s = Session(pingpong_decoder())
        kw.setdefault("fetch_interval", 0.02)
        kw.setdefault("status_interval", 0.05)
        r = Recorder(self.connect, s, **kw)
        self.addCleanup(r.stop)
        return s, r

    def wait_for(self, cond, timeout=3.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if cond():
                return True
            time.sleep(0.02)
        return False

    def test_records_decodes_and_polls_status(self):
        s, r = self.recorder(filters=[(0x180, 0x780)], error_frames=True)
        r.start()
        self.assertTrue(self.wait_for(lambda: r.state == "recording"))
        self.assertEqual(self.fake.trace_starts[-1]["filters"], [{"id": 0x180, "mask": 0x780}])
        self.assertTrue(self.fake.trace_starts[-1]["error_frames"])
        now = int(time.time() * 1e6)
        self.fake.push([Frame(now + i * 1000, 0x182, bytes([i, 0, 0, 0])) for i in range(10)])
        self.assertTrue(self.wait_for(lambda: len(s.trace) == 10))
        self.assertTrue(self.wait_for(lambda: "sdovar.2.2001:0" in s.analysis.series))
        self.assertEqual(s.trace.meta["bitrate"], 125000)
        r.stop()
        self.assertEqual(r.state, "stopped")
        self.assertEqual(self.fake.requests[-1]["op"], "trace_stop")

    def test_lost_frames_and_no_session(self):
        self.fake.trace_ring = 5
        s, r = self.recorder(fetch_interval=0.5)
        r.start()
        self.assertTrue(self.wait_for(lambda: r.state == "recording"))
        self.fake.push([Frame(T0 + i, 0x181, b"") for i in range(20)])
        self.assertTrue(self.wait_for(lambda: len(s.trace) == 5))
        self.assertEqual(s.trace.lost[0][1], 15)
        self.assertIn("15 frames lost", s.trace.markers[0]["label"])
        self.fake.trace_session = False
        self.assertTrue(self.wait_for(lambda: r.state == "no_bus"))

    def test_records_one_network(self):
        fake = FakePlugin(networks=TWO_NETWORKS)
        fake.__enter__()
        self.addCleanup(fake.__exit__)

        def connect():
            c = diag.Client("127.0.0.1", fake.port, TOKEN, 2.0, network="drives")
            c.connect()
            return c

        s = Session(pingpong_decoder())
        r = Recorder(connect, s, fetch_interval=0.02, status_interval=0.05)
        self.addCleanup(r.stop)
        r.start()
        self.assertTrue(self.wait_for(lambda: r.state == "recording"))
        fake.push([Frame(int(time.time() * 1e6), 0x182, bytes(4))])
        self.assertTrue(self.wait_for(lambda: len(s.trace) == 1))
        self.assertTrue(self.wait_for(lambda: r.status is not None))
        r.stop()
        self.assertEqual(r.status["network"], "drives")
        self.assertEqual({k: s.trace.meta[k] for k in ("network", "interface", "bitrate")},
                         {"network": "drives", "interface": "vcan1", "bitrate": 500000})
        self.assertEqual({q.get("network") for q in fake.requests}, {"drives"})
        # The network is saved with the trace.
        back = formats.read(written(s.trace, "pcapng"), "x.pcapng")
        self.assertEqual(back.meta["network"], "drives")

    def test_old_plugin(self):
        self.fake.trace_supported = False
        s, r = self.recorder()
        r.start()
        r.wait(3)
        self.assertEqual(r.state, "error")
        self.assertIn("too old for traces", r.message)

    def test_single_trigger_stops(self):
        spec = triggers.parse("emcy node=2", mode="single", post_s=0.0)
        s, r = self.recorder(trigger=spec)
        r.start()
        self.assertTrue(self.wait_for(lambda: r.state == "recording"))
        now = int(time.time() * 1e6)
        self.fake.push([Frame(now, 0x182, bytes(4)), Frame(now + 1000, 0x82, bytes.fromhex("1050010000000000")),
                        Frame(now + 2000, 0x182, bytes(4))])
        r.wait(3)
        self.assertFalse(r.running)
        self.assertEqual(r.message, "stopped by the trigger")
        self.assertEqual([m["kind"] for m in s.trace.markers], ["trigger"])

    def test_single_trigger_keeps_the_window(self):
        spec = triggers.parse("emcy node=2", mode="single", pre_s=0.1, post_s=0.0)
        s, r = self.recorder(trigger=spec)
        r.start()
        self.assertTrue(self.wait_for(lambda: r.state == "recording"))
        now = int(time.time() * 1e6)
        self.fake.push([Frame(now + i * 100000, 0x182, bytes([i, 0, 0, 0])) for i in range(5)] +
                       [Frame(now + 450000, 0x82, bytes.fromhex("1050010000000000")),
                        Frame(now + 460000, 0x182, bytes(4))])
        r.wait(3)
        self.assertEqual(r.message, "stopped by the trigger")
        # Only the 100 ms before the hit and the hit itself: 0x182 at 400 ms, the EMCY.
        self.assertEqual([f.time_us - now for f in s.trace], [400000, 450000])
        self.assertEqual(r.info()["trimmed"], 5)
        self.assertEqual(s.analysis.frames, 2)
        self.assertEqual(s.analysis.series["pingpong_TPDO1.UNSIGNED32_sent_from_slave"].values.tolist(), [4.0])

    def test_normal_trigger_autosaves(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder)
        spec = triggers.parse("frame id=0x182 data=03", mode="normal", pre_s=0.002, post_s=0.002,
                              autosave={"format": "blf", "folder": folder})
        s, r = self.recorder(trigger=spec, name_prefix="proj")
        r.start()
        self.assertTrue(self.wait_for(lambda: r.state == "recording"))
        now = int(time.time() * 1e6)
        self.fake.push([Frame(now + i * 1000, 0x182, bytes([i % 4, 0, 0, 0])) for i in range(12)])
        self.assertTrue(self.wait_for(lambda: len(r.saved) == 2))
        self.assertTrue(r.running)
        self.assertEqual(len([m for m in s.trace.markers if m["kind"] == "trigger"]), 3)
        self.assertTrue(all(os.path.basename(p).startswith("proj-trace-") and p.endswith(".blf") for p in r.saved))
        r.stop()
        self.assertEqual(len(r.saved), 3)  # the last window is written at stop


class Cli(unittest.TestCase):
    def test_trace_and_convert(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        with FakePlugin() as fake:
            stop = threading.Event()

            def feed():
                k = 0
                while not stop.is_set():
                    now = int(time.time() * 1e6)
                    fake.push([Frame(now, 0x182, bytes([k & 0xFF, 0, 0, 0])), Frame(now + 50, 0x80, b"", tx=True)])
                    k += 1
                    time.sleep(0.02)

            th = threading.Thread(target=feed, daemon=True)
            th.start()
            self.addCleanup(stop.set)
            out = io.StringIO()
            path = os.path.join(tmp, "run.trc")
            rc = diag.run(diag.parser().parse_args(["--runtime", fake.runtime, "--token", TOKEN, "trace", "-o", path,
                                                    "--duration", "0.6", "--config", PINGPONG]), out)
            stop.set()
            self.assertEqual(rc, 0)
            self.assertRegex(out.getvalue(), r"^\d+ frames in [\d.]+ s \(\d+ frames/s\), 0 lost, 0 dropped")
            with open(path, encoding="utf-8") as f:
                self.assertIn(";$FILEVERSION=2.1", f.read())
        out = io.StringIO()
        log = os.path.join(tmp, "a.log")
        with open(log, "w") as f:
            f.write("(1791181200.000100) can0 182#05000000 R\n(1791181200.000200) can0 080# T\n")
        csv = os.path.join(tmp, "a.csv")
        self.assertEqual(diag.run(diag.parser().parse_args(["convert", log, csv, "--config", PINGPONG]), out), 0)
        with open(csv, encoding="utf-8") as f:
            self.assertIn("pingpong_TPDO1,UNSIGNED32_sent_from_slave=5", f.read())
        self.assertEqual(diag.main(["convert", log, os.path.join(tmp, "a.txt")]), 2)

    def test_trace_and_convert_on_a_network(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        _, config = two_network_config(tmp)
        with FakePlugin(networks=TWO_NETWORKS) as fake:
            stop = threading.Event()

            def feed():
                while not stop.is_set():
                    fake.push([Frame(int(time.time() * 1e6), 0x182, NODE2_TPDO1)])
                    time.sleep(0.02)

            th = threading.Thread(target=feed, daemon=True)
            th.start()
            self.addCleanup(stop.set)
            base = ["--runtime", fake.runtime, "--token", TOKEN, "trace", "--duration", "0.4", "--config", config]
            # Without --network the runtime's two networks are named.
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                self.assertEqual(diag.main(base + ["-o", os.path.join(tmp, "never.log")]), 1)
            self.assertIn("runs 2 networks (io, drives); give --network NAME", err.getvalue())
            self.assertFalse(fake.trace_starts)
            path = os.path.join(tmp, "drives.pcapng")
            with contextlib.redirect_stderr(io.StringIO()):  # the drive EDS's lint notes
                rc = diag.run(diag.parser().parse_args(base + ["-o", path, "--network", "drives"]), io.StringIO())
            stop.set()
            self.assertEqual(rc, 0)
            self.assertEqual(fake.trace_starts[-1]["network"], "drives")
        trace = formats.read_file(path)
        self.assertEqual(trace.meta["network"], "drives")
        self.assertEqual(trace.meta["interface"], "vcan1")
        # convert decodes with the network the file names, or the one given.
        csv = os.path.join(tmp, "drives.csv")
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(diag.run(diag.parser().parse_args(["convert", path, csv, "--config", config]),
                                      io.StringIO()), 0)
        with open(csv, encoding="utf-8") as f:
            self.assertIn('drive_TPDO1,"Statusword=567, Position_actual_value=-1"', f.read())
        self.assertEqual(diag.run(diag.parser().parse_args(["convert", path, csv, "--config", config,
                                                            "--network", "io"]), io.StringIO()), 0)
        with open(csv, encoding="utf-8") as f:
            self.assertIn("pingpong_TPDO1,UNSIGNED32_sent_from_slave=4294902327", f.read())
        # A file that names no network needs --network with this config.
        log = os.path.join(tmp, "a.log")
        formats.write_file(trace, log)
        with self.assertRaises(diag.DiagError) as cm:
            diag.run(diag.parser().parse_args(["convert", log, csv, "--config", config]), io.StringIO())
        self.assertIn("2 networks (io, drives); name one with --network NAME", str(cm.exception))

    def test_bad_trigger_and_filter(self):
        with FakePlugin() as fake:
            base = ["--runtime", fake.runtime, "--token", TOKEN, "trace", "-o", "/tmp/never.log"]
            self.assertEqual(diag.main(base + ["--trigger", "nonsense"]), 2)
            self.assertEqual(diag.main(base + ["--filter", "zz"]), 2)
            # A signal the config does not decode is refused instead of never firing.
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                self.assertEqual(diag.main(base + ["--config", PINGPONG, "--trigger", "signal no_such_signal>0"]), 2)
                self.assertEqual(diag.main(base + ["--trigger", "signal x>0"]), 2)
            self.assertIn("no signal 'no_such_signal'; the config's signals are: pingpong_", err.getvalue())
            self.assertIn("--config canworks.json", err.getvalue())

    def test_old_plugin_fails(self):
        with FakePlugin() as fake:
            fake.trace_supported = False
            out = io.StringIO()
            with self.assertRaises(diag.DiagError) as cm:
                diag.run(diag.parser().parse_args(["--runtime", fake.runtime, "--token", TOKEN, "trace", "-o",
                                                   "/tmp/never.log", "--duration", "1"]), out)
            self.assertIn("too old", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
