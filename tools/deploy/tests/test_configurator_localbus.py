"""The configurator's USB adapter connection in "Commission a device"
(add-local-bus-commissioning, rework-commission-and-trim-configurator), on
python-can's virtual bus, and a config's online access without one."""

import itertools
import os
import threading
import time
import unittest
from unittest import mock

from canworks.localbus import core as core_mod

from .fake_canopen import FakeDevice, Peer
from .helpers import PINGPONG
from .test_configurator_online import Online
from .test_configurator_server import Running
from .test_localbus_check import error_frame

_n = itertools.count(1)


class AdapterTarget(Online):
    """Commission a device, on a virtual bus of its own."""

    def setUp(self):
        super().setUp()
        st = self.ok("POST", "/api/commission", {})
        self.canopen = st["canopen_dir"]
        self.ch = "cfg-localbus-%d-%d" % (os.getpid(), next(_n))
        self.devices = []
        p = mock.patch.object(core_mod, "LISTEN_S", 0.05)
        p.start()
        self.addCleanup(p.stop)

    def tearDown(self):
        self.request("POST", "/api/online/close", {})
        for d in self.devices:
            d.close()
        super().tearDown()

    def device(self, node, **kw):
        d = FakeDevice(self.ch, node, **kw)
        self.devices.append(d)
        return d

    def use_adapter(self, kbit=250, allow=False):
        self.ok("POST", "/api/online/settings", {"adapter": "virtual:" + self.ch, "adapter_bitrate": kbit})
        if allow:
            self.ok("POST", "/api/online/settings", {"allow_changes": True})

    def test_settings_kept_on_this_pc(self):
        self.use_adapter()
        v = self.ok("GET", "/api/online/settings")
        self.assertEqual((v["target"], v["adapter"], v["adapter_bitrate"], v["allow_changes"]),
                         ("adapter", "virtual:" + self.ch, 250, False))
        self.assertEqual(self.request("POST", "/api/online/settings", {"adapter": "nope"})[0], 422)
        self.assertEqual(self.request("POST", "/api/online/settings", {"adapter_bitrate": 2000})[0], 422)
        self.assertEqual(self.request("POST", "/api/online/settings", {"check_node": 0})[0], 422)
        self.assertEqual(self.ok("POST", "/api/online/settings", {"check_node": 5})["check_node"], 5)
        for root, _, names in os.walk(self.project):
            for name in names:
                with open(os.path.join(root, name), "rb") as f:
                    self.assertNotIn(self.ch.encode(), f.read(), name)

    def test_no_bit_rate_no_connection(self):
        self.ok("POST", "/api/online/settings", {"adapter": "virtual:" + self.ch})
        status, data, _ = self.request("POST", "/api/online/status", {})
        self.assertEqual((status, data.get("need")), (409, "adapter"))
        self.assertIn("pick the bus's bit rate", data["error"])

    def test_wrong_bit_rate_refused(self):
        peer = Peer(self.ch)
        self.addCleanup(peer.close)
        stop = threading.Event()

        def errors():
            while not stop.is_set():
                peer.bus.send(error_frame())
                time.sleep(0.01)

        t = threading.Thread(target=errors, daemon=True)
        t.start()
        try:
            self.use_adapter()
            status, data, _ = self.request("POST", "/api/online/status", {})
        finally:
            stop.set()
            t.join(1)
        self.assertEqual((status, data["kind"]), (422, "bitrate"), data)
        self.assertIn("does not run at 250 kbit/s", data["error"])
        self.assertFalse(self.server.connection.connected)

    def test_disconnect_and_ended_connection(self):
        self.device(2, heartbeat_s=0.05)
        self.use_adapter()
        r = self.ok("POST", "/api/online/status", {})
        self.assertEqual(r["status"]["bitrate_check"]["how"], "traffic")
        self.assertEqual(r["hello"]["bitrate_check"]["result"], "confirmed")
        time.sleep(0.2)
        self.assertGreater(self.ok("POST", "/api/online/status", {})["status"]["bus"]["frames"], 0)
        v = self.ok("POST", "/api/online/disconnect", {})
        self.assertFalse(v["connected"])
        self.assertFalse(self.server.connection.connected)
        # An ended connection is not opened again by itself.
        self.ok("POST", "/api/online/status", {})
        self.server.connection.client.core.end("test")
        status, data, _ = self.request("POST", "/api/online/status", {})
        self.assertEqual(status, 502, data)
        self.assertIn("connection ended: test", data["error"])
        self.assertFalse(self.server.connection.connected)

    def test_scan_stop(self):
        self.use_adapter()
        status, data, _ = self.request("POST", "/api/online/scan_stop", {})
        self.assertEqual(status, 422)
        self.assertIn("no scan is running", data["error"])
        self.assertTrue(self.ok("POST", "/api/online/scan", {"start": True})["running"])
        r = self.ok("POST", "/api/online/scan_stop", {})
        self.assertEqual((r["running"], r["stopped"]), (False, True))

    def test_status_without_token_or_diagnostics(self):
        self.save(self.pingpong(diagnostics=False))
        self.device(2, heartbeat_s=0.05)
        self.use_adapter(kbit=125)
        self.ok("POST", "/api/online/status", {})  # opens the adapter
        time.sleep(0.2)
        r = self.ok("POST", "/api/online/status", {})
        self.assertTrue(r["status"]["local"])
        self.assertEqual(r["config"], "local")
        self.assertEqual(r["status"]["bitrate"], 125000)
        nodes = {n["node_id"]: n for n in r["status"]["nodes"]}
        self.assertEqual(nodes[2]["state"], 127)
        self.assertTrue(nodes[2]["configured"])
        self.assertFalse(r["hello"]["allow_changes"])

    def test_changes_off_until_allowed(self):
        d = self.device(2)
        self.use_adapter()
        status, data, _ = self.request("POST", "/api/online/nmt", {"node": 2, "command": "stop"})
        self.assertEqual(status, 422)
        self.assertIn("changes not allowed", data["error"])
        client = self.server.connection.client
        self.ok("POST", "/api/online/settings", {"allow_changes": True})
        self.assertIs(self.server.connection.client, client)  # the same connection
        self.assertTrue(self.ok("POST", "/api/online/status", {})["hello"]["allow_changes"])
        self.ok("POST", "/api/online/nmt", {"node": 2, "command": "stop"})
        time.sleep(0.1)
        self.assertEqual(d.nmt_log, [2])
        # Another adapter turns it off again.
        self.ok("POST", "/api/online/settings", {"adapter": "virtual:" + self.ch})
        self.assertFalse(self.ok("GET", "/api/online/settings")["allow_changes"])

    def test_sdo_and_scan(self):
        self.save(self.pingpong(diagnostics=False))
        self.device(2, identity=(0x360, 0x1, 0, 0))
        self.device(9, identity=(0x111, 0x2, 0, 0))
        self.use_adapter()
        r = self.ok("POST", "/api/online/sdo_read", {"node": 2, "index": "0x1018", "subindex": 1, "type": "UNSIGNED32"})
        self.assertTrue(r["success"])
        r = self.ok("POST", "/api/online/scan", {"start": True})
        while r["running"]:
            time.sleep(0.1)
            r = self.ok("POST", "/api/online/scan", {"start": False})
        nodes = {n["node_id"]: n for n in r["nodes"]}
        self.assertEqual(nodes[2]["match"], "configured")
        self.assertEqual(nodes[9]["match"], "not configured")

    def test_error_field(self):
        # The device error history (0x1003) on a USB adapter: read, clear
        # refused without changes, then forced on a node heard OPERATIONAL.
        d = self.device(2, heartbeat_s=0.05, nmt_state=5,
                        od={(0x1003, 0): b"\x01", (0x1003, 1): (0x125000).to_bytes(4, "little")})
        self.use_adapter()
        r = self.ok("POST", "/api/online/error_field", {"node": 2})
        self.assertEqual((r["count"], r["entries"][0]["code"], r["entries"][0]["info"]), (1, 0x5000, 0x12))
        status, data, _ = self.request("POST", "/api/online/error_field_clear", {"node": 2})
        self.assertEqual(status, 422)
        self.assertIn("changes not allowed", data["error"])
        self.ok("POST", "/api/online/settings", {"allow_changes": True})
        time.sleep(0.2)
        status, data, _ = self.request("POST", "/api/online/error_field_clear", {"node": 2})
        self.assertEqual((status, data["force"]), (422, True), data)
        self.assertEqual(d.od[(0x1003, 0)], b"\x01")
        r = self.ok("POST", "/api/online/error_field_clear", {"node": 2, "force": True})
        self.assertEqual(r["count"], 0)
        self.assertEqual(d.od[(0x1003, 0)], b"\x00")

    def test_lss_force_after_asking(self):
        self.device(None, identity=(0x360, 0x1, 0x2, 0x77))
        peer = Peer(self.ch)
        try:
            self.use_adapter(allow=True)
            self.ok("POST", "/api/online/status", {})
            peer.send(0x080, b"")
            time.sleep(0.1)
            status, data, _ = self.request("POST", "/api/online/lss_find", {"start": True})
            self.assertEqual(status, 422)
            self.assertIn("another master is active", data["error"])
            r = self.ok("POST", "/api/online/lss_find", {"start": True, "force": True})
            while r["running"]:
                time.sleep(0.1)
                r = self.ok("POST", "/api/online/lss_find", {"start": False})
            self.assertTrue(r["found"])
            self.assertEqual(r["device"]["serial_number"], 0x77)
        finally:
            peer.close()

    def test_trace(self):
        self.device(2, heartbeat_s=0.05)
        self.use_adapter()
        status, data, _ = self.request("POST", "/api/trace/start", {})
        self.assertEqual((status, data["need"]), (409, "online"))  # Connect first
        self.ok("POST", "/api/online/status", {})
        status, data, _ = self.request("POST", "/api/trace/start", {})
        self.assertEqual(status, 200, data)
        time.sleep(0.6)
        self.ok("POST", "/api/trace/stop", {})
        deadline = time.time() + 5
        while time.time() < deadline:
            st = self.ok("GET", "/api/trace/state")
            if not st.get("recording"):
                break
            time.sleep(0.1)
        rows = self.ok("POST", "/api/trace/frames", {"offset": 0, "count": 50})
        self.assertIn("702", str(rows))


class Commission(Running):
    def test_commission_without_config(self):
        st = self.ok("POST", "/api/commission", {})
        self.assertTrue(st["commission"])
        self.assertFalse(st["config_exists"])
        v = self.ok("GET", "/api/online/settings")
        self.assertEqual(v["target"], "adapter")
        self.assertTrue(v["commission"])
        # Not remembered among the recent folders.
        self.assertNotIn(st["folder"], [r["path"] for r in self.ok("GET", "/api/state")["recent"]])


class ConfigMode(Online):
    def test_runtime_only(self):
        self.assertEqual(self.ok("GET", "/api/online/settings")["target"], "runtime")
        for body in ({"adapter": "virtual:x"}, {"adapter_bitrate": 250}, {"allow_changes": True}, {"check_node": 5}):
            status, data, _ = self.request("POST", "/api/online/settings", body)
            self.assertEqual(status, 422, body)
            self.assertIn("Commission a device", data["error"])

    def test_no_scan_or_detection(self):
        for path in ("/api/online/scan", "/api/online/scan_stop", "/api/online/adapter_detect", "/api/online/detect_bitrate"):
            status, _, _ = self.request("POST", path, {"start": True})
            self.assertIn(status, (404, 409), path)


del PINGPONG

if __name__ == "__main__":
    unittest.main()
