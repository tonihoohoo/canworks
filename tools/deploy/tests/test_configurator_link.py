"""The configurator's side of the remote link (add-remote-access): runtimes
for the connect box (discovery and remembered), the path and round trip in
the status answer, the background pairing's note, and the paired PCs of the
Online access section. Discovery and the link are mocked: no mDNS, no iroh."""

import json
import os
import threading
import unittest
from unittest import mock

from canworks import diag
from canworks.configurator import online
from canworks.link import discovery, pc as linkpc
from canworks.link.protocol import LinkError

from . import test_configurator_online as base
from .fake_diag import TOKEN, FakePlugin
from .helpers import tmpdir
from .test_configurator_server import read

FOUND = [
    {"name": "line3", "addresses": ["fe80::1%eth0", "192.168.1.50"], "diag": 7531, "runtime": 8443,
     "id": "a" * 64, "link": 7533},
    {"name": "bench", "addresses": ["10.0.0.7"], "diag": 7600, "runtime": None, "id": None, "link": None},
    {"name": "v6only", "addresses": ["fd00::7"], "diag": 7531, "runtime": None, "id": None, "link": None},
]


class Runtimes(base.Online):
    def test_discovered_and_remembered(self):
        linkpc.remember("line3", hosts=["192.168.1.50"], id="a" * 64, paired=True, internet=True)
        linkpc.remember("Attic", hosts=["10.1.1.1"])
        with mock.patch.object(discovery, "available", return_value=True), \
                mock.patch.object(discovery, "browse", return_value=FOUND) as browse:
            r = self.ok("GET", "/api/online/runtimes")
        browse.assert_called_once_with(2.0)
        self.assertTrue(r["discovery"])
        # The address to connect to: IPv4 first, the diagnostics port only when it is not the default.
        self.assertEqual([(d["name"], d["address"]) for d in r["discovered"]],
                         [("line3", "192.168.1.50"), ("bench", "10.0.0.7:7600"), ("v6only", "[fd00::7]:7531")])
        for d in r["discovered"]:
            diag.parse_runtime(d["address"])  # each one is a valid host for the settings
        self.assertEqual([(m["name"], m["paired"], m["internet"], m["link"]) for m in r["remembered"]],
                         [("Attic", False, False, False), ("line3", True, True, True)])
        self.assertEqual(r["remembered"][1]["hosts"], ["192.168.1.50"])

    def test_without_zeroconf(self):
        with mock.patch.object(discovery, "available", return_value=False), \
                mock.patch.object(discovery, "browse") as browse:
            r = self.ok("GET", "/api/online/runtimes")
        browse.assert_not_called()
        self.assertEqual((r["discovered"], r["remembered"], r["discovery"]), ([], [], False))

    def test_discovery_failure_lists_the_remembered(self):
        linkpc.remember("line3", hosts=["192.168.1.50"])
        with mock.patch.object(discovery, "available", return_value=True), \
                mock.patch.object(discovery, "browse", side_effect=OSError("no multicast")):
            r = self.ok("GET", "/api/online/runtimes")
        self.assertEqual(r["discovered"], [])
        self.assertEqual([m["name"] for m in r["remembered"]], ["line3"])

    def test_remembered_name_as_the_host(self):
        # Picking a remembered runtime fills its name: a valid host, and the settings say what it is.
        linkpc.remember("line3", hosts=["192.168.1.50"], id="a" * 64, paired=True)
        r = self.ok("POST", "/api/online/settings", {"host": "line3"})
        self.assertEqual(r["host"], "line3")
        self.assertEqual(r["remembered"], {"name": "line3", "link": True, "paired": True, "internet": False})
        r = self.ok("POST", "/api/online/settings", {"host": "192.168.1.50"})  # one of its addresses
        self.assertEqual(r["remembered"]["name"], "line3")
        r = self.ok("POST", "/api/online/settings", {"host": "plc.local"})
        self.assertIsNone(r["remembered"])


class PathInStatus(base.Online):
    def test_lan_path_and_round_trip(self):
        with FakePlugin() as fp:
            self.connect(fp)
            r = self.ok("POST", "/api/online/status", {})
            self.assertEqual(r["path"], "LAN")
            self.assertTrue(r["rtt_ms"] is None or isinstance(r["rtt_ms"], int))
            self.assertIsNone(r["pairing_note"])  # a loopback runtime is never paired

    def test_slow_path_reported(self):
        with FakePlugin() as fp, \
                mock.patch.object(online.Connection, "link_info",
                                  return_value={"path": "internet relayed", "rtt_ms": 240, "pairing_note": None}):
            self.connect(fp)
            r = self.ok("POST", "/api/online/status", {})
        self.assertEqual((r["path"], r["rtt_ms"]), ("internet relayed", 240))


class FakeClient:
    def __init__(self, host, pairing, path="LAN", rtts=(0.012,)):
        self.host, self.pairing, self.path = host, pairing, path
        self.rtt_ms = round(min(rtts) * 1000) if rtts else None

    def close(self):
        pass


class PairingNote(unittest.TestCase):
    def setUp(self):
        os.environ["CANWORKS_CONFIG_DIR"] = os.path.join(tmpdir(self), "cfg")
        self.addCleanup(os.environ.pop, "CANWORKS_CONFIG_DIR", None)

    def conn(self, client):
        c = online.Connection()
        c.client, c.key = client, (client.host, 7531, TOKEN)
        return c

    def test_note_once_when_internet_is_on(self):
        linkpc.remember("line3", hosts=["192.168.1.50"], id="a" * 64, paired=True, internet=True)
        done = threading.Event()
        thread = threading.Thread(target=done.wait)
        thread.start()
        job = {"thread": thread, "note": None}
        c = self.conn(FakeClient("192.168.1.50", job))
        self.assertEqual(c.link_info(), {"path": "LAN", "rtt_ms": 12, "pairing_note": None})  # still pairing
        job["note"] = "This PC is now paired with line3 and can reach it from other networks."
        done.set()
        thread.join()
        self.assertEqual(c.link_info()["pairing_note"], job["note"])
        self.assertIsNone(c.link_info()["pairing_note"])  # once
        # The same job on a reopened connection (canworks.link.pc keeps it): not again.
        c2 = self.conn(FakeClient("192.168.1.50", job))
        c2.notes_shown = c.notes_shown
        self.assertIsNone(c2.link_info()["pairing_note"])

    def test_no_note_without_internet(self):
        linkpc.remember("line3", hosts=["192.168.1.50"], id="a" * 64, paired=True, internet=False)
        thread = threading.Thread(target=lambda: None)
        thread.start()
        thread.join()
        job = {"thread": thread, "note": "This PC is now paired with line3."}
        self.assertIsNone(self.conn(FakeClient("192.168.1.50", job)).link_info()["pairing_note"])

    def test_adapter_has_no_path(self):
        c = online.Connection()
        c.client, c.key = FakeClient("x", None, path="ignored"), (online.AdapterTarget("slcan:COM5", 250000), None, None)
        self.assertEqual(c.link_info(), {"path": None, "rtt_ms": None, "pairing_note": None})
        self.assertEqual(online.Connection().link_info(), {"path": None, "rtt_ms": None, "pairing_note": None})


PCS = [{"id": "b" * 64, "name": "laptop", "paired": 1760000000, "last_seen": 1760100000, "via": "lan"},
       {"id": "c" * 64, "name": "office", "paired": 1760000000, "last_seen": None, "via": "allow"}]


class PairedPcs(base.Online):
    def setUp(self):
        super().setUp()
        self.entry = linkpc.remember("line3", hosts=["192.168.1.50"], id="a" * 64, paired=True)

    def test_needs_host_token_and_link_id(self):
        status, data, _ = self.request("POST", "/api/online/paired_pcs", {})
        self.assertEqual((status, data.get("need")), (409, "host"))
        self.ok("POST", "/api/online/settings", {"host": "plc.local"})
        status, data, _ = self.request("POST", "/api/online/paired_pcs", {})
        self.assertEqual((status, data.get("need")), (409, "token"))
        self.ok("POST", "/api/online/token", {"action": "set", "token": TOKEN})
        status, data, _ = self.request("POST", "/api/online/paired_pcs", {})
        self.assertEqual((status, data.get("need")), (409, "link"))
        self.assertIn("connect to it once on its local network", data["error"])

    def test_list_and_remove(self):
        self.ok("POST", "/api/online/settings", {"host": "line3"})
        self.ok("POST", "/api/online/token", {"action": "set", "token": TOKEN})
        with mock.patch.object(linkpc, "paired_pcs", return_value=(PCS, "b" * 64)) as listed:
            r = self.ok("POST", "/api/online/paired_pcs", {})
        self.assertEqual(listed.call_args[0][0]["name"], "line3")
        self.assertEqual(listed.call_args[0][1], TOKEN)
        self.assertEqual((r["runtime"], r["pcs"], r["you"]), ("line3", PCS, "b" * 64))
        with mock.patch.object(linkpc, "remove_pc", return_value=True) as removed, \
                mock.patch.object(linkpc, "available", return_value=False):
            r = self.ok("POST", "/api/online/remove_pc", {"id": "c" * 64})
        self.assertTrue(r["removed"])
        entry, token, pc_id = removed.call_args[0]
        self.assertEqual((entry["name"], token, pc_id), ("line3", TOKEN, "c" * 64))
        self.assertEqual(self.request("POST", "/api/online/remove_pc", {})[0], 400)

    def test_remove_this_pc_unpairs_without_the_token(self):
        self.ok("POST", "/api/online/settings", {"host": "192.168.1.50"})
        self.ok("POST", "/api/online/token", {"action": "set", "token": TOKEN})
        with mock.patch.object(linkpc, "available", return_value=True), \
                mock.patch.object(linkpc, "my_id", return_value="b" * 64), \
                mock.patch.object(linkpc, "unpair", return_value=True) as unpair, \
                mock.patch.object(linkpc, "remove_pc") as removed:
            r = self.ok("POST", "/api/online/remove_pc", {"id": "b" * 64})
        self.assertTrue(r["removed"])
        self.assertEqual(unpair.call_args[0][0]["name"], "line3")
        removed.assert_not_called()

    def test_link_errors(self):
        self.ok("POST", "/api/online/settings", {"host": "line3"})
        self.ok("POST", "/api/online/token", {"action": "set", "token": TOKEN})
        for kind, status in (("token", 422), ("unavailable", 422), ("unreachable", 502)):
            with mock.patch.object(linkpc, "paired_pcs", side_effect=LinkError(kind, "%s happened" % kind)):
                got, data, _ = self.request("POST", "/api/online/paired_pcs", {})
            self.assertEqual((got, data["kind"], data["error"]), (status, kind, "%s happened" % kind))


class RemoteLinkInConfig(base.Online):
    def test_saved_with_the_other_diagnostics_fields(self):
        cfg = self.pingpong()
        cfg["master"]["diagnostics"] = {"remote_link": {"pairing": "lan", "relays": ["https://relay.example.com"],
                                                        "internet": True},
                                        "allow_changes": True, "token_verifier": base.DIAG["token_verifier"]}
        self.save(cfg)
        saved = json.loads(read(os.path.join(self.canopen, "canworks.json"), "r"))["master"]["diagnostics"]
        self.assertEqual(list(saved), ["token_verifier", "allow_changes", "remote_link"])
        self.assertEqual(saved["remote_link"], {"pairing": "lan", "relays": ["https://relay.example.com"],
                                                "internet": True})

    def test_http_relay_refused_by_the_check(self):
        cfg = self.pingpong()
        cfg["master"]["diagnostics"]["remote_link"] = {"internet": True, "relays": ["http://relay.example.com"]}
        r = self.ok("POST", "/api/check", {"config": cfg})
        text = json.dumps(r)
        self.assertIn("relay URLs must use https", text)


if __name__ == "__main__":
    unittest.main()
