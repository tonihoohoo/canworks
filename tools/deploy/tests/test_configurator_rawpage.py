"""The CAN messages page's server side (configurator/rawpage.py) with
multiplexed messages (spec canopen-configurator, "CAN messages page" and
"Import a DBC into CAN messages")."""

import unittest

from canworks import contract  # noqa: F401  (loads before the configurator modules)
from canworks.configurator import rawpage

from .test_configurator_raw_page import MUX_DBC

try:
    import cantools  # noqa: F401
except ImportError:
    cantools = None


def config(tx=None, rx=None):
    raw = {}
    if tx is not None:
        raw["tx"] = tx
    if rx is not None:
        raw["rx"] = rx
    return {"schema_version": 2, "bridge": {"listen": "127.0.0.1:1502", "writers": ["127.0.0.1"]},
            "networks": [{"name": "cab", "protocol": "none", "adapter": {"type": "socketcan", "interface": "can0"},
                          "raw": raw}]}


def lamps(pages=None):
    entry = {"name": "Lamps", "id": 0x310, "period_ms": 100, "signals": [
        {"name": "Page", "start_bit": 0, "length": 8, "multiplexer": True},
        {"name": "Left", "start_bit": 8, "length": 8, "mux": {"values": [1]}},
        {"name": "Right", "start_bit": 8, "length": 8, "mux": {"values": [2]}}]}
    if pages:
        entry["pages"] = pages
    return entry


class Suggest(unittest.TestCase):
    def test_program_fills_the_switch(self):
        r = rawpage.suggest(config(tx=[lamps()]), 0, "tx", 0, [])
        self.assertTrue(all(s.get("iec_location") for s in r["entry"]["signals"]))
        self.assertIn("signals[0].iec_location", r["filled"])

    def test_all_and_rotate_leave_the_switch_empty(self):
        for pages in ("all", "rotate"):
            cfg = config(tx=[lamps(pages)])
            r = rawpage.suggest(cfg, 0, "tx", 0, [])
            sigs = r["entry"]["signals"]
            self.assertNotIn("iec_location", sigs[0], pages)
            self.assertTrue(sigs[1]["iec_location"].startswith("%Q"))
            self.assertTrue(sigs[2]["iec_location"].startswith("%Q"))
            self.assertNotIn("signals[0].iec_location", r["filled"])
            # The draft itself is not changed.
            self.assertNotIn("iec_location", cfg["networks"][0]["raw"]["tx"][0]["signals"][1])

    def test_received_switch_is_filled(self):
        entry = lamps("all")
        r = rawpage.suggest(config(rx=[entry]), 0, "rx", 0, [])
        self.assertTrue(r["entry"]["signals"][0]["iec_location"].startswith("%I"))


class MuxSummary(unittest.TestCase):
    def test_pages(self):
        self.assertEqual(rawpage.mux_summary(lamps()["signals"]), {"switches": ["Page"], "pages": 2})

    def test_ranges_and_nested(self):
        sigs = [{"name": "Page", "start_bit": 0, "length": 8, "multiplexer": True},
                {"name": "Sub", "start_bit": 8, "length": 4, "multiplexer": True, "mux": {"on": "Page", "values": [3]}},
                {"name": "A", "start_bit": 16, "length": 8, "mux": {"on": "Page", "values": [[1, 2], [5, 9]]}},
                {"name": "B", "start_bit": 16, "length": 8, "mux": {"on": "Sub", "values": [0, 1]}}]
        self.assertEqual(rawpage.mux_summary(sigs), {"switches": ["Page", "Sub"], "pages": 9})

    def test_plain_and_broken(self):
        self.assertEqual(rawpage.mux_summary([{"name": "X", "start_bit": 0, "length": 8}]), {"switches": [], "pages": 0})
        # A page on a switch that is not there: no page count, the check names it.
        broken = [{"name": "Page", "start_bit": 0, "length": 8, "multiplexer": True},
                  {"name": "A", "start_bit": 8, "length": 8, "mux": {"on": "Nope", "values": [1]}}]
        self.assertEqual(rawpage.mux_summary(broken), {"switches": ["Page"], "pages": 0})


@unittest.skipIf(cantools is None, "cantools is not installed")
class DbcImport(unittest.TestCase):
    def test_picker_lists_switches_and_pages(self):
        msgs = {m["name"]: m for m in rawpage.dbc_messages(MUX_DBC)["messages"]}
        self.assertEqual(msgs["Status"]["switches"], ["Page"])
        self.assertEqual(msgs["Status"]["pages"], 2)
        self.assertFalse(msgs["Status"]["mux_problem"])
        self.assertIn("several switches but no SG_MUL_VAL_", msgs["Twin"]["mux_problem"])

    def test_import_keeps_the_multiplexing(self):
        r = rawpage.dbc_import(config(rx=[]), 0, MUX_DBC, {"Status": "receive"}, [])
        self.assertEqual(r["notes"], [])
        sigs = {s["name"]: s for s in r["rx"][0]["signals"]}
        self.assertIs(sigs["Page"]["multiplexer"], True)
        self.assertEqual(sigs["Temp"]["mux"]["values"], [1])
        self.assertEqual(sigs["Press"]["mux"]["values"], [2])
        self.assertTrue(all(s.get("iec_location") for s in sigs.values()))


if __name__ == "__main__":
    unittest.main()


@unittest.skipIf(cantools is None, "needs cantools")
class DbcFile(unittest.TestCase):
    """The CAN messages page's DBC file: uploaded with the draft, written to
    the config folder on save when `raw.dbc` names it."""

    def setUp(self):
        import base64
        import os
        import tempfile
        from canworks.configurator import server
        self.server = server
        self.b64 = lambda text: base64.b64encode(text.encode()).decode()
        self.dir = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, self.dir, True)
        self.s = server.Session()
        self.addCleanup(self.s.close)
        self.s.open(self.dir, "standalone", new=True)
        self.path = lambda name: os.path.join(self.s.canopen_dir, name)

    def save(self, cfg):
        cfg["networks"][0]["adapter"]["bitrate"] = 250000
        return self.s.save(cfg)

    def upload(self, name, text, on_conflict=None):
        import base64
        return self.s.import_dbc(name, base64.b64decode(self.b64(text)), on_conflict, kind="raw")

    def test_upload_lists_and_save_writes_the_file(self):
        import os
        res = self.upload("status.dbc", MUX_DBC)
        self.assertEqual([m["name"] for m in res["messages"]], ["Status", "Twin"])
        self.assertEqual(res["problems"], [])
        self.assertIn("status.dbc", self.s.dbc_files())
        # Read back by name (Pick messages…), then the entries.
        self.assertEqual(len(self.s.import_dbc("status.dbc", kind="raw")["messages"]), 2)
        cfg = config(rx=[])
        r = self.s.raw_page("dbc_import", {"config": cfg, "network": 0, "name": "status.dbc", "picks": {"Status": "receive"}})
        cfg["networks"][0]["raw"] = {"rx": r["rx"], "dbc": "status.dbc"}
        self.save(cfg)
        self.assertTrue(os.path.isfile(self.path("status.dbc")))
        self.assertNotIn("status.dbc", self.s.pending_dbc)

    def test_an_unnamed_file_is_not_written(self):
        import os
        self.upload("status.dbc", MUX_DBC)
        self.save(config(rx=[]))
        self.assertFalse(os.path.isfile(self.path("status.dbc")))

    def test_same_name_different_file(self):
        self.upload("status.dbc", MUX_DBC)
        other = MUX_DBC.replace("Twin", "Pair")
        with self.assertRaises(self.server.ApiError) as cm:
            self.upload("status.dbc", other)
        self.assertEqual(cm.exception.status, 409)
        self.assertEqual(self.upload("status.dbc", other, "keep_both")["name"], "status-2.dbc")
        self.assertEqual([m["name"] for m in self.upload("status.dbc", other, "replace")["messages"]], ["Status", "Pair"])

    def test_missing_and_bad_files(self):
        with self.assertRaises(self.server.ApiError) as cm:
            self.s.import_dbc("gone.dbc", kind="raw")
        self.assertEqual(cm.exception.status, 404)
        with self.assertRaises(self.server.ApiError) as cm:
            self.upload("empty.dbc", 'VERSION ""\n\nNS_ :\n\nBS_:\n\nBU_:\n')
        self.assertEqual(cm.exception.status, 422)
        with self.assertRaises(self.server.ApiError) as cm:
            self.s.raw_page("dbc_import", {"config": config(rx=[]), "name": "gone.dbc", "picks": {}})
        self.assertEqual(cm.exception.status, 404)
