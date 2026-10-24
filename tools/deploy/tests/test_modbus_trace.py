"""The bridge's Modbus records on the PC (add-modbus-traffic-view;
canopen-bus-trace "Modbus records in a trace", "Modbus decoding with the
register map", "Delay between Modbus and CAN", "Modbus records in saved
traces"; canopen-online-diagnostics "Modbus trace in the command-line
client", "Modbus clients in the status")."""

import contextlib
import io
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import unittest

from canworks import diag
from canworks.bustrace import formats
from canworks.bustrace.decode import Decoder
from canworks.bustrace.model import Frame, Trace
from canworks.bustrace.modbus import MapDecoder, Record, decode_all
from canworks.bustrace.recorder import Recorder, Session

from .fake_diag import TOKEN, FakePlugin
from .test_contract import REPO

EXAMPLE = os.path.join(REPO, "examples", "modbus-bridge", "canworks.json")


def load():
    with open(EXAMPLE, encoding="utf-8") as f:
        return json.load(f)


def wait(cond, timeout=5):
    end = time.time() + timeout
    while time.time() < end and not cond():
        time.sleep(0.02)


def write16(start, values):
    pdu = bytes([16, start >> 8, start & 0xFF, 0, len(values), len(values) * 2])
    for v in values:
        pdu += (v & 0xFFFF).to_bytes(2, "big")
    return pdu, bytes([16, start >> 8, start & 0xFF, 0, len(values)])


def read4(start, values):
    return (bytes([4, start >> 8, start & 0xFF, 0, len(values)]),
            bytes([4, len(values) * 2]) + b"".join((v & 0xFFFF).to_bytes(2, "big") for v in values))


class Decoding(unittest.TestCase):
    def setUp(self):
        cfg = load()
        cfg["bridge"]["connections"] = [{"kind": "plc", "name": "Line HMI", "address": "192.168.10.20",
                                         "writes": True}]
        self.dec = MapDecoder(cfg)

    def test_named_write(self):
        q, a = write16(1, [0xFFFB])
        d = self.dec.decode(Record(1000, "192.168.10.20", q, a))
        self.assertEqual(d["client"], "Line HMI")
        self.assertEqual(d["text"], "write HR 1 dio.0x6411:1 = -5")
        self.assertEqual((d["short"], d["range"], d["result"]), ("HR", "1", "ok"))

    def test_read_names_and_bytes(self):
        q, a = read4(0, [1, 2, 3, 4])
        d = self.dec.decode(Record(1000, "127.0.0.1", q, a))
        self.assertEqual(d["client"], "127.0.0.1")
        self.assertEqual([v["value"] for v in d["values"]], [1, 2, 3, 4])
        # Byte rows: the high and low byte of holding register 0.
        q, a = write16(0, [0x0102])
        d = self.dec.decode(Record(1000, "127.0.0.1", q, a))
        self.assertEqual([(v["location"], v["value"]) for v in d["values"]], [("%QB0", 1), ("%QB1", 2)])

    def test_40001_hint(self):
        d = self.dec.decode(Record(1000, "192.168.10.20", bytes([3, 0x9C, 0x41, 0, 1]), bytes([0x83, 2])))
        self.assertEqual(d["result"], "exception 0x02 (illegal data address)")
        self.assertIn("Holding registers start at 0 here", d["hints"][0])
        self.assertIn("the image has 13 holding registers", d["hints"][0])

    def test_past_the_image_and_refused(self):
        d = self.dec.decode(Record(1000, "127.0.0.1", bytes([4, 0, 30, 0, 4]), bytes([0x84, 2])))
        self.assertIn("past the image: it has 31 input registers", d["hints"][0])
        d = self.dec.decode(Record(1000, "10.0.0.9", bytes([6, 0, 1, 0, 5]), bytes([0x86, 1]), flags=1))
        self.assertTrue(d["refused"])
        self.assertIn("not in the bridge's writers", d["hints"][0])

    def test_split_value(self):
        cfg = load()
        cfg["bridge"]["word_order"] = "low_first"
        entry = cfg["networks"][0]["nodes"][1]["rx_pdos"][0]["entries"]
        entry[2].update(type="UNSIGNED32", iec_location="%QD40")
        del entry[3]
        dec = MapDecoder(cfg)
        self.assertIsNone(dec.problem)
        q, a = write16(20, [0x0001, 0x0002])
        d = dec.decode(Record(1000, "127.0.0.1", q, a))
        self.assertEqual(d["values"][0]["value"], 0x00020001)  # low word first
        q, a = write16(20, [5])
        d = dec.decode(Record(1000, "127.0.0.1", q, a))
        self.assertIn("cuts dio.0x6411:1", d["hints"][0])

    def test_bits_in_registers(self):
        """A bit is served as a coil or discrete input and inside its byte's
        register: a register range names it too."""
        q, a = read4(8, [0x0500])  # input byte 16: bits 0 and 2
        d = self.dec.decode(Record(1000, "127.0.0.1", q, a))
        bits = {v["location"]: v["value"] for v in d["values"] if v["location"].startswith("%IX")}
        self.assertEqual(bits, {"%IX16.0": True, "%IX16.1": False, "%IX16.2": True})

    def test_map_hash_mismatch(self):
        dec = MapDecoder(load(), bridge_hash="0x12345678")
        q, a = write16(1, [1])
        d = dec.decode(Record(1000, "127.0.0.1", q, a))
        self.assertIn("is not the one the bridge runs", d["undecoded"])
        self.assertEqual(d["values"], [])


class Delays(unittest.TestCase):
    def test_write_to_rpdo_and_tpdo_to_read(self):
        cfg = load()
        can = Decoder.from_config(cfg, EXAMPLE)
        t = Trace()
        t.meta["network"] = cfg["networks"][0].get("name")
        q, a = write16(1, [500])
        t.append(Frame(9_999_000, 0x206, bytes([0, 0, 0, 0, 0, 0])))  # before the write: not it
        t.append_modbus(Record(10_000_000, "127.0.0.1", q, a))
        t.append(Frame(10_002_000, 0x206, bytes([0, 0, 0, 0, 0, 0])))  # the old value
        t.append(Frame(10_004_000, 0x206, bytes([0, 0, 0xF4, 0x01, 0, 0])))  # carries 500
        t.append(Frame(20_000_000, 0x185, (77).to_bytes(2, "little") + bytes(6)))
        t.append(Frame(20_005_000, 0x185, (77).to_bytes(2, "little") + bytes(6)))  # the same value again
        q, a = read4(0, [77])
        t.append_modbus(Record(20_007_000, "127.0.0.1", q, a))
        rows, table = decode_all(MapDecoder(cfg), t, can, t.meta["network"])
        w = [x for x in rows[0]["delays"] if x["location"] == "%QW2"][0]
        self.assertEqual((w["delay_us"], w["frame"]), (4000, 3))
        r = rows[1]["delays"][0]
        self.assertEqual(r["delay_us"], 7000)  # from the frame that first carried 77
        self.assertEqual(r["frame"], 4)
        by = {(x["short"], x["range"]): x for x in table}
        self.assertEqual(by[("HR", "1")]["delay_avg_ms"], 4.0)

    def test_write_to_rpdo_of_a_bit(self):
        """A BOOLEAN output that shares its holding register with a byte: the
        write's delay to the RPDO that carries the bit."""
        cfg = load()
        cfg["networks"][0]["nodes"][1]["rx_pdos"][0]["entries"][0].update(type="BOOLEAN", iec_location="%QX0.0")
        can = Decoder.from_config(cfg, EXAMPLE)
        t = Trace()
        t.meta["network"] = cfg["networks"][0].get("name")
        q, a = write16(0, [0x0100])
        t.append_modbus(Record(10_000_000, "127.0.0.1", q, a))
        t.append(Frame(10_001_000, 0x206, bytes(6)))  # the old value
        t.append(Frame(10_003_000, 0x206, bytes([1, 0, 0, 0, 0, 0])))  # carries TRUE
        rows, _ = decode_all(MapDecoder(cfg), t, can, t.meta["network"])
        self.assertIn("dio.0x6200:1 = TRUE", rows[0]["text"])
        w = [x for x in rows[0]["delays"] if x["location"] == "%QX0.0"][0]
        self.assertEqual((w["delay_us"], w["frame"]), (3000, 2))

    def test_not_seen_and_other_network(self):
        cfg = load()
        can = Decoder.from_config(cfg, EXAMPLE)
        t = Trace()
        q, a = write16(1, [9])
        t.append_modbus(Record(1_000_000, "127.0.0.1", q, a))
        rows, _ = decode_all(MapDecoder(cfg), t, can, "field")
        self.assertEqual(rows[0]["delays"][0]["text"], "not seen on the bus")
        rows, _ = decode_all(MapDecoder(cfg), t, can, "drives")
        self.assertIn("not traced", rows[0]["delays"][0]["text"])


class Files(unittest.TestCase):
    def trace(self):
        t = Trace()
        t.append(Frame(1000, 0x206, b"\x01\x02"))
        q, a = write16(1, [5])
        t.append_modbus(Record(1500, "192.168.10.20", q, a, seq=3, skipped=2, port=40000, conn=1, transaction=7))
        t.append(Frame(2000, 0x186, b"\x03"))
        t.append_modbus(Record(2500, "127.0.0.1", bytes([3, 0x9C, 0x41, 0, 1]), bytes([0x83, 2]), port=40001,
                               conn=2))
        t.meta["modbus_port"] = 1502
        return t

    def test_pcapng_round_trip(self):
        t = self.trace()
        out = io.BytesIO()
        formats.write_pcapng(t, out)
        back = formats.read(out.getvalue())
        self.assertEqual([f.modbus for f in back], [False, True, False, True])
        self.assertEqual([(r.address, r.req, r.resp, r.skipped, r.port, r.time_us) for r in back.modbus],
                         [(r.address, r.req, r.resp, r.skipped, r.port, r.time_us) for r in t.modbus])
        self.assertEqual(MapDecoder(load()).decode(back.modbus[0])["text"], "write HR 1 dio.0x6411:1 = 5")

    def test_other_formats_say_what_they_leave_out(self):
        t = self.trace()
        self.assertIn("pcapng only", formats.left_out(t, "asc"))
        self.assertIsNone(formats.left_out(t, "pcapng"))
        out = io.BytesIO()
        formats.write(t, out, "candump")
        self.assertEqual(len(out.getvalue().decode().splitlines()), 2)

    @unittest.skipUnless(shutil.which("tshark"), "tshark is not installed")
    def test_tshark_decodes_modbus(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "t.pcapng")
            formats.write_file(self.trace(), path)
            out = subprocess.run(["tshark", "-r", path, "-d", "tcp.port==1502,mbtcp", "-Y", "mbtcp"],
                                 capture_output=True, text=True, timeout=60).stdout
            self.assertGreaterEqual(out.count("Modbus/TCP"), 4)


class Recording(unittest.TestCase):
    def test_modbus_next_to_can(self):
        with FakePlugin() as fake:
            fake.modbus_bridge = True

            def connect():
                c = diag.Client("127.0.0.1", fake.port, TOKEN, 2.0)
                c.connect()
                return c
            s = Session(Decoder())
            r = Recorder(connect, s, fetch_interval=0.02, status_interval=0.05, modbus={"changes_only": True})
            r.start()
            wait(lambda: r.state == "recording" and fake.modbus_starts)
            fake.push([Frame(int(time.time() * 1e6) - 2_000_000, 0x206, b"\x00")])
            q, a = write16(1, [3])
            fake.push_modbus([Record(int(time.time() * 1e6) - 1_900_000, "127.0.0.1", q, a)])
            fake.push([Frame(int(time.time() * 1e6) - 1_800_000, 0x206, b"\x01")])
            deadline = time.time() + 5
            while time.time() < deadline and len(s.trace) < 3:
                time.sleep(0.05)
            r.stop()
            self.assertEqual([f.modbus for f in s.trace], [False, True, False])
            self.assertEqual(s.analysis.summary()["frames"], 2)
            self.assertEqual(s.analysis.summary()["modbus"], 1)
            self.assertEqual(fake.modbus_starts[0]["changes_only"], True)
            self.assertTrue(s.trace.meta.get("modbus"))

    def test_not_a_bridge_records_can(self):
        with FakePlugin() as fake:
            def connect():
                c = diag.Client("127.0.0.1", fake.port, TOKEN, 2.0)
                c.connect()
                return c
            s = Session(Decoder())
            r = Recorder(connect, s, fetch_interval=0.02, status_interval=0.05, modbus={"changes_only": True})
            r.start()
            wait(lambda: r.state == "recording")
            fake.push([Frame(int(time.time() * 1e6) - 1_000_000, 0x206, b"\x00")])
            deadline = time.time() + 5
            while time.time() < deadline and len(s.trace) < 1:
                time.sleep(0.05)
            r.stop()
            self.assertEqual(len(s.trace), 1)
            self.assertIn("not a bridge", r.info()["modbus_note"])


class CommandLine(unittest.TestCase):
    def test_modbus_trace_named_and_pcapng(self):
        # Spec "Watching an HMI's writes".
        with FakePlugin() as fake, tempfile.TemporaryDirectory() as tmp:
            fake.modbus_bridge = True
            fake.modbus_map_hash = MapDecoder(load()).map_hash
            q, a = write16(1, [500])
            threading.Timer(0.1, lambda: fake.push_modbus([
                Record(int(time.time() * 1e6), "192.168.10.20", bytes([6, 0, 1, 1, 0xF4]), bytes([6, 0, 1, 1, 0xF4]),
                       skipped=4),
                Record(int(time.time() * 1e6), "127.0.0.1", q, a)])).start()
            path = os.path.join(tmp, "m.pcapng")
            out = io.StringIO()
            rc = diag.run(diag.parser().parse_args(["--runtime", fake.runtime, "--token", TOKEN, "modbus-trace",
                                                    "--config", EXAMPLE, "--duration", "0.5", "-o", path]), out)
            self.assertEqual(rc, 0)
            text = out.getvalue()
            self.assertIn("192.168.10.20 fn 6 write HR 1 dio.0x6411:1 = 500 (after 4 unchanged) ok", text)
            self.assertIn("wrote 2 Modbus requests", text)
            self.assertEqual(len(formats.read_file(path).modbus), 2)
            self.assertEqual(fake.modbus_starts[0]["changes_only"], True)
            out = io.StringIO()
            diag.run(diag.parser().parse_args(["--runtime", fake.runtime, "--token", TOKEN, "modbus-trace", "--all",
                                               "--client", "192.168.10.20", "--duration", "0.1"]), out)
            self.assertEqual(fake.modbus_starts[1], {"op": "modbus_trace_start", "changes_only": False,
                                                     "clients": ["192.168.10.20"],
                                                     "id": fake.modbus_starts[1]["id"]})

    def test_not_a_bridge(self):
        with FakePlugin() as fake:
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                rc = diag.main(["--runtime", fake.runtime, "--token", TOKEN, "modbus-trace", "--duration", "0.1"])
            self.assertNotEqual(rc, 0)
            self.assertIn("not a bridge", err.getvalue())

    def test_status_client_lines(self):
        now = int(time.time() * 1e6)
        b = {"clients": [{"address": "127.0.0.1", "port": 40000, "writer": True, "connected_us": now - 30_000_000,
                          "rate": 100.0, "functions": {"3": 10}, "exceptions": {"0x02": 3}, "refused_writes": 0,
                          "last_write": {"table": "holding register", "start": 0, "count": 3}}],
             "closed_clients": [{"address": "192.168.10.20", "port": 5555, "ago_s": 12, "reason": "replies not read",
                                 "connected_s": 40, "requests": 900}]}
        lines = diag.modbus_client_lines(b)
        self.assertIn("client 127.0.0.1:40000 (writer), connected 30 s, 100.0 requests/s, exceptions 0x02 x3, "
                      "refused writes 0, last write HR 0-2", lines[0])
        self.assertEqual(lines[1], "  closed 192.168.10.20:5555 12 s ago: replies not read (after 40 s, 900 requests)")


if __name__ == "__main__":
    unittest.main()
