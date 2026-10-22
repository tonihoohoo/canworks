"""Plain CAN networks and the CAN messages page in a real browser (spec
canopen-configurator, "CAN messages page"): a plain network built from the
example DBC and saved, and the online view against the fake plugin's plain
network status. Needs Playwright, like test_configurator_page.py."""

import json
import os
import shutil

from canworks import diag

from .fake_diag import PLAIN_NETWORK, TOKEN, FakePlugin
from .helpers import REPO, add_network, net_action, tree_view, tool_tab
from .test_configurator_layout import CONTRAST, TARGETS
from .test_configurator_online_page import OnlineBase
from .test_configurator_page import load

EXAMPLE = os.path.join(REPO, "examples", "raw-can")

# A made-up status message with switch Page and a signal on each of pages 1
# and 2, and one with two switches and no SG_MUL_VAL_.
MUX_DBC = """VERSION ""

NS_ :

BS_:

BU_: Sensor

BO_ 768 Status: 3 Sensor
 SG_ Page M : 0|8@1+ (1,0) [0|255] "" Vector__XXX
 SG_ Temp m1 : 8|16@1- (0.1,0) [0|0] "degC" Vector__XXX
 SG_ Press m2 : 8|16@1+ (1,0) [0|0] "kPa" Vector__XXX

BO_ 769 Twin: 3 Sensor
 SG_ A M : 0|4@1+ (1,0) [0|15] "" Vector__XXX
 SG_ B M : 4|4@1+ (1,0) [0|15] "" Vector__XXX
 SG_ C m1 : 8|8@1+ (1,0) [0|255] "" Vector__XXX
"""


class RawPage(OnlineBase):
    def write_config(self, diagnostics=None):
        cfg = json.loads(json.dumps(self.cfg))
        if diagnostics:
            cfg["diagnostics"] = diagnostics
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)

    def test_build_a_plain_network_from_the_dbc(self):
        pg = self.page
        os.remove(self.config_path)
        self.open()
        add_network(pg)
        pg.click('#modal button[data-value="none"]')
        pg.wait_for_selector("h2:has-text('Bus')")
        # No nodes and no Add node… under this network in the tree.
        self.assertEqual(pg.locator('#tree .open-net [data-node], #tree .open-net [data-action="add-node"]').count(), 0)
        self.assertEqual(pg.locator('[data-path="master.node_id"]').count(), 0)
        net_action(pg, 0, "remove")
        pg.click('#modal button[data-value="remove"]')
        pg.wait_for_selector("h2:has-text('Bus')")
        pg.fill('input[data-path="adapter.interface"]', "can1")
        tree_view(pg, "raw")
        pg.wait_for_selector("h2:has-text('CAN messages')")
        self.assertEqual(pg.inner_text('[data-raw="dbc"]'), "No DBC file yet.")
        self.assertEqual(pg.locator('input[data-path="raw.dbc"]').count(), 0)
        # One click on Import DBC… opens the system file picker: no dialog first.
        with pg.expect_file_chooser() as fc:
            pg.click("#raw-import .file-button")
        self.assertFalse(pg.evaluate("() => document.querySelector('#modal').open"))
        fc.value.set_files(os.path.join(EXAMPLE, "cab.dbc"))
        pg.wait_for_selector('#modal select[data-pick="Joystick"]')
        # The PLC sends Display in the DBC, so Send is preselected.
        self.assertEqual(pg.input_value('#modal select[data-pick="Display"]'), "tx")
        self.assertEqual(pg.input_value('#modal select[data-pick="Joystick"]'), "rx")
        pg.select_option('#modal select[data-pick="Sensor"]', "")
        pg.click('#modal button[data-value="add"]')
        pg.wait_for_selector("#banner:has-text('Imported 3 messages from cab.dbc')")
        self.assertEqual(pg.inner_text('[data-raw="dbc"]'), "cab.dbc")
        self.assertIn("0x18FF1020 ext", pg.inner_text('[data-raw-table="rx"]'))
        pg.wait_for_function("() => document.body.dataset.checking === '0'")
        self.assertEqual(pg.text_content("#problem-list").strip(), "No problems.")
        # The network's own scan watchdog; a bad value shows at the field.
        pg.fill('input[data-path="raw.scan_watchdog_ms"]', "5")
        pg.wait_for_selector('input[data-path="raw.scan_watchdog_ms"].invalid')
        pg.fill('input[data-path="raw.scan_watchdog_ms"]', "250")
        pg.wait_for_function("() => document.body.dataset.checking === '0'")
        self.assertEqual(pg.text_content("#problem-list").strip(), "No problems.")
        pg.click("#btn-save")
        pg.wait_for_selector("#banner:has-text('Saved')")
        saved = load(self.config_path)
        net = saved["networks"][0]
        self.assertEqual(net["raw"]["scan_watchdog_ms"], 250)
        self.assertEqual(len(saved["networks"]), 1)
        self.assertEqual(net["protocol"], "none")
        self.assertEqual(net["adapter"]["interface"], "can1")
        self.assertEqual([m["name"] for m in net["raw"]["rx"]], ["Joystick", "Pedal"])
        self.assertEqual([m["name"] for m in net["raw"]["tx"]], ["Display"])
        self.assertEqual(net["raw"]["dbc"], "cab.dbc")
        self.assertTrue(os.path.isfile(os.path.join(self.project, "canworks", "cab.dbc")))
        self.assertTrue(all(s.get("iec_location") for m in net["raw"]["rx"] + net["raw"]["tx"] for s in m["signals"]))

    def plain_config(self, rx):
        self.cfg = {"schema_version": 2, "networks": [{
            "name": "cab", "protocol": "none", "adapter": {"type": "socketcan", "interface": "can0", "bitrate": 250000},
            "raw": {"rx": rx}}]}
        self.write_config()

    def test_pages_in_the_bit_grid(self):
        pg = self.page
        self.plain_config([{"name": "Status", "id": 0x300, "dlc": 3, "signals": [
            {"name": "Page", "start_bit": 0, "length": 8, "iec_location": "%IB300"},
            {"name": "Temp", "start_bit": 8, "length": 16, "iec_location": "%IW301"},
            {"name": "Press", "start_bit": 8, "length": 16, "iec_location": "%IW302"}]}])
        self.open()
        tree_view(pg, "raw")
        pg.click('tr[data-raw="rx:0"]')
        pg.wait_for_selector('[data-raw-editor="rx:0"]')
        # Before: Temp and Press overlap.
        self.assertGreater(pg.locator(".raw-bit.raw-clash").count(), 0)
        self.assertEqual(pg.locator('input[data-path="raw.rx[0].signals[1].mux"]').is_disabled(), True)
        pg.check('input[data-path="raw.rx[0].signals[0].multiplexer"]')
        pg.fill('input[data-path="raw.rx[0].signals[1].mux"]', "1")
        pg.press('input[data-path="raw.rx[0].signals[1].mux"]', "Tab")
        pg.fill('input[data-path="raw.rx[0].signals[2].mux"]', "2")
        pg.press('input[data-path="raw.rx[0].signals[2].mux"]', "Tab")
        pg.wait_for_selector('select[data-raw-page="rx:0"]')
        self.assertEqual(pg.eval_on_selector_all('select[data-raw-page="rx:0"] option', "os => os.map(o => o.textContent)"),
                         ["Page = 1", "Page = 2"])
        pg.select_option('select[data-raw-page="rx:0"]', label="Page = 2")
        self.assertEqual(pg.inner_text('[data-raw-shown="rx:0"]'), "Shows Page, Press")
        self.assertEqual(pg.locator(".raw-bit.raw-clash").count(), 0)
        self.assertIn("Press", pg.get_attribute(".raw-grid td[title='bit 8: Press']", "title"))
        # No overlap problem (nor any other).
        pg.wait_for_selector("#problem-list li.ok", state="attached")
        pg.select_option('select[data-raw-page="rx:0"]', label="Page = 1")
        self.assertEqual(pg.inner_text('[data-raw-shown="rx:0"]'), "Shows Page, Temp")
        # A page on a switch that is not there shows at the Page cell.
        pg.uncheck('input[data-path="raw.rx[0].signals[0].multiplexer"]')
        pg.wait_for_selector('input[data-path="raw.rx[0].signals[1].mux"].invalid')
        self.assertIn("Received Status, signal Temp:", pg.inner_text("#problem-list"))
        pg.check('input[data-path="raw.rx[0].signals[0].multiplexer"]')
        pg.wait_for_function("() => document.body.dataset.checking === '0'")
        # A value the 8-bit switch cannot have (path ...mux.values[0]) too.
        pg.fill('input[data-path="raw.rx[0].signals[1].mux"]', "300")
        pg.wait_for_selector('input[data-path="raw.rx[0].signals[1].mux"].invalid')
        self.assertIn("300", pg.inner_text("#problem-list"))
        pg.fill('input[data-path="raw.rx[0].signals[1].mux"]', "1")
        pg.wait_for_selector("#problem-list li.ok", state="attached")
        pg.click("#btn-save")
        pg.wait_for_selector("#banner:has-text('Saved')")
        sigs = load(self.config_path)["networks"][0]["raw"]["rx"][0]["signals"]
        self.assertEqual(sigs[0].get("multiplexer"), True)
        self.assertEqual(sigs[1]["mux"], {"values": [1]})
        self.assertEqual(sigs[2]["mux"], {"values": [2]})

    def test_selected_row_reads(self):
        """fix-clipped-text-configure: on a selected message row, in both
        themes, Remove and the row's text keep WCAG AA contrast."""
        pg = self.page
        self.plain_config([{"id": 0x300, "dlc": 8}])
        self.open()
        tree_view(pg, "raw")
        pg.click('tr[data-raw="rx:0"]')
        pg.wait_for_selector('tr.selected[data-raw="rx:0"]')
        check = CONTRAST.replace("#view *, #side *, #problems *, header *, #banner *, #sim-banner", ".raw-table tr.selected *")
        for theme in ("light", "dark"):
            pg.evaluate("(t) => showTheme(t)", theme)  # the colours under test, not the Settings menu
            pg.wait_for_timeout(200)
            self.assertTrue(pg.is_visible('tr.selected[data-raw="rx:0"] button.danger'))
            self.assertEqual(pg.evaluate(check), [], theme)

    def test_import_a_multiplexed_message(self):
        pg = self.page
        self.plain_config([])
        dbc = os.path.join(self.project, "status.dbc")
        with open(dbc, "w", encoding="utf-8") as f:
            f.write(MUX_DBC)
        self.open()
        tree_view(pg, "raw")
        pg.set_input_files('input[data-raw="dbc-input"]', dbc)
        pg.wait_for_selector('#modal select[data-pick="Status"]')
        self.assertEqual(pg.inner_text('#modal [data-raw-mux="Status"]'), "switch Page, 2 pages")
        self.assertNotIn("multiplexed left out", pg.inner_text("#modal"))
        self.assertIn("several switches but no SG_MUL_VAL_", pg.inner_text('#modal [data-raw-mux-problem="Twin"]'))
        pg.select_option('#modal select[data-pick="Twin"]', "")
        pg.click('#modal button[data-value="add"]')
        pg.wait_for_selector("#banner:has-text('Imported 1 message')")
        pg.wait_for_selector("#problem-list li.ok", state="attached")
        pg.click('tr[data-raw="rx:0"]')
        # Rows: the switch, then page 1, then page 2.
        self.assertEqual(pg.eval_on_selector_all('[data-raw-editor="rx:0"] .raw-signals tbody tr',
                                                 "rs => rs.map(r => r.dataset.signal)"), ["0", "1", "2"])
        self.assertEqual(pg.input_value('input[data-path="raw.rx[0].signals[2].mux"]'), "2")
        pg.click("#btn-save")
        pg.wait_for_selector("#banner:has-text('Saved')")
        m = load(self.config_path)["networks"][0]["raw"]["rx"][0]
        self.assertEqual(m["name"], "Status")
        by = {s["name"]: s for s in m["signals"]}
        self.assertIs(by["Page"]["multiplexer"], True)
        self.assertEqual(by["Temp"]["mux"]["values"], [1])
        self.assertEqual(by["Press"]["mux"]["values"], [2])
        self.assertNotIn("on", by["Temp"]["mux"])
        self.assertTrue(all(s.get("iec_location") for s in m["signals"]))

    def draft(self, expr):
        return self.page.evaluate("() => JSON.parse(JSON.stringify(%s))" % expr)

    def joystick_config(self, dbc="cab.dbc"):
        self.cfg = load(os.path.join(EXAMPLE, "canworks.json"))
        raw = self.cfg["networks"][0]["raw"]
        raw["rx"] = [m for m in raw["rx"] if m["name"] == "Joystick"]
        raw.pop("tx", None)
        raw["dbc"] = dbc
        self.write_config()

    def test_pick_more_messages_later(self):
        pg = self.page
        self.joystick_config()
        shutil.copy(os.path.join(EXAMPLE, "cab.dbc"), os.path.join(self.project, "canworks"))
        self.open()
        tree_view(pg, "raw")
        self.assertEqual(pg.inner_text('[data-raw="dbc"]'), "cab.dbc")
        self.assertEqual(pg.locator('[data-raw="dbc-missing"]').count(), 0)
        pg.click('button[data-raw="pick"]')
        pg.wait_for_selector('#modal select[data-pick="Joystick"]')
        self.assertEqual(pg.input_value('#modal select[data-pick="Joystick"]'), "")
        self.assertEqual(pg.inner_text('#modal [data-already="Joystick"]'), "already in received messages")
        pg.select_option('#modal select[data-pick="Display"]', "")
        pg.select_option('#modal select[data-pick="Sensor"]', "")
        pg.click('#modal button[data-value="add"]')
        pg.wait_for_selector("#banner:has-text('Imported 1 message from cab.dbc')")
        self.assertEqual(self.draft("S.config.raw.rx.map((m) => m.name)"), ["Joystick", "Pedal"])

    def test_cleared_signal_length(self):
        """A cleared signal length is a field problem, not a failed check."""
        pg = self.page
        self.joystick_config()
        self.open()
        tree_view(pg, "raw")
        pg.click('tr[data-raw="rx:0"]')
        length = 'input[data-path="raw.rx[0].signals[0].length"]'
        pg.fill(length, "")
        pg.press(length, "Tab")
        pg.wait_for_selector(length + ".invalid")
        self.assertIn("Received Joystick, signal X: missing", pg.inner_text("#problem-list"))
        self.assertGreater(pg.locator("#problem-list li.error").count(), 0)
        self.assertNotIn("hit an error", pg.inner_text("#banner"))

    def test_trace_and_frame_lab_without_canopen(self):
        """A plain network's Trace offers no CANopen kinds, and the Frame
        lab's examples are its own messages."""
        pg = self.page
        self.joystick_config()
        self.open()
        tool_tab(pg, "trace")
        pg.click("[data-trace=filters] > summary")
        kinds = pg.eval_on_selector_all("[data-trace-kind]", "es => es.map(e => e.dataset.traceKind)")
        self.assertEqual(kinds, ["error", "gap", "other", "raw"])
        self.assertEqual(pg.locator('[data-trace-tab="sequences"]').count(), 0)
        pg.click('[data-trace-tab="trigger"]')
        conds = pg.eval_on_selector_all('[data-trace-cond="0.type"] option', "es => es.map(e => e.value)")
        self.assertEqual(conds, ["frame", "signal", "bus", "error_frame"])
        tool_tab(pg, "framelab")
        pg.wait_for_selector("[data-fx=examples] .chip")
        chips = pg.eval_on_selector_all("[data-fx=examples] .chip", "es => es.map(e => e.textContent)")
        self.assertEqual(chips, ["Joystick"])
        self.assertEqual(pg.locator("[data-fx-mode=build]").count(), 0)
        pg.click('[data-fx-example="Joystick"]')
        pg.wait_for_selector("#fx-lab-inspector:has-text('Raw message Joystick')")

    def test_missing_dbc_file(self):
        pg = self.page
        self.joystick_config("old.dbc")
        self.open()
        tree_view(pg, "raw")
        self.assertIn("old.dbc is not in the config folder", pg.inner_text('[data-raw="dbc-missing"]'))
        self.assertEqual(pg.locator('button[data-raw="pick"]').count(), 0)

    def test_second_dbc_and_same_name(self):
        pg = self.page
        self.joystick_config()
        shutil.copy(os.path.join(EXAMPLE, "cab.dbc"), os.path.join(self.project, "canworks"))
        self.open()
        tree_view(pg, "raw")
        status = os.path.join(self.project, "status.dbc")
        with open(status, "w", encoding="utf-8") as f:
            f.write(MUX_DBC)
        # Another file: asked first, and keeping the first one changes nothing.
        pg.set_input_files('input[data-raw="dbc-input"]', status)
        pg.wait_for_selector("#modal-text:has-text('come from cab.dbc')")
        pg.click('#modal button[data-value="cancel"]')
        self.assertEqual(self.draft("S.config.raw.dbc"), "cab.dbc")
        # A different file named like the one in the folder: Keep both.
        other = os.path.join(self.project, "cab.dbc")
        with open(other, "w", encoding="utf-8") as f:
            f.write(MUX_DBC)
        pg.set_input_files('input[data-raw="dbc-input"]', other)
        pg.wait_for_selector("#modal-text:has-text('Replace it, or keep both')")
        pg.click('#modal button[data-value="keep_both"]')
        pg.wait_for_selector('#modal select[data-pick="Status"]')
        self.assertIn("cab-2.dbc", pg.inner_text("#modal-text"))
        pg.select_option('#modal select[data-pick="Twin"]', "")
        pg.click('#modal button[data-value="add"]')
        pg.wait_for_selector("#banner:has-text('from cab-2.dbc')")
        self.assertEqual(pg.inner_text('[data-raw="dbc"]'), "cab-2.dbc")
        pg.wait_for_function("() => document.body.dataset.checking === '0'")
        pg.click("#btn-save")
        pg.wait_for_selector("#banner:has-text('Saved')")
        self.assertTrue(os.path.isfile(os.path.join(self.project, "canworks", "cab-2.dbc")))
        with open(os.path.join(self.project, "canworks", "cab.dbc"), encoding="utf-8") as f:
            self.assertNotIn("Twin", f.read())
        # Removing every message clears the DBC file.
        for _ in range(2):
            pg.click('[data-raw-table="rx"] tbody tr button.danger >> nth=0')
        pg.wait_for_selector("[data-raw=dbc]:has-text('No DBC file yet.')")

    def test_online_view(self):
        pg = self.page
        self.cfg = load(os.path.join(EXAMPLE, "canworks.json"))
        self.cfg["networks"][0]["adapter"].pop("simulate")
        shutil.copy(os.path.join(EXAMPLE, "cab.dbc"), os.path.join(self.project, "canworks"))
        with FakePlugin(networks=[PLAIN_NETWORK]) as fp:
            # Multiplexed messages: unknown pages received, and a send whose
            # switch outputs select no page.
            fp.status["raw"]["rx"][1]["unknown_pages"] = 2
            fp.status["raw"]["tx"][0]["unknown_page"] = True
            self.write_config({"token_verifier": diag.token_verifier(TOKEN)})
            self.remember(fp.runtime)
            self.open()
            pg.click('button[data-view="online"]')
            pg.wait_for_selector('[data-online="raw"]')
            self.assertIn("plain CAN network up", pg.inner_text("#online-conn"))
            self.assertNotIn("No plain CAN session", pg.inner_text("#online-conn"))
            self.assertEqual(pg.inner_text('[data-online="bus"]'), "can0: error-active")
            self.assertIn("81 received, bus load 3 %", pg.inner_text('[data-online="raw"]'))
            self.assertIn("1 receivers", pg.inner_text('[data-online="raw-program"]'))
            self.assertIn("joystick", pg.inner_text('[data-online="raw-devices"]'))
            self.assertIn("0x181 [5] E8 03 0C FE 01", pg.inner_text('tr[data-raw-rx="Joystick"]'))
            pedal = pg.inner_text('tr[data-raw-rx="Pedal"]')
            self.assertIn("timed out, 1 short, 2 unknown pages", pedal)
            self.assertIn("0x18FF1020", pedal)
            self.assertIn("38", pg.inner_text('tr[data-raw-tx="Display"]'))
            self.assertIn("unknown page", pg.inner_text('tr[data-raw-tx="Display"]'))
            self.assertEqual(pg.locator('[data-online="lss"]').count(), 0)
            self.assertEqual(pg.locator("tr[data-online-node]").count(), 0)

    def test_simulation_view(self):
        pg = self.page
        self.cfg = load(os.path.join(EXAMPLE, "canworks.json"))
        shutil.copy(os.path.join(EXAMPLE, "cab.sim.json"), os.path.join(self.project, "canworks", "simulation.json"))
        self.write_config()
        self.open()
        # The links in running text are 24 px targets: Bus's CAN messages, Simulation's Online access.
        self.assertEqual(pg.evaluate(TARGETS), [])
        tool_tab(pg, "simulation")
        pg.wait_for_selector("#view a:has-text('Online access')")
        self.assertEqual(pg.evaluate(TARGETS), [])
        tool_tab(pg, "simfile")
        devices = pg.inner_text('[data-sim="raw-devices"]')
        self.assertIn("0x181 every 20 ms (X, Y)", devices)
        self.assertIn("0x18FF1020 every 50 ms", devices)
        pg.click('button[data-sim-tab="scenarios"]')
        pg.wait_for_selector("text=joystick_lost")
