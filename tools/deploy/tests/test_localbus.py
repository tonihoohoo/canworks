"""The local bus backend (canopen-local-bus) on python-can's virtual bus,
against fake devices. Runs on every PC tools runner: no CAN hardware."""

import base64
import io
import itertools
import json
import os
import shutil
import tempfile
import threading
import struct
import time
import unittest
from contextlib import redirect_stderr
from unittest import mock

import can

from canworks import diag
from canworks.bustrace.model import RECORD_SIZE, Frame
from canworks.localbus import AdapterError, LocalBus, parse
from canworks.localbus import client as client_mod
from canworks.localbus import core as core_mod

from .fake_canopen import FakeDevice, Peer
from .helpers import REPO

_n = itertools.count(1)


def channel():
    return "localbus-test-%d" % next(_n)


class Base(unittest.TestCase):
    def setUp(self):
        self.ch = channel()
        self.devices = []
        self.clients = []

    def tearDown(self):
        for c in self.clients:
            c.close()
        for d in self.devices:
            d.close()

    def device(self, node, **kw):
        d = FakeDevice(self.ch, node, **kw)
        self.devices.append(d)
        return d

    def client(self, allow_changes=False, **kw):
        c = LocalBus(parse("virtual:" + self.ch), 250000, allow_changes=allow_changes, listen_s=0.05, **kw)
        c.connect()
        self.clients.append(c)
        return c


class AdapterSpec(unittest.TestCase):
    def test_parse(self):
        s = parse("slcan:COM5", ["tty_baudrate=115200", "rtscts=true"])
        self.assertEqual((s.kind, s.channel), ("slcan", "COM5"))
        self.assertEqual(s.options, {"tty_baudrate": 115200, "rtscts": True})
        self.assertEqual(str(parse("slcan:/dev/tty.usbmodem14101")), "slcan:/dev/tty.usbmodem14101")

    def test_bad(self):
        for text in ("", "slcan", "slcan:", ":COM5"):
            with self.assertRaises(AdapterError):
                parse(text)
        with self.assertRaises(AdapterError) as e:
            parse("foo:0")
        self.assertIn("slcan", str(e.exception))

    def test_no_bitrate(self):
        c = LocalBus(parse("virtual:x"), None)
        with self.assertRaises(diag.DiagError) as e:
            c.connect()
        self.assertIn("bit rate", str(e.exception))

    def test_one_tool_per_adapter(self):
        from canworks.localbus import adapter
        spec = parse("virtual:lock-test")
        lock = adapter._Lock(spec)
        self.assertTrue(lock.acquire())
        try:
            with self.assertRaises(AdapterError) as e:
                adapter.open(spec, 250000)
            self.assertEqual(e.exception.kind, "busy")
            self.assertIn("in use", str(e.exception))
        finally:
            lock.release()

    def test_lock_per_user_and_lock_errors(self):
        # A shared temporary folder holds one lock folder per user, and a
        # lock that cannot be made is an unreachable adapter, not a
        # traceback (bug hunt PC lows).
        import tempfile
        from canworks.localbus import adapter
        lock = adapter._Lock(parse("virtual:lock-test"))
        if hasattr(os, "getuid"):
            self.assertEqual(os.path.basename(os.path.dirname(lock.path)), "canworks-adapters-%d" % os.getuid())
        real_open = os.open

        def refused(path, *a, **kw):
            if path.endswith(".lock"):
                raise PermissionError(13, "Permission denied")
            return real_open(path, *a, **kw)
        with mock.patch.object(adapter.os, "open", refused):
            with self.assertRaises(diag.DiagError) as e:
                LocalBus(parse("virtual:" + channel()), 250000, listen_s=0.05).connect()
        self.assertEqual(e.exception.kind, "unreachable")
        self.assertIn("Permission denied", str(e.exception))
        # A temp folder under a plain file cannot be made on any system.
        scratch = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, scratch)
        blocker = os.path.join(scratch, "plain-file")
        open(blocker, "w").close()
        with mock.patch.object(tempfile, "gettempdir", lambda: os.path.join(blocker, "sub")):
            with self.assertRaises(AdapterError) as e:
                adapter._Lock(parse("virtual:x"))
        self.assertEqual(e.exception.kind, "unreachable")


class Sdo(Base):
    def test_expedited_and_segmented(self):
        self.device(5, od={(0x2000, 1): b"\x11\x22", (0x2001, 0): bytes(range(40))})
        c = self.client(allow_changes=True)
        r = c.sdo_read(5, 0x1018, 1)
        self.assertTrue(r["success"])
        self.assertEqual(diag.parse_hex(r["data"]), struct.pack("<I", 0x360))
        r = c.sdo_read(5, 0x1008, 0)
        self.assertEqual(diag.parse_hex(r["data"]), b"fake device")
        r = c.sdo_read(5, 0x2001, 0)
        self.assertEqual(diag.parse_hex(r["data"]), bytes(range(40)))
        self.assertTrue(c.sdo_write(5, 0x2000, 1, b"\x33\x44")["success"])
        self.assertEqual(diag.parse_hex(c.sdo_read(5, 0x2000, 1)["data"]), b"\x33\x44")
        long = bytes(range(100, 130))
        self.assertTrue(c.sdo_write(5, 0x2001, 0, long)["success"])
        self.assertEqual(self.devices[0].od[(0x2001, 0)], long)

    def test_segmented_size_mismatch_aborts(self):
        # The data must match the size the server indicated (bug hunt PC lows).
        d = self.device(5, od={(0x2001, 0): bytes(range(40))})
        c = self.client()
        send = d.send
        for indicated in (43, 37):
            d.send = lambda cob, data, n=indicated: send(cob, (data[:4] + struct.pack("<I", n)) if data[0] == 0x41
                                                         else data)
            r = c.sdo_read(5, 0x2001, 0)
            self.assertFalse(r["success"])
            self.assertEqual(r["abort_code"], 0x06070010)
            self.assertIn("40 bytes for an indicated size of %d" % indicated, r["error"])

    def test_expedited_write_is_one_request(self):
        self.device(5, od={(0x2000, 1): b"\x11\x22"})
        c = self.client(allow_changes=True)
        c.sdo_read(5, 0x1018, 1)  # past the listen window
        watch = can.Bus(interface="virtual", channel=self.ch, receive_own_messages=False)
        try:
            self.assertTrue(c.sdo_write(5, 0x2000, 1, b"\x33\x44")["success"])
            time.sleep(0.2)
            sent = []
            while True:
                m = watch.recv(0)
                if m is None:
                    break
                if m.arbitration_id == 0x605:
                    sent.append(bytes(m.data))
        finally:
            watch.shutdown()
        self.assertEqual([d[0] for d in sent], [0x2B])  # expedited, 2 bytes; no segmented download after it

    def test_abort_and_timeout(self):
        self.device(5)
        c = self.client(allow_changes=True)
        r = c.sdo_read(5, 0x3000, 0)
        self.assertFalse(r["success"])
        self.assertEqual(r["abort_code"], 0x06020000)
        self.assertEqual(r["abort_code_hex"], "0x06020000")
        r = c.sdo_write(5, 0x1018, 1, b"\0\0\0\0")
        self.assertEqual(r["abort_code"], 0x06010002)
        r = c.sdo_read(9, 0x1018, 1, timeout_ms=50)
        self.assertEqual((r["success"], r["error"]), (False, "timeout"))

    def test_changes_gated(self):
        d = self.device(5)
        c = self.client()
        self.assertTrue(c.sdo_read(5, 0x1018, 1)["success"])
        for call in (lambda: c.sdo_write(5, 0x1010, 1, b"save"), lambda: c.nmt(5, "stop"),
                     lambda: c.lss_find(True), lambda: c.lss_inquire((1, 2, 3, 4))):
            with self.assertRaises(diag.DiagError) as e:
                call()
            self.assertIn("changes not allowed", str(e.exception))
        time.sleep(0.1)
        self.assertEqual(d.nmt_log, [])
        self.assertEqual(d.stored, [])

    def test_foreign_sdo_waits(self):
        self.device(5)
        peer = Peer(self.ch)
        try:
            c = self.client()
            # Timed from the peer's request: the tool holds off until
            # FOREIGN_SDO_S after it saw it, however long the sleep took.
            t = time.monotonic()
            peer.send(0x605, b"\x40\x00\x10\x00\0\0\0\0")
            time.sleep(0.05)
            self.assertTrue(c.sdo_read(5, 0x1018, 1)["success"])
            self.assertGreaterEqual(time.monotonic() - t, core_mod.FOREIGN_SDO_S)
        finally:
            peer.close()


    def test_foreign_answer_while_listening(self):
        # Another master reads the node while the tool still listens: its
        # answer must not be taken for the answer to the tool's first request.
        self.device(5)
        peer = Peer(self.ch)
        try:
            c = LocalBus(parse("virtual:" + self.ch), 250000, listen_s=0.4)
            c.connect()
            self.clients.append(c)
            out = {}
            t = threading.Thread(target=lambda: out.update(r=c.sdo_read(5, 0x1018, 1)))
            t.start()
            time.sleep(0.1)
            peer.send(0x605, b"\x40\x18\x10\x04\0\0\0\0")
            t.join(5)
            self.assertTrue(out["r"]["success"], out["r"])
            self.assertEqual(diag.parse_hex(out["r"]["data"]), struct.pack("<I", 0x360))
        finally:
            peer.close()

    def test_foreign_answer_during_request(self):
        # Another master's transfer to the same node is answered while the
        # tool waits: the tool skips that answer (and an abort for it) and
        # takes its own, without aborting anything.
        import can
        bus = can.Bus(interface="virtual", channel=self.ch, receive_own_messages=False)
        seen = []

        def node():
            while True:
                msg = bus.recv(2)
                if msg is None:
                    return
                seen.append(bytes(msg.data))
                if msg.arbitration_id == 0x605 and msg.data[0] == 0x40:
                    bus.send(can.Message(arbitration_id=0x585, data=b"\x43\x18\x10\x04\x34\x12\0\0",
                                         is_extended_id=False))
                    bus.send(can.Message(arbitration_id=0x585, data=b"\x80\x00\x10\x00\x00\x00\x02\x06",
                                         is_extended_id=False))
                    bus.send(can.Message(arbitration_id=0x585, data=b"\x43" + bytes(msg.data[1:4]) + b"\x60\x03\0\0",
                                         is_extended_id=False))
                    return

        t = threading.Thread(target=node)
        t.start()
        try:
            c = self.client()
            r = c.sdo_read(5, 0x1018, 1)
            t.join(5)
            self.assertTrue(r["success"], r)
            self.assertEqual(diag.parse_hex(r["data"]), struct.pack("<I", 0x360))
            time.sleep(0.1)
            self.assertEqual([d for d in seen if d[0] == 0x80], [])
        finally:
            bus.shutdown()


class StatusAndEmcy(Base):
    def test_heartbeat_and_emcy(self):
        d = self.device(5, heartbeat_s=0.05)
        c = self.client(config={7: {"name": "valve"}})
        time.sleep(0.2)
        d.emcy(0x5000, 0x81, b"\1\2\3\4\5")
        time.sleep(0.1)
        st = c.status()
        self.assertTrue(st["local"])
        self.assertFalse(st["other_master"])
        nodes = {n["node_id"]: n for n in st["nodes"]}
        self.assertEqual(nodes[5]["state"], 127)
        self.assertLess(nodes[5]["last_heard_s"], 1)
        self.assertEqual(nodes[5]["emcy"], {"code": 0x5000, "error_register": 0x81, "count": 1})
        self.assertEqual(nodes[7]["name"], "valve")
        self.assertIsNone(nodes[7]["state"])
        e = c.emcy(5)["emcy"][0]
        self.assertEqual((e["code"], e["error_register"], e["manufacturer"]), (0x5000, 0x81, "01 02 03 04 05"))

    def test_hello(self):
        c = self.client()
        self.assertTrue(c.info["local"])
        self.assertFalse(c.info["allow_changes"])
        self.assertEqual(c.info["networks"][0]["role"], "local")

    def test_other_master(self):
        self.device(None)
        peer = Peer(self.ch)
        try:
            c = self.client(allow_changes=True)
            peer.send(0x080, b"")
            time.sleep(0.1)
            st = c.status()
            self.assertTrue(st["other_master"])
            self.assertEqual(st["other_master_seen"]["what"], "SYNC")
            with self.assertRaises(diag.DiagError) as e:
                c.lss_find(True)
            self.assertIn("another master", str(e.exception))
            c.force = True
            self.assertIn("running", c.lss_find(True))
        finally:
            peer.close()

    def test_not_local(self):
        c = self.client()
        with self.assertRaises(diag.DiagError) as e:
            c.request("sim_status")
        self.assertEqual(str(e.exception), client_mod.NOT_LOCAL)


class NmtAndScan(Base):
    def test_nmt_one_node(self):
        d = self.device(5)
        c = self.client(allow_changes=True)
        c.nmt(5, "stop")
        c.nmt(5, "start")
        time.sleep(0.1)
        self.assertEqual(d.nmt_log, [2, 1])
        self.assertEqual(d.state, 5)

    def test_scan(self):
        self.device(3, identity=(0xAB, 0x1234, 1, 99), name="sensor")
        self.device(40, identity=(0xAB, 0x99, 2, 7))
        c = self.client(config={3: {"name": "s", "expect": {"vendor_id": 0xAB, "product_code": 0x1234}},
                                40: {"name": "other", "expect": {"product_code": 0x1}},
                                50: {"name": "missing"}})
        res = c.scan(True)
        while res["running"]:
            time.sleep(0.1)
            res = c.scan(False)
        self.assertEqual(res["total"], 127)
        nodes = {n["node_id"]: n for n in res["nodes"]}
        self.assertEqual(sorted(nodes), [3, 40, 50])
        self.assertEqual(nodes[3]["match"], "configured")
        self.assertEqual(nodes[3]["device_name"], "sensor")
        self.assertEqual(nodes[3]["serial_number"], 99)
        self.assertEqual(nodes[3]["device_type"], 0x00020191)
        self.assertEqual(nodes[40]["match"], "configured, different device")
        self.assertIn("product code", nodes[40]["differs"])
        self.assertEqual(nodes[50]["match"], "configured, no answer")


class Force(Base):
    """The plugin's rule on a local adapter: SDO writes and NMT other than
    start to a node heard OPERATIONAL, and a scan while one is, need force."""

    def test_running_node_needs_force(self):
        d = self.device(5, heartbeat_s=0.05)
        c = self.client(allow_changes=True)
        c.nmt(5, "start")  # never needs force
        time.sleep(0.3)
        for call in (lambda: c.nmt(5, "stop"), lambda: c.sdo_write(5, 0x2000, 0, b"\1"), lambda: c.scan(True)):
            with self.assertRaises(diag.DiagError) as e:
                call()
            self.assertTrue(diag.needs_force(e.exception), str(e.exception))
            self.assertTrue(str(e.exception).startswith("node 5 is OPERATIONAL; "), str(e.exception))
        self.assertEqual(d.nmt_log, [1])
        with self.assertRaises(diag.DiagError) as e:
            c.request("nmt", node=5, command="stop", force=1)
        self.assertIn("field 'force' must be true or false", str(e.exception))
        c.nmt(5, "stop", force=True)
        time.sleep(0.1)
        self.assertEqual(d.nmt_log, [1, 2])

    def test_other_master_or_running_node_needs_force(self):
        # Node 5 runs without a heartbeat the adapter heard (a slow one, or
        # node guarding); a PLC sends SYNC (bug hunt PC-H2).
        d = self.device(5, nmt_state=5)
        peer = Peer(self.ch)
        self.addCleanup(peer.close)
        c = self.client(allow_changes=True)
        peer.send(0x80, b"")
        time.sleep(0.1)
        self.assertTrue(c.status()["other_master"])
        for call, end in ((lambda: c.nmt(5, "stop"), "node 5 may be under its control"),
                          (lambda: c.sdo_write(5, 0x2000, 0, b"\1"), "node 5 may be under its control"),
                          (lambda: c.scan(True), "a scan sends SDO requests to every node ID")):
            with self.assertRaises(diag.DiagError) as e:
                call()
            self.assertTrue(diag.needs_force(e.exception), str(e.exception))
            self.assertTrue(str(e.exception).startswith("another master is active on this bus (SYNC, last at "),
                            str(e.exception))
            self.assertIn(end, str(e.exception))
        self.assertTrue(c.sdo_read(5, 0x1018, 1)["success"])
        c.nmt(5, "start")
        c.sdo_write(5, 0x2000, 0, b"\1", force=True)
        time.sleep(0.1)
        self.assertEqual(d.nmt_log, [1])
        # Without another master, any node heard OPERATIONAL counts.
        self.ch = channel()
        self.device(7, heartbeat_s=0.05, nmt_state=5)
        self.device(6)
        c = self.client(allow_changes=True)
        time.sleep(0.2)
        with self.assertRaises(diag.DiagError) as e:
            c.sdo_write(6, 0x2000, 0, b"\1")
        self.assertEqual(str(e.exception), "node 7 is OPERATIONAL; a program may drive node 6 too; force needed")

    def test_running_node_and_other_master_both_named(self):
        # The hardware run of 9.2: node 23 heard OPERATIONAL and the PLC's
        # SYNC on the bus; the refusal names both.
        self.device(5, heartbeat_s=0.05, nmt_state=5)
        peer = Peer(self.ch)
        self.addCleanup(peer.close)
        c = self.client(allow_changes=True)
        peer.send(0x80, b"")
        time.sleep(0.3)
        for call in (lambda: c.nmt(5, "stop"), lambda: c.sdo_write(5, 0x2000, 0, b"\1")):
            with self.assertRaises(diag.DiagError) as e:
                call()
            self.assertTrue(diag.needs_force(e.exception), str(e.exception))
            self.assertTrue(str(e.exception).startswith(
                "node 5 is OPERATIONAL; another master is active on this bus (SYNC, last at "), str(e.exception))

    def test_no_bit_rate_detection(self):
        c = self.client(allow_changes=True)
        for op in ("detect_bitrate", "detect_bitrate_status", "detect_bitrate_stop"):
            with self.assertRaises(diag.DiagError) as e:
                c.request(op)
            self.assertIn("not available on a local adapter", str(e.exception))

    def test_session_force(self):
        d = self.device(5, heartbeat_s=0.05)
        c = self.client(allow_changes=True, force=True)
        c.nmt(5, "start")
        time.sleep(0.3)
        c.nmt(5, "preop")
        time.sleep(0.1)
        self.assertEqual(d.nmt_log, [1, 0x80])


class Lss(Base):
    def address(self, d):
        return d.identity

    def test_find_and_set(self):
        d = self.device(None, identity=(0x360, 0x1, 0x2, 0xBEEF))
        c = self.client(allow_changes=True)
        res = c.lss_find(True)
        while res["running"]:
            time.sleep(0.1)
            res = c.lss_find(False)
        self.assertTrue(res["found"], res)
        self.assertEqual(tuple(res["device"][k] for k in diag.LSS_KEYS), d.identity)
        self.assertEqual(res["device"]["node_id"], 255)
        r = c.lss_inquire(d.identity)
        self.assertEqual(r, {"node_id": 255, "configured": False})
        r = c.lss_set_id(d.identity, 12)
        self.assertEqual((r["node_id"], r["had_node_id"], r["stored"]), (12, False, False))
        self.assertNotIn("lss", d.stored)
        self.assertEqual(d.node, 12)
        r = c.lss_set_bitrate(d.identity, 125, store=True)
        self.assertTrue(r["stored"])
        self.assertEqual(d.bit_timing, 4)
        self.assertIn("lss", d.stored)

    def test_find_with_vendor(self):
        d = self.device(None, identity=(0x360, 0x7, 0x2, 0x55))
        # One answer that does not come in time reads as a 1 bit and spoils
        # the address: the search starts over and still finds the device.
        send, answers = d.send, []

        def lossy(cob, data):
            if cob == 0x7E4 and data[:1] == b"\x4f":
                answers.append(data)
                if len(answers) == 3:  # a bit probe of the revision number
                    return
            send(cob, data)
        d.send = lossy
        c = self.client(allow_changes=True)
        res = c.lss_find(True, 0x360, 0x7)
        while res["running"]:
            time.sleep(0.05)
            res = c.lss_find(False)
        self.assertEqual(res["device"]["serial_number"], 0x55)
        self.assertTrue(res["found"])
        del d

    def test_none_found(self):
        c = self.client(allow_changes=True)
        res = c.lss_find(True)
        while res["running"]:
            time.sleep(0.05)
            res = c.lss_find(False)
        self.assertFalse(res["found"])
        with self.assertRaises(diag.DiagError) as e:
            c.lss_inquire((1, 2, 3, 4))
        self.assertIn("not found", str(e.exception))

    def test_id_in_use(self):
        self.device(12, heartbeat_s=0.05)
        d = self.device(None, identity=(1, 2, 3, 4))
        c = self.client(allow_changes=True)
        time.sleep(0.2)
        with self.assertRaises(diag.DiagError) as e:
            c.lss_set_id(d.identity, 12)
        self.assertIn("in use", str(e.exception))


class Trace(Base):
    def test_records(self):
        d = self.device(5, heartbeat_s=0.05)
        c = self.client(allow_changes=True)
        r = c.trace_start([(0x700, 0x780), (0x600, 0x780), (0x580, 0x780)])
        self.assertEqual(r["record_size"], RECORD_SIZE)
        c.sdo_read(5, 0x1018, 1)
        time.sleep(0.2)
        f = c.trace_fetch(r["next"])
        data = base64.b64decode(f["frames"])
        frames = [Frame.unpack(data, i) for i in range(0, len(data), RECORD_SIZE)]
        ids = [fr.can_id for fr in frames]
        self.assertIn(0x705, ids)
        tx = [fr for fr in frames if fr.tx]
        self.assertEqual([fr.can_id for fr in tx], [0x605])
        self.assertIn(0x585, ids)
        self.assertTrue(all(abs(fr.time_us / 1e6 - time.time()) < 5 for fr in frames))
        c.trace_stop()
        with self.assertRaises(diag.DiagError):
            c.trace_fetch(0)
        del d


def cli(*argv):
    """canworks-diag with its exit status, stdout and stderr."""
    out, err = io.StringIO(), io.StringIO()
    with redirect_stderr(err), mock.patch.object(core_mod, "LISTEN_S", 0.05):
        try:
            args = diag.parser().parse_args(list(argv))
            code = diag.run(args, out)
        except diag.DiagError as e:
            err.write("canworks-diag: %s\n" % e)
            code = 2 if e.kind == "usage" else 1
        except SystemExit as e:
            code = e.code
    return code, out.getvalue(), err.getvalue()


class Cli(Base):
    def adapter(self):
        return ["--adapter", "virtual:" + self.ch]

    def test_status_and_sdo(self):
        self.device(5, heartbeat_s=0.05)
        code, out, err = cli(*self.adapter(), "--bitrate", "250", "sdo-read", "5", "0x1018", "1",
                             "--type", "UNSIGNED32")
        self.assertEqual(code, 0, err)
        self.assertIn("864", out)  # 0x360
        code, out, err = cli(*self.adapter(), "--bitrate", "250", "status")
        self.assertEqual(code, 0, err)
        self.assertIn("read-only", out)

    def test_no_bitrate(self):
        code, out, err = cli(*self.adapter(), "scan")
        self.assertEqual(code, 2)
        self.assertIn("--bitrate", err)

    def test_both_targets(self):
        code, out, err = cli(*self.adapter(), "--runtime", "plc.local", "--bitrate", "250", "status")
        self.assertEqual(code, 2)
        self.assertIn("not both", err)

    def test_sim_needs_runtime(self):
        code, out, err = cli(*self.adapter(), "sim", "status")
        self.assertEqual(code, 2)
        self.assertIn("need a runtime", err)

    def test_changes_need_switch(self):
        d = self.device(5)
        code, out, err = cli(*self.adapter(), "--bitrate", "250", "nmt", "5", "stop")
        self.assertEqual(code, 1)
        self.assertIn("--allow-changes", err)
        code, out, err = cli(*self.adapter(), "--bitrate", "250", "--allow-changes", "nmt", "5", "stop")
        self.assertEqual(code, 0, err)
        time.sleep(0.1)
        self.assertEqual(d.nmt_log, [2])

    def test_bitrate_from_config(self):
        self.device(2, identity=(0x360, 0x1, 0, 0))
        cfg = os.path.join(REPO, "config", "pingpong", "canopen_config.json")
        code, out, err = cli(*self.adapter(), "scan", "--config", cfg)
        self.assertEqual(code, 0, err)
        self.assertIn("node   2", out)

    def test_backup(self):
        self.device(2, od={(0x1017, 0): b"\x00\x00"})
        eds = os.path.join(REPO, "config", "pingpong", "cpp-slave.eds")
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "n2.dcf")
            code, out, err = cli(*self.adapter(), "--bitrate", "250", "backup", "2", "--eds", eds, "-o", path)
            self.assertEqual(code, 0, err)
            with open(path, encoding="utf-8") as f:
                text = f.read()
        self.assertIn("[DeviceComissioning]", text)
        self.assertIn("NodeID=2", text)

    def test_trace(self):
        self.device(5, heartbeat_s=0.05)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "t.log")
            code, out, err = cli(*self.adapter(), "--bitrate", "250", "trace", "-o", path, "--duration", "0.6")
            self.assertEqual(code, 0, err)
            with open(path, encoding="utf-8") as f:
                self.assertIn("705#7F", f.read())

    def test_adapters(self):
        code, out, err = cli("--json", "adapters")
        self.assertEqual(code, 0, err)
        self.assertIsInstance(json.loads(out), list)



class AdapterList(unittest.TestCase):
    def _usb(self, ids, platform="darwin"):
        """_usb_adapters() and gs_usb:N opens on a gs_usb package whose scan
        finds `ids` [(vid, pid)], at USB bus 1, addresses 3, 4, ..."""
        from types import ModuleType, SimpleNamespace
        from canworks.localbus import adapter as adapter_mod

        class GsUsb:
            def __init__(self, k, vid, pid):
                self.bus, self.address = 1, 3 + k
                self.gs_usb = SimpleNamespace(idVendor=vid, idProduct=pid)

            @classmethod
            def scan(cls):
                return [GsUsb(k, v, p) for k, (v, p) in enumerate(ids)]

            def start(self, flags=0):
                pass

        pkg, mod = ModuleType("gs_usb"), ModuleType("gs_usb.gs_usb")
        mod.GsUsb = pkg.gs_usb = GsUsb
        with mock.patch.dict("sys.modules", {"gs_usb": pkg, "gs_usb.gs_usb": mod}), \
                mock.patch.object(adapter_mod.sys, "platform", platform):
            found = adapter_mod._usb_adapters()
            opened = {}
            for a in found:
                kwargs = {}
                adapter_mod._gs_usb_options(parse("gs_usb:" + a["channel"]), kwargs)
                opened[a["channel"]] = (kwargs["bus"], kwargs["address"])
            return found, opened

    def test_gs_usb_listed_as_opened(self):
        # The listing is the gs_usb package's own scan, so gs_usb:N opens the
        # adapter listed as N, also for USB IDs other than 1D50:606F (bug
        # hunt PC-M5).
        found, opened = self._usb([(0x1209, 0x2323), (0x1D50, 0x606F)])
        self.assertEqual([(a["type"], a["channel"], a["usb_id"], a["usb_bus"], a["usb_address"]) for a in found],
                         [("gs_usb", "0", "1209:2323", 1, 3), ("gs_usb", "1", "1D50:606F", 1, 4)])
        self.assertEqual(opened, {"0": (1, 3), "1": (1, 4)})
        self.assertIn("candleLight", found[1]["known"])
        self.assertIn("bus 1 address 3", found[0]["description"])

    def test_gs_usb_not_on_linux(self):
        self.assertEqual(self._usb([(0x1D50, 0x606F)], platform="linux")[0], [])  # a SocketCAN link there

    def test_no_pyusb(self):
        from canworks.localbus import adapter as adapter_mod
        with mock.patch.dict("sys.modules", {"usb": None, "usb.core": None}), \
                mock.patch.object(adapter_mod.sys, "platform", "win32"):
            self.assertEqual(adapter_mod._usb_adapters(), [])

    def test_gs_usb_mode_and_close(self):
        # The check leaves listen-only on the open USB handle (reset mode,
        # then start with the new flags: no USB reset), and closing puts the
        # channel in reset mode before letting go of the interface.
        from types import ModuleType, SimpleNamespace
        from canworks.localbus import adapter as adapter_mod

        calls = []

        class Usb:
            def ctrl_transfer(self, *args):
                calls.append(("mode", args[1], args[4]))

            def reset(self):
                calls.append(("usb reset",))

        class Dev:
            device_capability = SimpleNamespace(fclk_can=48000000, feature=0xFFFF)
            device_flags = 0x10

            def __init__(self):
                self.gs_usb = Usb()

        class DeviceMode:
            def __init__(self, mode, flags):
                self.mode, self.flags = mode, flags

            def pack(self):
                return (self.mode, self.flags)

        class Bus:
            def __init__(self):
                self.gs_usb = Dev()

            def shutdown(self):
                calls.append(("shutdown",))

        structs = ModuleType("gs_usb.gs_usb_structures")
        structs.DeviceMode = DeviceMode
        usb, util = ModuleType("usb"), ModuleType("usb.util")
        util.dispose_resources = lambda dev: calls.append(("dispose", dev))
        usb.util = util
        bus = Bus()
        lock = mock.Mock()
        opened = adapter_mod.Opened(parse("gs_usb:0"), bus, 250000, lock, listen_only=True)
        self.assertTrue(opened.echoes)
        self.assertEqual(opened.confirm, adapter_mod.CONFIRM_ECHO)
        with mock.patch.dict("sys.modules", {"gs_usb.gs_usb_structures": structs, "usb": usb, "usb.util": util}):
            opened.set_mode(listen_only=False, one_shot=True)
            self.assertEqual(calls, [("mode", 2, (0, 0)), ("mode", 2, (1, 0x10 | 0x1000 | 0x08))])
            self.assertFalse(opened.listen_only)
            del calls[:]
            opened.close()
            opened.close()  # once only
        self.assertEqual(calls, [("mode", 2, (0, 0)), ("shutdown",), ("dispose", bus.gs_usb.gs_usb)])
        lock.release.assert_called_once_with()

    def test_gs_usb_timing(self):
        from types import SimpleNamespace
        from canworks.localbus import adapter as adapter_mod
        cap = SimpleNamespace(fclk_can=48000000, tseg1_min=1, tseg1_max=16, tseg2_min=1, tseg2_max=8, sjw_max=4,
                              brp_min=1, brp_max=1024, brp_inc=1)
        for kbit in (10, 20, 50, 125, 250, 500, 800, 1000):
            prop, ph1, ph2, sjw, brp = adapter_mod.gs_usb_timing(cap, kbit * 1000)
            nbt = 1 + prop + ph1 + ph2
            self.assertEqual(48000000 // (brp * nbt), kbit * 1000)
            self.assertGreaterEqual((nbt - ph2) * 100.0 / nbt, 75.0)
        # A fast clock needs a large prescaler at 50 kbit/s (python-can's own stops at 64).
        fast = SimpleNamespace(**dict(vars(cap), fclk_can=170000000))
        self.assertIsNotNone(adapter_mod.gs_usb_timing(fast, 50000))
        self.assertIsNone(adapter_mod.gs_usb_timing(SimpleNamespace(**dict(vars(cap), brp_max=4)), 10000))

    def test_gs_usb_open_outside_linux(self):
        # Opened by USB bus and address (so closing does not start the adapter
        # again), and its start does not try to detach a kernel driver.
        from types import ModuleType, SimpleNamespace
        from canworks.localbus import adapter as adapter_mod

        class Dev:
            def is_kernel_driver_active(self, interface):
                return True  # what macOS libusb says after the USB reset

            def detach_kernel_driver(self, interface):
                raise OSError("Access denied")

        class GsUsb:
            def __init__(self, bus, address):
                self.bus, self.address, self.gs_usb = bus, address, Dev()

            @classmethod
            def scan(cls):
                return [GsUsb(1, 4), GsUsb(2, 7)]

            def start(self, flags=0):
                if self.gs_usb.is_kernel_driver_active(0):
                    self.gs_usb.detach_kernel_driver(0)
                return "started"

        pkg, mod = ModuleType("gs_usb"), ModuleType("gs_usb.gs_usb")
        mod.GsUsb = pkg.gs_usb = GsUsb
        with mock.patch.dict("sys.modules", {"gs_usb": pkg, "gs_usb.gs_usb": mod}), \
                mock.patch.object(adapter_mod.sys, "platform", "darwin"):
            kwargs = {}
            adapter_mod._gs_usb_options(parse("gs_usb:1"), kwargs)
            self.assertEqual(kwargs, {"bus": 2, "address": 7})
            dev = GsUsb(1, 4)
            self.assertEqual(dev.start(), "started")
            self.assertTrue(dev.gs_usb.is_kernel_driver_active(0))  # put back after the start
            with self.assertRaises(AdapterError) as e:
                adapter_mod._gs_usb_options(parse("gs_usb:2"), {})
            self.assertEqual(e.exception.kind, "unreachable")
            with self.assertRaises(AdapterError) as e:
                adapter_mod._gs_usb_options(parse("gs_usb:first"), {})
            self.assertEqual(e.exception.kind, "usage")

    def test_gs_usb_drain_throws_away_an_earlier_connections_frames(self):
        # Frames the adapter still holds from the last connection (a refused
        # rate's error frames, a backlog) are read and dropped before the
        # channel starts; the read timeout ends it.
        from types import SimpleNamespace
        from canworks.localbus import adapter as adapter_mod
        left = [b"stale"] * 3
        reads = []

        def read(endpoint, size, timeout):
            reads.append((endpoint, timeout))
            if not left:
                raise OSError("timeout")
            return left.pop()

        adapter_mod._gs_usb_drain(SimpleNamespace(gs_usb=SimpleNamespace(read=read)))
        self.assertEqual(len(reads), 4)
        self.assertEqual(reads[0][0], 0x81)
        adapter_mod._gs_usb_drain(SimpleNamespace(gs_usb=None))  # never raises

    def test_libusb_dll_on_the_path_on_windows(self):
        import os
        import tempfile
        from types import SimpleNamespace
        from canworks.localbus import adapter as adapter_mod
        pkg = tempfile.mkdtemp()
        dll_dir = os.path.join(pkg, "_platform", "windows", "x86_64")
        os.makedirs(dll_dir)
        open(os.path.join(dll_dir, "libusb-1.0.dll"), "wb").close()
        spec = SimpleNamespace(submodule_search_locations=[pkg])
        with mock.patch.object(adapter_mod.sys, "platform", "win32"), \
                mock.patch("importlib.util.find_spec", return_value=spec), \
                mock.patch("platform.machine", return_value="AMD64"), \
                mock.patch.dict(os.environ, {"PATH": "x"}), \
                mock.patch.object(adapter_mod._libusb_path, "done", False, create=True):
            adapter_mod._libusb_path()
            self.assertEqual(os.environ["PATH"], dll_dir + os.pathsep + "x")
            adapter_mod._libusb_path()  # once per process
            self.assertEqual(os.environ["PATH"], dll_dir + os.pathsep + "x")

if __name__ == "__main__":
    unittest.main()
