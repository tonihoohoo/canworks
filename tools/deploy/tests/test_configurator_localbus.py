"""The configurator's USB adapter target and "Commission a device"
(add-local-bus-commissioning), on python-can's virtual bus."""

import itertools
import os
import time
import unittest
from unittest import mock

from canworks.localbus import core as core_mod

from .fake_canopen import FakeDevice, Peer
from .helpers import PINGPONG
from .test_configurator_online import Online
from .test_configurator_server import Running

_n = itertools.count(1)


class AdapterTarget(Online):
    def setUp(self):
        super().setUp()
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
        self.ok("POST", "/api/online/settings", {"target": "adapter"})
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
        for root, _, names in os.walk(self.project):
            for name in names:
                with open(os.path.join(root, name), "rb") as f:
                    self.assertNotIn(self.ch.encode(), f.read(), name)

    def test_detect_in_the_connection_form(self):
        self.assertEqual(self.ok("POST", "/api/online/adapter_detect_status", {})["verdict"], None)
        status, data, _ = self.request("POST", "/api/online/adapter_detect", {"adapter": "nope"})
        self.assertEqual(status, 422)
        status, data, _ = self.request("POST", "/api/online/adapter_detect", {"adapter": "gs_usb:0"})
        self.assertEqual(status, 422)
        self.assertIn("no listen-only mode", data["error"])
        r = self.ok("POST", "/api/online/adapter_detect", {"adapter": "virtual:" + self.ch, "adapter_bitrate": 250})
        self.assertTrue(r["running"])
        self.assertEqual((r["total"], r["configured_kbit"], r["adapter"]), (8, 250, "virtual:" + self.ch))
        self.server.adapter_sweep.stop()
        r = self.ok("POST", "/api/online/adapter_detect_status", {})
        self.assertEqual((r["running"], r["verdict"], r["error"]), (False, "failed", "stopped"))

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
        self.assertTrue(r["config_bitrate"])
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
        self.ok("POST", "/api/online/settings", {"allow_changes": True})
        self.ok("POST", "/api/online/nmt", {"node": 2, "command": "stop"})
        time.sleep(0.1)
        self.assertEqual(d.nmt_log, [2])
        # A new target turns it off again.
        self.ok("POST", "/api/online/settings", {"target": "adapter"})
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


del PINGPONG

if __name__ == "__main__":
    unittest.main()
