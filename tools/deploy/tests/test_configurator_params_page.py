"""The configurator's object dictionary and parameters tabs and the TIME
period field in a real browser, against the fake diagnostics channel
(add-device-parameters tasks 4.2-4.4). Needs Playwright, like
test_configurator_page.py.

With CANWORKS_SCREENSHOTS=DIR the tests also save the screenshots of task 4.5
there (light and dark)."""

import base64
import copy
import json
import os
import shutil
import tempfile
import unittest

from .fake_diag import status as fake_status
from .test_configurator_online_page import OnlineBase
from .test_configurator_page import RTD, load
from .test_parameters import NODE, FakeDevice

SHOTS = os.environ.get("CANWORKS_SCREENSHOTS")


class ParamsPage(OnlineBase):
    def setUp(self):
        super().setUp()
        cfg = load(os.path.join(RTD, "canopen_config.json"))
        cfg["nodes"][0]["sdo_variables"] = [{"name": "alarm_limit", "index": "0x6126", "subindex": 2, "type": "REAL32",
                                             "direction": "write", "iec_location": "%QD310"}]
        for e in cfg["nodes"][0]["tx_pdos"][0]["entries"]:
            e["iec_location"] = e["iec_location"].replace("%IW", "%IW3")
        cfg["nodes"][0]["status_location"] = "%IX310.0"
        self.cfg = cfg
        shutil.copy(os.path.join(RTD, "rtd8.eds"), os.path.join(self.project, "canworks"))
        self.write_config()

    def device(self, allow=True, booted=True):
        fp = FakeDevice(allow_changes=allow)
        node = copy.deepcopy(fake_status()["nodes"][0])
        # PRE-OPERATIONAL, as while it is set up: writes to an OPERATIONAL
        # node ask first (test_configurator_online_page).
        node.update(node_id=NODE, name="rtd", booted=booted, emcy={"code": 0, "error_register": 0, "count": 0},
                    sdo_variables=[], state=127)
        fp.status["nodes"].insert(0, node)
        return fp

    def open_node(self, fp, allow=True, tab=None):
        self.online(fp, allow=allow)
        pg = self.page
        pg.wait_for_selector("text=Connected to")
        pg.click('tr[data-online-node="%d"]' % NODE)
        if tab:
            pg.click('button[data-online-tab="%s"]' % tab)

    def shot(self, name, selector=None):
        if not SHOTS:
            return
        os.makedirs(SHOTS, exist_ok=True)
        self.page.set_viewport_size({"width": 1280, "height": 900})
        if not selector:
            self.page.evaluate("() => { const h = document.querySelector('#online-node h2'); "
                               "window.scrollTo(0, h.getBoundingClientRect().top + window.scrollY - 70); "
                               "for (const x of document.querySelectorAll('*')) if (x.scrollLeft) x.scrollLeft = 0; }")
        for theme in ("light", "dark"):
            self.page.evaluate("t => document.documentElement.dataset.theme = t", theme)
            self.page.wait_for_timeout(100)
            target = self.page.locator(selector) if selector else self.page
            target.screenshot(path=os.path.join(SHOTS, "%s-%s.png" % (name, theme)))

    # -- object dictionary -----------------------------------------------------
    def search(self, text):
        self.page.fill('input[data-online="od-filter"]', text)

    def test_object_dictionary(self):
        pg = self.page
        with self.device() as fp:
            fp.set(0x6112, 3, b"\x02")
            self.open_node(fp, tab="od")
            pg.wait_for_selector('details[data-od-group="profile"]')
            self.assertIn("Communication", pg.inner_text('details[data-od-group="communication"] summary'))
            # Groups start folded; a search unfolds what matches.
            self.assertFalse(pg.locator('details[data-od-group="profile"]').evaluate("d => d.open"))
            row = 'tr[data-od-key="%d:1"]' % 0x6110
            self.search("6110")
            pg.wait_for_selector(row, state="visible")
            self.assertIn("set by config", pg.inner_text(row))
            self.assertIn("AI0_Sensor_Type", pg.inner_text(row))
            self.assertNotIn("AI Sensor Type", pg.inner_text(row))  # no repeated object name
            self.assertTrue(pg.locator('details[data-od-group="communication"]').is_hidden())
            self.search("0x6126")
            self.assertIn("SDO variable alarm_limit", pg.inner_text('tr[data-od-key="%d:2"]' % 0x6126))
            self.search("")
            # Read all with progress; a value that differs from the EDS default is marked, also on its object.
            pg.click('button[data-online="od-read-all"]')
            pg.wait_for_selector('[data-online="od-summary"]:has-text("read, 0 not readable")')
            self.search("0x6112")
            self.assertIn("1 ≠ default", pg.inner_text('tr[data-od-object-row="%d"]' % 0x6112))
            self.assertIn("≠ default", pg.inner_text('tr[data-od-key="%d:3"]' % 0x6112))
            self.assertNotIn("≠ default", pg.inner_text('tr[data-od-key="%d:4"]' % 0x6112))
            # Search hides the other rows and empty groups.
            self.search("0x1018")
            self.assertTrue(pg.locator('details[data-od-group="profile"]').is_hidden())
            self.assertTrue(pg.locator('tr[data-od-key="%d:1"]' % 0x1018).is_visible())
            # Read one entry.
            fp.set(0x1018, 4, (0x99).to_bytes(4, "little"))
            pg.click('tr[data-od-key="%d:4"] button[data-online="od-read"]' % 0x1018)
            pg.wait_for_selector('tr[data-od-key="%d:4"]:has-text("153 (0x00000099)")' % 0x1018)
            self.search("0x6112")
            # Edit in place, with read-back.
            pg.click('tr[data-od-key="%d:3"] button[data-online="od-edit"]' % 0x6112)
            pg.fill('tr[data-od-key="%d:3"] input[data-online="od-input"]' % 0x6112, "0")
            pg.click('tr[data-od-key="%d:3"] button[data-online="od-write"]' % 0x6112)
            pg.wait_for_selector('tr[data-od-key="%d:3"] .od-value:not(.differs):has-text("0")' % 0x6112)
            self.assertEqual(fp.value(0x6112, 3), b"\x00")
            # Editing an entry the config writes asks first.
            self.search("0x6110")
            pg.click(row + ' button[data-online="od-edit"]')
            pg.fill(row + ' input[data-online="od-input"]', "31")
            pg.click(row + ' button[data-online="od-write"]')
            self.assertIn("configuration writes this entry at every boot", pg.inner_text("#modal-text"))
            pg.click('#modal button[data-value="cancel"]')
            pg.click(row + ' .od-value button:has-text("Cancel")')
            # The watch list reads again and again.
            self.search("0x7130")
            pg.check('tr[data-od-key="%d:1"] input[data-online="od-watch"]' % 0x7130)
            pg.wait_for_selector('[data-online="watch"] tr[data-watch-key]')
            before = len(fp.sdo_requests("sdo_read"))
            pg.wait_for_timeout(2500)
            self.assertGreaterEqual(len(fp.sdo_requests("sdo_read")) - before, 2)
            self.search("0x611")
            self.shot("object-dictionary")

    def test_copy_as_st_call(self):
        """add-plc-sdo-blocks 4.4: Copy as ST call."""
        pg = self.page
        with self.device() as fp:
            self.open_node(fp, tab="od")
            pg.wait_for_selector('details[data-od-group="profile"]')
            pg.evaluate("() => { window.__copied = []; navigator.clipboard.writeText = async (t) => { "
                        "window.__copied.push(t); }; }")
            copied = lambda: pg.evaluate("() => window.__copied[window.__copied.length - 1]")
            # A read-only INTEGER16 entry copies the read call at once.
            self.search("0x7130")
            # Read, Edit and ST fit in the actions column (a button that spills
            # over sits under the watch column and cannot be clicked).
            spill = pg.evaluate("""() => {
                const b = document.querySelector('tr[data-od-key="%d:1"] button[data-online="od-st"]');
                return b.getBoundingClientRect().right - b.closest("td").getBoundingClientRect().right; }""" % 0x7130)
            self.assertLessEqual(spill, 0)
            pg.click('tr[data-od-key="%d:1"] button[data-online="od-st"]' % 0x7130)
            pg.wait_for_function("() => window.__copied.length === 1")
            text = copied()
            self.assertIn("rd_n%d_7130_1 : CO_SDO_READ;" % NODE, text)
            self.assertIn("NODE := %d, INDEX := 16#7130, SUBINDEX := 1" % NODE, text)
            self.assertIn("LWORD_TO_INT(rd_n%d_7130_1.DATA)" % NODE, text)
            self.assertIn("Copied the CO_SDO_READ call", pg.inner_text("#banner"))
            # The device name (const VISIBLE_STRING) is only read, as a string.
            self.search("0x1008")
            pg.click('tr[data-od-key="%d:0"] button[data-online="od-st"]' % 0x1008)
            pg.wait_for_function("() => window.__copied.length === 2")
            self.assertIn(": CO_SDO_READ_STRING;", copied())
            # A read-write entry asks which call.
            self.search("0x6112")
            pg.click('tr[data-od-key="%d:3"] button[data-online="od-st"]' % 0x6112)
            pg.click('#modal button[data-value="write"]')
            pg.wait_for_function("() => window.__copied.length === 3")
            self.assertIn("wr_n%d_6112_3 : CO_SDO_WRITE;" % NODE, copied())
            self.assertIn("DATA := USINT_TO_LWORD(value), SIZE := 0", copied())
            # Any entry: no type gives CO_SDO_READ / CO_SDO_WRITE; REAL32 the REAL blocks.
            self.search("")
            pg.click('details[data-online="od-any"] > summary')
            pg.fill('input[data-online="od-any-index"]', "0x2100")
            pg.fill('input[data-online="od-any-sub"]', "3")
            pg.click('button[data-online="od-any-st"]')
            pg.click('#modal button[data-value="read"]')
            pg.wait_for_function("() => window.__copied.length === 4")
            self.assertIn("rd_n%d_2100_3 : CO_SDO_READ;" % NODE, copied())
            pg.select_option('select[data-online="od-any-type"]', "REAL32")
            pg.click('button[data-online="od-any-st"]')
            pg.click('#modal button[data-value="write"]')
            pg.wait_for_function("() => window.__copied.length === 5")
            self.assertIn(": CO_SDO_WRITE_REAL;", copied())

    def test_tree_read_object_filters_formats(self):
        """improve-od-browser 2.1-2.5."""
        pg = self.page
        with self.device() as fp:
            fp.set(0x6110, 2, b"\x20\x00")
            fp.set(0x1001, 0, b"\x11")
            self.open_node(fp, tab="od")
            pg.wait_for_selector('details[data-od-group="profile"]')
            pg.click('details[data-od-group="profile"] > summary')
            obj = 'tr[data-od-object-row="%d"]' % 0x6110
            self.assertIn("ARRAY, 9 entries", pg.inner_text(obj))
            self.assertTrue(pg.locator('tr[data-od-key="%d:1"]' % 0x6110).is_hidden())
            pg.click(obj + ' button[data-online="od-toggle"]')
            self.assertTrue(pg.locator('tr[data-od-key="%d:1"]' % 0x6110).is_visible())
            # Read on the object reads its 9 entries.
            before = len(fp.sdo_requests("sdo_read"))
            pg.click(obj + ' button[data-online="od-read-object"]')
            pg.wait_for_selector('tr[data-od-key="%d:8"] [data-online="od-shown"]' % 0x6110)
            reads = fp.sdo_requests("sdo_read")[before:]
            self.assertEqual(reads, [(0x6110, s) for s in range(9)])
            self.assertIn("1 ≠ default", pg.inner_text(obj))
            # Formats: hex and binary.
            key = 'tr[data-od-key="%d:2"]' % 0x6110
            self.assertEqual(pg.inner_text(key + ' [data-online="od-shown"]'), "32 (0x0020)")
            pg.select_option(key + ' select[data-online="od-format"]', "hex")
            self.assertEqual(pg.inner_text(key + ' [data-online="od-shown"]'), "0x0020")
            pg.select_option(key + ' select[data-online="od-format"]', "bin")
            self.assertEqual(pg.inner_text(key + ' [data-online="od-shown"]'), "0b0000 0000 0010 0000")
            # Filters: changed from default, combined with the search.
            pg.click('button[data-online="od-read-all"]')
            pg.wait_for_selector('[data-online="od-summary"]:has-text("read")')
            pg.check('input[data-od-filter="changed"]')
            shown = pg.eval_on_selector_all("tr[data-od-key]", "rs => rs.filter(r => r.offsetParent).map(r => r.dataset.odKey)")
            # (the identity in 0x1018 differs from the EDS defaults too)
            self.assertEqual(sorted(shown), sorted(["%d:2" % 0x6110, "%d:0" % 0x1001] + ["%d:%d" % (0x1018, s) for s in (1, 2, 3)]))
            pg.uncheck('input[data-od-filter="changed"]')
            pg.check('input[data-od-filter="writable"]')
            self.search("sensor")
            shown = pg.eval_on_selector_all("tr[data-od-key]", "rs => rs.filter(r => r.offsetParent).map(r => r.dataset.odKey)")
            self.assertEqual(sorted(shown), sorted("%d:%d" % (0x6110, s) for s in range(1, 9)))
            pg.uncheck('input[data-od-filter="writable"]')
            # PDO marks with the PLC location.
            pg.check('input[data-od-filter="pdo"]')
            self.search("")
            self.assertIn("TPDO1 bits 0-15, %IW3100", pg.inner_text('tr[data-od-key="%d:1"]' % 0x7130))
            self.assertIn("TPDO1 bits 16-31", pg.inner_text('tr[data-od-key="%d:2"]' % 0x7130))
            pg.uncheck('input[data-od-filter="pdo"]')
            # Bit view of the error register.
            self.search("0x1001")
            pg.click('tr[data-od-key="%d:0"] button[data-online="od-bits"]' % 0x1001)
            bits = pg.inner_text('tr[data-od-key="%d:0"] [data-online="od-bit-list"]' % 0x1001)
            self.assertIn("generic error", bits)
            self.assertIn("communication error", bits)
            self.assertNotIn("voltage", bits)
            # Bit names come from the entry's note (the built-in CiA 402 notes for a drive); no bits, no bit view.
            names = pg.evaluate("""() => [odBitNames({ index: 0x6041, subindex: 0, type: "UNSIGNED16" }, { data: "37 02" },
                                                     { bits: { 0: "ready to switch on", 1: "switched on", 2: "operation enabled",
                                                               4: "voltage enabled", 5: "quick stop" } }),
                                          odBitNames({ index: 0x6041, subindex: 0, type: "UNSIGNED16" }, { data: "37 02" }, {})]""")
            self.assertEqual(names[0], ["ready to switch on", "switched on", "operation enabled", "voltage enabled",
                                        "quick stop", "bit 9"])
            self.assertIsNone(names[1])
            self.assertEqual(pg.evaluate("""() => [odPdoText({ pdo: "RPDO1", bits: [3, 3], location: "%QX100.3" }),
                                                   odPdoText({ pdo: "TPDO1", bits: [0, 15] })]"""),
                             ["RPDO1 bit 3, %QX100.3", "TPDO1 bits 0-15"])

    def visible_keys(self):
        return self.page.eval_on_selector_all("tr[data-od-key]", "rs => rs.filter(r => r.offsetParent).map(r => r.dataset.odKey)")

    def test_watch_list(self):
        """improve-od-browser 3.1-3.2."""
        pg = self.page
        self.cfg["nodes"][0]["sdo_variables"].append({"name": "sensor5", "index": "0x6110", "subindex": 5, "type": "UNSIGNED16",
                                                      "direction": "read", "iec_location": "%IW3200", "period_ms": 100})
        with self.device() as fp:
            self.open_node(fp, tab="od")
            pg.wait_for_selector('details[data-od-group="profile"]')
            pg.select_option('select[data-online="watch-period"]', "500")
            for q, key in (("0x7130", (0x7130, 1)), ("0x7130", (0x7130, 2)), ("0x1008", (0x1008, 0))):
                self.search(q)
                pg.check('tr[data-od-key="%d:%d"] input[data-online="od-watch"]' % key)
            pg.wait_for_selector('[data-online="watch-round"]')
            self.assertIn("SDO variables the program reads periodically", pg.inner_text('[data-online="watch-sdo-vars"]'))
            row = '[data-online="watch"] tr[data-watch-key="%d:1"]' % 0x7130
            pg.wait_for_selector(row + ' [data-online="watch-age"]:has-text(" s")')
            fp.set(0x7130, 1, (250).to_bytes(2, "little"))
            pg.wait_for_selector(row + ".changed")
            fp.set(0x7130, 1, (-20 & 0xFFFF).to_bytes(2, "little"))
            pg.wait_for_selector(row + ' [data-online="watch-min"]:has-text("-20")')
            self.assertEqual(pg.inner_text(row + ' [data-online="watch-max"]'), "250")
            pg.click('button[data-online="watch-reset"]')
            # The graph: two numeric lines, the string entry has none; points come with each round.
            pg.click('button[data-online="watch-graph-toggle"]')
            pg.wait_for_selector('[data-online="watch-graph"] .uplot')
            legend = pg.inner_text('[data-online="watch-graph"] .u-legend')
            self.assertIn("AI0_Input_PV", legend)
            self.assertIn("AI1_Input_PV", legend)
            self.assertNotIn("1008", legend)
            n1 = int(pg.get_attribute('[data-online="watch-graph"]', "data-points"))
            pg.wait_for_timeout(1200)
            self.assertGreater(int(pg.get_attribute('[data-online="watch-graph"]', "data-points")), n1)
            # A slow node: the round takes longer than the period.
            fp.delay = 0.25
            pg.wait_for_selector('[data-online="watch-round"]:has-text("longer than the chosen 500 ms")', timeout=8000)
            fp.delay = 0
            # The list is kept on this PC and comes back after a reload.
            pg.reload()
            pg.click('button[data-view="online"]')
            pg.wait_for_selector("text=Connected to")
            pg.click('tr[data-online-node="%d"]' % NODE)
            pg.click('button[data-online-tab="od"]')
            pg.wait_for_selector('[data-online="watch"] tr[data-watch-key="%d:0"]' % 0x1008)
            self.assertEqual(pg.eval_on_selector_all('[data-online="watch"] tr[data-watch-key]', "rs => rs.map(r => r.dataset.watchKey)"),
                             ["%d:1" % 0x7130, "%d:2" % 0x7130, "%d:0" % 0x1008])
            self.assertEqual(pg.input_value('select[data-online="watch-period"]'), "500")
            with open(os.path.join(self.cfg_dir, "online.json"), encoding="utf-8") as f:
                self.assertEqual(json.load(f)["projects"][self.project]["watch"][str(NODE)]["period_ms"], 500)
            pg.wait_for_selector('[data-online="watch"] tr[data-watch-key="%d:1"] strong' % 0x7130)
            pg.click('button[data-online="watch-graph-toggle"]')
            pg.wait_for_selector('[data-online="watch-graph"] .uplot')
            pg.wait_for_timeout(3000)
            self.shot("watch-graph", '[data-online="od"] fieldset')

    def test_edit_keep_any_compare_csv(self):
        """improve-od-browser 4.1-4.5."""
        pg = self.page
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        with self.device() as fp:
            self.open_node(fp, tab="od")
            pg.wait_for_selector('details[data-od-group="profile"]')
            # Limits shown; a value outside them asks first, Cancel sends nothing.
            self.search("0x6110")
            row = 'tr[data-od-key="%d:5"]' % 0x6110
            pg.click(row + ' button[data-online="od-edit"]')
            self.assertEqual(pg.inner_text(row + ' [data-online="od-limits"]'), "EDS limits: 30 to 33")
            pg.fill(row + ' input[data-online="od-input"]', "40")
            pg.click(row + ' button[data-online="od-write"]')
            self.assertIn("The EDS allows 30 to 33", pg.inner_text("#modal-text"))
            pg.click('#modal button[data-value="cancel"]')
            self.assertEqual(fp.sdo_requests("sdo_write"), [])
            # A value inside them is written, read back, and can be kept as a startup SDO.
            pg.fill(row + ' input[data-online="od-input"]', "32")
            pg.click(row + ' button[data-online="od-write"]')
            pg.wait_for_selector(row + ' button[data-online="od-keep"]')
            self.assertIn("32", pg.inner_text(row + ' [data-online="od-shown"]'))
            pg.click(row + ' button[data-online="od-keep"]')
            sdo = pg.evaluate("() => S.config.nodes[0].sdo")
            self.assertIn({"index": "0x6110", "subindex": 5, "type": "UNSIGNED16", "value": 32}, sdo)
            self.assertTrue(pg.evaluate("() => S.dirty"))
            self.assertEqual(fp.sdo_requests("sdo_write"), [(0x6110, 5)])
            # An entry with a startup SDO: its value changes, no second entry.
            row1 = 'tr[data-od-key="%d:1"]' % 0x6110
            pg.click(row1 + ' button[data-online="od-edit"]')
            pg.fill(row1 + ' input[data-online="od-input"]', "31")
            pg.click(row1 + ' button[data-online="od-write"]')
            pg.click('#modal button[data-value="write"]')
            pg.click(row1 + ' button[data-online="od-keep"]')
            sdo = pg.evaluate("() => S.config.nodes[0].sdo")
            self.assertEqual([x["value"] for x in sdo if x["index"] == "0x6110" and x["subindex"] == 1], [31])
            self.assertEqual(len(sdo), 5)
            # The heartbeat object is not kept: the plugin sets it.
            self.search("0x1017")
            hb = 'tr[data-od-key="%d:0"]' % 0x1017
            pg.click(hb + ' button[data-online="od-edit"]')
            pg.fill(hb + ' input[data-online="od-input"]', "100")
            pg.click(hb + ' button[data-online="od-write"]')
            pg.click('#modal button[data-value="write"]')
            pg.wait_for_selector(hb + ' [data-online="od-keep-reason"]')
            self.assertIn("plugin sets 0x1017 itself from the node's heartbeat setting", pg.inner_text(hb))
            # Any entry, also one the EDS does not list.
            fp.set(0x2100, 3, b"\x01\x02")
            pg.click('details[data-online="od-any"] > summary')
            pg.fill('input[data-online="od-any-index"]', "0x2100")
            pg.fill('input[data-online="od-any-sub"]', "3")
            pg.click('button[data-online="od-any-read"]')
            pg.wait_for_selector('[data-online="od-any-result"]:has-text("01 02")')
            # Compare marks from the parameters tab.
            pg.click('button[data-online-tab="params"]')
            path = self.backup(os.path.join(tmp, "node5-rtd.dcf"))
            fp.set(0x6112, 3, b"\x02")
            pg.set_input_files('input[data-online="compare-file"]', path)
            pg.click('button[data-online="compare"]')
            pg.wait_for_selector('[data-online="compare-summary"]')
            pg.click('button[data-online-tab="od"]')
            pg.wait_for_selector('[data-online="od-compare"]:has-text("node5-rtd.dcf")')
            self.search("")
            pg.check('input[data-od-filter="compare"]')
            self.assertEqual(self.visible_keys(), ["%d:3" % 0x6112])
            self.assertIn("≠ backup: 0", pg.inner_text('tr[data-od-key="%d:3"]' % 0x6112))
            # CSV of the shown rows.
            with pg.expect_download() as d:
                pg.click('button[data-online="od-csv"]')
            out = os.path.join(tmp, "od.csv")
            d.value.save_as(out)
            with open(out, encoding="utf-8") as f:
                lines = f.read().splitlines()
            self.assertEqual(lines[0], "Entry,Name,Type,Access,EDS default,Value,Marks")
            self.assertEqual(len(lines), 2)
            self.assertTrue(lines[1].startswith("0x6112:3,"))
            pg.click('button[data-online="od-compare-clear"]')
            self.assertEqual(pg.locator('input[data-od-filter="compare"]').count(), 0)

    def test_od_values_follow_compare_restore_and_writes(self):
        """fix-gui-test-findings C6: the object dictionary shows what a
        compare read, and no stale value after a restore or a write."""
        pg = self.page
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        row = 'tr[data-od-key="%d:3"]' % 0x6112
        shown = row + ' [data-online="od-shown"]'
        with self.device() as fp:
            self.open_node(fp, tab="od")
            pg.click('button[data-online="od-read-all"]')
            pg.wait_for_selector('[data-online="od-summary"]:has-text("read, 0 not readable")')
            before = fp.value(0x6112, 3)[0]
            pg.click('button[data-online-tab="params"]')
            path = self.backup(os.path.join(tmp, "b.dcf"))
            fp.set(0x6112, 3, bytes([before + 1]))
            pg.set_input_files('input[data-online="compare-file"]', path)
            pg.click('button[data-online="compare"]')
            pg.wait_for_selector('[data-online="compare-summary"]:has-text("1 different")')
            pg.click('button[data-online-tab="od"]')
            self.search("0x6112")
            pg.wait_for_selector(row, state="visible")
            self.assertTrue(pg.inner_text(shown).startswith(str(before + 1)))
            self.assertIn("≠ backup: %d" % before, pg.inner_text(row))
            # A restore writes it back: the shown value is gone until read again.
            pg.click('button[data-online-tab="params"]')
            pg.set_input_files('input[data-online="restore-file"]', path)
            pg.click('button[data-online="restore"]')
            pg.click('#modal button[data-value="restore"]')
            pg.wait_for_selector('[data-online="restore-done"]:has-text("1 written")')
            pg.click('button[data-online-tab="od"]')
            pg.wait_for_selector(row, state="visible")
            self.assertEqual(pg.locator(shown).count(), 0)
            pg.click(row + ' button[data-online="od-read"]')
            pg.wait_for_selector(shown)
            # So does a write from the Overview's SDO panel.
            pg.click('button[data-online-tab="overview"]')
            pg.fill('input[data-online="index"]', "0x6112")
            pg.fill('input[data-online="subindex"]', "3")
            pg.select_option('select[data-online="type"]', "UNSIGNED8")
            pg.fill('input[data-online="value"]', "1")
            pg.click('button[data-online="write"]')
            pg.wait_for_selector('[data-online="sdo-result"]:has-text("Written")')
            pg.click('button[data-online-tab="od"]')
            pg.wait_for_selector(row, state="visible")
            self.assertEqual(pg.locator(shown).count(), 0)

    def test_watch_graph_draws_its_lines(self):
        """C8: the graph's series had no colour, so it drew nothing."""
        pg = self.page
        with self.device() as fp:
            self.open_node(fp, tab="od")
            pg.wait_for_selector('details[data-od-group="profile"]')
            pg.select_option('select[data-online="watch-period"]', "500")
            for sub in (1, 2):
                self.search("0x7130")
                pg.check('tr[data-od-key="%d:%d"] input[data-online="od-watch"]' % (0x7130, sub))
            for theme in ("light", "dark"):
                pg.evaluate("t => document.documentElement.dataset.theme = t", theme)
                pg.click('button[data-online="watch-graph-toggle"]')
                pg.wait_for_selector('[data-online="watch-graph"] .uplot')
                for k in range(4):
                    fp.set(0x7130, 1, (100 * k).to_bytes(2, "little"))
                    fp.set(0x7130, 2, (50 * k).to_bytes(2, "little"))
                    pg.wait_for_timeout(500)
                # Each series has a colour and a line; the canvas has drawn pixels in both.
                strokes = pg.evaluate("() => S.od[%d].plot.series.slice(1).map((s) => s._stroke || s.stroke())" % NODE)
                self.assertEqual(len(strokes), 2)
                self.assertTrue(all(isinstance(c, str) and c.startswith("#") for c in strokes), strokes)
                self.assertNotEqual(strokes[0], strokes[1])
                drawn = pg.evaluate("""(colors) => {
                    const c = document.querySelector('[data-online="watch-graph"] canvas');
                    const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
                    const rgb = colors.map((h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16)));
                    const seen = rgb.map(() => 0);
                    for (let i = 0; i < d.length; i += 4) rgb.forEach((x, k) => {
                      if (d[i + 3] > 200 && Math.abs(d[i] - x[0]) < 8 && Math.abs(d[i + 1] - x[1]) < 8 && Math.abs(d[i + 2] - x[2]) < 8) seen[k]++;
                    });
                    return seen; }""", strokes)
                self.assertTrue(all(n > 0 for n in drawn), drawn)
                pg.click('button[data-online="watch-graph-toggle"]')

    def test_notes_in_object_dictionary(self):
        # Device notes (canopen-device-notes): text, meaning, scaled value, a
        # value picker on edit and the note editor.
        with open(os.path.join(self.project, "canworks", "rtd8.eds.notes.json"), "w", encoding="utf-8") as f:
            json.dump({"format": "canworks-notes.v1", "objects": {
                "0x6112:3": {"text": "Mode of channel 3", "values": {"0": "off", "2": "fast"}},
                "0x6126:1": {"unit": "bar", "scale": 0.5}}}, f)
        pg = self.page
        with self.device() as fp:
            fp.set(0x6112, 3, b"\x02")
            self.open_node(fp, tab="od")
            pg.wait_for_selector('details[data-od-group="profile"]')
            pg.click('button[data-online="od-read-all"]')
            pg.wait_for_selector('[data-online="od-summary"]:has-text("read, 0 not readable")')
            row = 'tr[data-od-key="%d:3"]' % 0x6112
            self.search("0x6112")
            self.assertIn("Mode of channel 3", pg.inner_text(row))
            self.assertIn("(fast)", pg.inner_text(row + ' [data-online="od-meaning"]'))
            # The built-in CiA 301 note of the heartbeat time; the search finds note texts.
            self.search("sends its heartbeat")
            pg.wait_for_selector('tr[data-od-key="%d:0"]' % 0x1017, state="visible")
            # Edit by name.
            self.search("0x6112")
            pg.click(row + ' button[data-online="od-edit"]')
            pg.select_option(row + ' select[data-value-pick]', "0")
            self.assertEqual(pg.input_value(row + ' input[data-online="od-input"]'), "0")
            pg.click(row + ' button[data-online="od-write"]')
            pg.wait_for_selector(row + ' [data-online="od-meaning"]:has-text("(off)")')
            self.assertEqual(fp.value(0x6112, 3), b"\x00")
            # The note editor keeps a draft edit; its button stays inside the actions column.
            note_box = pg.locator(row + ' button[data-online="od-note-edit"]').bounding_box()
            watch_box = pg.locator(row + ' td.od-watch').bounding_box()
            self.assertLessEqual(note_box["x"] + note_box["width"], watch_box["x"])
            pg.click(row + ' button[data-online="od-note-edit"]')
            pg.fill('#modal [data-note-field="text"]', "Speed of channel 3")
            pg.click('#modal button[data-value="save"]')
            pg.wait_for_selector(row + ':has-text("Speed of channel 3")')
            self.assertEqual(pg.evaluate("() => S.model.notes['rtd8.eds']['0x6112:3']"), {"text": "Speed of channel 3", "values": {"0": "off", "2": "fast"}})
            self.search("0x6126")
            self.assertIn("bar", pg.inner_text('tr[data-od-key="%d:1"]' % 0x6126))

    def test_runtime_with_other_network_names(self):
        # A draft with one network against a runtime that runs two networks
        # of other names: the draft's node 5 still has its EDS online.
        self.other_names()

    def test_runtime_with_other_network_names_v2(self):
        # The same with a version 2 draft whose one network has a third name.
        net = copy.deepcopy(self.cfg)
        net.pop("schema_version", None)
        net["name"] = "line"
        v2 = {"schema_version": 2, "networks": [net]}

        def write_config(diagnostics=None):
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(dict(v2, **({"diagnostics": diagnostics} if diagnostics else {})), f, indent=2)
        self.write_config = write_config
        self.other_names()

    def other_names(self):
        from .fake_diag import TWO_NETWORKS
        pg = self.page
        with self.device() as fp:
            fp.networks = copy.deepcopy(TWO_NETWORKS)
            self.open_node(fp, tab="od")
            pg.wait_for_selector('details[data-od-group="profile"]')
            self.assertEqual(pg.locator('[data-online="no-eds"]').count(), 0)

    def test_read_only(self):
        pg = self.page
        with self.device(allow=False) as fp:
            self.open_node(fp, allow=False, tab="od")
            pg.wait_for_selector('[data-online="od-read-only"]')
            self.assertTrue(pg.is_disabled('tr[data-od-key="%d:3"] button[data-online="od-edit"]' % 0x6112))
            pg.click('button[data-online-tab="params"]')
            pg.wait_for_selector('[data-online="params-read-only"]')
            self.assertTrue(pg.is_disabled('button[data-online="restore"]'))
            self.assertFalse(pg.is_disabled('button[data-online="backup"]'))

    # -- parameters --------------------------------------------------------------
    def backup(self, path):
        pg = self.page
        with pg.expect_download() as d:
            pg.click('button[data-online="backup"]')
        d.value.save_as(path)
        pg.wait_for_selector('[data-online="backup-done"]')
        return path

    def test_backup_compare_restore_store(self):
        pg = self.page
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        with self.device() as fp:
            fp.set(0x1010, 1, b"\0\0\0\0")
            self.open_node(fp, tab="params")
            pg.wait_for_selector('button[data-online="store"]')
            path = self.backup(os.path.join(tmp, "b.dcf"))
            with open(path, encoding="utf-8") as f:
                self.assertIn("NodeName=rtd", f.read())
            orig = fp.value(0x6112, 3)
            fp.set(0x6112, 3, b"\x02")
            # Compare against the file: differences first.
            pg.set_input_files('input[data-online="compare-file"]', path)
            pg.click('button[data-online="compare"]')
            pg.wait_for_selector('[data-online="compare-summary"]:has-text("1 different")')
            self.assertIn("different", pg.inner_text("table.compare-rows tbody tr:first-child"))
            # Restore: preview, hold option off, then the result says nothing was stored.
            pg.set_input_files('input[data-online="restore-file"]', path)
            pg.click('button[data-online="restore"]')
            pg.wait_for_selector('[data-online="restore-preview"]')
            self.assertFalse(pg.is_checked('input[data-online="restore-hold"]'))
            self.assertIn("left out", pg.inner_text('[data-online="restore-preview"]'))
            self.shot("restore-dialog", "#modal")
            pg.check('input[data-online="restore-hold"]')
            pg.click('#modal button[data-value="restore"]')
            pg.wait_for_selector('[data-online="restore-done"]:has-text("1 written, 0 failed")')
            self.assertIn("not stored on the device", pg.inner_text('[data-online="restore-note"]'))
            self.assertEqual(fp.value(0x6112, 3), orig)
            self.assertNotIn((0x1010, 1), fp.sdo_requests("sdo_write"))
            # Store is its own dialog.
            pg.click('button[data-online="store"]')
            self.assertIn("0x1010 sub 1", pg.inner_text("#modal-text"))
            pg.click('#modal button[data-value="store"]')
            pg.wait_for_selector("#banner:has-text('stored (0x1010 sub 1)')")
            self.assertEqual(fp.value(0x1010, 1), b"save")

    def test_restore_to_another_product_needs_a_tick(self):
        pg = self.page
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        with self.device() as fp:
            self.open_node(fp, tab="params")
            path = self.backup(os.path.join(tmp, "b.dcf"))
            fp.set(0x1018, 2, (0x3E9).to_bytes(4, "little"))
            fp.set(0x6112, 3, b"\x02")
            pg.set_input_files('input[data-online="restore-file"]', path)
            pg.click('button[data-online="restore"]')
            pg.wait_for_selector('[data-online="restore-preview"]:has-text("product code differs")')
            self.assertTrue(pg.is_disabled('#modal button[data-value="restore"]'))
            pg.check('input[data-online="restore-other"]')
            pg.click('#modal button[data-value="restore"]')
            pg.wait_for_selector('[data-online="restore-done"]:has-text("1 written")')

    def test_backup_of_a_node_that_has_not_booted_warns(self):
        pg = self.page
        with self.device(booted=False) as fp:
            self.open_node(fp, tab="params")
            pg.click('button[data-online="backup"]')
            self.assertIn("has not booted", pg.inner_text("#modal-text"))
            pg.click('#modal button[data-value="cancel"]')
            self.assertFalse(fp.sdo_requests("sdo_read"))

    def test_job_survives_a_reload(self):
        pg = self.page
        with self.device() as fp:
            fp.delay = 0.02
            self.open_node(fp, tab="od")
            pg.click('button[data-online="od-read-all"]')
            pg.wait_for_selector('[data-online="job-progress"]')
            pg.reload()
            pg.wait_for_selector("#editor:not([hidden])")
            pg.click('button[data-view="online"]')
            pg.wait_for_selector("text=Connected to")
            pg.click('tr[data-online-node="%d"]' % NODE)
            pg.click('button[data-online-tab="od"]')
            pg.wait_for_selector('[data-online="job-progress"]')
            pg.click('button[data-online="job-cancel"]')
            pg.wait_for_selector('[data-online="od-summary"]:has-text("cancelled")')

    # -- TIME period --------------------------------------------------------------
    def test_time_period_field(self):
        pg = self.page
        self.open()
        pg.click('button[data-view="bus"]')
        pg.click('details[data-advanced="master"] > summary')
        f = 'input[data-path="master.time_period_ms"]'
        pg.wait_for_selector(f)
        self.assertEqual(pg.inner_text('[data-online="time-cob"]'), "")
        pg.fill(f, "1000")
        self.assertEqual(pg.inner_text('[data-online="time-cob"]'), "Sent on COB-ID 0x100.")
        pg.wait_for_selector('[data-for="master.time_period_ms"]:has-text("no configured node is set to consume")')
        pg.fill('input[data-path="master.time_cob_id"]', "0x180")
        self.assertEqual(pg.inner_text('[data-online="time-cob"]'), "Sent on COB-ID 0x180.")
        pg.fill(f, "")
        pg.wait_for_function("() => document.body.dataset.checking === '0'")
        pg.click("#btn-save")
        pg.wait_for_selector("#banner:has-text('Saved')")
        with open(self.config_path, encoding="utf-8") as fh:
            self.assertNotIn("time_period_ms", json.load(fh)["master"])


if __name__ == "__main__":
    unittest.main()
