"""The local bus backend (canopen-local-bus) on python-can's virtual bus,
against fake devices. Runs on every PC tools runner: no CAN hardware."""

import base64
import itertools
import struct
import time
import unittest

from openplc_canopen_deploy import diag
from openplc_canopen_deploy.bustrace.model import RECORD_SIZE, Frame
from openplc_canopen_deploy.localbus import AdapterError, LocalBus, parse
from openplc_canopen_deploy.localbus import client as client_mod

from .fake_canopen import FakeDevice, Peer

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
        from openplc_canopen_deploy.localbus import adapter
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
            peer.send(0x605, b"\x40\x00\x10\x00\0\0\0\0")
            time.sleep(0.05)
            t = time.monotonic()
            self.assertTrue(c.sdo_read(5, 0x1018, 1)["success"])
            self.assertGreaterEqual(time.monotonic() - t, 0.1)
        finally:
            peer.close()


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


if __name__ == "__main__":
    unittest.main()
