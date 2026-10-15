"""Raw frames on the local bus backend: send_frame on python-can's virtual
bus, and the slcan adapter's listen-only open for the bit rate check (and
its switch to normal mode) on a fake serial port."""

import base64
import os
import time
import unittest
from unittest import mock

import can

from canworks import diag
from canworks.bustrace.model import RECORD_SIZE, Frame
from canworks.localbus import AdapterError, parse
from canworks.localbus import adapter as adapter_mod

from .fake_canopen import Peer
from .helpers import REPO
from .test_localbus import Base, channel


# ---------------------------------------------------------------------------
# Listen-only on slcan


class FakeBus:
    def __init__(self, **kw):
        self.kw = kw

    def shutdown(self):
        pass


class ListenOnly(unittest.TestCase):
    def _slcan(self, knows_m1, answers=True, busy=False):
        """A fake slcan serial port; firmware that knows the 'm' (mode)
        command answers it with CR, other firmware with BEL. With `answers`
        false it answers nothing, as some firmware does. With `busy` an open
        channel receives frames without end, as on a busy bus."""
        from can.interfaces import slcan
        ports = []

        class Port:
            def __init__(self, url, **kw):
                self.written, self.inbuf = b"", bytearray()
                self.open = False
                ports.append(self)

            def write(self, b):
                self.written += b
                if b[:1] in (b"O", b"L"):
                    self.open = True
                elif b[:1] == b"C":
                    self.open = False
                if b[:1] == b"m" and answers:
                    self.inbuf += b"\r" if knows_m1 else b"\x07"

            @property
            def in_waiting(self):
                if busy and self.open and not self.inbuf:
                    self.inbuf += b"t0800\r"  # a SYNC frame
                return len(self.inbuf)

            def read(self, n):
                out = bytes(self.inbuf[:n])
                del self.inbuf[:n]
                return out

            def flush(self):
                pass

            def close(self):
                pass

        p = mock.patch.object(slcan, "serial", mock.Mock(serial_for_url=Port))
        p.start()
        self.addCleanup(p.stop)
        return ports

    def test_slcan_silent_mode(self):
        ports = self._slcan(knows_m1=True)
        opened = adapter_mod.open(parse("slcan:COM9"), 250000, listen_only=True, options={"sleep_after_open": 0})
        sent = ports[-1].written
        self.assertIn(b"S5\r", sent)
        self.assertTrue(sent.endswith(b"m1\rO\r"), sent)
        self.assertNotIn(b"L\r", sent)
        # The check leaves listen-only on the same serial connection: closed, mode back, open.
        ports[-1].written = b""
        opened.set_mode(listen_only=False)
        self.assertEqual([c for c in ports[-1].written.split(b"\r") if c], [b"C", b"m0", b"O"])
        self.assertFalse(opened.listen_only)
        ports[-1].written = b""
        opened.close()
        self.assertTrue(ports[-1].written.endswith(b"C\r"), ports[-1].written)
        self.assertNotIn(b"m0", ports[-1].written)
        # A normal open sets normal mode before opening.
        opened = adapter_mod.open(parse("slcan:COM9"), 250000, options={"sleep_after_open": 0})
        self.assertTrue(ports[-1].written.endswith(b"m0\rO\r"))
        opened.close()

    def test_slcan_rate_it_cannot_run(self):
        self._slcan(knows_m1=True)
        with self.assertRaises(AdapterError) as e:
            adapter_mod.open(parse("slcan:COM9"), 800000, options={"sleep_after_open": 0})
        self.assertEqual(e.exception.kind, "usage")
        self.assertIn("cannot run at 800 kbit/s", str(e.exception))

    def test_slcan_opens_on_a_busy_bus(self):
        # python-can opens the channel in set_bitrate() and once more; frames
        # arriving without end must not keep the open waiting for quiet.
        ports = self._slcan(knows_m1=True, busy=True)
        started = time.monotonic()
        opened = adapter_mod.open(parse("slcan:COM9"), 500000, options={"sleep_after_open": 0})
        self.assertLess(time.monotonic() - started, 3)
        commands = [c for c in ports[-1].written.split(b"\r") if c]
        self.assertEqual(commands[commands.index(b"S6"):], [b"S6", b"m0", b"O"])
        opened.close()

    def test_slcan_unanswered_mode_command_opens_normally(self):
        ports = self._slcan(knows_m1=True, answers=False)
        opened = adapter_mod.open(parse("slcan:COM9"), 250000, listen_only=True, options={"sleep_after_open": 0})
        self.assertTrue(ports[-1].written.endswith(b"m1\rO\r"), ports[-1].written)
        ports[-1].written = b""
        opened.set_mode(listen_only=False)
        self.assertEqual(ports[-1].written, b"")  # it was never listen-only
        opened.close()

    def test_slcan_without_silent_mode_opens_with_L(self):
        ports = self._slcan(knows_m1=False)
        opened = adapter_mod.open(parse("slcan:COM9"), 250000, listen_only=True, options={"sleep_after_open": 0})
        sent = ports[-1].written
        self.assertTrue(sent.endswith(b"m1\rL\r"), sent)
        self.assertNotIn(b"O\r", sent)
        ports[-1].written = b""
        opened.set_mode(listen_only=False)
        self.assertEqual([c for c in ports[-1].written.split(b"\r") if c], [b"C", b"O"])
        opened.close()

    def test_others_open_normally(self):
        bus = mock.Mock(side_effect=lambda **kw: FakeBus(**kw))
        with mock.patch.object(can, "Bus", bus):
            opened = adapter_mod.open(parse("pcan:PCAN_USBBUS1"), 125000, listen_only=True)
            self.assertFalse(opened.listen_only)
            self.assertNotIn("state", opened.bus.kw)
            self.assertIsNone(opened.confirm)
            opened.close()

    def test_virtual(self):
        opened = adapter_mod.open(parse("virtual:" + channel()), 250000, listen_only=True)
        self.assertFalse(opened.listen_only)
        self.assertEqual(opened.confirm, adapter_mod.CONFIRM_NO_ERRORS)
        opened.close()


# ---------------------------------------------------------------------------
# send_frame on the virtual bus


class Send(Base):
    def setUp(self):
        super().setUp()
        self.peer = Peer(self.ch)
        self.addCleanup(self.peer.close)

    def client(self, *args, **kw):
        c = super().client(*args, **kw)
        self.heard(0.05)  # the bit rate check's probe on this silent bus
        return c

    def heard(self, wait=0.2):
        out, end = [], time.monotonic() + wait
        while time.monotonic() < end:
            m = self.peer.bus.recv(0.02)
            if m is not None:
                out.append(m)
        return out

    def test_needs_allow_changes(self):
        c = self.client()
        with self.assertRaises(diag.DiagError) as e:
            c.send_frame(0x60A, b"\x40\x18\x10\x01")
        self.assertIn("changes not allowed", str(e.exception))
        self.assertEqual(self.heard(0.1), [])

    def test_single_ext_and_remote(self):
        c = self.client(allow_changes=True)
        r = c.trace_start()
        self.assertEqual(c.send_frame(0x60A, b"\x40\x18\x10\x01\0\0\0\0"), {"sent": True})
        self.assertEqual(c.send_frame(0x1ABCDEF, b"\x01", ext=True), {"sent": True})
        self.assertEqual(c.send_frame(0x7F0, rtr=True, dlc=2), {"sent": True})
        got = self.heard()
        self.assertEqual([(m.arbitration_id, m.is_extended_id, m.is_remote_frame, m.dlc) for m in got],
                         [(0x60A, False, False, 8), (0x1ABCDEF, True, False, 1), (0x7F0, False, True, 2)])
        data = base64.b64decode(c.trace_fetch(r["next"])["frames"])
        frames = [Frame.unpack(data, i) for i in range(0, len(data), RECORD_SIZE)]
        self.assertEqual([(f.can_id, f.ext, f.rtr, f.tx) for f in frames],
                         [(0x60A, False, False, True), (0x1ABCDEF, True, False, True), (0x7F0, False, True, True)])

    def test_fields(self):
        c = self.client(allow_changes=True)
        for fields, text in (({"can_id": 0x800}, "can_id"), ({"can_id": 1, "data": "zz"}, "hexadecimal"),
                             ({"can_id": 1, "data": "00 " * 9}, "at most 8"),
                             ({"can_id": 1, "rtr": True, "data": "00"}, "remote frame"),
                             ({"can_id": 1, "period_ms": 5}, "10-60000"),
                             ({"can_id": 1, "count": 3}, "needs 'period_ms'")):
            with self.assertRaises(diag.DiagError) as e:
                c.request("send_frame", **fields)
            self.assertIn(text, str(e.exception))

    def test_force_for_the_cob_id_map(self):
        c = self.client(allow_changes=True, config={5: {"name": "valve"}})
        for can_id, use in ((0x000, "0x000 is NMT"), (0x205, "0x205 is RPDO1 of node 5 (valve)"),
                            (0x585, "SDO response channel of node 5"), (0x705, "heartbeat of node 5")):
            with self.assertRaises(diag.DiagError) as e:
                c.send_frame(can_id, b"\x01")
            self.assertIn(use, str(e.exception))
            self.assertTrue(diag.needs_force(e.exception), str(e.exception))
        self.assertEqual(self.heard(0.1), [])
        self.assertEqual(c.send_frame(0x205, b"\x01", force=True), {"sent": True})
        self.assertEqual(c.send_frame(0x206, b"\x01"), {"sent": True})  # node 6 is not configured
        self.assertEqual(c.send_frame(0x205, b"\x01", ext=True), {"sent": True})  # extended: never in the map
        self.assertEqual(len(self.heard()), 3)

    def test_force_while_operational_or_another_master(self):
        c = self.client(allow_changes=True)
        self.peer.send(0x705, b"\x05")
        time.sleep(0.1)
        with self.assertRaises(diag.DiagError) as e:
            c.send_frame(0x60A, b"\x01")
        self.assertEqual(str(e.exception), "node 5 is OPERATIONAL; force needed")
        self.peer.send(0x705, b"\x7f")
        time.sleep(0.1)
        self.assertEqual(c.send_frame(0x60A, b"\x01"), {"sent": True})
        self.peer.send(0x080, b"")
        time.sleep(0.1)
        with self.assertRaises(diag.DiagError) as e:
            c.send_frame(0x60A, b"\x01")
        self.assertIn("another master is active", str(e.exception))
        self.assertTrue(diag.needs_force(e.exception))

    def test_rate_limit(self):
        c = self.client(allow_changes=True)
        c.core.wait_listened()
        ok = limited = 0
        for _ in range(60):
            try:
                c.send_frame(0x60A, b"\x01")
                ok += 1
            except diag.DiagError as e:
                self.assertEqual(str(e), "rate limit")
                limited += 1
        self.assertGreaterEqual(ok, 50)
        self.assertLess(ok, 60)
        self.assertEqual(ok + limited, 60)

    def test_cyclic_with_count(self):
        c = self.client(allow_changes=True)
        r = c.send_frame(0x60A, b"\x01", period_ms=20, count=5)
        self.assertEqual((r["period_ms"], r["count"]), (20, 5))
        self.assertEqual(c.status()["send_jobs"][0]["job"], r["job"])
        got = self.heard(0.5)
        self.assertEqual(len(got), 5)
        self.assertEqual(c.status()["send_jobs"], [])
        stopped = c.send_frame_stop(r["job"])["stopped"]
        self.assertEqual([(s["job"], s["sent"], s["reason"]) for s in stopped], [(r["job"], 5, "count reached")])
        with self.assertRaises(diag.DiagError) as e:
            c.send_frame_stop(r["job"])  # reported once
        self.assertIn("no job", str(e.exception))

    def test_stop_close_and_job_limit(self):
        c = self.client(allow_changes=True)
        other = self.client(allow_changes=True)  # a second handle on the same adapter
        jobs = [c.send_frame(0x600 + i, b"", period_ms=50)["job"] for i in range(1, 9)]
        with self.assertRaises(diag.DiagError) as e:
            other.send_frame(0x610, b"", period_ms=50)
        self.assertIn("too many jobs", str(e.exception))
        self.assertEqual(other.send_frame_stop(), {"stopped": []})  # not its jobs
        stopped = c.send_frame_stop(jobs[0])["stopped"]
        self.assertEqual(stopped[0]["reason"], "stopped")
        self.assertEqual(len(other.status()["send_jobs"]), 7)
        c.close()
        self.assertEqual(other.status()["send_jobs"], [])
        self.heard(0.1)
        self.assertEqual(self.heard(0.2), [])

    def test_cli(self):
        from .test_localbus import cli
        adapter = ["--adapter", "virtual:" + self.ch, "--bitrate", "250"]
        code, out, err = cli(*adapter, "send", "0x60A", "40 18 10 01")
        self.assertEqual(code, 1)
        self.assertIn("changes not allowed", err)
        code, out, err = cli(*adapter, "--allow-changes", "send", "0x60A", "40 18 10 01")
        self.assertEqual(code, 0, err)
        self.assertIn("sent", out)
        code, out, err = cli(*adapter, "--allow-changes", "send", "0x000", "01 05")
        self.assertEqual(code, 1)
        self.assertIn("0x000 is NMT; force needed; add --force", err)
        code, out, err = cli(*adapter, "--allow-changes", "send", "0x60B", "01", "--period-ms", "20", "--count", "4")
        self.assertEqual(code, 0, err)
        got = [m.arbitration_id for m in self.heard(0.3)]
        self.assertEqual(got.count(0x60B), 4)
        self.assertEqual(got.count(0x60A), 1)

    def test_cli_config_and_force_before_the_command(self):
        from .test_localbus import cli
        adapter = ["--adapter", "virtual:" + self.ch, "--bitrate", "250", "--allow-changes"]
        cfg = os.path.join(REPO, "config", "pingpong", "canopen_config.json")  # node 2
        code, out, err = cli(*adapter, "send", "--config", cfg, "0x202", "01")
        self.assertEqual(code, 1)
        self.assertIn("0x202 is RPDO1 of node 2", err)
        code, out, err = cli(*adapter, "send", "0x202", "01")  # without the config node 2 is unknown
        self.assertEqual(code, 0, err)
        # --force counts before the command as after it.
        code, out, err = cli(*adapter, "--force", "send", "--config", cfg, "0x202", "01")
        self.assertEqual(code, 0, err)
        self.assertIn("(forced)", out)
        self.assertEqual([m.arbitration_id for m in self.heard()].count(0x202), 2)


if __name__ == "__main__":
    unittest.main()
