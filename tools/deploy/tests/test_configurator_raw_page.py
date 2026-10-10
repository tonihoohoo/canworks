"""Plain CAN networks and the CAN messages page in a real browser (spec
canopen-configurator, "CAN messages page"): a plain network built from the
example DBC and saved, and the online view against the fake plugin's plain
network status. Needs Playwright, like test_configurator_page.py."""

import json
import os
import shutil

from canworks import diag

from .fake_diag import PLAIN_NETWORK, TOKEN, FakePlugin
from .helpers import REPO
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
        pg.click('button[data-net-action="add"]')
        pg.click('#modal button[data-value="none"]')
        pg.wait_for_selector("h2:has-text('Bus')")
        self.assertTrue(pg.is_hidden("#nodes-caption"))
        self.assertTrue(pg.is_hidden("#nav-scan"))
        self.assertEqual(pg.locator('[data-path="master.node_id"]').count(), 0)
        pg.click('#net-bar button[data-net="0"]')
        pg.click('button[data-net-action="remove"]')
        pg.click('#modal button[data-value="remove"]')
        pg.wait_for_selector("h2:has-text('Bus')")
        pg.fill('input[data-path="adapter.interface"]', "can1")
        pg.click("#nav-raw")
        pg.wait_for_selector("h2:has-text('CAN messages')")
        pg.click("#raw-import")
        pg.set_input_files('#modal input[type="file"]', os.path.join(EXAMPLE, "cab.dbc"))
        pg.click('#modal button[data-value="next"]')
        pg.wait_for_selector('#modal select[aria-label="Use Joystick"]')
        # The PLC sends Display in the DBC, so Send is preselected.
        self.assertEqual(pg.input_value('#modal select[aria-label="Use Display"]'), "send")
        pg.select_option('#modal select[aria-label="Use Joystick"]', "receive")
        pg.select_option('#modal select[aria-label="Use Pedal"]', "receive")
        pg.click('#modal button[data-value="import"]')
        pg.wait_for_selector("#banner:has-text('Imported 3 messages')")
        self.assertIn("0x18FF1020 ext", pg.inner_text('[data-raw-table="rx"]'))
        pg.wait_for_function("() => document.body.dataset.checking === '0'")
        self.assertEqual(pg.inner_text("#problem-list"), "No problems.")
        pg.click("#btn-save")
        pg.wait_for_selector("#banner:has-text('Saved')")
        saved = load(self.config_path)
        net = saved["networks"][0]
        self.assertEqual(len(saved["networks"]), 1)
        self.assertEqual(net["protocol"], "none")
        self.assertEqual(net["adapter"]["interface"], "can1")
        self.assertEqual([m["name"] for m in net["raw"]["rx"]], ["Joystick", "Pedal"])
        self.assertEqual([m["name"] for m in net["raw"]["tx"]], ["Display"])
        self.assertEqual(net["raw"]["dbc"], "cab.dbc")
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
        pg.click("#nav-raw")
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
        pg.wait_for_selector("#problem-list li.ok")
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
        pg.wait_for_selector("#problem-list li.ok")
        pg.click("#btn-save")
        pg.wait_for_selector("#banner:has-text('Saved')")
        sigs = load(self.config_path)["networks"][0]["raw"]["rx"][0]["signals"]
        self.assertEqual(sigs[0].get("multiplexer"), True)
        self.assertEqual(sigs[1]["mux"], {"values": [1]})
        self.assertEqual(sigs[2]["mux"], {"values": [2]})

    def test_import_a_multiplexed_message(self):
        pg = self.page
        self.plain_config([])
        dbc = os.path.join(self.project, "status.dbc")
        with open(dbc, "w", encoding="utf-8") as f:
            f.write(MUX_DBC)
        self.open()
        pg.click("#nav-raw")
        pg.click("#raw-import")
        pg.set_input_files('#modal input[type="file"]', dbc)
        pg.click('#modal button[data-value="next"]')
        pg.wait_for_selector('#modal select[aria-label="Use Status"]')
        self.assertEqual(pg.inner_text('#modal [data-raw-mux="Status"]'), "switch Page, 2 pages")
        self.assertNotIn("multiplexed left out", pg.inner_text("#modal"))
        self.assertIn("several switches but no SG_MUL_VAL_", pg.inner_text('#modal [data-raw-mux-problem="Twin"]'))
        pg.select_option('#modal select[aria-label="Use Status"]', "receive")
        pg.click('#modal button[data-value="import"]')
        pg.wait_for_selector("#banner:has-text('Imported 1 message')")
        pg.wait_for_selector("#problem-list li.ok")
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
        pg.click("#nav-simulation")
        pg.click('button[data-sim-tab="file"]')
        devices = pg.inner_text('[data-sim="raw-devices"]')
        self.assertIn("0x181 every 20 ms (X, Y)", devices)
        self.assertIn("0x18FF1020 every 50 ms", devices)
        pg.click('button[data-sim-tab="scenarios"]')
        pg.wait_for_selector("text=joystick_lost")
