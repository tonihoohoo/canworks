"""Network documentation export (canworks.docexport and
docwriter): the document model against the DBC and DCF exports, the bus-load
estimate, privacy, stable output, the HTML (well-formed, self-contained, the
JSON island), golden models of the example configs and the CLI."""

import base64
import contextlib
import copy
import datetime
import html.parser
import io
import json
import os
import re
import shutil
import tempfile
import unittest

from canworks import cli, dbcexport, dcfexport, docexport, docwriter

from .test_contract import FIXTURES, REPO, load_cases

EDS_DIR = os.path.join(FIXTURES, "eds")
FIXTURE_CONFIG = os.path.join(EDS_DIR, "canworks.json")
EDITOR_PROJECT = os.path.join(FIXTURES, "editor-project")
GOLDEN = os.path.join(os.path.dirname(__file__), "data", "doc")
EXAMPLES = ("rtd-sensor", "cia402-drive", "two-networks", "pingpong", "slave", "gateway")
NOW = datetime.datetime(2026, 1, 2, 3, 4)


def example(name):
    path = os.path.join(REPO, "config", name, "canopen_config.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f), path


def base_config():
    return copy.deepcopy(load_cases()["base"])


def build(cfg, path=FIXTURE_CONFIG, **kw):
    kw.setdefault("now", NOW)
    return docexport.build(cfg, path, **kw)


def frame(net, name):
    return next(f for f in net["frames"] if f["name"] == name)


def pdo(node, kind, number):
    return next(p for p in node["pdos"] if p["kind"] == kind and p["number"] == number)


class _Checker(html.parser.HTMLParser):
    """Balanced tags (void elements aside), unique ids, no external URL."""

    VOID = {"meta", "link", "br", "img", "input", "hr", "line", "rect", "path", "source"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.ids, self.problems = [], set(), []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if a.get("id"):
            if a["id"] in self.ids:
                self.problems.append("duplicate id " + a["id"])
            self.ids.add(a["id"])
        for key in ("src", "href"):
            if (a.get(key) or "").startswith(("http:", "https:", "//")):
                self.problems.append("external %s %s" % (key, a[key]))
        if tag not in self.VOID:
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID:
            self.stack.pop()

    def handle_endtag(self, tag):
        if tag in self.VOID:
            return
        if not self.stack or self.stack[-1] != tag:
            self.problems.append("unexpected </%s> (open: %s)" % (tag, self.stack[-3:]))
            return
        self.stack.pop()


def check_html(test, text):
    c = _Checker()
    c.feed(text)
    c.close()
    test.assertEqual(c.problems, [])
    test.assertEqual(c.stack, [])
    return c


def island(text):
    m = re.search(r'<script type="application/json" id="canopen-doc">(.*?)</script>', text, re.S)
    return json.loads(m.group(1).replace("<\\/", "</"))


class Model(unittest.TestCase):
    def test_rtd_example(self):
        cfg, path = example("rtd-sensor")
        m = build(cfg, path)
        [net] = m["networks"]
        self.assertEqual((net["interface"], net["bitrate"]), ("vcan0", 125000))
        [node] = net["nodes"]
        self.assertEqual((node["node_id"], node["name"]), (5, "rtd"))
        self.assertEqual((pdo(node, "TPDO", 1)["cob_id"], pdo(node, "TPDO", 2)["cob_id"]), (0x185, 0x285))
        locs = [r["location"] for r in m["io"]]
        for loc in ["%IW100", "%IW101", "%IW102", "%IW103", "%IB100", "%IB101", "%IB102", "%IB103", "%IX10.0"]:
            self.assertIn(loc, locs)
        self.assertEqual(m["doc_schema_version"], 1)
        self.assertEqual(m["warnings"], [])

    def test_error_stops(self):
        cfg = base_config()
        cfg["nodes"][0]["tx_pdos"][0]["number"] = 2
        with self.assertRaises(docexport.ExportFailed) as e:
            build(cfg)
        self.assertIn("TPDO 2", str(e.exception))

    def test_two_networks_and_one(self):
        cfg, path = example("two-networks")
        m = build(cfg, path)
        self.assertEqual([n["name"] for n in m["networks"]], ["io", "drives"])
        self.assertEqual({r["network"] for r in m["io"]}, {"io", "drives"})
        m = build(cfg, path, network="drives")
        self.assertEqual([n["name"] for n in m["networks"]], ["drives"])
        self.assertEqual({r["network"] for r in m["io"]}, {"drives"})
        with self.assertRaises(docexport.ExportFailed):
            build(cfg, path, network="nope")

    def test_frames_match_the_dbc(self):
        for name in EXAMPLES:
            cfg, path = example(name)
            m = build(cfg, path)
            for net in (n for n in m["networks"] if n["role"] == "master"):
                one = docexport.contract.network_config(cfg, net["name"] or None)
                dbc = dbcexport.build(one, path, checked=True)  # checked as a whole above
                for msg in dbc.messages:
                    f = frame(net, msg.name)
                    self.assertEqual((f["cob_id"], f["dlc"]), (msg.cob_id, msg.length), (name, msg.name))

    def test_auto_cob_id_as_the_dbc(self):
        cfg = base_config()
        cfg["nodes"][0]["tx_pdos"][0]["cob_id"] = "auto"
        dbc = dbcexport.build(cfg, FIXTURE_CONFIG)
        cob = next(x.cob_id for x in dbc.messages if x.name == "pingpong_TPDO1")
        [net] = build(cfg)["networks"]
        self.assertEqual(pdo(net["nodes"][0], "TPDO", 1)["cob_id"], cob)

    def test_boot_writes_match_the_dcf_export(self):
        for name in EXAMPLES:
            cfg, path = example(name)
            m = build(cfg, path)
            for net in (n for n in m["networks"] if n["role"] == "master"):
                one = docexport.contract.network_config(cfg, net["name"] or None)
                downloads = dcfexport.plugin_downloads(one, path)
                for node in net["nodes"]:
                    d = downloads[node["node_id"]]
                    got = [(w["index"], w["subindex"], w["data"]) for w in node["boot"]["writes"]]
                    self.assertEqual(got, [(i, s, data.hex()) for i, s, data in d.writes], (name, node["node_id"]))

    def test_write_sources(self):
        [net] = build(base_config())["networks"]
        writes = net["nodes"][0]["boot"]["writes"]
        startup = [w for w in writes if w["source"] == "startup SDO"]
        self.assertEqual([(w["index"], w["subindex"]) for w in startup], [(0x1017, 0)])
        self.assertIs(writes[-1], startup[-1])  # startup SDOs come last
        self.assertTrue(all(w["source"] == "PDO configuration" for w in writes if 0x1400 <= w["index"] <= 0x1BFF))
        cfg = base_config()
        cfg["nodes"][0]["config_check"] = True
        cfg["nodes"][0]["eds"] = "config-check.eds"
        [net] = build(cfg)["networks"]
        sources = [w["source"] for w in net["nodes"][0]["boot"]["writes"]]
        self.assertEqual(sources[-2:], ["configuration check", "configuration check"])

    def test_master_heartbeat_time_and_sdo_frames(self):
        cfg = base_config()
        cfg["master"].update(heartbeat_ms=100, time_period_ms=1000)
        [net] = build(cfg)["networks"]
        hb = frame(net, "Master_Heartbeat")
        self.assertEqual((hb["cob_id"], hb["producer"], hb["trigger"]), (0x701, "Master", "every 100 ms"))
        self.assertEqual(frame(net, "TIME")["cob_id"], 0x100)
        req, rsp = frame(net, "pingpong_SDO_Request"), frame(net, "pingpong_SDO_Response")
        self.assertEqual((req["cob_id"], req["producer"]), (0x602, "Master"))
        self.assertEqual((rsp["cob_id"], rsp["producer"]), (0x582, "pingpong"))
        self.assertIn("on demand", req["trigger"])
        self.assertEqual([f["cob_id"] for f in net["frames"]], sorted(f["cob_id"] for f in net["frames"]))

    def test_master_bootup_without_heartbeat(self):
        [net] = build(base_config())["networks"]
        hb = frame(net, "Master_Heartbeat")
        self.assertEqual((hb["cob_id"], hb["trigger"], hb["rate_worst"]), (0x701, "off (boot-up message only)", 0))

    def test_sync_off(self):
        cfg = base_config()
        del cfg["master"]["sync_period_us"]
        for key in ("tx_pdos", "rx_pdos"):
            cfg["nodes"][0][key][0]["transmission"] = 255
        [net] = build(cfg)["networks"]
        self.assertNotIn("SYNC", [f["name"] for f in net["frames"]])
        self.assertIn({"label": "SYNC", "value": "off", "object": "0x1005"}, net["settings"])

    def test_identity_and_eds_hash(self):
        cfg, path = example("cia402-drive")
        [net] = build(cfg, path)["networks"]
        [node] = net["nodes"]
        import hashlib
        with open(os.path.join(os.path.dirname(path), "servo402.eds"), "rb") as f:
            self.assertEqual(node["eds"]["sha256"], hashlib.sha256(f.read()).hexdigest())
        info = docexport.eds_mod.device_info(os.path.join(os.path.dirname(path), "servo402.eds"))
        vendor = next(i for i in node["identity"] if i["field"] == "Vendor ID")
        self.assertEqual((vendor["eds"], vendor["checked"]), (info["vendor_id"], True))

    def test_device_mapping_shows_unused_objects(self):
        cfg = base_config()
        n = cfg["nodes"][0]
        n["eds"] = "fixed-io.eds"
        n["tx_pdos"] = [{"entries": [{"index": "0x6000", "subindex": 2, "type": "UNSIGNED8", "iec_location": "%IB40"}]}]
        n["rx_pdos"] = [{"entries": [{"index": "0x6200", "subindex": 1, "type": "UNSIGNED8", "iec_location": "%QB40"}]}]
        n["sdo"] = []
        [net] = build(cfg)["networks"]
        t = pdo(net["nodes"][0], "TPDO", 1)
        self.assertEqual(t["mapping"], "device")
        self.assertEqual([(e["index"], e["subindex"], e["used"]) for e in t["entries"]],
                         [(0x6000, 1, False), (0x6000, 2, True)])

    def test_receive_timeout(self):
        cfg = base_config()
        t = cfg["nodes"][0]["tx_pdos"][0]
        t.update({"event_timer_ms": 100, "timeout_ms": "auto", "timeout_location": "%IX20.0"})
        doc = build(cfg)
        [net] = doc["networks"]
        self.assertEqual(pdo(net["nodes"][0], "TPDO", 1)["timeout"],
                         {"ms": 200, "auto": True, "on_timeout": "hold", "location": "%IX20.0", "variables": []})
        self.assertIn("%IX20.0", [u["location"] for u in doc["io"]])
        self.assertIn("Receive timeout 200 ms (auto), hold, timeout bit <code>%IX20.0</code>", docwriter.write(doc))
        # Without timeout_ms there is no timeout; RPDOs never have one.
        del t["timeout_ms"], t["timeout_location"]
        [net] = build(cfg)["networks"]
        self.assertNotIn("timeout", pdo(net["nodes"][0], "TPDO", 1))

    def test_plc_variable_names_and_cycle_from_project(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        project = os.path.join(tmp, "proj")
        shutil.copytree(EDITOR_PROJECT, project)
        shutil.copytree(EDS_DIR, os.path.join(project, "canworks"))
        cfg = base_config()
        cfg["nodes"][0]["tx_pdos"][0]["entries"][0]["iec_location"] = "%ID10"
        with open(os.path.join(project, "pous", "programs", "main.st"), "a", encoding="utf-8") as f:
            f.write("\nPROGRAM other\n  VAR\n    ping AT %ID10 : UDINT;\n  END_VAR\nEND_PROGRAM\n")
        path = os.path.join(project, "canworks", "canworks.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        [net] = build(cfg, path, names=dbcexport.project_names(path))["networks"]
        self.assertEqual(pdo(net["nodes"][0], "TPDO", 1)["entries"][0]["variables"], ["ping"])
        self.assertEqual(docexport.project_cycle_ms(path), 20.0)
        self.assertIsNone(docexport.project_cycle_ms(FIXTURE_CONFIG))

    def test_od_extract(self):
        cfg = base_config()
        used = build(cfg)["networks"][0]["nodes"][0]["od"]
        every = build(cfg, od="all")["networks"][0]["nodes"][0]["od"]
        self.assertLess(len(used), len(every))
        row = next(o for o in used if (o["index"], o["subindex"]) == (0x1017, 0))
        self.assertTrue(row["configured"].startswith("100 "))
        self.assertIn((0x4001, 0), [(o["index"], o["subindex"]) for o in used])

    def test_meaning(self):
        [net] = build(base_config())["networks"]
        writes = net["nodes"][0]["boot"]["writes"]
        cob = next(w for w in writes if (w["index"], w["subindex"]) == (0x1800, 1) and "valid" in w["meaning"])
        self.assertIn("COB-ID 0x182", cob["meaning"])


class BusLoad(unittest.TestCase):
    def test_cyclic_pdo(self):
        # rtd-sensor: TPDO 1 has 8 bytes, transmission 1, SYNC every 100 ms, 125 kbit/s.
        cfg, path = example("rtd-sensor")
        [net] = build(cfg, path)["networks"]
        t = frame(net, "rtd_TPDO1")
        self.assertEqual(t["bits"], 135)
        self.assertEqual((t["load_cyclic"], t["load_worst"]), (1.08, 1.08))

    def test_frame_bits(self):
        self.assertEqual([docexport.frame_bits(n) for n in (0, 1, 8)], [55, 65, 135])

    def test_event_pdo_with_inhibit(self):
        cfg = base_config()
        cfg["nodes"][0]["tx_pdos"][0].update(transmission=255, inhibit_time_us=10000)
        [net] = build(cfg)["networks"]
        t = frame(net, "pingpong_TPDO1")
        self.assertEqual((t["rate_cyclic"], t["rate_worst"]), (0.0, 100.0))
        self.assertNotIn(t["load_worst"], (0, None))

    def test_unbounded_event_pdo(self):
        cfg = base_config()
        cfg["nodes"][0]["tx_pdos"][0].update(transmission=255, inhibit_time_us=0, event_timer_ms=0)
        m = build(cfg)
        [net] = m["networks"]
        self.assertTrue(net["bus_load"]["unbounded"])
        self.assertTrue(any("node 2 TPDO 1" in w and "unbounded" in w for w in m["warnings"]))

    def test_plc_cycle_sync(self):
        cfg = base_config()
        del cfg["master"]["sync_period_us"]
        cfg["master"]["sync_source"] = "plc_cycle"
        [net] = build(cfg)["networks"]
        self.assertEqual(frame(net, "SYNC")["load_cyclic"], 0.0)
        self.assertTrue(net["bus_load"]["notes"])
        [net] = build(cfg, plc_cycle_ms=10)["networks"]
        self.assertEqual(frame(net, "SYNC")["rate_cyclic"], 100.0)
        self.assertEqual(net["bus_load"]["notes"], [])

    def test_high_load_warning(self):
        cfg = base_config()
        cfg["master"]["sync_period_us"] = 1000
        cfg["adapter"]["bitrate"] = 125000
        for key in ("tx_pdos", "rx_pdos"):
            cfg["nodes"][0][key][0]["transmission"] = 1
        m = build(cfg)
        self.assertTrue(any("above 60 %" in w for w in m["warnings"]), m["warnings"])


class Privacy(unittest.TestCase):
    def test_no_token_or_absolute_paths(self):
        tmp = tempfile.mkdtemp(prefix="plantdocs-")
        self.addCleanup(shutil.rmtree, tmp)
        folder = os.path.join(tmp, "canworks")
        shutil.copytree(EDS_DIR, folder)
        cfg = base_config()
        cfg["master"]["diagnostics"] = {"token_verifier": "SCRAM-SHA-256$4096:b3BlbnBsYy1jYW5vcGVuLQ==$SCwajLpaZodu1wAN8vyPszAhAZJB4cXO6Rk+MpacSlQ=:7p7OTxtK+R6omxv8Fdz+xdCpEf4bc82kbkxCL8w33kg="}
        path = os.path.join(folder, "canworks.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        text, _ = docexport.export(cfg, path, embed_eds=True, now=NOW)
        self.assertNotIn("SCwajLpaZodu1wAN8vyPszAhAZJB4cXO6Rk", text)
        self.assertNotIn(tmp, text)
        self.assertNotIn("plantdocs-", text)
        self.assertIn("cpp-slave.eds", text)
        for name in EXAMPLES:
            cfg, path = example(name)
            text, _ = docexport.export(cfg, path, now=NOW)
            self.assertNotIn(REPO, text)


class Html(unittest.TestCase):
    def test_well_formed_and_self_contained(self):
        for name in EXAMPLES:
            cfg, path = example(name)
            text, _ = docexport.export(cfg, path, now=NOW, od="all")
            c = check_html(self, text)
            self.assertTrue(text.startswith("<!doctype html>"))
            self.assertNotRegex(text, r"<(script|link|img)[^>]+(src|href)=\"https?:")
            for net in island(text)["networks"]:
                self.assertIn(net["anchor"], c.ids)
                for node in net["nodes"]:
                    self.assertIn(node["anchor"], c.ids)
                    for p in node["pdos"]:
                        self.assertIn(p["anchor"], c.ids)

    def test_json_island(self):
        cfg, path = example("rtd-sensor")
        text, _ = docexport.export(cfg, path, now=NOW)
        data = island(text)
        self.assertEqual(data["doc_schema_version"], 1)
        [node] = data["networks"][0]["nodes"]
        t1 = pdo(node, "TPDO", 1)
        self.assertEqual((node["node_id"], t1["cob_id"], len(t1["entries"])), (5, 0x185, 4))

    def test_stable_output(self):
        cfg, path = example("cia402-drive")
        a, _ = docexport.export(cfg, path, now=datetime.datetime(2026, 1, 1, 10, 0))
        b, _ = docexport.export(cfg, path, now=datetime.datetime(2026, 1, 1, 10, 1))
        self.assertNotEqual(a, b)
        self.assertEqual(a.replace("2026-01-01 10:00", "X"), b.replace("2026-01-01 10:01", "X"))

    def test_anchors(self):
        self.assertEqual(docexport.anchor("node", "drives", 4), "node-drives-4")
        self.assertEqual(docexport.anchor("node", "", 4), "node-4")

    def test_embedded_eds(self):
        cfg = base_config()
        text, _ = docexport.export(cfg, FIXTURE_CONFIG, embed_eds=True, now=NOW)
        m = re.search(r'download="cpp-slave.eds" href="data:application/octet-stream;base64,([^"]+)"', text)
        with open(os.path.join(EDS_DIR, "cpp-slave.eds"), "rb") as f:
            self.assertEqual(base64.b64decode(m.group(1)), f.read())
        text, _ = docexport.export(cfg, FIXTURE_CONFIG, now=NOW)
        self.assertNotIn("base64,", text)

    def test_title(self):
        text, _ = docexport.export(base_config(), FIXTURE_CONFIG, title="Line 3 <A>", now=NOW)
        self.assertIn("<title>Line 3 &lt;A&gt;</title>", text)


class SlaveNetworks(unittest.TestCase):
    def test_slave_device(self):
        cfg, path = example("slave")
        [net] = build(cfg, path)["networks"]
        self.assertEqual((net["role"], net["master_node_id"]), ("slave", None))
        [dev] = net["nodes"]
        self.assertEqual((dev["role"], dev["node_id"], dev["boot"]), ("slave", 10, None))
        speed = next(o for o in dev["objects"] if o["index"] == 0x2000)
        self.assertEqual((speed["location"], speed["pdo"]), ("%IW300", "RPDO1 bits 0-15"))
        self.assertIn("upper master writes", speed["direction"])
        hb = frame(net, "OpenPLC_Heartbeat")
        self.assertEqual((hb["cob_id"], hb["producer"]), (0x70A, "OpenPLC"))
        t1 = frame(net, "OpenPLC_TPDO1")
        self.assertEqual((t1["cob_id"], t1["rate_worst"]), (0x18A, 0))
        self.assertIn("not counted", t1["trigger"])
        self.assertEqual(frame(net, "OpenPLC_RPDO1")["producer"], "upper master")
        self.assertTrue(any("Another master runs this bus" in n for n in net["bus_load"]["notes"]))

    def test_slave_tpdo_at_plc_scan(self):
        cfg, path = example("slave")
        [net] = build(cfg, path, plc_cycle_ms=10)["networks"]
        t1 = frame(net, "OpenPLC_TPDO1")
        self.assertEqual(t1["rate_worst"], 100.0)
        self.assertIn("once per PLC scan (10 ms)", t1["trigger"])

    def test_lss_node_id(self):
        cfg, path = example("slave")
        cfg["networks"][0]["slave"]["node_id"] = None
        [net] = build(cfg, path)["networks"]
        self.assertEqual([f["name"] for f in net["frames"]], ["NMT", "SYNC"])
        self.assertIn("node ID from LSS", docexport.export(cfg, path, now=NOW)[0])

    def test_gateway(self):
        cfg, path = example("gateway")
        model = build(cfg, path)
        g = model["gateway"]
        self.assertEqual((g["upper"], g["sdo_bridge"], g["on_upper_loss"]), ("upper", True, "zero"))
        ping = next(r for r in g["routes"] if r["name"] == "ping")
        self.assertEqual((ping["field_node"], ping["field_link"]), (2, "node-field-2"))
        self.assertTrue(ping["direction"].startswith("down"))
        text, _ = docexport.export(cfg, path, now=NOW)
        self.assertIn('id="gateway"', text)
        self.assertIn('href="#node-field-2"', text)
        self.assertIsNone(build(cfg, path, network="field")["gateway"])


class Golden(unittest.TestCase):
    """The document model of each example config (UPDATE_GOLDEN=1 rewrites)."""

    def test_examples(self):
        for name in EXAMPLES:
            cfg, path = example(name)
            got = json.dumps(build(cfg, path), indent=1, sort_keys=True, ensure_ascii=False) + "\n"
            golden = os.path.join(GOLDEN, name + ".json")
            if os.environ.get("UPDATE_GOLDEN"):
                os.makedirs(GOLDEN, exist_ok=True)
                with open(golden, "w", encoding="utf-8") as f:
                    f.write(got)
            with self.subTest(name), open(golden, encoding="utf-8") as f:
                self.assertEqual(json.loads(got), json.load(f))


class Cli(unittest.TestCase):
    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def config_in(self, cfg):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        shutil.copytree(EDS_DIR, os.path.join(tmp, "eds"))
        path = os.path.join(tmp, "eds", "canworks.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        return tmp, path

    def test_export(self):
        tmp, path = self.config_in(base_config())
        out_file = os.path.join(tmp, "network.html")
        code, out, err = self.run_cli("--config", path, "--export-html", out_file, "--doc-title", "Bench",
                                      "--doc-od", "all", "--doc-embed-eds")
        self.assertEqual(code, 0, err)
        self.assertIn("wrote " + out_file, out)
        with open(out_file, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("<title>Bench</title>", text)
        self.assertIn("base64,", text)

    def test_failure_leaves_file(self):
        cfg = base_config()
        cfg["nodes"][0]["tx_pdos"][0]["number"] = 2
        tmp, path = self.config_in(cfg)
        out_file = os.path.join(tmp, "network.html")
        with open(out_file, "w") as f:
            f.write("old")
        code, _, err = self.run_cli("--config", path, "--export-html", out_file)
        self.assertEqual(code, 1)
        self.assertIn("TPDO 2", err)
        with open(out_file) as f:
            self.assertEqual(f.read(), "old")

    def test_options_need_export_html(self):
        tmp, path = self.config_in(base_config())
        for extra in (["--doc-od", "all"], ["--doc-embed-eds"], ["--doc-title", "x"], ["--doc-cycle-ms", "10"]):
            code, _, err = self.run_cli("--config", path, "--export-dbc", os.path.join(tmp, "x.dbc"), *extra)
            self.assertEqual(code, 1)
            self.assertIn("needs --export-html", err)
        code, _, err = self.run_cli("--config", path, "--export-html", os.path.join(tmp, "x.html"), "--runtime", "h")
        self.assertEqual(code, 1)
        self.assertIn("only writes an HTML document", err)

    def test_network_option(self):
        cfg, path = example("two-networks")
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        out_file = os.path.join(tmp, "drives.html")
        code, _, err = self.run_cli("--config", path, "--export-html", out_file, "--network", "drives")
        self.assertEqual(code, 0, err)
        with open(out_file, encoding="utf-8") as f:
            data = island(f.read())
        self.assertEqual([n["name"] for n in data["networks"]], ["drives"])


if __name__ == "__main__":
    unittest.main()
