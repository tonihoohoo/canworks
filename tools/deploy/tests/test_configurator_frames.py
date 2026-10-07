"""The configurator's Send panel and bit rate detection API against a fake
plugin (add-raw-frames-bitrate-detect task 3.2)."""

import time

from .fake_diag import TWO_NETWORKS, FakePlugin
from .test_configurator_online import Online


class SendFrames(Online):
    def test_single_frame(self):
        with FakePlugin(allow_changes=True) as fp:
            self.connect(fp)
            self.assertEqual(self.ok("POST", "/api/online/send_frame", {"id": "60A", "data": "40 18 10 01"}),
                             {"sent": True})
            self.ok("POST", "/api/online/send_frame", {"id": "0x7F0", "rtr": True, "dlc": 2})
            self.ok("POST", "/api/online/send_frame", {"id": "1ABCDEF", "ext": True, "data": "01"})
        self.assertEqual([(f["id"], f["rtr"], f["dlc"], f["data"]) for f in fp.sent],
                         [(0x60A, False, 4, "40 18 10 01"), (0x7F0, True, 2, ""), (0x1ABCDEF, False, 1, "01")])
        self.assertTrue(fp.sent[2]["ext"])

    def test_checked_before_sending(self):
        with FakePlugin(allow_changes=True) as fp:
            self.connect(fp)
            for body, why in (({"id": "XYZ"}, "not hexadecimal"), ({"id": "800"}, "out of range"),
                              ({"id": "60A", "data": "00 11 22 33 44 55 66 77 88"}, "at most 8"),
                              ({"id": "60A", "rtr": True}, "DLC"), ({"id": "60A", "period_ms": 5}, "10-60000"),
                              ({"id": "60A", "period_ms": 100, "count": 0.5}, "count")):
                status, data, _ = self.request("POST", "/api/online/send_frame", body)
                self.assertEqual(status, 422, body)
                self.assertIn(why, data["error"])
            self.assertEqual(fp.sent, [])

    def test_refusals_and_force(self):
        with FakePlugin(allow_changes=False) as fp:
            self.connect(fp)
            status, data, _ = self.request("POST", "/api/online/send_frame", {"id": "60A"})
            self.assertEqual((status, data["error"], data["force"]), (422, "changes not allowed", False))
        with FakePlugin(allow_changes=True) as fp:
            self.connect(fp)
            status, data, _ = self.request("POST", "/api/online/send_frame", {"id": "205", "data": "01"})
            self.assertEqual((status, data["error"], data["force"]),
                             (422, "0x205 is RPDO1 of node 5; force needed", True))
            self.assertEqual(fp.sent, [])
            self.ok("POST", "/api/online/send_frame", {"id": "205", "data": "01", "force": True})
            self.assertTrue(fp.sent[0]["forced"])

    def test_older_plugin(self):
        with FakePlugin(allow_changes=True) as fp:
            fp.send_supported = fp.detect_supported = False
            self.connect(fp)
            for path in ("/api/online/send_frame", "/api/online/detect_bitrate"):
                status, data, _ = self.request("POST", path, {"id": "60A"})
                self.assertEqual((status, data["kind"]), (422, "too_old"))
                self.assertIn("too old for sending frames", data["error"])

    def test_cyclic_jobs(self):
        with FakePlugin(allow_changes=True) as fp:
            self.connect(fp)
            self.assertEqual(self.ok("POST", "/api/online/send_jobs", {}), {"jobs": [], "ended": []})
            self.assertEqual(fp.connections, 0)  # nothing to poll opens no connection
            r = self.ok("POST", "/api/online/send_frame", {"id": "60A", "data": "01", "period_ms": 50})
            self.assertEqual((r["job"], r["period_ms"], r["count"]), (1, 50, None))
            self.ok("POST", "/api/online/send_frame", {"id": "60B", "period_ms": 10, "count": 3})
            # The online view's connection closing does not stop them.
            self.ok("POST", "/api/online/status", {})
            self.ok("POST", "/api/online/close", {})
            time.sleep(0.2)
            r = self.ok("POST", "/api/online/send_jobs", {})
            self.assertEqual([j["job"] for j in r["jobs"]], [1])
            self.assertGreater(r["jobs"][0]["sent"], 1)
            self.assertEqual([(j["job"], j["sent"], j["reason"]) for j in r["ended"]], [(2, 3, "count reached")])
            r = self.ok("POST", "/api/online/send_stop", {})
            self.assertEqual([(s["job"], s["reason"]) for s in r["stopped"]], [(1, "stopped")])
            self.assertEqual(self.ok("POST", "/api/online/send_jobs", {}), {"jobs": [], "ended": []})
            # One job by its number.
            r = self.ok("POST", "/api/online/send_frame", {"id": "60A", "period_ms": 100})
            r = self.ok("POST", "/api/online/send_stop", {"job": r["job"]})
            self.assertEqual([s["job"] for s in r["stopped"]], [3])
            self.assertEqual(self.request("POST", "/api/online/send_stop", {"job": "x"})[0], 400)

    def test_jobs_end_with_the_connection(self):
        with FakePlugin(allow_changes=True) as fp:
            self.connect(fp)
            self.server.sender.connection.idle = 0.3
            self.ok("POST", "/api/online/send_frame", {"id": "60A", "period_ms": 100})
            time.sleep(0.7)  # the page stopped polling: the connection closes, the plugin ends the job
            self.assertEqual(fp.jobs[1]["reason"], "client disconnected")
            r = self.ok("POST", "/api/online/send_jobs", {})
            self.assertEqual([(j["job"], j["reason"]) for j in r["ended"]], [(1, "connection closed")])
            # A new host closes the send connection too.
            self.ok("POST", "/api/online/send_frame", {"id": "60A", "period_ms": 100})
            self.ok("POST", "/api/online/settings", {"host": fp.runtime})
            time.sleep(0.1)
            self.assertEqual(fp.jobs[2]["reason"], "client disconnected")

    def test_picked_network(self):
        with FakePlugin(allow_changes=True, networks=TWO_NETWORKS) as fp:
            self.connect(fp)
            self.ok("POST", "/api/online/send_frame", {"id": "60A", "network": "drives"})
            r = self.ok("POST", "/api/online/send_frame", {"id": "60A", "period_ms": 100, "network": "drives"})
            self.assertEqual(fp.sent[0]["network"], "drives")
            self.assertEqual(fp.jobs[r["job"]]["frame"]["network"], "drives")
            jobs = self.ok("POST", "/api/online/send_jobs", {})["jobs"]
            self.assertEqual((jobs[0]["network"], jobs[0]["id"]), ("drives", 0x60A))
            self.assertEqual(len(self.ok("POST", "/api/online/send_stop", {})["stopped"]), 1)


class DetectBitrate(Online):
    def sweep(self, **body):
        r = self.ok("POST", "/api/online/detect_bitrate", body)
        while r["running"]:
            r = self.ok("POST", "/api/online/detect_bitrate_status", {})
        return r

    def test_detected(self):
        with FakePlugin(allow_changes=True) as fp:
            self.connect(fp)
            self.assertEqual(self.ok("POST", "/api/online/detect_bitrate_status", {}),
                             {"running": False, "verdict": None})
            r = self.sweep(rounds=2)
            self.assertEqual((r["verdict"], r["bitrate_kbit"], r["matches_config"]), ("detected", 250, False))
            self.assertEqual([x["bitrate_kbit"] for x in r["results"]], [1000, 800, 500, 250, 125, 50, 20, 10])
            self.assertEqual(fp.sweeps[0]["rounds"], 2)
            fp.sweep_hears = {}
            self.assertEqual(self.sweep()["verdict"], "silent")
            for body in ({"rates": [300]}, {"rates": "all"}, {"rounds": 0}):
                self.assertEqual(self.request("POST", "/api/online/detect_bitrate", body)[0], 400, body)

    def test_refusals(self):
        with FakePlugin(allow_changes=True) as fp:
            self.connect(fp)
            fp.operational = 5
            status, data, _ = self.request("POST", "/api/online/detect_bitrate", {})
            self.assertEqual((status, data["force"]), (422, True))
            self.assertIn("node 5 is OPERATIONAL", data["error"])
            self.assertEqual(self.sweep(force=True)["verdict"], "detected")
            self.assertTrue(fp.sweeps[0]["force"])
            fp.sweep = None
            fp.detect_refusal = "no bit rate on a virtual bus"
            status, data, _ = self.request("POST", "/api/online/detect_bitrate", {"force": True})
            self.assertEqual((status, data["error"], data["force"]), (422, "no bit rate on a virtual bus", False))
