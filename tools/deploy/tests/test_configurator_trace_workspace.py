"""The trace workspace on the server (trace-workspace tasks 2.1-2.7): the By
identifier table with change marks, reference and silent identifiers,
incremental answers, continuing a recording after its connection ended, the
transmit list on this PC and list files, and decoding in Commission a
device."""

import json
import os
import shutil
import tempfile
import time
import unittest
from unittest import mock

from canworks import diag
from canworks.bustrace.decode import Decoder
from canworks.bustrace.model import Frame
from canworks.bustrace.recorder import Recorder, Session
from canworks.bustrace.stats import Analysis
from canworks.configurator import transmit

from .fake_diag import FakePlugin
from .test_bustrace import T0, pingpong_decoder
from .test_configurator_trace import Trace

EDS = os.path.join(os.path.dirname(__file__), "..", "..", "..", "config", "pingpong", "cpp-slave.eds")


def row(table, id_, tx=False):
    return next(r for r in table if r["id"] == id_ and (r["dir"] == "Tx") == tx)


class IdTable(unittest.TestCase):
    def test_changed_bytes_static_and_last_cycle(self):
        a = Analysis(pingpong_decoder())
        a.feed(Frame(T0, 0x185, bytes.fromhex("2500EA00")))
        a.feed(Frame(T0 + 10000, 0x185, bytes.fromhex("2500EB00")))
        a.feed(Frame(T0 + 30000, 0x185, bytes.fromhex("2500EB00")))
        r = row(a.id_table(), 0x185)
        self.assertEqual(r["changed"], 0)  # the last two frames are equal
        self.assertEqual(r["static"], 0b1011)  # byte 2 changed once
        self.assertEqual(r["changed_at"][2], T0 + 10000)
        self.assertEqual(r["cycle_last_ms"], 20.0)
        self.assertEqual(r["dlc"], 4)
        a.feed(Frame(T0 + 40000, 0x185, bytes.fromhex("2501EB00")))
        r = row(a.id_table(), 0x185)
        self.assertEqual(r["changed"], 0b0010)

    def test_sent_and_received_are_two_rows(self):
        a = Analysis(Decoder())
        a.feed(Frame(T0, 0x60A, bytes(8), tx=True))
        a.feed(Frame(T0 + 100, 0x60A, bytes(8)))
        t = a.id_table()
        self.assertEqual([(r["id_text"], r["dir"]) for r in t], [("60A", "Rx"), ("60A", "Tx")])
        self.assertNotEqual(t[0]["key"], t[1]["key"])

    def test_incremental_rows(self):
        a = Analysis(Decoder())
        a.feed(Frame(T0, 0x181, b"\x01"))
        a.feed(Frame(T0, 0x182, b"\x01"))
        rev = a.rev
        a.feed(Frame(T0 + 1000, 0x182, b"\x02"))
        self.assertEqual([r["id"] for r in a.id_table(rev)], [0x182])
        self.assertEqual(a.id_table(a.rev), [])

    def test_two_thousand_identifiers(self):
        """A busy bus: the whole table once, then only what changed, quickly."""
        a = Analysis(Decoder())
        for k in range(2000):
            a.feed(Frame(T0 + k, 0x10000 + k, bytes([k & 0xFF, 0]), ext=True))
        self.assertEqual(len(a.id_table()), 2000)
        rev = a.rev
        for k in range(0, 2000, 100):
            a.feed(Frame(T0 + 10000 + k, 0x10000 + k, bytes([k & 0xFF, 1]), ext=True))
        start = time.perf_counter()
        changed = a.id_table(rev)
        took = time.perf_counter() - start
        self.assertEqual(len(changed), 20)
        self.assertTrue(all(r["changed"] == 0b10 for r in changed))
        self.assertLess(took, 0.05)

    def test_reference(self):
        a = Analysis(Decoder())
        a.feed(Frame(T0, 0x185, bytes.fromhex("2500EA00")))
        a.set_reference()
        a.feed(Frame(T0 + 1000, 0x185, bytes.fromhex("2504EA00")))
        a.feed(Frame(T0 + 2000, 0x185, bytes.fromhex("2504EA00")))
        a.feed(Frame(T0 + 3000, 0x709, b"\x00"))
        r = row(a.id_table(), 0x185)
        self.assertEqual((r["ref_diff"], r["ref_new"]), (0b0010, False))
        self.assertTrue(row(a.id_table(), 0x709)["ref_new"])
        a.set_reference(clear=True)
        self.assertNotIn("ref_diff", row(a.id_table(), 0x185))

    def test_silent(self):
        a = Analysis(Decoder())
        for i in range(5):
            a.feed(Frame(T0 + i * 100000, 0x707, b"\x05"))
        last = T0 + 400000
        self.assertFalse(row(a.id_table(now_us=last + 900000), 0x707)["silent"])  # under 1 s
        self.assertTrue(row(a.id_table(now_us=last + 1100000), 0x707)["silent"])
        a.feed(Frame(T0, 0x708, b"\x05"))
        a.feed(Frame(T0 + 1000, 0x708, b"\x05"))
        self.assertFalse(row(a.id_table(now_us=T0 + 10 ** 8), 0x708)["silent"])  # fewer than three frames


class FakeClient:
    def __init__(self, fail=None):
        self.fail = fail

    def trace_start(self, filters, error_frames):
        if self.fail:
            raise diag.DiagError("refused", self.fail)
        return {"next": 0, "bitrate": 500000}

    def trace_fetch(self, after, count):
        raise diag.DiagError("eof", "connection ended: bus-off")

    def trace_stop(self):
        pass

    def status(self):
        return {}

    def close(self):
        pass


class ConnectionEnd(unittest.TestCase):
    def test_ended_connection_keeps_frames_with_a_marker(self):
        s = Session(Decoder())
        s.feed([Frame(T0 + i, 0x181, b"") for i in range(5)])
        r = Recorder(lambda: FakeClient(), s, fetch_interval=0.01)
        r.start()
        r.wait(3)
        self.assertEqual(r.state, "ended")
        self.assertEqual(r.message, "connection ended: bus-off")
        self.assertEqual(sum(1 for f in s.trace if not f.gap), 5)
        self.assertEqual(s.trace.markers[-1]["kind"], "end")
        self.assertEqual(s.trace.markers[-1]["label"], "connection ended: bus-off")

    def test_page_disconnect_ends_the_recording(self):
        s = Session(Decoder())
        r = Recorder(lambda: FakeClient(), s, ended=lambda: "disconnected")
        r.start()
        r.wait(3)
        self.assertEqual((r.state, r.message), ("ended", "connection ended: disconnected"))

    def test_runtime_not_answering_ends_after_the_limit(self):
        def connect():
            raise diag.DiagError("unreachable", "no route to host")
        s = Session(Decoder())
        with mock.patch("canworks.bustrace.recorder.RECONNECT_INTERVAL", 0.02):
            r = Recorder(connect, s, lost_after=0.1)
            r.start()
            r.wait(3)
        self.assertEqual(r.state, "ended")
        self.assertIn("not answering", r.message)


class Live(Trace):
    def setUp(self):
        super().setUp()
        self.fake = FakePlugin()
        self.fake.__enter__()
        self.addCleanup(self.fake.__exit__)
        self.connect(self.fake)
        self.cfg = self.pingpong()
        self.save(self.cfg)
        self.addCleanup(lambda: self.request("POST", "/api/trace/stop", {}))

    def recording(self):
        return self.wait_for(lambda: self.state()["recording"]["state"] == "recording")

    def test_ids_incremental_filter_and_reference(self):
        self.ok("POST", "/api/trace/start", {})
        self.assertTrue(self.recording())
        now = int(time.time() * 1e6)
        self.fake.push([Frame(now, 0x182, bytes([1, 0, 0, 0])), Frame(now + 1000, 0x702, b"\x05")])
        self.assertTrue(self.wait_for(lambda: self.state()["frames"] == 2))
        first = self.ok("POST", "/api/trace/ids", {})
        self.assertTrue(first["reset"])
        self.assertEqual([r["id_text"] for r in first["ids"]], ["182", "702"])
        self.assertEqual(self.state()["meta"]["connection"], "runtime")
        since = {k: first[k] for k in ("generation", "rev", "filter")}
        self.fake.push([Frame(now + 2000, 0x182, bytes([2, 0, 0, 0]))])
        self.assertTrue(self.wait_for(lambda: self.state()["frames"] == 3))
        upd = self.ok("POST", "/api/trace/ids", {"since": since})
        self.assertFalse(upd["reset"])
        self.assertEqual([(r["id_text"], r["changed"]) for r in upd["ids"]], [("182", 1)])
        # A display filter keeps the identifiers it matches; a changed filter starts over.
        flt = self.ok("POST", "/api/trace/ids", {"since": since, "filter": {"kinds": ["heartbeat"]}})
        self.assertTrue(flt["reset"])
        self.assertEqual([r["id_text"] for r in flt["ids"]], ["702"])
        ref = self.ok("POST", "/api/trace/ids/reference", {"at": "now"})
        self.assertTrue(ref["reference"])
        self.fake.push([Frame(now + 3000, 0x182, bytes([2, 4, 0, 0]))])
        self.assertTrue(self.wait_for(lambda: self.state()["frames"] == 4))
        r = row(self.ok("POST", "/api/trace/ids", {})["ids"], 0x182)
        self.assertEqual(r["ref_diff"], 0b10)
        self.assertEqual(r["seq"], 3)
        self.assertFalse(self.ok("POST", "/api/trace/ids/reference", {"at": None})["reference"])

    def test_continue_appends_after_a_gap(self):
        self.ok("POST", "/api/trace/start", {})
        self.assertTrue(self.recording())
        now = int(time.time() * 1e6)
        self.fake.push([Frame(now, 0x182, bytes(4))])
        self.assertTrue(self.wait_for(lambda: self.state()["frames"] == 1))
        self.ok("POST", "/api/trace/stop", {})
        generation = self.state()["generation"]
        st = self.ok("POST", "/api/trace/start", {"continue": True})
        self.assertEqual(st["generation"], generation)
        self.assertTrue(self.recording())
        self.fake.push([Frame(int(time.time() * 1e6), 0x182, bytes(4))])
        st = self.wait_for(lambda: (lambda x: x if x["frames"] == 3 else None)(self.state()))  # frame, gap, frame
        self.assertTrue(st, self.state())
        rows = self.ok("POST", "/api/trace/frames", {"offset": 0, "count": 5})["rows"]
        self.assertTrue(rows[1]["gap"])
        # Continue is for the same network and a recording only.
        self.ok("POST", "/api/trace/stop", {})
        self.ok("POST", "/api/trace/clear", {})
        status, data, _ = self.request("POST", "/api/trace/start", {"continue": True})
        self.assertEqual(status, 409)
        self.assertIn("no recording to continue", data["error"])


class TransmitStore(Trace):
    def test_list_per_folder_and_network_and_files(self):
        self.pingpong()
        rows = [{"name": "valve open", "id": "205", "data": "01"},
                {"id": "0x301", "data": "11 22", "period_ms": 100, "count": 5},
                {"id": "18FF0017", "ext": True, "rtr": True, "dlc": 3}]
        got = self.ok("POST", "/api/trace/transmit", {"frames": rows})["frames"]
        self.assertEqual([r["id"] for r in got], ["205", "301", "18FF0017"])
        self.assertEqual(got[0]["dlc"], 1)
        self.assertEqual(got[1]["period_ms"], 100)
        self.assertEqual(self.ok("POST", "/api/trace/transmit", {})["frames"], got)
        self.assertEqual(self.ok("POST", "/api/trace/transmit", {"network": "other"})["frames"], [])
        status, data, _ = self.request("POST", "/api/trace/transmit", {"frames": [{"id": "205", "data": "0F 1"}]})
        self.assertEqual(status, 422)
        self.assertIn("whole bytes", data["error"])
        status, data, _ = self.request("POST", "/api/trace/transmit/check", {"frame": {"id": "800", "data": ""}})
        self.assertIn("out of range", data["error"])
        dump = self.ok("POST", "/api/trace/transmit/dump", {"frames": got, "network": "io"})
        self.assertEqual(dump["name"], "io.transmit.json")
        self.assertEqual(json.loads(dump["text"])["format"], "canworks-transmit")
        back = self.ok("POST", "/api/trace/transmit/load", {"text": dump["text"], "network": "drives"})
        self.assertEqual((back["frames"], back["network"], back["other_network"]), (got, "io", True))
        status, data, _ = self.request("POST", "/api/trace/transmit/load", {"text": "{}"})
        self.assertIn("not a transmit list file", data["error"])

    def test_prefs(self):
        self.pingpong()
        self.assertEqual(self.ok("GET", "/api/trace/prefs")["view"], "ids")
        p = self.ok("POST", "/api/trace/prefs", {"prefs": {"view": "frames", "split": 55}})
        self.assertEqual((p["view"], p["split"]), ("frames", 55))
        status, _, _ = self.request("POST", "/api/trace/prefs", {"prefs": {"view": "nope"}})
        self.assertEqual(status, 422)


class TransmitRows(unittest.TestCase):
    def test_rules(self):
        self.assertEqual(transmit.check_row({"id": "7ff", "data": ""})["id"], "7FF")
        for bad, text in (({"id": "zz"}, "hex"), ({"id": "1", "data": "00" * 9}, "at most 8"),
                          ({"id": "1", "period_ms": 5}, "10 to 60000"), ({"id": "1", "count": 0}, "at least 1"),
                          ({"id": "1", "rtr": True, "dlc": 9}, "DLC")):
            with self.assertRaises(transmit.Invalid) as e:
                transmit.check_row(bad)
            self.assertIn(text, str(e.exception))

    def test_store_survives_bad_files(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        with open(os.path.join(d, transmit.STORE), "w") as f:
            f.write("not json")
        st = transmit.Store(d)
        self.assertEqual(st.rows("/x", "io"), [])
        self.assertEqual(st.prefs()["view"], "ids")
        st.set_rows("/x", "io", [{"id": "1"}])
        self.assertEqual(len(st.rows("/x", "io")), 1)
        self.assertEqual(st.rows("/y", "io"), [])


class CommissionDecoding(unittest.TestCase):
    def test_eds_names_without_a_config(self):
        from canworks.configurator.tracing import commission_decoder
        eds = EDS
        d = commission_decoder({"12": eds, "200": eds, "5": "x.txt"}, lambda p: p)
        self.assertEqual(sorted(d.eds), [12])
        self.assertEqual(d.node_label(12), "node 12")
        text = d.decode(Frame(T0, 0x60C, bytes.fromhex("4018100100000000"))).text
        self.assertIn("1018", text)
