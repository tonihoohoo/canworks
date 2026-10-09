"""Raw frames and bit rate detection on the local bus backend
(add-raw-frames-bitrate-detect, section 6): listen-only per adapter type on
fakes, send_frame and detect_bitrate on python-can's virtual bus, and the
verdict against the cases the plugin's unit test checks too."""

import base64
import json
import os
import subprocess
import threading
import time
import unittest
from unittest import mock

import can

from canworks import bitrate as bitrate_mod
from canworks import diag
from canworks.bustrace.model import RECORD_SIZE, Frame
from canworks.localbus import AdapterError, parse
from canworks.localbus import adapter as adapter_mod
from canworks.localbus import sweep as sweep_mod

from .fake_canopen import Peer
from .helpers import REPO
from .test_localbus import Base, channel


class VerdictParity(unittest.TestCase):
    def test_cases(self):
        with open(os.path.join(REPO, "test", "fixtures", "sweep_verdicts.json"), encoding="utf-8") as f:
            cases = json.load(f)["cases"]
        self.assertGreaterEqual(len(cases), 8)
        for c in cases:
            rows = [{"bitrate_kbit": k, "frames": n, "error_frames": e} for k, n, e in c["results"]]
            self.assertEqual(bitrate_mod.decide(rows), {"verdict": c["verdict"], "bitrate_kbit": c["bitrate_kbit"],
                                                        "candidates": c["candidates"]}, c["name"])

    def test_rates(self):
        self.assertEqual(bitrate_mod.RATES, diag.DETECT_RATES)


# ---------------------------------------------------------------------------
# Listen-only per adapter type


class FakeIp:
    """`ip` for one CAN link: answers `ip -details -json link show` from its
    state and records every `ip link set`."""

    def __init__(self, kind="can", up=True, bitrate=250000, fail=None):
        self.kind, self.up, self.bitrate, self.fail = kind, up, bitrate, fail
        self.listen_only = False
        self.calls = []

    def run(self, cmd, **kw):
        if cmd[:3] == ["ip", "-details", "-json"]:
            info = {"flags": ["UP"] if self.up else [], "linkinfo": {"info_kind": self.kind, "info_data": {
                "bittiming": {"bitrate": self.bitrate}}}}
            return subprocess.CompletedProcess(cmd, 0, json.dumps([info]), "")
        args = cmd[1:]
        self.calls.append(" ".join(args))
        if self.fail and self.fail[0] in " ".join(args):
            return subprocess.CompletedProcess(cmd, 2, "", self.fail[1])
        if args[-1] == "down":
            self.up = False
        elif args[-1] == "up":
            self.up = True
        if "bitrate" in args:
            self.bitrate = int(args[args.index("bitrate") + 1])
        if "listen-only" in args:
            self.listen_only = args[args.index("listen-only") + 1] == "on"
        return subprocess.CompletedProcess(cmd, 0, "", "")


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
        # Another rate on the same serial connection: closed, mode back, silent again.
        ports[-1].written = b""
        self.assertTrue(opened.retune(500000))
        self.assertEqual([c for c in ports[-1].written.split(b"\r") if c], [b"C", b"m0", b"S6", b"m1", b"O"])
        ports[-1].written = b""
        opened.close()
        self.assertTrue(ports[-1].written.endswith(b"C\rm0\r"), ports[-1].written)
        # A normal open sets normal mode before opening.
        opened = adapter_mod.open(parse("slcan:COM9"), 250000, options={"sleep_after_open": 0})
        self.assertTrue(ports[-1].written.endswith(b"m0\rO\r"))
        opened.close()

    def test_slcan_opens_on_a_busy_bus(self):
        # python-can opens the channel in set_bitrate() and once more; frames
        # arriving without end must not keep the open waiting for quiet.
        ports = self._slcan(knows_m1=True, busy=True)
        started = time.monotonic()
        opened = adapter_mod.open(parse("slcan:COM9"), 500000, options={"sleep_after_open": 0})
        self.assertLess(time.monotonic() - started, 3)
        commands = [c for c in ports[-1].written.split(b"\r") if c]
        self.assertEqual(commands[commands.index(b"S6"):], [b"S6", b"m0", b"O"])
        self.assertTrue(opened.retune(250000))
        opened.close()

    def test_slcan_unconfirmed_silent_mode_is_refused(self):
        ports = self._slcan(knows_m1=True, answers=False)
        with self.assertRaises(adapter_mod.AdapterError) as cm:
            adapter_mod.open(parse("slcan:COM9"), 250000, listen_only=True, options={"sleep_after_open": 0})
        self.assertEqual(cm.exception.kind, "unconfirmed")
        self.assertTrue(str(cm.exception).endswith("disturb_bus needed"))
        sent = ports[-1].written
        self.assertIn(b"m1\r", sent)
        self.assertNotIn(b"O\r", sent)
        self.assertNotIn(b"L\r", sent)
        self.assertTrue(sent.endswith(b"C\rm0\r"), sent)  # closed, mode set back
        # The lock is free again.
        opened = adapter_mod.open(parse("slcan:COM9"), 250000, options={"sleep_after_open": 0})
        opened.close()

    def test_slcan_unconfirmed_silent_mode_with_disturb_bus(self):
        ports = self._slcan(knows_m1=True, answers=False)
        opened = adapter_mod.open(parse("slcan:COM9"), 250000, listen_only=True, options={"sleep_after_open": 0},
                                  disturb_bus=True)
        sent = ports[-1].written
        self.assertTrue(sent.endswith(b"m1\rO\r"), sent)
        self.assertNotIn(b"L\r", sent)
        ports[-1].written = b""
        opened.close()
        self.assertTrue(ports[-1].written.endswith(b"C\rm0\r"), ports[-1].written)

    def test_sweep_passes_disturb_bus(self):
        seen = []

        def opener(spec, bitrate, listen_only=False, options=None, **kw):
            seen.append(kw)
            raise adapter_mod.AdapterError("unconfirmed", adapter_mod.UNCONFIRMED)

        with self.assertRaises(adapter_mod.AdapterError):
            sweep_mod.Sweep(parse("slcan:COM9"), [500], 100, opener=opener).start()
        with self.assertRaises(adapter_mod.AdapterError):
            sweep_mod.Sweep(parse("slcan:COM9"), [500], 100, opener=opener, disturb_bus=True).start()
        self.assertEqual(seen, [{}, {"disturb_bus": True}])

    def test_slcan_without_silent_mode_opens_with_L(self):
        ports = self._slcan(knows_m1=False)
        opened = adapter_mod.open(parse("slcan:COM9"), 250000, listen_only=True, options={"sleep_after_open": 0})
        sent = ports[-1].written
        self.assertTrue(sent.endswith(b"m1\rL\r"), sent)
        self.assertNotIn(b"O\r", sent)
        ports[-1].written = b""
        self.assertTrue(opened.retune(500000))
        self.assertEqual(ports[-1].written.split(b"\r")[:2], [b"C", b"S6"])
        self.assertTrue(ports[-1].written.endswith(b"L\r"))
        self.assertNotIn(b"O\r", ports[-1].written)
        opened.close()
        opened = adapter_mod.open(parse("slcan:COM9"), 250000, options={"sleep_after_open": 0})
        self.assertTrue(ports[-1].written.endswith(b"O\r"))
        opened.close()

    def test_pcan_passive(self):
        with mock.patch.object(can, "Bus", side_effect=lambda **kw: FakeBus(**kw)):
            opened = adapter_mod.open(parse("pcan:PCAN_USBBUS1"), 125000, listen_only=True)
            self.assertEqual(opened.bus.kw["state"], can.BusState.PASSIVE)
            self.assertEqual(opened.bus.kw["bitrate"], 125000)
            opened.close()
            opened = adapter_mod.open(parse("pcan:PCAN_USBBUS1"), 125000)
            self.assertNotIn("state", opened.bus.kw)
            opened.close()

    def test_others_have_none(self):
        bus = mock.Mock(side_effect=lambda **kw: FakeBus(**kw))
        with mock.patch.object(can, "Bus", bus):
            for text in ("gs_usb:0", "serial:/dev/ttyUSB0"):
                with self.assertRaises(AdapterError) as e:
                    adapter_mod.open(parse(text), 250000, listen_only=True)
                self.assertIn(adapter_mod.NO_LISTEN_ONLY, str(e.exception))
        bus.assert_not_called()

    def test_virtual(self):
        opened = adapter_mod.open(parse("virtual:" + channel()), 250000, listen_only=True)
        self.assertTrue(opened.listen_only)
        opened.close()

    def socketcan(self, ip, bitrate=500000):
        with mock.patch.object(adapter_mod.subprocess, "run", ip.run), \
                mock.patch.object(adapter_mod.sys, "platform", "linux"), \
                mock.patch.object(can, "Bus", side_effect=lambda **kw: FakeBus(**kw)):
            return adapter_mod.open(parse("socketcan:can0"), bitrate, listen_only=True)

    def test_socketcan_sets_and_restores_the_link(self):
        ip = FakeIp(up=True, bitrate=250000)
        opened = self.socketcan(ip)
        self.assertEqual(ip.calls, ["link set dev can0 down",
                                    "link set dev can0 type can bitrate 500000 listen-only on",
                                    "link set dev can0 up"])
        self.assertTrue(ip.listen_only and ip.up)
        with mock.patch.object(adapter_mod.subprocess, "run", ip.run):
            self.assertEqual(opened.close(), "")
        self.assertEqual(ip.calls[3:], ["link set dev can0 down",
                                        "link set dev can0 type can bitrate 250000 listen-only off",
                                        "link set dev can0 up"])
        self.assertEqual((ip.listen_only, ip.bitrate, ip.up), (False, 250000, True))

    def test_socketcan_link_down_stays_down(self):
        ip = FakeIp(up=False, bitrate=125000)
        opened = self.socketcan(ip)
        with mock.patch.object(adapter_mod.subprocess, "run", ip.run):
            opened.close()
        self.assertEqual((ip.listen_only, ip.up), (False, False))

    def test_socketcan_without_permission(self):
        ip = FakeIp(fail=("down", "RTNETLINK answers: Operation not permitted"))
        with self.assertRaises(AdapterError) as e:
            self.socketcan(ip)
        text = str(e.exception)
        self.assertIn("CAP_NET_ADMIN", text)
        self.assertIn("sudo ip link set dev can0 type can bitrate 500000 listen-only on", text)

    def test_socketcan_driver_without_listen_only(self):
        ip = FakeIp(fail=("listen-only on", "RTNETLINK answers: Operation not supported"))
        with self.assertRaises(AdapterError) as e:
            self.socketcan(ip)
        self.assertIn(adapter_mod.NO_LISTEN_ONLY, str(e.exception))
        self.assertFalse(ip.listen_only)
        self.assertTrue(ip.up)  # set back as it was

    def test_vcan(self):
        with self.assertRaises(AdapterError) as e:
            self.socketcan(FakeIp(kind="vcan"))
        self.assertIn("no bit rate on a virtual bus", str(e.exception))


# ---------------------------------------------------------------------------
# send_frame on the virtual bus


class Send(Base):
    def setUp(self):
        super().setUp()
        self.peer = Peer(self.ch)
        self.addCleanup(self.peer.close)

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


# ---------------------------------------------------------------------------
# detect_bitrate on the virtual bus: the "bus" carries traffic at 250 kbit/s


class Detect(Base):
    def setUp(self):
        super().setUp()
        self.peer = Peer(self.ch)
        self.addCleanup(self.peer.close)
        self.opened = []
        real = adapter_mod.open

        def opener(spec, bitrate, listen_only=False, options=None):
            self.opened.append((bitrate, listen_only))
            if listen_only and bitrate != 250000:
                spec = parse("virtual:" + channel())  # another rate: nothing to hear
            return real(spec, bitrate, listen_only, options)

        p = mock.patch.object(adapter_mod, "open", opener)
        p.start()
        self.addCleanup(p.stop)
        self.running = True
        self.traffic = threading.Thread(target=self._traffic, daemon=True)
        self.traffic.start()
        self.addCleanup(self._end_traffic)

    def _traffic(self):
        while self.running:
            self.peer.send(0x705, b"\x7f")
            time.sleep(0.02)

    def _end_traffic(self):
        self.running = False
        self.traffic.join()

    def wait(self, c):
        res = c.detect_bitrate_status()
        end = time.monotonic() + 10
        while res["running"] and time.monotonic() < end:
            time.sleep(0.05)
            res = c.detect_bitrate_status()
        return res

    def test_no_listen_only_refused_before_closing(self):
        # A gs_usb adapter has no listen-only mode: the sweep is refused while
        # the connection stays open, not closed and reopened at once.
        c = self.client()
        core = c.core
        c.spec = adapter_mod.Spec("gs_usb", "0")
        self.opened.clear()
        with self.assertRaises(diag.DiagError) as e:
            c.detect_bitrate(per_rate_ms=100)
        self.assertIn("no listen-only mode", str(e.exception))
        self.assertIn("lone-device", str(e.exception))
        self.assertIs(c.core, core)
        self.assertEqual(self.opened, [])

    def test_detects_and_reopens(self):
        c = self.client()  # read-only: listen-only needs no allow-changes
        c.trace_start()
        res = c.detect_bitrate(per_rate_ms=100)
        self.assertTrue(res["running"])
        with self.assertRaises(diag.DiagError) as e:
            c.sdo_read(5, 0x1018, 1)
        self.assertEqual(str(e.exception), "no bus")
        self.assertTrue(c.status()["bitrate_sweep"]["running"])
        res = self.wait(c)
        self.assertEqual((res["verdict"], res["bitrate_kbit"], res["matches_config"]), ("detected", 250, True))
        rows = {r["bitrate_kbit"]: r for r in res["results"]}
        self.assertGreater(rows[250]["frames"], 0)
        self.assertEqual(rows[250]["ids"], [0x705])
        self.assertEqual(rows[1000]["frames"], 0)
        # Stopped early after the round that detected it; every rate listen-only, then the handle's rate.
        self.assertEqual([b for b, lo in self.opened if lo], [r * 1000 for r in bitrate_mod.RATES])
        self.assertEqual(self.opened[-1], (250000, False))
        # The handle keeps working, its trace too.
        self.assertFalse(c.status()["bitrate_sweep"]["running"])
        time.sleep(0.1)
        data = base64.b64decode(c.trace_fetch(0)["frames"])
        self.assertIn(0x705, [Frame.unpack(data, i).can_id for i in range(0, len(data), RECORD_SIZE)])

    def test_subset_and_silent(self):
        c = self.client()
        c.detect_bitrate(rates=[500, 125], per_rate_ms=100, rounds=2)
        res = self.wait(c)
        self.assertEqual(res["verdict"], "silent")
        self.assertEqual([r["bitrate_kbit"] for r in res["results"]], [500, 125])
        self.assertEqual((res["done"], res["total"]), (4, 4))

    def test_busy_when_shared(self):
        c = self.client()
        self.client()
        with self.assertRaises(diag.DiagError) as e:
            c.detect_bitrate(per_rate_ms=100)
        self.assertIn("busy", str(e.exception))
        self.assertTrue(c.status()["local"])

    def test_fields(self):
        c = self.client()
        for fields, text in (({"rates": [300]}, "field 'rates'"), ({"per_rate_ms": 50}, "100-10000"),
                             ({"rounds": 21}, "rounds")):
            with self.assertRaises(diag.DiagError) as e:
                c.request("detect_bitrate", **fields)
            self.assertIn(text, str(e.exception))
        self.assertEqual(c.detect_bitrate_status(), {"running": False, "configured_kbit": 250, "verdict": None})

    def test_no_listen_only_reopens(self):
        c = self.client()
        with mock.patch.object(sweep_mod.Sweep, "_open", side_effect=AdapterError("usage", "no listen-only here")):
            with self.assertRaises(diag.DiagError) as e:
                c.detect_bitrate()
        self.assertIn("no listen-only here", str(e.exception))
        self.assertTrue(c.status()["local"])

    def test_cli_opens_only_for_the_sweep(self):
        # No connection at a guessed rate first: every open is the sweep's,
        # listen-only, and --bitrate is not needed.
        from .test_localbus import cli
        code, out, err = cli("--adapter", "virtual:" + self.ch, "detect-bitrate", "--per-rate-ms", "100")
        self.assertEqual(code, 0, err)
        self.assertIn("250 kbit/s detected", out)
        self.assertTrue(self.opened)
        self.assertTrue(all(listen_only for _, listen_only in self.opened), self.opened)

    def test_cli(self):
        from .test_localbus import cli
        code, out, err = cli("--adapter", "virtual:" + self.ch, "--bitrate", "250", "detect-bitrate",
                             "--per-rate-ms", "100")
        self.assertEqual(code, 0, err)
        self.assertIn("250 kbit/s detected, as configured", out)


class StandaloneSweep(unittest.TestCase):
    def test_dialog_sweep_closes_everything(self):
        spec = parse("virtual:" + channel())
        s = sweep_mod.Sweep(spec, [250, 125], 100, configured_kbit=None)
        s.start()
        while s.status()["running"]:
            time.sleep(0.05)
        res = s.status()
        self.assertEqual(res["verdict"], "silent")
        self.assertNotIn("matches_config", res)
        # The adapter is free again.
        adapter_mod.open(spec, 250000).close()


    def test_rates_the_adapter_cannot_set_are_left_out(self):
        virt = parse("virtual:" + channel())
        opened = []

        def opener(spec, bitrate, listen_only=False, options=None):
            opened.append(bitrate // 1000)
            return adapter_mod.open(virt, bitrate, listen_only, options)

        s = sweep_mod.Sweep(parse("slcan:/dev/ttyACM0"), [1000, 800, 500], 100, opener=opener)
        self.assertEqual(s.total, 2)
        s.start()
        while s.status()["running"]:
            time.sleep(0.05)
        res = s.status()
        self.assertEqual((res["verdict"], res.get("error")), ("silent", None))
        self.assertEqual([r["bitrate_kbit"] for r in res["results"]], [1000, 500])
        self.assertEqual(res["skipped_kbit"], [800])
        self.assertEqual(opened, [1000, 500])
        self.assertEqual(diag.skipped_text(res), "not tried: 800 kbit/s (the adapter cannot be set to it)")
        self.assertEqual(diag.skipped_text({"results": []}), "")
        self.assertEqual(adapter_mod.unsupported_rates(parse("socketcan:can0"), list(bitrate_mod.RATES)), [])
        with self.assertRaises(AdapterError) as e:
            sweep_mod.Sweep(parse("slcan:/dev/ttyACM0"), [800], 100, opener=opener).start()
        self.assertIn("cannot be set to 800 kbit/s", str(e.exception))


if __name__ == "__main__":
    unittest.main()
