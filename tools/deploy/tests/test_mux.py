"""Multiplexed signals in the PC tools (spec can-multiplexed-signals): the
shared rule in canworks/raw/mux.py, and its use in the raw and J1939
checks, DBC import and export, trace decoding, frame explanation,
declarations, the J1939 simulator, the simulation file and the online
status text. The config checks' messages are in the shared fixtures
(test_raw.SharedCases, test_contract.SharedFixtures)."""

import copy
import io
import os
import unittest
from unittest import mock

from canworks import contract, dbcexport, diag
from canworks.configurator.declare import identifier
from canworks.raw import assist, contract as raw_contract, declare, mux
from canworks.raw.decode import RawDecoder

from .test_contract import load_cases

try:
    import cantools
    from canworks.j1939 import dbc as j1939_dbc
    from canworks.raw import dbc
except ImportError:  # a dependency of the tools; a shard without it skips these
    cantools = None

GOLDEN = os.path.join(os.path.dirname(__file__), "data", "dbc")


def layout(signals, errors=None, warnings=None):
    sigs = [dict(s, path="signals[%d]" % k) for k, s in enumerate(signals)]
    return mux.Layout.build(sigs, [] if errors is None else errors, [] if warnings is None else warnings)


# Simple: Page (byte 0) with Temp on page 1 and Press on page 2 (bytes 1-2).
SIMPLE = [
    {"name": "Page", "start_bit": 0, "length": 8, "multiplexer": True, "iec_location": "%IB400"},
    {"name": "Temp", "start_bit": 8, "length": 16, "scale": 0.1, "unit": "degC", "mux": {"values": [1]},
     "iec_location": "%IW402"},
    {"name": "Press", "start_bit": 8, "length": 16, "unit": "kPa", "mux": {"values": [2]}, "iec_location": "%IW404"},
    {"name": "Count", "start_bit": 24, "length": 8, "iec_location": "%IB406"},
]
# Extended: Sub is a switch on Page 3, B on Sub 1, C on Page 1-2 and 5-9.
EXTENDED = [
    {"name": "Page", "start_bit": 0, "length": 8, "multiplexer": True},
    {"name": "Sub", "start_bit": 8, "length": 8, "multiplexer": True, "mux": {"on": "Page", "values": [3]},
     "iec_location": "%QB401"},
    {"name": "B", "start_bit": 16, "length": 8, "mux": {"on": "Sub", "values": [1]}, "iec_location": "%QB402"},
    {"name": "C", "start_bit": 16, "length": 8, "mux": {"on": "Page", "values": [[1, 2], [5, 9]]},
     "iec_location": "%QB403"},
]


class Rule(unittest.TestCase):
    def test_activity(self):
        lay = layout(EXTENDED)
        self.assertTrue(lay.multiplexed)
        active, unknown = lay.activity([3, 1, 0, 0])
        self.assertEqual((active, unknown), ([True, True, True, False], False))
        active, unknown = lay.activity([6, 1, 0, 0])
        self.assertEqual((active, unknown), ([True, False, False, True], False))
        # Page 3 with Sub 2: Sub has a dependent, none is active.
        self.assertEqual(lay.activity([3, 2, 0, 0]), ([True, True, False, False], True))
        self.assertEqual(lay.activity([4, 0, 0, 0]), ([True, False, False, False], True))

    def test_evaluate(self):
        lay = layout(SIMPLE)
        self.assertEqual(lay.evaluate(bytes([2, 0x90, 1, 7])), ([True, False, True, True], False, False, 4))
        self.assertEqual(lay.evaluate(bytes([7, 0, 0, 0])), ([True, False, False, True], True, False, 4))
        # The switch itself is not in the frame: short, it needs one byte.
        self.assertEqual(lay.evaluate(b"")[2:], (True, 1))
        # Page 1 of a message whose pages need different lengths.
        short = layout([SIMPLE[0], dict(SIMPLE[1], length=8), dict(SIMPLE[2], length=40)])
        self.assertEqual(short.evaluate(bytes([1, 5]))[1:], (False, False, 2))
        self.assertEqual(short.evaluate(bytes([2, 5]))[1:], (False, False, 6))

    def test_page_count_and_pages(self):
        lay = layout(EXTENDED)
        # Page 1, 2, 5..9 (7 pages for C) and Page 3 with Sub 1.
        self.assertEqual(lay.page_count(), 8)
        pages = lay.pages()
        self.assertEqual([(v[0], v[1]) for v, _ in pages], [(1, 0), (2, 0), (3, 1), (5, 0), (6, 0), (7, 0), (8, 0),
                                                            (9, 0)])
        self.assertEqual(pages[2][1], [True, True, True, False])
        self.assertEqual(pages[0][1], [True, False, False, True])
        big = layout([SIMPLE[0], dict(SIMPLE[1], mux={"values": [[0, 199]]})])
        self.assertEqual(big.page_count(), 200)
        self.assertEqual(layout(SIMPLE[3:]).page_count(), 1)

    def test_can_share(self):
        lay = layout(EXTENDED)
        self.assertFalse(lay.can_share(2, 3))  # B needs Page 3, C pages 1-2, 5-9
        self.assertTrue(lay.can_share(0, 3))
        self.assertTrue(lay.can_share(1, 2))
        simple = layout(SIMPLE)
        self.assertFalse(simple.can_share(1, 2))
        self.assertTrue(simple.can_share(1, 3))
        both = layout([SIMPLE[0], SIMPLE[1], dict(SIMPLE[2], mux={"values": [1, 2]})])
        self.assertTrue(both.can_share(1, 2))

    def test_page_label_and_text(self):
        lay = layout(EXTENDED)
        self.assertEqual(lay.page_label(bytes([3, 1, 0])), "Page=3 Sub=1")
        self.assertEqual(lay.page_label(bytes([5, 1, 0])), "Page=5")
        self.assertEqual(mux.page_text(EXTENDED[3], EXTENDED), "page Page=1-2,5-9")
        self.assertEqual(mux.page_text(SIMPLE[1], SIMPLE), "page Page=1")
        self.assertEqual(mux.page_text(SIMPLE[3], SIMPLE), "")

    def test_errors_leave_it_plain(self):
        errors, warnings = [], []
        lay = layout([SIMPLE[0], dict(SIMPLE[1], mux={"on": "Pgae", "values": [1]})], errors, warnings)
        self.assertFalse(lay.multiplexed)
        self.assertEqual(errors, ["signals[1].mux.on: no switch named 'Pgae' in this message"])
        self.assertEqual(warnings, [])


class RawChecks(unittest.TestCase):
    def test_locations_and_dlc(self):
        raw = {"rx": [{"id": 1, "signals": [dict(SIMPLE[1], valid_location="%IX400.0")]}],
               "tx": [{"id": 2, "period_ms": 10, "pages": "all", "signals": EXTENDED}]}
        locs = [p for _, p in raw_contract.locations(raw, "r")]
        self.assertIn("r.rx[0].signals[0].valid_location", locs)
        self.assertNotIn("r.tx[0].signals[0].iec_location", locs)
        # Every page's signals: B and C end in byte 2.
        self.assertEqual(raw_contract.tx_dlc(raw["tx"][0]), 3)

    def test_rx_need_is_per_page(self):
        sigs = [SIMPLE[0], dict(SIMPLE[1], length=8, iec_location="%IB402"),
                dict(SIMPLE[2], length=40, iec_location="%IL408")]
        raw = {"rx": [{"name": "Status", "id": 768, "signals": sigs}]}
        errors, warnings, _ = raw_contract.check_raw(raw, "raw")
        self.assertEqual((errors, warnings), ([], []))

    def test_suggest_leaves_plugin_switches(self):
        entry = {"id": 2, "period_ms": 10, "pages": "rotate", "signals": copy.deepcopy(EXTENDED)}
        for s in entry["signals"]:
            s.pop("iec_location", None)
        filled = assist.suggest_locations(entry, "tx", set())
        self.assertEqual(filled, ["signals[2].iec_location", "signals[3].iec_location"])
        entry["pages"] = "program"
        self.assertEqual(assist.suggest_locations(entry, "tx", set()),
                         ["signals[0].iec_location", "signals[1].iec_location"])


class J1939Checks(unittest.TestCase):
    def config(self, signals, **extra):
        cfg = copy.deepcopy(load_cases("cases-j1939.json")["base"])
        cfg["networks"][1]["j1939"]["tx"].append(dict({"pgn": 65284, "name": "Display", "period_ms": 100,
                                                       "signals": signals}, **extra))
        return cfg

    def check(self, cfg):
        return contract.check_config(cfg, os.path.join(os.path.dirname(__file__), "..", "..", "..", "test",
                                                       "fixtures", "eds", "canworks.json"))

    def test_unused_switch_warns(self):
        r = self.check(self.config([{"name": "Line", "start_bit": 0, "length": 8, "multiplexer": True,
                                     "iec_location": "%QB220"},
                                    {"name": "A", "start_bit": 8, "length": 8, "iec_location": "%QB221"}]))
        self.assertTrue(r.ok, r.errors)
        self.assertIn("networks[1]: j1939: tx[1]: signals[0]: switch Line has no signal that depends on it",
                      "\n".join(r.warnings))

    def test_nested_switch_set_by_plugin(self):
        sigs = copy.deepcopy(EXTENDED)
        for s in sigs:
            s.pop("iec_location", None)
        sigs[2]["iec_location"], sigs[3]["iec_location"] = "%QB221", "%QB222"
        cfg = self.config(sigs, pages="rotate")
        r = self.check(cfg)
        self.assertTrue(r.ok, r.errors)
        j = contract.parse_j1939(cfg["networks"][1])
        tx = j["tx"][1]
        self.assertEqual((tx["pages"], tx["layout"].page_count()), ("rotate", 8))
        self.assertIsNone(tx["signals"][0]["location"])


class Decoding(unittest.TestCase):
    RAW = {"rx": [{"name": "Status", "id": 0x300, "signals": SIMPLE}]}

    def test_rows(self):
        # Spec scenarios "Multiplexed frame" and "Unknown page".
        d = RawDecoder(self.RAW)
        self.assertEqual(d.text(0x300, False, bytes([2, 0x90, 1, 5])), "Status [Page=2] Press=400 (400 kPa) Count=5")
        self.assertEqual(d.text(0x300, False, bytes([1, 0xFA, 0, 5])), "Status [Page=1] Temp=250 (25 degC) Count=5")
        self.assertEqual(d.text(0x300, False, bytes([7, 0, 0, 5])), "Status [Page=7 unknown] Count=5")
        (p,) = d.decode_pages(0x300, False, bytes([2, 0x90, 1, 5]))
        self.assertEqual((p["page"], p["unknown_page"], p["active"], p["switches"]), ("Page=2", False, [0, 2, 3], [0]))
        self.assertEqual(d.decode(0x300, False, bytes([2, 0x90, 1, 5])),
                         [("Status", [("Page", 2, None, ""), ("Press", 400, None, "kPa"), ("Count", 5, None, "")])])

    def test_series_only_from_active_frames(self):
        from canworks.bustrace.decode import Decoder
        from canworks.bustrace.model import Frame
        dec = Decoder()
        dec.attach_raw({"json": {"raw": self.RAW}, "protocol": "none"})
        d = dec.decode_raw(Frame(0, 0x300, bytes([2, 0x90, 1, 5])))
        keys = [k for k, _ in d.signals]
        self.assertIn("Status.Press", keys)
        self.assertNotIn("Status.Temp", keys)

    def test_explain_marks_the_page(self):
        from canworks.bustrace.decode import PlainDecoder
        from canworks.bustrace.explain import explain
        from canworks.bustrace.model import Frame
        dec = PlainDecoder()
        dec.attach_raw({"json": {"raw": self.RAW}, "protocol": "none"})
        out = explain(Frame(0, 0x300, bytes([2, 0x90, 1, 5])), dec)
        names = {f["name"] for f in out["fields"]}
        self.assertTrue({"Page", "Press", "Count"} <= names, names)
        self.assertNotIn("Temp", names)
        self.assertIn("page Page=2", out["meaning"])


class Declarations(unittest.TestCase):
    def test_page_in_comment(self):
        raw = {"rx": [{"name": "Status", "id": 0x300, "signals": SIMPLE}],
               "tx": [{"name": "Display", "id": 0x301, "period_ms": 100, "pages": "all", "signals": EXTENDED}]}
        decls = declare.declarations(raw, "", "", "", lambda n: n, identifier, {})
        by = {d["name"]: d for d in decls}
        self.assertTrue(by["Status_Temp"]["description"].endswith("; page Page=1"), by["Status_Temp"])
        self.assertNotIn("page", by["Status_Count"]["description"])
        self.assertIn("page Sub=1", by["Display_B"]["description"])
        self.assertNotIn("Display_Page", by)  # set by the plugin, no location


class Status(unittest.TestCase):
    def test_unknown_pages(self):
        out = io.StringIO()
        diag._print_raw_status({"running": True, "rx": [
            {"message": "Status (0x300)", "count": 9, "seen": True, "age_ms": 5, "last_id": 0x300, "last_dlc": 8,
             "last_data": "07", "unknown_pages": 3}],
            "tx": [{"message": "Display (0x301)", "count": 4, "unknown_page": True}]}, out)
        text = out.getvalue()
        self.assertIn("5 ms ago, 3 unknown pages", text)
        self.assertIn("unknown page", text.split("Display (0x301)")[1])


@unittest.skipIf(cantools is None, "cantools is not installed")
class DbcImport(unittest.TestCase):
    EXTENDED_DBC = (
        'VERSION ""\nNS_ :\n\tSG_MUL_VAL_\nBS_:\nBU_: A\n'
        'BO_ 768 Status: 8 A\n'
        ' SG_ Page M : 0|8@1+ (1,0) [0|0] "" Vector__XXX\n'
        ' SG_ Sub m3M : 8|8@1+ (1,0) [0|0] "" Vector__XXX\n'
        ' SG_ B m1 : 16|8@1+ (1,0) [0|0] "" Vector__XXX\n'
        ' SG_ C m1 : 24|8@1+ (1,0) [0|0] "" Vector__XXX\n\n'
        'SG_MUL_VAL_ 768 Sub Page 3-3;\nSG_MUL_VAL_ 768 B Sub 1-1;\nSG_MUL_VAL_ 768 C Page 1-2, 5-9;\n')
    NO_MUL_VAL = (
        'VERSION ""\nBU_: A\nBO_ 768 Status: 8 A\n'
        ' SG_ Page M : 0|8@1+ (1,0) [0|0] "" Vector__XXX\n SG_ Sub M : 8|8@1+ (1,0) [0|0] "" Vector__XXX\n'
        ' SG_ B m1 : 16|8@1+ (1,0) [0|0] "" Vector__XXX\n')

    def test_extended(self):
        (m,) = dbc.read_dbc(self.EXTENDED_DBC)
        self.assertTrue(m["multiplexed"])
        got = [(s["name"], s.get("multiplexer"), s.get("mux")) for s in m["signals"]]
        self.assertEqual(got, [("Page", True, None), ("Sub", True, {"on": "Page", "values": [3]}),
                               ("B", None, {"on": "Sub", "values": [1]}),
                               ("C", None, {"on": "Page", "values": [[1, 2], [5, 9]]})])
        entry = dbc.to_entry(m, "receive")
        errors, warnings, _ = raw_contract.check_raw({"rx": [dict(entry, signals=[
            dict(s, iec_location="%%IB%d" % (400 + k)) for k, s in enumerate(entry["signals"])])]}, "raw")
        self.assertEqual((errors, warnings), ([], []))

    def test_several_switches_without_mul_val(self):
        (m,) = dbc.read_dbc(self.NO_MUL_VAL)
        self.assertEqual(m["mux_problem"], "several switches but no SG_MUL_VAL_; multiplexing left out")
        self.assertFalse(m["multiplexed"])
        self.assertFalse(any("mux" in s or "multiplexer" in s for s in m["signals"]))
        raw, notes = assist.import_messages([m], {"Status": "receive"})
        self.assertEqual(notes, ["Status: several switches but no SG_MUL_VAL_; multiplexing left out"])
        self.assertEqual(len(raw["rx"][0]["signals"]), 3)

    def test_j1939_import(self):
        text = self.NO_MUL_VAL.replace("BO_ 768 ", "BO_ %d " % (0x98FF0400)) + \
            'BO_ %d Pages: 8 A\n SG_ Page M : 0|8@1+ (1,0) [0|0] "" Vector__XXX\n' \
            ' SG_ Temp m1 : 8|8@1+ (1,0) [0|0] "" Vector__XXX\n SG_ Press m2 : 8|8@1+ (1,0) [0|0] "" Vector__XXX\n' \
            % 0x98FF0500
        imported = j1939_dbc.load(text=text)
        self.assertIn("message Status (ID 0x18FF0400) has several switches but no SG_MUL_VAL_; its multiplexing is "
                      "left out", imported.problems)
        pages = imported.find(0xFF05)[0]
        self.assertEqual([(s["name"], s.get("multiplexer"), s.get("mux")) for s in pages["signals"]],
                         [("Page", True, None), ("Temp", None, {"values": [1]}), ("Press", None, {"values": [2]})])
        entry = j1939_dbc.config_entry(pages, "rx", set())
        self.assertEqual(entry["signals"][1]["mux"], {"values": [1]})
        self.assertTrue(entry["signals"][0]["multiplexer"])


@unittest.skipIf(cantools is None, "cantools is not installed")
class DbcExport(unittest.TestCase):
    RAW = {"rx": [{"name": "Status", "id": 0x300, "dlc": 8, "timeout_ms": 300, "signals": SIMPLE}],
           "tx": [{"name": "Display", "id": 0x301, "period_ms": 100, "pages": "all", "signals": EXTENDED}]}

    def golden(self, name, text):
        path = os.path.join(GOLDEN, name)
        if os.environ.get("UPDATE_GOLDEN"):
            with open(path, "w", encoding="ascii", newline="") as f:
                f.write(text)
        with open(path, encoding="ascii", newline="") as f:
            self.assertEqual(text, f.read())

    def test_raw_golden_and_round_trip(self):
        # Spec scenario "Multiplexed message round trip".
        text = dbc.export_dbc(self.RAW, "cab")
        self.golden("raw-mux.dbc", text)
        self.assertIn(" SG_ Page M : 0|8@1+", text)
        self.assertIn(" SG_ Temp m1 : 8|16@1+", text)
        self.assertIn(" SG_ Sub m3M : 8|8@1+", text)
        self.assertIn("SG_MUL_VAL_ 769 C Page 1-2, 5-9;", text)
        self.assertNotIn("SG_MUL_VAL_ 768", text)  # simple multiplexing needs none
        cantools.database.load_string(text, "dbc", strict=True)
        back = {m["name"]: m for m in dbc.read_dbc(text)}
        for kind, original in (("rx", self.RAW["rx"][0]), ("tx", self.RAW["tx"][0])):
            got = [(s["name"], s.get("multiplexer", False), s.get("mux")) for s in back[original["name"]]["signals"]]
            several = sum(1 for s in original["signals"] if s.get("multiplexer")) > 1
            want = [(s["name"], s.get("multiplexer", False), s.get("mux") if several or "mux" not in s else
                     {"values": s["mux"]["values"]}) for s in original["signals"]]
            self.assertEqual(got, want, kind)

    def test_j1939_golden_and_round_trip(self):
        # Spec scenario "Extended multiplexing round trip".
        cfg = copy.deepcopy(load_cases("cases-j1939.json")["base"])
        j = cfg["networks"][1]["j1939"]
        sigs = copy.deepcopy(EXTENDED)
        sigs[0]["iec_location"] = "%QB219"
        for k, s in enumerate(sigs[1:]):
            s["iec_location"] = "%%QB%d" % (220 + k)
        j["tx"].append({"pgn": 65284, "name": "Display", "period_ms": 100, "signals": sigs})
        j["rx"].append({"pgn": 65285, "name": "Status", "signals": [
            {"name": "Page", "start_bit": 0, "length": 8, "multiplexer": True, "iec_location": "%IB219"},
            {"name": "Temp", "start_bit": 8, "length": 16, "mux": {"values": [1]}, "iec_location": "%IW220"},
            {"name": "Press", "start_bit": 8, "length": 16, "mux": {"values": [2]}, "iec_location": "%IW222"}]})
        net = contract.networks(cfg)[1]
        with mock.patch.object(j1939_dbc, "__version__", "TEST"):
            text = j1939_dbc.export(net, "canworks.json")
        self.golden("j1939-mux.dbc", text)
        cantools.database.load_string(text, "dbc", strict=True)
        imported = j1939_dbc.load(text=text)
        self.assertEqual(imported.problems, [])
        display = imported.find(65284)[0]
        self.assertEqual([(s["name"], s.get("multiplexer", False), s.get("mux")) for s in display["signals"]],
                         [(s["name"], s.get("multiplexer", False), s.get("mux")) for s in EXTENDED])
        status = imported.find(65285)[0]
        self.assertEqual([s.get("mux") for s in status["signals"]], [None, {"values": [1]}, {"values": [2]}])


@unittest.skipIf(cantools is None, "cantools is not installed")
class J1939Trace(unittest.TestCase):
    DBC = ('VERSION ""\nBU_: Engine\n'
           'BO_ %d Status: 8 Engine\n'
           ' SG_ Page M : 0|8@1+ (1,0) [0|255] "" Vector__XXX\n'
           ' SG_ Temp m1 : 8|16@1+ (1,0) [0|1000] "degC" Vector__XXX\n'
           ' SG_ Press m2 : 8|16@1+ (1,0) [0|1000] "kPa" Vector__XXX\n'
           'BA_DEF_ BO_ "GenMsgCycleTime" INT 0 65535;\nBA_DEF_DEF_ "GenMsgCycleTime" 0;\n'
           'BA_ "GenMsgCycleTime" BO_ %d 100;\n') % ((0x98FF0400,) * 2)

    def path(self):
        import tempfile
        d = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, d)
        p = os.path.join(d, "machine.dbc")
        with open(p, "w") as f:
            f.write(self.DBC)
        return p

    def test_decodes_only_the_page(self):
        # Spec scenario "Multiplexed PGN": Page=2 and Press, no Temp.
        from canworks.bustrace.j1939 import J1939Decoder, load_dbc
        from canworks.bustrace.model import Frame
        dec = J1939Decoder()
        dec.messages = load_dbc(self.path())
        d = dec.decode(Frame(0, 0x18FF0400, bytes([2, 0x90, 1, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF]), ext=True))
        self.assertIn("[Page=2] Press=400 kPa", d.text)
        self.assertNotIn("Temp", d.text)
        self.assertEqual(dict(d.signals), {"Status.Page": 2, "Status.Press": 400})
        d = dec.decode(Frame(0, 0x18FF0400, bytes([9, 0, 0, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF]), ext=True))
        self.assertIn("[Page=9 unknown]", d.text)

    def test_simulator_pages(self):
        # Spec scenario "Multiplexed message" of the J1939 simulator.
        from canworks.j1939 import sim
        db = sim.load_dbc(self.path())
        (plan,) = sim.plans(db, "Engine")
        frames = plan.payloads(0.0)
        self.assertEqual([f[0] for f in frames], [1, 2])
        self.assertEqual(frames[0][3:], b"\xff" * 5)
        self.assertIn("2 pages", plan.describe())
        (rot,) = sim.plans(db, "Engine", mux="rotate")
        self.assertEqual([rot.payloads(0.0)[0][0] for _ in range(3)], [1, 2, 1])


class SimFile(unittest.TestCase):
    def test_multiplexed_device(self):
        from canworks import simfile
        cfg = {"schema_version": 2, "networks": [
            {"name": "cab", "protocol": "none", "adapter": {"type": "socketcan", "interface": "can1",
                                                           "bitrate": 250000}}]}
        send = {"id": 0x300, "dlc": 3, "period_ms": 100, "pages": "rotate", "signals": [
            {"name": "Page", "start_bit": 0, "length": 8, "multiplexer": True},
            {"name": "Temp", "start_bit": 8, "length": 16, "mux": {"values": [1]}, "source": {"constant": 250}},
            {"name": "Press", "start_bit": 8, "length": 16, "mux": {"values": [2]}, "source": {"constant": 400}}]}
        import tempfile
        d = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, d)
        path = os.path.join(d, "simulation.json")

        def check(s):
            data = {"schema_version": 2, "raw_devices": [{"name": "status", "send": [s]}], "networks": {"cab": {}}}
            return simfile.check(data, path, cfg, os.path.join(d, "canworks.json"))

        self.assertEqual(check(send).errors, [])
        bad = copy.deepcopy(send)
        bad["signals"][1]["mux"]["on"] = "Pgae"
        del bad["signals"][2]["source"]
        text = "\n".join(check(bad).errors)
        self.assertIn("raw_devices[0].send[0].signals[1].mux.on: no switch named 'Pgae' in this message", text)
        self.assertIn("raw_devices[0].send[0].signals[2]: needs a 'source'", text)
        plain = {"id": 0x300, "dlc": 1, "period_ms": 100, "pages": "all",
                 "signals": [{"start_bit": 0, "length": 8, "source": {"constant": 1}}]}
        self.assertIn("pages: only for a send with a switch", "\n".join(check(plain).errors))


if __name__ == "__main__":
    unittest.main()
