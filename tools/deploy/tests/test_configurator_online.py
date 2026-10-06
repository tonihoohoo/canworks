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

from openplc_canopen_deploy import diag
from openplc_canopen_deploy.configurator import online

from .fake_diag import TOKEN, FakePlugin, closed_port
from .helpers import PINGPONG, REPO, tmpdir
from .test_configurator_server import RTD, Running, read, rtd_node

DIAG = {"token_sha256": diag.hash_token(TOKEN)}


class Online(Running):
    def setUp(self):
        super().setUp()
        self.open_project()
        self.canopen = os.path.join(self.project, "canopen")

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
        self.assertEqual(r["token_sha256"], hashlib.sha256(r["token"].encode()).hexdigest())
        cfg = self.pingpong(diagnostics=False)
        cfg["master"]["diagnostics"] = {"token_sha256": r["token_sha256"]}
        self.save(cfg)
        saved = read(os.path.join(self.canopen, "canopen.json"), "r")
        self.assertIn(r["token_sha256"], saved)
        for root, _, names in os.walk(self.project):
            for name in names:
                self.assertNotIn(r["token"].encode(), read(os.path.join(root, name)), name)
        settings = os.path.join(self.dir, "cfg", "online.json")
        self.assertIn(r["token"], read(settings, "r"))
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(os.stat(settings).st_mode), 0o600)
        self.assertEqual(self.ok("GET", "/api/online/settings")["token"], r["token"])

    def test_token_from_another_pc_checked_against_the_hash(self):
        status, data, _ = self.request("POST", "/api/online/token",
                                       {"action": "set", "token": "wrong", "token_sha256": DIAG["token_sha256"]})
        self.assertEqual(status, 422)
        self.assertIn("does not match", data["error"])
        self.assertIsNone(self.ok("GET", "/api/online/settings")["token"])
        self.ok("POST", "/api/online/token", {"action": "set", "token": TOKEN, "token_sha256": DIAG["token_sha256"]})
        self.assertEqual(self.ok("GET", "/api/online/settings")["token"], TOKEN)
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
            raw = read(os.path.join(self.canopen, "canopen.json"))
            fp.status["config_sha256"] = hashlib.sha256(raw).hexdigest()
            self.assertEqual(self.ok("POST", "/api/online/status", {})["config"], "same")
            self.assertEqual(fp.connections, 1)  # kept open between refreshes

    def test_fingerprint_of_the_deployed_file(self):
        self.save(self.pingpong())
        path = os.path.join(self.canopen, "canopen.json")
        # What the deploy tool and the editor hook write as conf/canopen.json.
        import sys
        sys.path.insert(0, os.path.join(REPO, "tools", "editor-hook"))
        self.addCleanup(sys.path.remove, os.path.join(REPO, "tools", "editor-hook"))
        from openplc_canopen_deploy import bundle
        deployed, _ = bundle.rewrite(json.loads(read(path, "r")), path)
        text = json.dumps(deployed, indent=2) + "\n"
        self.assertIn(hashlib.sha256(text.encode()).hexdigest(), online.fingerprints(path))

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
        self.assertEqual(m[0]["vendor_name"], "openplc-canopen test devices")
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
        cfg["nodes"].append({"node_id": 40, "name": "rtd", "eds": "rtd-rev2.eds", "revision_number": 0x00010002,
                             "serial_number": 99})
        self.save(cfg)
        self.assertIn("rtd-rev2.eds", os.listdir(self.canopen))
        # A file in canopen/ is used as it is.
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


class Helpers(unittest.TestCase):
    def test_device_info(self):
        from openplc_canopen_deploy import eds
        info = eds.device_info(os.path.join(RTD, "rtd8.eds"))
        self.assertEqual((info["vendor_id"], info["product_code"], info["revision_number"]),
                         (0xF0F0F0, 0x404, 0x00010003))
        self.assertIsNone(eds.device_info(os.path.join(tmpdir(self), "missing.eds")))

    def test_expected_identity(self):
        exp = online.expected_identity({"revision_number": "0x10", "serial_number": 0},
                                       os.path.join(PINGPONG, "cpp-slave.eds"))
        self.assertEqual(exp, {"vendor_id": 0x360, "product_code": 0, "revision_number": 16})


if __name__ == "__main__":
    unittest.main()
