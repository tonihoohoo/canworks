"""The configurator's adapter on another machine (add-remote-adapter): the
target and its token kept on this PC per server, never in a project, the
connection through an adapter server on python-can's virtual bus, the
connection bar's summary with the server and the round trip, the recent
connection without a token, and the adapter servers apart from runtimes."""

import itertools
import json
import os
import threading
from unittest import mock

from canworks import diag
from canworks.configurator import online
from canworks.link import discovery
from canworks.localbus import core as core_mod
from canworks.localbus import parse, serve

from . import fake_tls
from .fake_canopen import FakeDevice
from .test_configurator_online import Online

TOKEN = "cfg-adapter-token"
_n = itertools.count(1)


class RemoteTarget(Online):
    def setUp(self):
        super().setUp()
        self.ch = "cfg-remote-%d-%d" % (os.getpid(), next(_n))
        self.srv = serve.AdapterServer(parse("virtual:" + self.ch), 250000, diag.token_verifier(TOKEN),
                                       bind="127.0.0.1", port=0, listen_s=0.05, name="benchbox",
                                       context=fake_tls.server_context(), cert_hash=fake_tls.CERT_HASH,
                                       log=lambda line: None, allow_changes=True)
        threading.Thread(target=self.srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)
        self.address = "127.0.0.1:%d" % self.srv.port
        self.device = FakeDevice(self.ch, 2, heartbeat_s=0.05)
        self.addCleanup(self.device.close)
        p = mock.patch.object(core_mod, "LISTEN_S", 0.05)
        p.start()
        self.addCleanup(p.stop)

    def tearDown(self):
        self.request("POST", "/api/online/disconnect", {})
        super().tearDown()

    def test_target_and_token_kept_on_this_pc(self):
        status, data, _ = self.request("POST", "/api/online/settings", {"remote_adapter": True})
        self.assertEqual(status, 200, data)
        self.assertEqual((data["target"], data["remote_adapter"], data["remote_token_set"]), ("adapter", True, False))
        status, data, _ = self.request("POST", "/api/online/status", {})
        self.assertEqual((status, data.get("need")), (409, "remote_host"))
        self.assertEqual(self.request("POST", "/api/online/settings", {"remote_host": "x:y"})[0], 422)
        self.ok("POST", "/api/online/settings", {"remote_host": self.address})
        status, data, _ = self.request("POST", "/api/online/status", {})
        self.assertEqual((status, data.get("need")), (409, "remote_token"))
        v = self.ok("POST", "/api/online/settings", {"remote_token": TOKEN})
        self.assertTrue(v["remote_token_set"])
        with open(os.path.join(self.dir, "cfg", "online.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["adapter_tokens"], {self.address: TOKEN})
        for root, _, names in os.walk(self.project):
            for name in names:
                with open(os.path.join(root, name), "rb") as f:
                    self.assertNotIn(TOKEN.encode(), f.read(), name)
        self.assertFalse(self.ok("POST", "/api/online/settings", {"remote_token": ""})["remote_token_set"])

    def test_connect_through_the_server(self):
        self.ok("POST", "/api/online/settings", {"remote_adapter": True, "remote_host": self.address})
        self.ok("POST", "/api/online/settings", {"remote_token": TOKEN})
        r = self.ok("POST", "/api/online/status", {})
        self.assertTrue(r["status"]["local"])
        c = r["conn"]
        self.assertEqual((c["kind"], c["target"], c["remote"]),
                         ("adapter", "virtual:%s on %s" % (self.ch, self.address), self.address))
        self.assertIsInstance(c["rtt_ms"], int)
        self.assertEqual(c["allow_changes_source"], "switch")
        self.assertEqual(r["config_bitrate"], None)  # no saved config yet
        self.assertEqual(r["recent"][0], {"kind": "remote_adapter", "host": self.address})
        # Allow changes switches on the open connection, on the server too.
        self.ok("POST", "/api/online/settings", {"allow_changes": True})
        self.assertTrue(self.ok("POST", "/api/online/status", {})["status"]["allow_changes"])
        res = self.ok("POST", "/api/online/sdo_read", {"node": 2, "index": "0x1018", "subindex": 1,
                                                       "type": "UNSIGNED32"})
        self.assertTrue(res["success"])
        self.assertEqual(self.srv.status()["pcs"][0]["address"], "127.0.0.1")
        self.ok("POST", "/api/online/disconnect", {})
        self.assertFalse(self.server.connection.connected)

    def test_read_only_server_keeps_changes_off(self):
        # Allow changes on this PC cannot open a server started without --allow-changes.
        self.srv.allow_changes = False
        self.ok("POST", "/api/online/settings", {"remote_adapter": True, "remote_host": self.address})
        self.ok("POST", "/api/online/settings", {"remote_token": TOKEN})
        self.ok("POST", "/api/online/status", {})
        self.ok("POST", "/api/online/settings", {"allow_changes": True})
        r = self.ok("POST", "/api/online/status", {})
        self.assertFalse(r["status"]["allow_changes"])
        self.assertFalse(r["hello"]["allow_changes"])
        self.assertFalse(r["conn"]["server_allow_changes"])

    def test_wrong_token(self):
        self.ok("POST", "/api/online/settings", {"remote_adapter": True, "remote_host": self.address})
        self.ok("POST", "/api/online/settings", {"remote_token": "not-it"})
        status, data, _ = self.request("POST", "/api/online/status", {})
        self.assertEqual(status, 200)
        self.assertFalse(data["reachable"])
        self.assertIn("wrong token", data["error"])

    def test_back_to_the_runtime(self):
        self.ok("POST", "/api/online/settings", {"remote_adapter": True, "remote_host": self.address})
        self.ok("POST", "/api/online/settings", {"remote_token": TOKEN})
        self.ok("POST", "/api/online/status", {})
        v = self.ok("POST", "/api/online/settings", {"remote_adapter": False})
        self.assertEqual((v["target"], v["remote_adapter"]), ("runtime", False))
        self.assertFalse(self.server.connection.connected)


class ServersApart(Online):
    def test_runtimes_and_adapter_servers(self):
        found = [discovery._entry("plc", ["192.0.2.8"], 7531, {"diag": "7531"}),
                 discovery._entry("benchbox adapter socketcan:can0", ["192.0.2.7"], 7536,
                                  {"kind": "adapter", "name": "benchbox", "adapter": "socketcan:can0", "bitrate": "500"})]
        with mock.patch.object(discovery, "available", lambda: True), \
                mock.patch.object(discovery, "browse", lambda wait: found):
            runtimes = self.ok("GET", "/api/online/runtimes")
            servers = self.ok("GET", "/api/online/adapter_servers")
        self.assertEqual([r["name"] for r in runtimes["discovered"]], ["plc"])
        self.assertEqual(servers["servers"], [{"name": "benchbox", "address": "192.0.2.7", "adapter": "socketcan:can0",
                                               "bitrate_kbit": 500}])

    def test_recent_entry(self):
        self.assertEqual(online.recent_entry("benchbox", remote=True), {"kind": "remote_adapter", "host": "benchbox"})
