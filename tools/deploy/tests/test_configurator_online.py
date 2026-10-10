"""The configurator's online access: token and host on this PC, the proxy to
the plugin's diagnostics channel, and EDS matching for scan results
(add-online-diagnostics tasks 3.2-3.5)."""

import hashlib
import json
import os
import shutil
import stat
import time
import unittest

from canworks import diag
from canworks.configurator import online

from .fake_diag import SLAVE_NETWORK, TOKEN, TWO_NETWORKS, FakePlugin, closed_port, slave_status
from .helpers import PINGPONG, REPO, tmpdir
from .test_configurator_server import RTD, Running, read, rtd_node

DIAG = {"token_verifier": diag.token_verifier(TOKEN)}


class Online(Running):
    def setUp(self):
        super().setUp()
        self.open_project()
        self.canopen = os.path.join(self.project, "canworks")

    def save(self, cfg):
        status, data, _ = self.request("POST", "/api/save", {"config": cfg, "allow_overlap": True})
        self.assertEqual(status, 200, data)
        return data

    def pingpong(self, diagnostics=True):
        with open(os.path.join(PINGPONG, "canopen_config.json"), encoding="utf-8") as f:
            cfg = json.load(f)
        self.assertEqual(self.eds(os.path.join(PINGPONG, "cpp-slave.eds"))[0], 200)
        if diagnostics:
            cfg["master"]["diagnostics"] = dict(DIAG)
        return cfg

    def connect(self, fake, token=TOKEN):
        self.ok("POST", "/api/online/settings", {"host": fake.runtime})
        if token:
            self.ok("POST", "/api/online/token", {"action": "set", "token": token})


class Settings(Online):
    def test_generate_keeps_token_out_of_the_project(self):
        r = self.ok("POST", "/api/online/token", {"action": "generate"})
        self.assertGreaterEqual(len(r["token"]), 32)
        self.assertTrue(diag.token_matches(r["token"], r["token_verifier"]))
        cfg = self.pingpong(diagnostics=False)
        cfg["master"]["diagnostics"] = {"token_verifier": r["token_verifier"]}
        self.save(cfg)
        saved = read(os.path.join(self.canopen, "canworks.json"), "r")
        self.assertIn(r["token_verifier"], saved)
        for root, _, names in os.walk(self.project):
            for name in names:
                self.assertNotIn(r["token"].encode(), read(os.path.join(root, name)), name)
        settings = os.path.join(self.dir, "cfg", "online.json")
        self.assertIn(r["token"], read(settings, "r"))
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(os.stat(settings).st_mode), 0o600)
        self.assertEqual(self.ok("GET", "/api/online/settings")["token"], r["token"])

    def test_token_from_another_pc_checked_against_the_verifier(self):
        status, data, _ = self.request("POST", "/api/online/token",
                                       {"action": "set", "token": "wrong", "token_verifier": DIAG["token_verifier"]})
        self.assertEqual(status, 422)
        self.assertIn("does not match", data["error"])
        self.assertIsNone(self.ok("GET", "/api/online/settings")["token"])
        self.ok("POST", "/api/online/token", {"action": "set", "token": TOKEN, "token_verifier": DIAG["token_verifier"]})
        self.assertEqual(self.ok("GET", "/api/online/settings")["token"], TOKEN)
        self.assertTrue(self.ok("POST", "/api/online/token", {"action": "check", "token_verifier": DIAG["token_verifier"]})["match"])
        self.assertFalse(self.ok("POST", "/api/online/token",
                                 {"action": "check", "token_verifier": diag.token_verifier("other")})["match"])

    def test_upgrade_of_the_former_token_sha256(self):
        # A config from before the encrypted channel: the same token gets a verifier.
        old = hashlib.sha256(TOKEN.encode()).hexdigest()
        self.ok("POST", "/api/online/token", {"action": "set", "token": TOKEN, "token_sha256": old})
        self.assertTrue(self.ok("POST", "/api/online/token", {"action": "check", "token_sha256": old})["match"])
        v = self.ok("POST", "/api/online/token", {"action": "verifier"})["token_verifier"]
        self.assertTrue(diag.token_matches(TOKEN, v))
        self.ok("POST", "/api/online/token", {"action": "forget"})
        self.assertIsNone(self.ok("GET", "/api/online/settings")["token"])

    def test_host_and_library(self):
        self.assertEqual(self.request("POST", "/api/online/settings", {"host": "pi:notaport"})[0], 422)
        self.assertEqual(self.request("POST", "/api/online/settings", {"eds_library": "/no/such/dir"})[0], 422)
        r = self.ok("POST", "/api/online/settings", {"host": "plc.local", "eds_library": RTD})
        self.assertEqual((r["host"], r["eds_library"]), ("plc.local", RTD))

    def test_offline_editing_opens_no_connection(self):
        with FakePlugin() as fp:
            self.connect(fp)
            self.save(self.pingpong())
            self.ok("GET", "/api/state")
            self.assertEqual(fp.connections, 0)

    def test_needs_host_and_token(self):
        status, data, _ = self.request("POST", "/api/online/status", {})
        self.assertEqual((status, data.get("need")), (409, "host"))
        self.ok("POST", "/api/online/settings", {"host": "127.0.0.1:1"})
        status, data, _ = self.request("POST", "/api/online/status", {})
        self.assertEqual((status, data.get("need")), (409, "token"))


class ConcurrentSettings(unittest.TestCase):
    def test_parallel_updates_all_land(self):
        # The server makes one Settings per request; two at once used to share
        # one temporary file, and one request failed with no answer.
        import threading
        d = tmpdir(self)
        errors = []

        def update(i):
            try:
                for _ in range(20):
                    online.Settings(d).update_project("/p%d" % i, host="h%d" % i)
            except Exception as e:  # pragma: no cover
                errors.append(e)

        threads = [threading.Thread(target=update, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual({k: v["host"] for k, v in online.Settings(d).load()["projects"].items()},
                         {"/p%d" % i: "h%d" % i for i in range(4)})
        self.assertEqual([f for f in os.listdir(d) if f.endswith(".tmp")], [])


class Proxy(Online):
    def test_status_and_fingerprint(self):
        with FakePlugin() as fp:
            self.connect(fp)
            r = self.ok("POST", "/api/online/status", {})
            self.assertEqual(r["config"], "none")  # nothing saved yet
            self.assertEqual(r["hello"]["allow_changes"], False)
            self.assertEqual(r["status"]["nodes"][1]["boot_error"], "J")
            self.save(self.pingpong())
            self.assertEqual(self.ok("POST", "/api/online/status", {})["config"], "different")
            raw = read(os.path.join(self.canopen, "canworks.json"))
            fp.status["config_sha256"] = hashlib.sha256(raw).hexdigest()
            self.assertEqual(self.ok("POST", "/api/online/status", {})["config"], "same")
            self.assertEqual(fp.connections, 1)  # kept open between refreshes

    def test_fingerprint_of_the_deployed_file(self):
        self.save(self.pingpong())
        path = os.path.join(self.canopen, "canworks.json")
        # What the deploy tool and the editor hook write as conf/canworks.json.
        import sys
        sys.path.insert(0, os.path.join(REPO, "tools", "editor-hook"))
        self.addCleanup(sys.path.remove, os.path.join(REPO, "tools", "editor-hook"))
        from canworks import bundle
        deployed, _ = bundle.rewrite(json.loads(read(path, "r")), path)
        text = json.dumps(deployed, indent=2) + "\n"
        self.assertIn(hashlib.sha256(text.encode()).hexdigest(), online.fingerprints(path))
        # The file the bundle really carries, written on this OS (LF on Windows too).
        work = tmpdir(self)
        os.makedirs(os.path.join(work, "src"))
        staged, _ = bundle.assemble(os.path.join(work, "src"), deployed, {}, work)
        raw = read(os.path.join(staged, "conf", "canworks.json"))
        self.assertIn(hashlib.sha256(raw).hexdigest(), online.fingerprints(path))

    def test_connection_errors(self):
        self.ok("POST", "/api/online/settings", {"host": "127.0.0.1:%d" % closed_port()})
        self.ok("POST", "/api/online/token", {"action": "set", "token": TOKEN})
        status, data, _ = self.request("POST", "/api/online/status", {})
        self.assertEqual((status, data["kind"]), (502, "closed"))
        with FakePlugin() as fp:
            self.connect(fp, token="wrong")
            self.ok("POST", "/api/online/token", {"action": "set", "token": "wrong"})
            status, data, _ = self.request("POST", "/api/online/status", {})
            self.assertEqual((status, data["kind"]), (502, "token"))
        self.ok("POST", "/api/online/settings", {"host": "no-such-host.invalid"})
        status, data, _ = self.request("POST", "/api/online/status", {})
        self.assertEqual((status, data["kind"]), (502, "unreachable"))

    def test_port_from_the_config(self):
        with FakePlugin() as fp:
            self.ok("POST", "/api/online/settings", {"host": "127.0.0.1"})
            self.ok("POST", "/api/online/token", {"action": "set", "token": TOKEN})
            self.assertEqual(self.ok("POST", "/api/online/status", {"port": fp.port})["status"]["session"], True)

    def test_emcy_with_classes(self):
        with FakePlugin() as fp:
            self.connect(fp)
            r = self.ok("POST", "/api/online/emcy", {"node": 2})
        self.assertEqual([e["class"] for e in r["emcy"]], ["temperature", "error reset or no error"])

    def test_sdo_read_decoded(self):
        with FakePlugin() as fp:
            self.connect(fp)
            r = self.ok("POST", "/api/online/sdo_read", {"node": 2, "index": "0x1018", "subindex": 4, "type": 7})
            self.assertEqual(r["decoded"]["text"], "305419896 (0x12345678)")
            r = self.ok("POST", "/api/online/sdo_read", {"node": 2, "index": 0x1008, "subindex": 0, "type": 9})
            self.assertEqual(r["decoded"]["text"], "pingpong")
            r = self.ok("POST", "/api/online/sdo_read", {"node": 2, "index": "0x6000", "subindex": 1})
            self.assertFalse(r["success"])
            self.assertEqual(r["abort_text"], "object does not exist in the object dictionary")
            self.assertEqual(r["reason"], "abort 0x06020000: object does not exist in the object dictionary")
            self.assertEqual(self.request("POST", "/api/online/sdo_read", {"node": 200, "index": 1})[0], 400)

    def test_write_and_nmt_refused_when_not_allowed(self):
        with FakePlugin(allow_changes=False) as fp:
            self.connect(fp)
            status, data, _ = self.request("POST", "/api/online/sdo_write",
                                           {"node": 2, "index": "0x2000", "subindex": 0, "type": 7, "value": "5"})
            self.assertEqual((status, data["error"], data["kind"]), (422, "changes not allowed", "refused"))
            status, data, _ = self.request("POST", "/api/online/nmt", {"node": 2, "command": "stop"})
            self.assertEqual((status, data["error"]), (422, "changes not allowed"))

    def test_write_and_nmt(self):
        with FakePlugin(allow_changes=True) as fp:
            self.connect(fp)
            r = self.ok("POST", "/api/online/sdo_write",
                        {"node": 2, "index": "0x2000", "subindex": 0, "type": 7, "value": "0x1E"})
            self.assertTrue(r["success"])
            self.assertEqual(fp.objects[(2, 0x2000, 0)], b"\x1e\x00\x00\x00")
            status, data, _ = self.request("POST", "/api/online/sdo_write",
                                           {"node": 2, "index": "0x2000", "subindex": 0, "type": 5, "value": "300"})
            self.assertEqual(status, 422)
            self.assertIn("out of range for UNSIGNED8", data["error"])
            self.ok("POST", "/api/online/nmt", {"node": 2, "command": "stop"})
            node = self.ok("POST", "/api/online/status", {})["status"]["nodes"][0]
            self.assertEqual((node["hold"], node["hold_by"]), ("stopped", "operator"))
            self.assertEqual(self.request("POST", "/api/online/nmt", {"node": 2, "command": "halt"})[0], 400)

    def test_running_node_needs_force(self):
        with FakePlugin(allow_changes=True) as fp:
            fp.force_running = True
            self.connect(fp)
            write = {"node": 2, "index": "0x2000", "subindex": 0, "type": 7, "value": "7"}
            status, data, _ = self.request("POST", "/api/online/sdo_write", write)
            self.assertEqual((status, data["force"]), (422, True), data)
            self.assertIn("force needed", data["error"])
            self.assertEqual(fp.objects[(2, 0x2000, 0)], b"\x00\x00\x00\x00")  # not written
            self.assertTrue(self.ok("POST", "/api/online/sdo_write", dict(write, force=True))["success"])
            self.assertEqual(fp.objects[(2, 0x2000, 0)], b"\x07\x00\x00\x00")
            status, data, _ = self.request("POST", "/api/online/nmt", {"node": 2, "command": "reset"})
            self.assertEqual((status, data["force"]), (422, True), data)
            self.ok("POST", "/api/online/nmt", {"node": 2, "command": "stop", "force": True})
            self.ok("POST", "/api/online/nmt", {"node": 2, "command": "start", "force": True})
            self.assertEqual(fp.forced, [("sdo_write", 2), ("nmt", 2)])  # START never carries force
            status, data, _ = self.request("POST", "/api/online/scan", {"start": True})
            self.assertEqual((status, data["force"]), (422, True), data)
            self.ok("POST", "/api/online/scan", {"start": True, "force": True})
            self.assertEqual(fp.forced[-1], ("scan", None))
            self.assertEqual(self.request("POST", "/api/online/sdo_read", dict(write, force=True))[0], 200)
            self.assertEqual(fp.forced[-1], ("scan", None), "a read never carries force")

    def test_idle_close(self):
        with FakePlugin() as fp:
            self.connect(fp)
            self.server.connection.idle = 0.3
            self.ok("POST", "/api/online/status", {})
            self.assertTrue(self.server.connection.connected)
            time.sleep(0.6)
            self.assertFalse(self.server.connection.connected)
            self.ok("POST", "/api/online/status", {})
            self.ok("POST", "/api/online/close", {})
            self.assertFalse(self.server.connection.connected)
            self.assertEqual(fp.connections, 2)


class Scan(Online):
    def library(self):
        lib = os.path.join(self.dir, "eds-library")
        os.makedirs(os.path.join(lib, "vendor-a"))
        text = read(os.path.join(RTD, "rtd8.eds"), "r")
        # Two revisions of the same device (vendor 0xAB, product 0x1234 as the fake scan reports node 40).
        base = text.replace("VendorNumber=0x00F0F0F0", "VendorNumber=0xAB").replace("ProductNumber=0x00000404",
                                                                            "ProductNumber=0x1234")
        with open(os.path.join(lib, "vendor-a", "rtd-rev1.eds"), "w") as f:
            f.write(base.replace("RevisionNumber=0x00010003", "RevisionNumber=0x00010001"))
        with open(os.path.join(lib, "rtd-rev2.eds"), "w") as f:
            f.write(base.replace("RevisionNumber=0x00010003", "RevisionNumber=0x00010002"))
        with open(os.path.join(lib, "broken.eds"), "w") as f:
            f.write("not an ini file [")
        self.ok("POST", "/api/online/settings", {"eds_library": lib})
        return lib

    def scan(self):
        r = self.ok("POST", "/api/online/scan", {"start": True})
        polls = 0
        while r["running"]:
            polls += 1
            r = self.ok("POST", "/api/online/scan", {"start": False})
        self.assertGreater(polls, 0)
        return {d["node_id"]: d for d in r["nodes"]}

    def test_matches_from_the_library(self):
        lib = self.library()
        cfg = self.pingpong()
        self.save(cfg)
        with FakePlugin() as fp:
            self.connect(fp)
            found = self.scan()
        m = found[40]["eds_matches"]
        self.assertEqual([x["name"] for x in m], ["rtd-rev2.eds", "rtd-rev1.eds"])  # exact revision first
        self.assertTrue(m[0]["revision_match"])
        self.assertEqual(m[0]["vendor_name"], "canworks test devices")
        self.assertEqual(found[41]["eds_matches"], [])
        self.assertEqual(found[2]["expected"], {"vendor_id": 0x360, "product_code": 0})
        self.assertEqual(found[2]["config_eds"], "cpp-slave.eds")
        self.assertEqual(found[2]["eds_matches"][0]["where"], "project")
        # Add the found sensor: the EDS is imported, the project unchanged until save.
        before = sorted(os.listdir(self.canopen))
        r = self.ok("POST", "/api/online/use_eds", {"path": m[0]["path"]})
        self.assertEqual(r["name"], "rtd-rev2.eds")
        self.assertIn("objects", r["summary"])
        self.assertEqual(sorted(os.listdir(self.canopen)), before)
        cfg["nodes"].append({"node_id": 40, "name": "rtd", "eds": "rtd-rev2.eds", "heartbeat_ms": 100, "revision_number": 0x00010002,
                             "serial_number": 99})
        self.save(cfg)
        self.assertIn("rtd-rev2.eds", os.listdir(self.canopen))
        # A file in canworks/ is used as it is.
        r = self.ok("POST", "/api/online/use_eds", {"path": os.path.join(self.canopen, "cpp-slave.eds")})
        self.assertEqual(r["name"], "cpp-slave.eds")
        self.assertEqual(self.request("POST", "/api/online/use_eds",
                                      {"path": os.path.join(REPO, "config", "pingpong", "cpp-slave.eds")})[0], 403)
        self.assertEqual(self.request("POST", "/api/online/use_eds",
                                      {"path": os.path.join(lib, "..", "cfg", "online.json")})[0], 400)

    def test_expected_identity_from_the_draft(self):
        cfg = self.pingpong()
        cfg["nodes"][0]["revision_number"] = 2
        with FakePlugin() as fp:
            self.connect(fp)
            self.ok("POST", "/api/online/scan", {"start": True, "config": cfg})
            r = self.ok("POST", "/api/online/scan", {"start": False, "config": cfg})
            while r["running"]:
                r = self.ok("POST", "/api/online/scan", {"start": False, "config": cfg})
        node2 = [d for d in r["nodes"] if d["node_id"] == 2][0]
        self.assertEqual(node2["expected"]["revision_number"], 2)


class TwoNetworks(Online):
    """A plugin that runs io and drives (add-several-can-networks task 6.4):
    every route passes the page's network."""

    def two(self):
        with open(os.path.join(REPO, "config", "two-networks", "canopen_config.json"), encoding="utf-8") as f:
            cfg = json.load(f)
        self.assertEqual(self.eds(os.path.join(REPO, "config", "two-networks", "cpp-slave.eds"))[0], 200)
        cfg["diagnostics"] = dict(DIAG)
        cfg["networks"][1]["nodes"][0]["name"] = "drive"
        return cfg

    def test_status_names_the_network(self):
        with FakePlugin(networks=TWO_NETWORKS) as fp:
            self.connect(fp)
            r = self.ok("POST", "/api/online/status", {"network": "drives"})
            self.assertEqual((r["network"], r["status"]["bus"]["interface"]), ("drives", "vcan1"))
            self.assertEqual([n["name"] for n in r["networks"]], ["io", "drives"])
            # A tab the runtime does not run: the first network, said so.
            r = self.ok("POST", "/api/online/status", {"network": "can7"})
            self.assertEqual((r["network"], r["status"]["bus"]["interface"]), ("io", "vcan0"))
            r = self.ok("POST", "/api/online/status", {})
            self.assertEqual(r["network"], "io")

    def test_one_network_sends_none(self):
        with FakePlugin() as fp:
            self.connect(fp)
            r = self.ok("POST", "/api/online/status", {"network": "can0"})
            self.assertEqual((r["network"], r["networks"]), (None, []))
            self.ok("POST", "/api/online/sdo_read", {"node": 2, "index": "0x1008", "type": 9, "network": "can0"})
            self.assertFalse([q for q in fp.requests if "network" in q])

    def test_sdo_and_nmt_go_to_the_picked_network(self):
        with FakePlugin(networks=TWO_NETWORKS, allow_changes=True) as fp:
            self.connect(fp)
            r = self.ok("POST", "/api/online/sdo_read", {"node": 2, "index": "0x1008", "type": 9, "network": "drives"})
            self.assertEqual(r["decoded"]["text"], "drive")
            r = self.ok("POST", "/api/online/sdo_read", {"node": 2, "index": "0x1008", "type": 9, "network": "io"})
            self.assertEqual(r["decoded"]["text"], "pingpong")
            self.ok("POST", "/api/online/nmt", {"node": 2, "command": "stop", "network": "drives"})
            self.assertEqual(fp.network("drives").status["nodes"][0]["state"], 4)
            self.assertEqual(fp.status["nodes"][0]["hold"], "none")
            # Without a network the plugin refuses, naming both.
            status, data, _ = self.request("POST", "/api/online/sdo_read", {"node": 2, "index": "0x1008"})
            self.assertEqual(status, 422)
            self.assertIn("io, drives", data["error"])

    def test_scan_and_od_entries_use_the_network(self):
        cfg = self.two()
        with FakePlugin(networks=TWO_NETWORKS, scan_polls=0) as fp:
            self.connect(fp)
            r = self.ok("POST", "/api/online/scan", {"start": True, "config": cfg, "network": "drives"})
            self.assertEqual(r["network"], "drives")
            self.assertEqual(r["nodes"][0]["config_name"], "drive")
            self.assertEqual([q.get("network") for q in fp.requests if q["op"] == "scan"], ["drives"])
            r = self.ok("POST", "/api/online/od_entries", {"node": 2, "config": cfg, "network": "drives"})
            self.assertEqual((r["configured"], r["eds"]), (True, "cpp-slave.eds"))
            # Watch lists are kept per network.
            self.ok("POST", "/api/online/watch", {"node": 2, "network": "drives", "keys": [[0x1008, 0]]})
            self.assertEqual(self.ok("POST", "/api/online/watch", {"node": 2, "network": "io"})["keys"], [])
            self.assertEqual(self.ok("POST", "/api/online/watch", {"node": 2, "network": "drives"})["keys"],
                             [[0x1008, 0]])


class SlaveNetwork(Online):
    """A slave network in the online view (add-canopen-slave tasks 4.2 and
    6.8): its status, its own dictionary, and the master's routes refused."""

    def config(self, name):
        folder = os.path.join(REPO, "config", name)
        with open(os.path.join(folder, "canopen_config.json"), encoding="utf-8") as f:
            cfg = json.load(f)
        os.makedirs(self.canopen, exist_ok=True)
        for f in os.listdir(folder):
            if f.endswith(".eds"):
                shutil.copy(os.path.join(folder, f), self.canopen)
        cfg["diagnostics"] = dict(DIAG)
        return cfg

    def test_status_and_own_dictionary(self):
        with FakePlugin(networks=[SLAVE_NETWORK]) as fp:
            self.connect(fp)
            r = self.ok("POST", "/api/online/status", {})
            self.assertEqual((r["networks"][0]["role"], r["networks"][0]["node_id"]), ("slave", 10))
            st = r["status"]
            self.assertEqual((st["role"], st["slave"]["node_id"], st["slave"]["sync_count"]), ("slave", 10, 42))
            self.assertEqual([p["number"] for p in st["slave"]["tpdos"]], [1, 2])
            r = self.ok("POST", "/api/online/sdo_read", {"node": 10, "index": "0x1008", "type": "VISIBLE_STRING"})
            self.assertEqual(r["decoded"]["text"], "OpenPLC slave example")
            status, data, _ = self.request("POST", "/api/online/sdo_read", {"node": 2, "index": "0x1008"})
            self.assertEqual((status, data["kind"]), (422, "refused"))
            self.assertIn("node 2 is not this slave (node ID 10)", data["error"])
            for path, body in (("nmt", {"node": 10, "command": "stop"}), ("emcy", {"node": 10}),
                               ("scan", {"start": True}), ("lss_find", {"start": True})):
                status, data, _ = self.request("POST", "/api/online/" + path, body)
                self.assertEqual(status, 422, path)
                self.assertIn('network "line" is a slave network; %s needs a master network' % path, data["error"])

    def test_object_dictionary_of_the_slave(self):
        cfg = self.config("slave")
        with FakePlugin(networks=[SLAVE_NETWORK]) as fp:
            self.connect(fp)
            r = self.ok("POST", "/api/online/od_entries", {"node": 10, "config": cfg})
            self.assertEqual((r["slave"], r["configured"], r["eds"]), (True, False, "openplc-slave.eds"))
            by_key = {(e["index"], e["subindex"]): e for e in r["entries"]}
            self.assertEqual(by_key[(0x2000, 1)]["slave_bind"], {"iec_location": "%IW300", "name": "speed_setpoint"})
            self.assertEqual(by_key[(0x2100, 2)]["slave_bind"], {"iec_location": "%QW301", "name": ""})
            self.assertNotIn("slave_bind", by_key[(0x1008, 0)])
            r = self.ok("POST", "/api/online/od_read", {"node": 10, "config": cfg, "keys": [[0x2000, 1], [0x1008, 0]]})
            self.assertEqual(sorted(v["index"] for v in r["values"]), [0x1008, 0x2000])
            # Backup, compare, restore and store are for a master network's nodes.
            status, data, _ = self.request("POST", "/api/online/backup", {"node": 10, "config": cfg})
            self.assertEqual(status, 409)
            self.assertIn("backup needs a master network", data["error"])
            cfg["networks"][0]["slave"]["eds"] = ""
            status, data, _ = self.request("POST", "/api/online/od_entries", {"node": 10, "config": cfg})
            self.assertEqual(status, 422)
            self.assertIn("has no EDS yet", data["error"])
            # A master network's node is still looked up as before.
            self.assertEqual(self.request("POST", "/api/online/od_entries",
                                          {"node": 2, "config": self.pingpong()})[1]["configured"], True)

    def test_gateway_upper_network(self):
        cfg = self.config("gateway")
        nets = [dict(TWO_NETWORKS[0], name="field"), dict(SLAVE_NETWORK, name="upper", node_id=20)]
        with FakePlugin(networks=nets) as fp:
            fp.network("upper").status.update(slave_status(gateway=True), network="upper")
            self.connect(fp)
            r = self.ok("POST", "/api/online/status", {"network": "upper"})
            self.assertEqual(r["status"]["gateway"], {"routes": 2, "upper_ok": False, "forwarded_errors": 1})
            r = self.ok("POST", "/api/online/od_entries", {"node": 20, "config": cfg, "network": "upper"})
            by_key = {(e["index"], e["subindex"]): e for e in r["entries"]}
            self.assertEqual(by_key[(0x2101, 1)]["slave_bind"], {"route": "pong"})
            self.assertEqual(by_key[(0x2100, 1)]["slave_bind"], {"iec_location": "%QX300.0", "name": ""})
            # The field network's nodes are master nodes as before.
            r = self.ok("POST", "/api/online/od_entries", {"node": 2, "config": cfg, "network": "field"})
            self.assertEqual((r["slave"], r["configured"]), (False, True))


class Helpers(unittest.TestCase):
    def test_device_info(self):
        from canworks import eds
        info = eds.device_info(os.path.join(RTD, "rtd8.eds"))
        self.assertEqual((info["vendor_id"], info["product_code"], info["revision_number"]),
                         (0xF0F0F0, 0x404, 0x00010003))
        self.assertIsNone(eds.device_info(os.path.join(tmpdir(self), "missing.eds")))

    def test_expected_identity(self):
        exp = online.expected_identity({"revision_number": "0x10", "serial_number": 0},
                                       os.path.join(PINGPONG, "cpp-slave.eds"))
        self.assertEqual(exp, {"vendor_id": 0x360, "product_code": 0, "revision_number": 16})


class Retries(unittest.TestCase):
    """Connection.call sends a request again after a timeout only when it
    only reads: a change may have been carried out already."""

    class FakeClient:
        def __init__(self, sent, fail):
            self.sent, self.fail = sent, fail
            self.network = None
            self.info = {}

        def connect(self):
            pass

        def close(self):
            pass

        def request(self, op, timeout=None, **fields):
            self.sent.append(op)
            if self.fail and self.fail[0] == op:
                self.fail.pop(0)
                raise diag.DiagError("timeout", "runtime did not answer in 3 s")
            return {"op": op}

        def nmt(self, node, command):
            return self.request("nmt", node=node, command=command)

        def status(self):
            return self.request("status")

    def connection(self, *fail):
        """A Connection whose client times out once on each op of `fail`."""
        sent = []
        conn = online.Connection(idle=60)
        self.addCleanup(conn.close)
        fail = list(fail)

        def opener(key):
            conn.client, conn.key = self.FakeClient(sent, fail), key

        conn._open = opener
        return conn, sent

    def test_change_not_sent_again(self):
        conn, sent = self.connection("nmt")
        with self.assertRaises(diag.DiagError) as cm:
            conn.call("h", 1, "t", lambda c: c.nmt(5, "reset"))
        self.assertEqual(sent, ["nmt"])
        self.assertIn("no answer; the request may have been carried out", str(cm.exception))
        self.assertFalse(conn.connected)

    def test_read_sent_again(self):
        conn, sent = self.connection("status")
        self.assertEqual(conn.call("h", 1, "t", lambda c: c.status()), {"op": "status"})
        self.assertEqual(sent, ["status", "status"])

    def test_read_then_change(self):
        conn, sent = self.connection("nmt")
        with self.assertRaises(diag.DiagError):
            conn.call("h", 1, "t", lambda c: (c.status(), c.nmt(5, "stop")))
        self.assertEqual(sent, ["status", "nmt"])


if __name__ == "__main__":
    unittest.main()
