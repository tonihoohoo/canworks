"""The configurator's device parameter routes: object dictionary entries and
reads, backup, compare, restore and store as jobs (add-device-parameters
task 4.1), against the fake diagnostics channel."""

import base64
import json
import os
import time
import unittest

from .test_configurator_online import DIAG, Online
from .test_configurator_server import RTD
from .test_parameters import NODE, FakeDevice


def rtd_config():
    with open(os.path.join(RTD, "canopen_config.json"), encoding="utf-8") as f:
        cfg = json.load(f)
    cfg["master"]["diagnostics"] = dict(DIAG)
    cfg["nodes"][0]["sdo_variables"] = [{"name": "alarm_limit", "index": "0x6126", "subindex": 2, "type": "REAL32",
                                         "direction": "write", "iec_location": "%QD100"}]
    return cfg


class Params(Online):
    def setUp(self):
        super().setUp()
        self.assertEqual(self.eds(os.path.join(RTD, "rtd8.eds"))[0], 200)
        self.cfg = rtd_config()

    def body(self, **extra):
        return dict({"node": NODE, "config": self.cfg}, **extra)

    def job(self, data, cancel=False):
        """Waits for a job a route started and returns its final state."""
        job_id = data["job"]["id"]
        end = time.monotonic() + 15
        while True:
            j = self.ok("POST", "/api/online/job", {"id": job_id, "cancel": cancel})["job"]
            if j["state"] != "running" or time.monotonic() > end:
                return j
            time.sleep(0.05)

    def backup(self, fp):
        j = self.job(self.ok("POST", "/api/online/backup", self.body()))
        self.assertEqual(j["state"], "done", j)
        return j["result"]


class Entries(Params):
    def test_grouped_with_marks(self):
        with FakeDevice() as fp:
            self.connect(fp)
            r = self.ok("POST", "/api/online/od_entries", self.body())
            by = {(e["index"], e["subindex"]): e for e in r["entries"]}
            self.assertEqual(by[(0x1018, 1)]["group"], "communication")
            self.assertEqual(by[(0x6110, 1)]["group"], "profile")
            self.assertTrue(by[(0x6110, 1)]["config"])  # startup SDO
            self.assertEqual(by[(0x6126, 2)]["sdo_variable"], "alarm_limit")
            self.assertTrue(r["configured"])
            self.assertEqual(r["has_store"], "0x1010" in "".join("0x%04X" % e["index"] for e in r["entries"]))

    def test_tree_limits_and_pdo_marks(self):
        """improve-od-browser 1.2."""
        with FakeDevice() as fp:
            self.connect(fp)
            r = self.ok("POST", "/api/online/od_entries", self.body())
            by = {(e["index"], e["subindex"]): e for e in r["entries"]}
            self.assertEqual(by[(0x6110, 1)]["object_type"], "ARRAY")
            self.assertEqual(by[(0x1000, 0)]["object_type"], "VAR")
            self.assertEqual(by[(0x1018, 1)]["object_type"], "RECORD")
            self.assertEqual(by[(0x6110, 1)]["sub_name"], "AI0_Sensor_Type")
            self.assertEqual(by[(0x6110, 1)]["name"], "AI Sensor Type: AI0_Sensor_Type")  # unchanged
            self.assertEqual((by[(0x6110, 1)]["low_limit"], by[(0x6110, 1)]["high_limit"]), (30, 33))
            self.assertEqual(by[(0x7130, 1)]["pdo"], [{"pdo": "TPDO1", "bits": [0, 15], "location": "%IW100"}])
            self.assertEqual(by[(0x7130, 2)]["pdo"][0]["bits"], [16, 31])
            self.assertNotIn("pdo", by[(0x6110, 1)])
            # A draft whose PDOs cannot be read yet gives no marks but still the tab.
            self.cfg["nodes"][0]["tx_pdos"][0]["entries"][0] = {"index": "0x7130"}
            r = self.ok("POST", "/api/online/od_entries", self.body())
            self.assertFalse(any("pdo" in e for e in r["entries"]))
            # A scanned node has no PDO marks.
            self.ok("POST", "/api/online/settings", {"eds_library": RTD})
            r = self.ok("POST", "/api/online/od_entries", {"node": NODE, "eds_path": os.path.join(RTD, "rtd8.eds")})
            self.assertFalse(any("pdo" in e for e in r["entries"]))

    def test_scanned_node_from_eds_path(self):
        with FakeDevice() as fp:
            self.connect(fp)
            self.ok("POST", "/api/online/settings", {"eds_library": RTD})
            r = self.ok("POST", "/api/online/od_entries",
                        {"node": NODE, "eds_path": os.path.join(RTD, "rtd8.eds")})
            self.assertFalse(r["configured"])
            self.assertGreater(len(r["entries"]), 50)
            status, data, _ = self.request("POST", "/api/online/od_entries", {"node": NODE, "eds_path": "/etc/passwd"})
            self.assertEqual(status, 403)
            status, data, _ = self.request("POST", "/api/online/od_entries", {"node": 9})
            self.assertEqual(status, 422)
            self.assertIn("has no EDS", data["error"])


class Reads(Params):
    def test_read_keys_and_all(self):
        with FakeDevice() as fp:
            self.connect(fp)
            r = self.ok("POST", "/api/online/od_read", self.body(keys=[["0x1018", 1], [0x6000, 9]]))
            self.assertEqual(r["values"][0]["text"], "405 (0x00000195)")
            self.assertEqual(r["failures"][0]["abort_code"], 0x06020000)
            self.assertEqual(self.request("POST", "/api/online/od_read", self.body(keys=[[1, 0]] * 65))[0], 400)
            j = self.job(self.ok("POST", "/api/online/od_read", self.body(all=True)))
            self.assertEqual(j["state"], "done")
            self.assertEqual(j["result"]["failed"], 0)
            self.assertEqual(j["done"], j["total"])
            self.assertEqual(j["result"]["read"], j["total"])

    def test_one_job_at_a_time_and_cancel(self):
        with FakeDevice() as fp:
            self.connect(fp)
            fp.delay = 0.02
            first = self.ok("POST", "/api/online/od_read", self.body(all=True))
            status, data, _ = self.request("POST", "/api/online/backup", self.body())
            self.assertEqual(status, 409)
            j = self.job(first, cancel=True)
            self.assertEqual(j["state"], "cancelled")
            self.assertTrue(j["result"]["cancelled"])
            self.assertLess(j["result"]["read"], j["total"])
            # A reloaded page finds the last job without its ID.
            self.assertEqual(self.ok("POST", "/api/online/job", {})["job"]["id"], first["job"]["id"])


class BackupCompareRestore(Params):
    def test_round_trip(self):
        with FakeDevice() as fp:
            fp.set(0x1010, 1, b"\0\0\0\0")
            self.connect(fp)
            b = self.backup(fp)
            self.assertEqual(b["name"][:9], "node5-rtd")
            self.assertEqual((b["failed"], b["boot_state"]), (0, None))
            text = base64.b64decode(b["data"]).decode()
            self.assertIn("NodeName=rtd", text)

            orig = fp.value(0x6112, 3)
            fp.set(0x6112, 3, b"\x02")
            fp.set(0x6110, 1, b"\x10\x00")  # written by the config: never restored
            j = self.job(self.ok("POST", "/api/online/compare", self.body(reference="file", file=b["data"])))
            self.assertEqual(j["result"]["summary"]["different"], 2)
            self.assertEqual(j["result"]["rows"][0]["result"], "different")
            j = self.job(self.ok("POST", "/api/online/compare", self.body(reference="config")))
            rows = {(r["index"], r["subindex"]): r for r in j["result"]["rows"]}
            self.assertEqual(rows[(0x6110, 1)]["result"], "different")
            self.assertNotIn((0x6112, 3), rows)
            j = self.job(self.ok("POST", "/api/online/compare", self.body(reference="eds")))
            self.assertEqual(j["state"], "done")

            plan = self.job(self.ok("POST", "/api/online/restore_plan", self.body(file=b["data"])))
            self.assertEqual(plan["state"], "done", plan)
            self.assertEqual([(w["index"], w["subindex"]) for w in plan["result"]["writes"]], [(0x6112, 3)])
            reasons = {(s["index"], s["subindex"]): s["reason"] for s in plan["result"]["skipped"]}
            self.assertEqual(reasons[(0x6110, 1)], "written by the configuration at boot")
            self.assertTrue(plan["result"]["allow_changes"])

            fp.requests.clear()
            r = self.job(self.ok("POST", "/api/online/restore", self.body(plan=plan["id"], hold=True)))
            self.assertEqual(r["state"], "done", r)
            self.assertEqual(len(r["result"]["written"]), 1)
            self.assertTrue(r["result"]["released"])
            self.assertEqual(fp.value(0x6112, 3), orig)
            self.assertIn("not stored", r["result"]["note"])
            ops = [(q["op"], q.get("command")) for q in fp.requests if q.get("node") == NODE and q["op"] == "nmt"]
            self.assertEqual(ops, [("nmt", "preop"), ("nmt", "start")])
            self.assertNotIn((0x1010, 1), fp.sdo_requests("sdo_write"))
            # One restore per preview.
            self.assertEqual(self.request("POST", "/api/online/restore", self.body(plan=plan["id"]))[0], 409)

    def test_identity_needs_override(self):
        with FakeDevice() as fp:
            self.connect(fp)
            b = self.backup(fp)
            fp.set(0x1018, 2, (0x3E9).to_bytes(4, "little"))
            fp.set(0x6112, 3, b"\x02")
            plan = self.job(self.ok("POST", "/api/online/restore_plan", self.body(file=b["data"])))
            self.assertIn("product code differs", plan["result"]["refused"])
            status, data, _ = self.request("POST", "/api/online/restore", self.body(plan=plan["id"]))
            self.assertEqual(status, 422)
            self.assertFalse(fp.sdo_requests("sdo_write"))
            r = self.job(self.ok("POST", "/api/online/restore", self.body(plan=plan["id"], ignore_identity=True)))
            self.assertEqual(len(r["result"]["written"]), 1)

    def test_cancel_releases_the_hold(self):
        with FakeDevice() as fp:
            self.connect(fp)
            b = self.backup(fp)
            for sub in range(1, 9):
                fp.set(0x6112, sub, b"\x02")
            plan = self.job(self.ok("POST", "/api/online/restore_plan", self.body(file=b["data"])))
            fp.delay = 0.1
            r = self.job(self.ok("POST", "/api/online/restore", self.body(plan=plan["id"], hold=True)), cancel=True)
            self.assertEqual(r["state"], "cancelled")
            self.assertTrue(r["result"]["released"])
            self.assertLess(len(r["result"]["written"]), 8)
            nmt = [q["command"] for q in fp.requests if q.get("op") == "nmt" and q.get("node") == NODE]
            self.assertEqual(nmt, ["preop", "start"])


class ReadOnly(Params):
    def test_restore_and_store_refused(self):
        with FakeDevice(allow_changes=False) as fp:
            self.connect(fp)
            b = self.backup(fp)
            plan = self.job(self.ok("POST", "/api/online/restore_plan", self.body(file=b["data"])))
            self.assertFalse(plan["result"]["allow_changes"])
            status, data, _ = self.request("POST", "/api/online/restore", self.body(plan=plan["id"]))
            self.assertEqual((status, data["error"]), (422, "changes not allowed"))
            status, data, _ = self.request("POST", "/api/online/store", self.body())
            self.assertEqual((status, data["error"]), (422, "changes not allowed"))


class Store(Params):
    def test_store_writes_save(self):
        with FakeDevice() as fp:
            fp.set(0x1010, 1, b"\0\0\0\0")
            self.connect(fp)
            r = self.ok("POST", "/api/online/store", self.body(subindex=1))
            self.assertTrue(r["stored"])
            self.assertEqual(fp.value(0x1010, 1), b"save")
            self.assertEqual(self.request("POST", "/api/online/store", self.body(subindex=0))[0], 400)


if __name__ == "__main__":
    unittest.main()


class WatchLists(Params):
    """improve-od-browser 1.3: watch lists kept in online.json on this PC."""

    def test_kept_per_node(self):
        self.assertEqual(self.ok("POST", "/api/online/watch", {"node": 5}), {"node": 5, "keys": [], "period_ms": 1000})
        r = self.ok("POST", "/api/online/watch", {"node": 5, "keys": [[0x7130, 1], [0x6110, 1], [0x7130, 1]],
                                                  "period_ms": 500})
        self.assertEqual(r["keys"], [[0x7130, 1], [0x6110, 1]])
        # A fresh read of the settings file (a new configurator) finds it again.
        from canworks.configurator import online
        from canworks.configurator.server import config_dir
        saved = online.Settings(config_dir()).project(self.project)
        self.assertEqual(saved["watch"]["5"], {"keys": [[0x7130, 1], [0x6110, 1]], "period_ms": 500})
        self.assertEqual(self.ok("POST", "/api/online/watch", {"node": 5})["period_ms"], 500)
        self.assertEqual(self.ok("POST", "/api/online/watch", {"node": 6})["keys"], [])
        status, data, _ = self.request("POST", "/api/online/watch", {"node": 5, "keys": [[0x2000, s] for s in range(33)]})
        self.assertEqual(status, 400)
        self.assertIn("at most 32", data["error"])
        self.assertEqual(self.request("POST", "/api/online/watch", {"node": 5, "keys": [], "period_ms": 100})[0], 400)
        self.assertEqual(self.request("POST", "/api/online/watch", {"node": 0})[0], 400)
        self.ok("POST", "/api/online/watch", {"node": 5, "keys": []})
        self.assertNotIn("watch", online.Settings(config_dir()).project(self.project))
