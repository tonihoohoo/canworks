"""The configurator's Trace view on the server: /api/trace/* against the fake
diagnostics channel and with opened files (add-bus-trace task 4.2)."""

import base64
import os
import time

from canworks.bustrace import formats
from canworks.bustrace.model import Frame

from .test_bustrace import T0, sample_trace, written
from .test_configurator_online import Online
from .fake_diag import FakePlugin


def b64(data):
    return base64.b64encode(data).decode("ascii")


class Trace(Online):
    def wait_for(self, cond, timeout=4.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            v = cond()
            if v:
                return v
            time.sleep(0.03)
        return False

    def state(self):
        return self.ok("GET", "/api/trace/state")

    def open_sample(self, cfg=None):
        body = {"name": "sample.log", "data": b64(written(sample_trace(), "candump"))}
        if cfg is not None:
            body["config"] = cfg
        return self.ok("POST", "/api/trace/open", body)


class Files(Trace):
    def test_open_decode_filter_and_export_without_a_runtime(self):
        cfg = self.pingpong()
        st = self.open_sample(cfg)
        self.assertEqual(st["source"], "sample.log")
        self.assertEqual(st["frames"], len(sample_trace()) - 1)  # the gap is not in a candump log
        self.assertEqual(st["recording"]["state"], "idle")
        self.assertIn("pingpong_TPDO1.UNSIGNED32_sent_from_slave", [s["key"] for s in st["series"]])
        rows = self.ok("POST", "/api/trace/frames", {"offset": 0, "count": 5})
        self.assertEqual(rows["total"], st["frames"])
        self.assertEqual(rows["rows"][0]["text"], "start node 2 (pingpong)")
        self.assertEqual(rows["rows"][2]["name"], "pingpong_RPDO1")
        sdo = self.ok("POST", "/api/trace/frames", {"filter": {"nodes": [2], "kinds": ["sdo"]}})
        self.assertEqual(sdo["total"], 4)
        self.assertTrue(all(r["kind"] == "sdo" for r in sdo["rows"]))
        self.assertIn("= 305419896", sdo["rows"][1]["text"])
        text = self.ok("POST", "/api/trace/frames", {"filter": {"text": "serial number"}})
        self.assertEqual(text["total"], 2)
        ids = self.ok("POST", "/api/trace/frames", {"filter": {"id_from": 0x180, "id_to": 0x1FF, "dir": "rx"}})
        self.assertEqual(ids["total"], 5)
        # Identifiers as the trace shows them: hex, with or without 0x.
        for lo, hi in (("180", "1FF"), ("0x180", "0x1ff")):
            hexed = self.ok("POST", "/api/trace/frames", {"filter": {"id_from": lo, "id_to": hi, "dir": "rx"}})
            self.assertEqual(hexed["total"], 5, (lo, hi))
        status, data, _ = self.request("POST", "/api/trace/frames", {"filter": {"id_from": "18G"}})
        self.assertEqual(status, 400)
        self.assertEqual(data["error"], "ID from must be a hex identifier, e.g. 180 or 0x180")
        at = self.ok("POST", "/api/trace/frames", {"at_us": T0 + 300000, "count": 10})
        self.assertEqual(at["rows"][at["focus"] - at["offset"]]["kind"], "emcy")
        table = self.ok("POST", "/api/trace/ids", {})["ids"]
        self.assertEqual([r["id_text"] for r in table][:3], ["000", "080", "082"])
        series = self.ok("POST", "/api/trace/series", {"keys": ["pingpong_TPDO1.UNSIGNED32_sent_from_slave",
                                                                 "bus.rate"]})["series"]
        self.assertEqual(series["pingpong_TPDO1.UNSIGNED32_sent_from_slave"][1], [1, 2, 3, 4, 5])
        self.assertTrue(series["bus.rate"][1])
        for fmt in ("pcapng", "candump", "asc", "blf", "trc", "csv"):
            r = self.ok("POST", "/api/trace/export", {"format": fmt, "start_us": T0, "end_us": T0 + 55000})
            data = base64.b64decode(r["data"])
            self.assertTrue(r["name"].startswith("rtd-monitor-trace."), r["name"])
            if fmt in ("pcapng", "candump", "asc"):
                self.assertEqual(len([f for f in formats.read(data, r["name"]) if not f.gap]), 17, fmt)
        r = self.ok("POST", "/api/trace/export", {"format": "signals",
                                                  "keys": ["pingpong_TPDO1.UNSIGNED32_sent_from_slave"]})
        self.assertEqual(base64.b64decode(r["data"]).decode().count("\r\n"), 6)
        # Start needs online access; the opened file stays.
        status, data, _ = self.request("POST", "/api/trace/start", {})
        self.assertEqual((status, data["need"]), (409, "online"))
        self.assertEqual(self.state()["source"], "sample.log")

    def test_save_never_in_the_canopen_folder(self):
        self.open_sample()
        r = self.ok("POST", "/api/trace/save", {"format": "blf"})
        self.assertTrue(r["path"].startswith(os.path.join(self.dir, "cfg", "traces", "rtd-monitor-trace-")), r)
        self.assertTrue(r["path"].endswith(".blf") and os.path.isfile(r["path"]))
        status, data, _ = self.request("POST", "/api/trace/save", {"folder": self.canopen})
        self.assertEqual(status, 422)
        self.assertIn("canworks folder", data["error"])
        status, _, _ = self.request("POST", "/api/trace/trigger", {"trigger": {
            "conditions": [{"type": "error_frame"}], "autosave": {"format": "log", "folder": self.canopen}}})
        self.assertEqual(status, 422)
        # Auto-save needs a full path to a folder that exists.
        for folder, why in (("relative/dir", "is not a full path"), (os.path.join(self.dir, "nonexistent"),
                                                                      "does not exist")):
            status, data, _ = self.request("POST", "/api/trace/trigger", {"trigger": {
                "conditions": [{"type": "error_frame"}], "autosave": {"format": "log", "folder": folder}}})
            self.assertEqual(status, 422, folder)
            self.assertIn(why, data["error"])

    def test_bad_files_and_clear(self):
        status, data, _ = self.request("POST", "/api/trace/open", {"name": "x.blf", "data": b64(b"LOGG" + bytes(200))})
        self.assertEqual(status, 422)
        self.assertIn("BLF files cannot be opened", data["error"])
        self.open_sample()
        st = self.ok("POST", "/api/trace/clear", {})
        self.assertEqual((st["frames"], st["source"]), (0, None))
        status, _, _ = self.request("POST", "/api/trace/export", {"format": "asc"})
        self.assertEqual(status, 409)


class Live(Trace):
    def setUp(self):
        super().setUp()
        self.fake = FakePlugin()
        self.fake.__enter__()
        self.addCleanup(self.fake.__exit__)
        self.connect(self.fake)
        self.cfg = self.pingpong()
        self.save(self.cfg)
        self.addCleanup(lambda: self.request("POST", "/api/trace/stop", {}))

    def test_record_filter_and_keep_over_reload(self):
        st = self.ok("POST", "/api/trace/start", {"filters": [{"id": 0x180, "mask": 0x780}], "error_frames": True,
                                                   "config": self.cfg})
        self.assertEqual(st["source"], "live")
        self.assertTrue(self.wait_for(lambda: self.state()["recording"]["state"] == "recording"))
        self.assertEqual(self.fake.trace_starts[-1]["filters"], [{"id": 0x180, "mask": 0x780}])
        now = int(time.time() * 1e6)
        self.fake.push([Frame(now + i * 10000, 0x182, bytes([i, 0, 0, 0])) for i in range(20)])
        self.assertTrue(self.wait_for(lambda: self.state()["frames"] == 20))
        rows = self.ok("POST", "/api/trace/frames", {"filter": {"kinds": ["pdo"]}, "count": 5, "offset": 18})
        self.assertEqual((rows["total"], rows["offset"], len(rows["rows"])), (20, 15, 5))
        self.assertEqual(rows["rows"][-1]["text"], "UNSIGNED32_sent_from_slave=19")
        # More frames extend the same filter view.
        self.fake.push([Frame(now + 300000, 0x182, bytes([99, 0, 0, 0]))])
        self.assertTrue(self.wait_for(lambda: self.ok("POST", "/api/trace/frames",
                                                      {"filter": {"kinds": ["pdo"]}})["total"] == 21))
        st = self.state()  # what a reloaded page reads
        self.assertTrue(st["recording"]["running"])
        self.assertTrue(self.wait_for(lambda: any(s["key"] == "sdovar.2.2001:0" for s in self.state()["series"])))
        status, _, _ = self.request("POST", "/api/trace/open", {"name": "a.log", "data": b64(b"")})
        self.assertEqual(status, 409)
        st = self.ok("POST", "/api/trace/stop", {})
        self.assertEqual(st["recording"]["state"], "stopped")
        self.assertEqual(st["frames"], 21)

    def test_old_plugin_and_wrong_token(self):
        self.fake.trace_supported = False
        status, data, _ = self.request("POST", "/api/trace/start", {})
        self.assertEqual((status, data["kind"]), (422, "too_old"))
        self.assertIn("too old for traces", data["error"])
        self.ok("POST", "/api/online/token", {"action": "set", "token": "wrong"})
        status, data, _ = self.request("POST", "/api/trace/start", {})
        self.assertEqual(status, 502)

    def test_single_trigger_stops_and_normal_trigger_saves(self):
        trig = {"conditions": [{"type": "emcy", "node": 2}], "mode": "single", "pre_s": 1, "post_s": 0}
        st = self.ok("POST", "/api/trace/start", {"trigger": trig})
        self.assertEqual(st["trigger_text"], "EMCY from node 2")
        self.assertTrue(self.wait_for(lambda: self.state()["recording"]["state"] == "recording"))
        now = int(time.time() * 1e6)
        self.fake.push([Frame(now, 0x182, bytes(4)), Frame(now + 1000, 0x082, bytes.fromhex("1050010000000000"))])
        st = self.wait_for(lambda: (lambda s: s if not s["recording"]["running"] else None)(self.state()))
        self.assertTrue(st)
        self.assertEqual(st["recording"]["message"], "stopped by the trigger")
        self.assertEqual([m["kind"] for m in st["markers"]], ["trigger"])
        # Normal mode: markers and an auto-saved window per hit, recording goes on.
        folder = os.path.join(self.dir, "auto")
        os.mkdir(folder)
        trig = {"conditions": [{"type": "frame", "id": "0x702"}], "mode": "normal", "pre_s": 1, "post_s": 0,
                "autosave": {"format": "log", "folder": folder}}
        self.ok("POST", "/api/trace/start", {"trigger": trig})
        self.assertTrue(self.wait_for(lambda: self.state()["recording"]["state"] == "recording"))
        now = int(time.time() * 1e6)
        self.fake.push([Frame(now, 0x702, bytes([5])), Frame(now + 1000, 0x182, bytes(4)),
                        Frame(now + 2000, 0x702, bytes([5])), Frame(now + 3000, 0x182, bytes(4))])
        st = self.wait_for(lambda: (lambda s: s if len(s["recording"]["saved"]) == 2 else None)(self.state()))
        self.assertTrue(st, self.state())
        self.assertTrue(st["recording"]["running"])
        self.assertTrue(all(p.startswith(os.path.join(folder, "rtd-monitor-trace-")) for p in st["recording"]["saved"]))
        # A signal name the config does not decode is refused; a bare signal name is found.
        bad = {"conditions": [{"type": "signal", "key": "nope", "op": ">", "value": 0}]}
        status, data, _ = self.request("POST", "/api/trace/trigger", {"trigger": bad})
        self.assertEqual(status, 422)
        self.assertIn("no signal 'nope'", data["error"])
        st = self.ok("POST", "/api/trace/trigger", {"trigger": {"conditions": [
            {"type": "signal", "key": "UNSIGNED32_sent_from_slave", "op": ">", "value": 0}]}})
        self.assertEqual(st["trigger"]["conditions"][0]["key"], "pingpong_TPDO1.UNSIGNED32_sent_from_slave")
        # Changing the trigger while recording.
        st = self.ok("POST", "/api/trace/trigger", {"trigger": None})
        self.assertEqual(st["trigger"], None)


class TwoNetworks(Trace):
    """A trace records the picked network and decodes with its nodes
    (add-several-can-networks task 6.4)."""

    def test_record_and_open_with_the_picked_network(self):
        from .fake_diag import TWO_NETWORKS
        from .test_configurator_online import TwoNetworks as Online2
        cfg = Online2.two(self)
        with FakePlugin(networks=TWO_NETWORKS) as fake:
            self.connect(fake)
            self.save(cfg)
            self.addCleanup(lambda: self.request("POST", "/api/trace/stop", {}))
            st = self.ok("POST", "/api/trace/start", {"network": "drives"})
            self.assertEqual(st["network"], "drives")
            self.assertTrue(self.wait_for(lambda: self.state()["recording"]["state"] == "recording"))
            self.assertEqual(fake.trace_starts[-1]["network"], "drives")
            self.assertIn("drive_TPDO1.UNSIGNED32_sent_from_slave", [s["key"] for s in self.state()["series"]])
            self.ok("POST", "/api/trace/stop", {})
            status, data, _ = self.request("POST", "/api/trace/start", {})
            self.assertEqual(status, 422)
            self.assertIn("io, drives", data["error"])
        # A file decodes with one network's nodes: the page names it; without
        # it the file opens without the nodes, and says why.
        status, data, _ = self.request("POST", "/api/trace/open", {"name": "sample.log", "config": cfg,
                                                                   "data": b64(written(sample_trace(), "candump"))})
        self.assertEqual(status, 200)
        self.assertIn("name one", " ".join(data["warnings"]))
        st = self.ok("POST", "/api/trace/open", {"name": "sample.log", "network": "io", "config": cfg,
                                                  "data": b64(written(sample_trace(), "candump"))})
        self.assertEqual(st["network"], "io")
        self.assertIn("pingpong_TPDO1.UNSIGNED32_sent_from_slave", [s["key"] for s in st["series"]])
