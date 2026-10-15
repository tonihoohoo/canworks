"""The bit rate check on connect, bus errors ending the connection, adapters
that echo their frames, and stopping a scan (canopen-local-bus), on
python-can's virtual bus with fake devices and a peer that sends error
frames as a controller at another bit rate would see them."""

import threading
import time
import unittest
from unittest import mock

import can

from canworks import diag
from canworks.localbus import LocalBus, parse
from canworks.localbus import adapter as adapter_mod
from canworks.localbus import core as core_mod

from .fake_canopen import FakeDevice, Peer
from .test_localbus import channel

ERR_ACK = 0x020
ERR_PROT = 0x008


def error_frame(ident=ERR_PROT, data=b"\0\0\x02\0\0\0\0\0"):
    return can.Message(arbitration_id=ident, data=data, is_error_frame=True, is_extended_id=False)


class Case(unittest.TestCase):
    def setUp(self):
        self.ch = channel()
        self.closers = []

    def tearDown(self):
        for c in reversed(self.closers):
            c()

    def device(self, node, **kw):
        d = FakeDevice(self.ch, node, **kw)
        self.closers.append(d.close)
        return d

    def peer(self):
        p = Peer(self.ch)
        self.closers.append(p.close)
        return p

    def client(self, echo=False, listen_s=0.2, **kw):
        spec = parse("virtual:" + self.ch, ["receive_own_messages=true"] if echo else [])
        c = LocalBus(spec, 250000, listen_s=listen_s, **kw)
        self.closers.append(c.close)
        c.connect()
        return c

    def noisy(self, peer, every=0.02, frame=None):
        """The peer sends error frames until the test ends."""
        stop = threading.Event()

        def run():
            while not stop.is_set():
                peer.bus.send(frame or error_frame())
                time.sleep(every)

        t = threading.Thread(target=run, daemon=True)
        t.start()
        self.closers.insert(0, lambda: (stop.set(), t.join(1)))


class Check(Case):
    def test_busy_bus_confirmed_without_sending(self):
        self.device(5, heartbeat_s=0.05)
        p = self.peer()
        c = self.client()
        self.assertEqual(c.info["bitrate_check"], {"result": "confirmed", "how": "traffic", "bitrate_kbit": 250})
        self.assertEqual(c.status()["bitrate_check"]["how"], "traffic")
        sent = []
        while True:
            m = p.bus.recv(0.05)
            if m is None:
                break
            if m.arbitration_id != 0x705:
                sent.append(m)
        self.assertEqual(sent, [])  # nothing from the PC

    def test_errors_refuse_the_rate(self):
        self.noisy(self.peer())
        with self.assertRaises(diag.DiagError) as e:
            self.client()
        self.assertEqual(e.exception.kind, "bitrate")
        self.assertIn("the bus does not run at 250 kbit/s", str(e.exception))
        # The adapter was closed: it opens again at once.
        opened = adapter_mod.open(parse("virtual:" + self.ch), 250000)
        opened.close()

    def test_silent_bus_probe(self):
        p = self.peer()
        c = self.client()
        self.assertEqual(c.info["bitrate_check"]["how"], "probe acknowledged")
        m = p.bus.recv(0.5)
        self.assertEqual((m.arbitration_id, bytes(m.data)), (0x7E5, bytes([0x5E]) + bytes(7)))
        self.assertIsNone(p.bus.recv(0.1))  # sent once

    def test_silent_bus_probe_with_echo(self):
        c = self.client(echo=True)
        self.assertEqual(c.info["bitrate_check"]["how"], "probe acknowledged")

    def test_probe_not_acknowledged(self):
        p = self.peer()

        def ack_errors():
            m = p.bus.recv(2)
            if m is not None and m.arbitration_id == 0x7E5:
                p.bus.send(error_frame(ERR_ACK, bytes(8)))

        t = threading.Thread(target=ack_errors, daemon=True)
        t.start()
        with self.assertRaises(diag.DiagError) as e:
            self.client()
        t.join(2)
        self.assertIn("no device acknowledged at 250 kbit/s", str(e.exception))

    def test_probe_meets_bit_errors(self):
        p = self.peer()

        def bit_errors():
            m = p.bus.recv(2)
            if m is not None and m.arbitration_id == 0x7E5:
                p.bus.send(error_frame())

        t = threading.Thread(target=bit_errors, daemon=True)
        t.start()
        with self.assertRaises(diag.DiagError) as e:
            self.client()
        t.join(2)
        self.assertIn("the bus does not run at 250 kbit/s", str(e.exception))

    def unconfirmable(self):
        real = adapter_mod.open

        def opener(*a, **kw):
            o = real(*a, **kw)
            o.confirm = None  # as slcan: cannot tell whether a frame got out
            return o
        return mock.patch.object(core_mod.adapter_mod, "open", opener)

    def test_adapter_without_confirmation_needs_a_node(self):
        p = self.peer()
        with self.unconfirmable():
            with self.assertRaises(diag.DiagError) as e:
                self.client()
        self.assertIn("--check-node", str(e.exception))
        self.assertIsNone(p.bus.recv(0.1))  # nothing sent

    def test_check_node_answers(self):
        self.device(5)
        with self.unconfirmable():
            c = self.client(check_node=5)
        self.assertEqual(c.info["bitrate_check"]["how"], "node 5 answered")

    def test_check_node_silent(self):
        self.device(5)
        with self.unconfirmable():
            with self.assertRaises(diag.DiagError) as e:
                self.client(check_node=6)
        self.assertIn("node 6 did not answer at 250 kbit/s", str(e.exception))

    def test_cli_check_node(self):
        self.device(5)
        from .test_localbus import cli
        with self.unconfirmable(), mock.patch.object(core_mod, "LISTEN_S", 0.05):
            code, out, err = cli("--adapter", "virtual:" + self.ch, "--bitrate", "250", "--check-node", "5",
                                 "sdo-read", "5", "0x1018", "1")
        self.assertEqual(code, 0, err)


class BusErrors(Case):
    def test_error_burst_ends_the_connection(self):
        p = self.peer()
        c = self.client()
        for _ in range(core_mod.ERROR_BURST):
            p.bus.send(error_frame())
        time.sleep(0.3)
        with self.assertRaises(diag.DiagError) as e:
            c.status()
        self.assertEqual(e.exception.kind, "eof")
        self.assertIn("connection ended", str(e.exception))
        # A new connection checks again.
        c.close()
        c2 = self.client()
        self.assertEqual(c2.info["bitrate_check"]["result"], "confirmed")

    def test_bus_off_ends_the_connection(self):
        p = self.peer()
        c = self.client()
        p.bus.send(error_frame(0x040, bytes(8)))
        time.sleep(0.3)
        with self.assertRaises(diag.DiagError) as e:
            c.status()
        self.assertIn("bus-off", str(e.exception))

    def test_some_errors_with_traffic_go_on(self):
        self.device(5, heartbeat_s=0.02)
        p = self.peer()
        c = self.client()
        for _ in range(3):
            p.bus.send(error_frame())
        time.sleep(0.2)
        self.assertTrue(c.status()["session"])


class Echoes(Case):
    def test_own_requests_are_not_another_master(self):
        self.device(23)
        c = self.client(echo=True, allow_changes=True)
        r = c.trace_start()
        self.assertTrue(c.sdo_read(23, 0x1018, 1)["success"])
        c.sdo_write(23, 0x1010, 1, b"\0\0\0\0")
        st = c.status()
        self.assertFalse(st["other_master"], st["other_master_seen"])
        from canworks.bustrace.model import RECORD_SIZE, Frame
        import base64
        data = base64.b64decode(c.trace_fetch(r["next"])["frames"])
        frames = [Frame.unpack(data, i) for i in range(0, len(data), RECORD_SIZE)]
        requests = [f for f in frames if f.can_id == 0x617]
        self.assertEqual(len(requests), 2)  # each once
        self.assertTrue(all(f.tx for f in requests))

    def test_missing_echo_ends_the_connection(self):
        self.device(23)
        c = self.client(echo=True)
        with mock.patch.object(c.core.bus, "send", lambda msg, timeout=None: None), \
                mock.patch.object(core_mod, "ECHO_S", 0.1):
            with self.assertRaises(diag.DiagError):
                c.sdo_read(23, 0x1018, 1)
        with self.assertRaises(diag.DiagError) as e:
            c.status()
        self.assertIn("stopped sending", str(e.exception))


class ScanStop(Case):
    def test_stop(self):
        self.device(3)
        c = self.client()
        c.scan(True)
        time.sleep(0.05)
        res = c.scan_stop()
        self.assertFalse(res["running"])
        self.assertTrue(res["stopped"])
        self.assertLess(res["done"], res["total"])

    def test_not_running(self):
        c = self.client()
        with self.assertRaises(diag.DiagError) as e:
            c.scan_stop()
        self.assertIn("no scan is running", str(e.exception))

    def test_send_failure_ends_the_scan(self):
        c = self.client()

        def broken(*a, **kw):
            raise adapter_mod.AdapterError("unreachable", "adapter virtual:x could not send: gone")

        with mock.patch.object(c.core, "transmit", broken):
            c.scan(True)
            deadline = time.monotonic() + 3
            res = c.scan(False)
            while res["running"] and time.monotonic() < deadline:
                time.sleep(0.05)
                res = c.scan(False)
        self.assertFalse(res["running"])
        self.assertIn("could not send", res["error"])
        self.assertLess(res["seconds"], 1.0)


if __name__ == "__main__":
    unittest.main()
