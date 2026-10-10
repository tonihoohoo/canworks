"""The configurator's routes for writing a configuration to a device,
restore defaults and the PDO test (add-device-commissioning task 4), on a
USB adapter target on python-can's virtual bus. No CAN hardware."""

import base64
import json
import os
import shutil
import struct
import time
import unittest

from canworks import dcfexport

from .test_commissioning import FIXED_IO, IDENTITY, RTD, fixed_io_od, rtd_od
from .test_configurator_localbus import AdapterTarget as _Target


class AdapterTarget(_Target):
    """The adapter target's fixtures without its tests."""


for _name in [n for n in dir(_Target) if n.startswith("test_")]:
    setattr(AdapterTarget, _name, None)


class Commissioning(AdapterTarget):
    def setUp(self):
        super().setUp()
        self.assertEqual(self.eds(os.path.join(RTD, "rtd8.eds"))[0], 200)
        with open(os.path.join(RTD, "canopen_config.json"), encoding="utf-8") as f:
            self.cfg = json.load(f)

    def rtd(self, node=5, **kw):
        od, ro = rtd_od(node)
        od.update(kw.pop("od", {}))
        kw.setdefault("identity", IDENTITY)
        return self.device(node, od=od, ro=ro, nvm=True, **kw)

    def body(self, **extra):
        return dict({"node": 5, "config": self.cfg}, **extra)

    def job(self, data, cancel=False):
        job_id = data["job"]["id"]
        end = time.monotonic() + 15
        while True:
            j = self.ok("POST", "/api/online/job", {"id": job_id, "cancel": cancel})["job"]
            if j["state"] != "running" or time.monotonic() > end:
                return j
            time.sleep(0.05)

    def preview(self, **extra):
        j = self.job(self.ok("POST", "/api/online/configure_plan", self.body(**extra)))
        self.assertEqual(j["state"], "done", j)
        return j


class WriteConfiguration(Commissioning):
    def test_preview_write_store_and_verify(self):
        dev = self.rtd(od={(0x1800, 2): b"\x01"})
        self.use_adapter(allow=True)
        plan = self.preview(source="config", from_node=5)
        r = plan["result"]
        self.assertTrue(r["allow_changes"] and r["local"] and r["has_store"] and r["has_restore"])
        self.assertIsNone(r["refused"])
        self.assertGreater(r["writes"], 0)
        tpdo = [s for s in r["steps"] if s["group"] == "TPDO1" and s["send"]]
        self.assertEqual(tpdo[0]["role"], "off")
        self.assertEqual((tpdo[-1]["index"], tpdo[-1]["subindex"]), (0x1800, 1))
        self.assertFalse([s for s in r["steps"] if s["index"] in (0x1010, 0x1011)])

        res = self.job(self.ok("POST", "/api/online/configure", self.body(plan=plan["id"], store=True)))
        self.assertEqual(res["state"], "done", res)
        self.assertTrue(res["result"]["verified"], res["result"])
        self.assertTrue(res["result"]["store"]["stored"])
        self.assertEqual(dev.od[(0x6110, 1)], struct.pack("<H", 30))
        # One write per preview.
        self.assertEqual(self.request("POST", "/api/online/configure", self.body(plan=plan["id"]))[0], 409)

        dev.power_cycle()
        v = self.job(self.ok("POST", "/api/online/configure_verify", self.body(source="config", from_node=5)))
        self.assertEqual(v["state"], "done", v)
        self.assertEqual(v["result"]["differences"], [])

    def test_from_a_dcf_without_store_then_verify_after_power_cycle(self):
        dev = self.rtd()
        self.use_adapter(allow=True)
        files, _ = dcfexport.export(self.cfg, os.path.join(RTD, "canopen_config.json"))
        dcf = base64.b64encode(next(iter(files.values())).encode()).decode()
        plan = self.preview(source="dcf", file=dcf, file_name="node5.dcf")
        res = self.job(self.ok("POST", "/api/online/configure", self.body(plan=plan["id"])))
        self.assertTrue(res["result"]["verified"], res["result"])
        self.assertIsNone(res["result"]["store"])
        dev.power_cycle()
        v = self.job(self.ok("POST", "/api/online/configure_verify", self.body(source="dcf", file=dcf)))
        self.assertTrue(v["result"]["differences"])

    def test_identity_refused_and_changes_off(self):
        self.rtd(identity=(0x123, 0x404, 1, 1))
        self.use_adapter()
        plan = self.preview(source="config", from_node=5)
        self.assertIn("vendor", plan["result"]["refused"])
        self.assertFalse(plan["result"]["allow_changes"])
        status, data, _ = self.request("POST", "/api/online/configure", self.body(plan=plan["id"]))
        self.assertEqual((status, data["error"]), (422, "changes not allowed"))
        self.ok("POST", "/api/online/settings", {"allow_changes": True})
        plan = self.preview(source="config", from_node=5)
        status, data, _ = self.request("POST", "/api/online/configure", self.body(plan=plan["id"]))
        self.assertEqual(status, 422)
        self.assertIn("refused", data["error"])
        plan = self.preview(source="config", from_node=5, ignore_identity=True)
        self.assertIsNone(plan["result"]["refused"])

    def test_bad_requests(self):
        self.rtd()
        self.use_adapter(allow=True)
        self.assertEqual(self.request("POST", "/api/online/configure_plan", self.body(source="x"))[0], 400)
        self.assertEqual(self.request("POST", "/api/online/configure_plan",
                                      self.body(source="config", from_node=9))[0], 422)
        self.assertEqual(self.request("POST", "/api/online/configure", self.body(plan=999))[0], 409)


class RestoreDefaults(Commissioning):
    def test_restore_and_reset(self):
        dev = self.rtd(od={(0x6110, 1): b"\x10\x00"})
        self.use_adapter(allow=True)
        e = self.ok("POST", "/api/online/od_entries", self.body())
        self.assertTrue(e["has_restore"])
        self.assertIn(1, e["restore_subindices"])
        r = self.ok("POST", "/api/online/restore_defaults", self.body(subindex=1, reset=True))
        self.assertTrue(r["restored"] and r["reset"])
        self.assertEqual(self.request("POST", "/api/online/restore_defaults", self.body(subindex=0))[0], 400)

    def test_needs_allow_changes(self):
        self.rtd()
        self.use_adapter()
        status, data, _ = self.request("POST", "/api/online/restore_defaults", self.body())
        self.assertEqual((status, data["error"]), (422, "changes not allowed"))


class PdoTestRoutes(AdapterTarget):
    def setUp(self):
        super().setUp()
        os.makedirs(self.canopen, exist_ok=True)
        shutil.copy(FIXED_IO, self.canopen)

    def test_layout_values_sync_and_stop(self):
        dev = self.device(5, od=fixed_io_od(), pdo=True, nmt_state=127)
        self.use_adapter(allow=True)
        body = {"node": 5, "eds_path": os.path.basename(FIXED_IO)}
        r = self.ok("POST", "/api/online/pdo_test_start", dict(body, start=True))
        self.assertEqual(r["source"], "device")
        self.assertEqual([p["name"] for p in r["rpdos"]], ["RPDO1"])
        self.ok("POST", "/api/online/sync_start", {"node": 5, "period_ms": 50})
        self.ok("POST", "/api/online/pdo_test_set", {"node": 5, "rpdo": 1, "values": {"0x6200:1": "15"}})
        time.sleep(0.5)
        st = self.ok("POST", "/api/online/pdo_test_status", {"node": 5})
        self.assertTrue(st["running"])
        self.assertGreater(st["tpdos"][0]["count"], 0)
        self.assertEqual(dev.od[(0x6200, 1)], b"\x0f")
        self.assertTrue(st["sync"]["running"])
        self.ok("POST", "/api/online/sync_stop", {"node": 5})
        self.ok("POST", "/api/online/pdo_test_stop", {"node": 5})
        self.assertFalse(self.ok("POST", "/api/online/pdo_test_status", {"node": 5})["running"])

    def test_needs_an_adapter_and_changes(self):
        self.device(5, od=fixed_io_od(), pdo=True)
        self.use_adapter()
        status, data, _ = self.request("POST", "/api/online/pdo_test_start",
                                       {"node": 5, "eds_path": os.path.basename(FIXED_IO)})
        self.assertEqual(status, 422)
        self.assertIn("changes not allowed", data["error"])


class LoneDetect(AdapterTarget):
    """The connection form's lone-device sweep goes through the guards of
    canworks-diag's (localbus/client.py _lone_fields), whatever the page sends."""

    def detect(self, **body):
        return self.request("POST", "/api/online/adapter_detect",
                            dict({"adapter": "virtual:" + self.ch, "adapter_bitrate": 250, "lone_device": True}, **body))

    def test_two_devices_refused(self):
        devices = [self.device(5, heartbeat_s=0.01), self.device(7, heartbeat_s=0.01)]
        self.ok("POST", "/api/online/settings", {"allow_changes": True})
        status, data, _ = self.detect()
        self.assertEqual(status, 422, data)
        self.assertIn("more than one node is on the bus (heard nodes 5, 7", data["error"])
        self.assertIsNone(self.server.adapter_sweep)
        time.sleep(0.1)
        for d in devices:
            self.assertEqual([m for m in d.received if m.arbitration_id not in (0x705, 0x707)], [], "nothing sent")

    def test_needs_allow_changes(self):
        status, data, _ = self.detect()
        self.assertEqual(status, 422, data)
        self.assertIn("changes not allowed", data["error"])
        self.assertIsNone(self.server.adapter_sweep)

    def test_needs_a_bit_rate_to_listen_at(self):
        self.ok("POST", "/api/online/settings", {"allow_changes": True})
        status, data, _ = self.detect(adapter_bitrate=0)
        self.assertEqual(status, 422, data)
        self.assertIn("bit rate", data["error"])
        self.assertIsNone(self.server.adapter_sweep)

    def test_connection_form_lone_device(self):
        self.ok("POST", "/api/online/settings", {"allow_changes": True})
        r = self.ok("POST", "/api/online/adapter_detect", {"adapter": "virtual:" + self.ch, "adapter_bitrate": 250,
                                                           "lone_device": True})
        self.assertTrue(r["lone_device"])
        self.server.adapter_sweep.stop()


del _Target

if __name__ == "__main__":
    unittest.main()
