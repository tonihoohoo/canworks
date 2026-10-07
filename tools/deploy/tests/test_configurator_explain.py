"""The configurator's frame explanations on the server: the inspector on
trace rows, the Sequences tab and the Frame lab (add-frame-inspector
tasks 4.1-4.3)."""

from .test_configurator_trace import Trace


class Inspector(Trace):
    def test_explain_a_trace_row(self):
        cfg = self.pingpong()
        self.save(cfg)
        self.open_sample()
        rows = self.ok("POST", "/api/trace/frames", {"offset": 0, "count": 20})["rows"]
        tpdo = next(r for r in rows if r["id"] == "182")
        m = self.ok("POST", "/api/trace/explain", {"seq": tpdo["seq"]})
        self.assertEqual((m["kind"], m["seq"], m["dir"]), ("pdo", tpdo["seq"], "Rx"))
        self.assertEqual(m["identifier"]["node"], 2)
        self.assertEqual(m["wire"]["bitrate"], 125000)  # a candump log has none: the saved config's
        self.assertFalse(m["wire"]["bitrate_assumed"])
        answer = next(r for r in rows if r["id"] == "582")
        m = self.ok("POST", "/api/trace/explain", {"seq": answer["seq"]})
        self.assertEqual(m["kind"], "sdo")
        self.assertIn("1018h:04", m["meaning"])
        m = self.ok("POST", "/api/trace/explain", {"seq": tpdo["seq"], "bitrate": 1000000})
        self.assertEqual(m["wire"]["bitrate"], 1000000)
        status, data, _ = self.request("POST", "/api/trace/explain", {"seq": 9999})
        self.assertEqual(status, 404, data)

    def test_sequences(self):
        self.open_sample(self.pingpong())
        sdo = self.ok("POST", "/api/trace/sequence", {"kind": "sdo"})
        self.assertEqual(sdo["total"], 2)
        self.assertEqual([c["result"] for c in sdo["conversations"]], ["done", "aborted"])
        self.assertEqual(sdo["nodes"], [2])
        self.assertEqual(self.ok("POST", "/api/trace/sequence", {"kind": "sdo", "node": 3})["total"], 0)
        sync = self.ok("POST", "/api/trace/sequence", {"kind": "sync"})
        self.assertEqual((sync["count"], sync["cycle"]["n"]), (5, 0))
        self.assertEqual(sync["period_min_us"], 10000)
        groups = [r["group"] for r in sync["cycle"]["frames"]]
        self.assertEqual(groups[0], "sync")
        last = self.ok("POST", "/api/trace/sequence", {"kind": "sync", "n": "slowest"})
        self.assertEqual(last["cycle"]["n"], last["slowest"])
        boot = self.ok("POST", "/api/trace/sequence", {"kind": "boot"})
        self.assertEqual(boot["kind"], "boot")
        status, _, _ = self.request("POST", "/api/trace/sequence", {"kind": "nope"})
        self.assertEqual(status, 400)


class FrameLab(Trace):
    def test_explain_typed_frames(self):
        cfg = self.pingpong()
        r = self.ok("POST", "/api/explain", {"frame": "182#05000000", "config": cfg})
        m = r["explanation"]
        self.assertEqual((m["kind"], m["candump"]), ("pdo", "182#05000000"))
        self.assertTrue(any("sent from slave" in (f.get("object_name") or "") or "sent" in f["name"]
                            for f in m["fields"]), m["fields"])
        r = self.ok("POST", "/api/explain", {"frame": "000#0100", "bitrate": 250000})
        self.assertEqual(r["explanation"]["wire"]["bitrate"], 250000)
        self.assertEqual(r["bitrate_from"], "chosen")
        status, data, _ = self.request("POST", "/api/explain", {"frame": "185#123"})
        self.assertEqual((status, data["field"]), (422, "frame"))
        self.assertIn("whole bytes", data["error"])

    def test_build_frames(self):
        cfg = self.pingpong()
        ex = self.ok("POST", "/api/explain/build", {"what": "examples", "config": cfg})["examples"]
        self.assertIn("SYNC", [e["label"] for e in ex])
        pdos = self.ok("POST", "/api/explain/build", {"what": "pdos", "config": cfg})
        self.assertTrue(pdos["pdos"] and pdos["nodes"][0]["node"] == 2)
        r = self.ok("POST", "/api/explain/build", {"what": "sdo", "config": cfg, "node": 2, "index": "0x1017",
                                                   "subindex": 0, "op": "write", "value": "1000"})
        self.assertEqual([f["frame"] for f in r["frames"]], ["602#2B171000E8030000", "582#6017100000000000"])
        self.assertEqual(r["frames"][0]["explanation"]["kind"], "sdo")
        status, data, _ = self.request("POST", "/api/explain/build", {"what": "heartbeat", "node": 200})
        self.assertEqual((status, data["field"]), (422, "node"))
        r = self.ok("POST", "/api/explain/build", {"what": "nmt", "command": "start", "node": 0})
        self.assertEqual(r["frames"][0]["frame"], "000#0100")

    def test_no_runtime_needed(self):
        # The Frame lab never asks for online access: no runtime is set up here.
        r = self.ok("POST", "/api/explain", {"frame": "705#05"})
        self.assertEqual(r["explanation"]["kind"], "heartbeat")


class SequenceAt(Trace):
    def test_sequence_holding_a_frame(self):
        self.open_sample(self.pingpong())
        rows = self.ok("POST", "/api/trace/frames", {"offset": 0, "count": 30})["rows"]
        answer = next(r for r in rows if r["id"] == "582")
        sdo = self.ok("POST", "/api/trace/sequence", {"kind": "sdo", "at": answer["seq"]})
        self.assertEqual(sdo["selected"], sdo["conversations"][0]["seq"])
        tpdo = [r for r in rows if r["id"] == "182"][2]
        sync = self.ok("POST", "/api/trace/sequence", {"kind": "sync", "at": tpdo["seq"]})
        self.assertEqual(sync["cycle"]["n"], 2)
