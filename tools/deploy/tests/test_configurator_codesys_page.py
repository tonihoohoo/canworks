"""The CODESYS target in a real browser (spec canopen-configurator "Project
target", "Only what the target uses is shown", "Switching the target",
"Variable names of PDO entries", "CODESYS settings", "CODESYS actions",
"Target of a new config", "Commission in a CODESYS project"): an OpenPLC
project switched to CODESYS and back, what the page hides, a leftover value
with Remove, the CODESYS page and Bus page settings, Download for CODESYS,
Build without CODESYS, and a new CODESYS config from the start page. Needs
Playwright, like test_configurator_page.py."""

import json
import os
import shutil

from canworks.configurator import server as srv

from .helpers import REPO, tree_node, tree_view, new_config
from .test_configurator_online_page import OnlineBase
from .test_configurator_page import load

EXAMPLE = os.path.join(REPO, "examples", "modbus-bridge")


class CodesysPage(OnlineBase):
    def setUp(self):
        super().setUp()
        # The example as an OpenPLC project: no bridge, per-type locations from 100.
        cfg = load(os.path.join(EXAMPLE, "canworks.json"))
        del cfg["bridge"]
        self.cfg = srv.Session().pack_openplc(cfg)["config"]
        self.cfg["networks"][0]["master"]["scan_watchdog_ms"] = 500
        for name in ("rtd8.eds", "dio16.eds"):
            shutil.copy(os.path.join(EXAMPLE, name), os.path.join(self.project, "canworks"))
        self.write_config()

    def write_config(self, diagnostics=None):
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(self.cfg, f, indent=2)

    def checked(self):
        self.page.wait_for_function("() => document.body.dataset.checking === '0'")

    def to_codesys(self, button="remove"):
        pg = self.page
        self.assertEqual(pg.input_value('select[data-target="1"]'), "openplc")
        self.assertEqual(pg.locator("#tree #nav-codesys").count(), 0)
        pg.select_option('select[data-target="1"]', "codesys")
        pg.wait_for_selector("#modal[open]")
        self.assertIn("Switch the project to CODESYS?", pg.inner_text("#modal-text"))
        self.assertIn("not used by CODESYS", pg.inner_text("#modal-text"))
        self.assertIn("scan_watchdog_ms", pg.inner_text("#modal-extra"))
        self.assertEqual(pg.get_attribute('#modal-buttons button[data-value="remove"]', "class"), "primary")
        pg.click('#modal-buttons button[data-value="%s"]' % button)
        pg.wait_for_selector("#banner:has-text('targets CODESYS now')")
        pg.wait_for_selector("#tree #nav-codesys")
        self.checked()

    def test_switch_hides_and_back(self):
        pg = self.page
        self.open()
        self.assertEqual(pg.inner_text("[data-target-mark]"), " · OpenPLC")
        self.assertTrue(pg.is_visible('input[data-path="master.scan_watchdog_ms"]'))
        self.to_codesys()
        self.assertEqual(pg.inner_text("[data-target-mark]"), " · CODESYS")
        self.assertEqual(pg.inner_text("#problem-list"), "No problems.")
        # The Bus page: no scan watchdog, EDS lint, bus diagnostics or simulation; the CODESYS settings.
        for path in ("master.scan_watchdog_ms", "master.eds_lint", "master.bus_state_location", "adapter.type",
                     "adapter.simulate"):
            self.assertFalse(pg.is_visible('[data-path="%s"]' % path), path)
        self.assertEqual(pg.locator('select[data-path="master.sync_source"] option[value="plc_cycle"]').count(), 0)
        self.assertEqual([o for o in pg.eval_on_selector_all('select[data-path="protocol"] option', "os => os.map(o => o.value)")], [""])
        self.assertEqual(pg.eval_on_selector_all('select[data-path="role"] option', "os => os.map(o => o.value)"), [""])
        pg.fill('input[data-path="codesys.net_id"]', "0")
        self.assertEqual(pg.evaluate("() => S.config.codesys"), {"net_id": 0})
        # The tree: no CAN messages, no Online access; the CODESYS page.
        self.assertEqual(pg.locator('#tree [data-view="raw"]').count(), 0)
        self.assertEqual(pg.locator("#tree #nav-access").count(), 0)
        self.assertFalse(pg.is_visible('#tool-tabs [data-view="declarations"]'))
        # The header: Build and Download, no editor project actions.
        self.assertTrue(pg.is_visible("#btn-codesys-build"))
        self.assertTrue(pg.is_visible("#btn-codesys-download"))
        # The node's PDOs: a Variable column with the names, no PLC location column.
        tree_node(pg, 1, "pdos")
        pg.wait_for_selector('input[data-path="nodes[1].tx_pdos[0].entries[0].name"]')
        self.assertEqual(pg.locator('input[data-path$=".iec_location"]').count(), 0)
        self.assertNotIn("PLC location", pg.inner_text(".pdo table thead"))
        self.assertEqual(pg.input_value('input[data-path="nodes[1].tx_pdos[0].entries[0].name"]'), "Read_input_8_bit_1")
        pg.fill('input[data-path="nodes[1].tx_pdos[0].entries[0].name"]', "door_open")
        self.checked()
        self.assertEqual(pg.inner_text("#problem-list"), "No problems.")
        # The CODESYS page.
        tree_view(pg, "codesys")
        pg.wait_for_selector("h2:has-text('CODESYS')")
        pg.fill('input[data-path="codesys.project"]', "C:\\Projects\\cell.project")
        self.assertEqual(pg.evaluate("() => S.model.top.codesys"), {"project": "C:\\Projects\\cell.project"})
        self.checked()
        pg.click("#btn-save")
        pg.wait_for_selector("#banner:has-text('Saved')")
        saved = load(self.config_path)
        self.assertEqual(saved["codesys"], {"project": "C:\\Projects\\cell.project"})
        self.assertEqual(saved["networks"][0]["codesys"], {"net_id": 0})
        entries = saved["networks"][0]["nodes"][1]["tx_pdos"][0]["entries"]
        self.assertEqual(entries[0], {"index": "0x6000", "subindex": 1, "type": "UNSIGNED8", "name": "door_open"})
        self.assertNotIn("scan_watchdog_ms", saved["networks"][0]["master"])
        # Download for CODESYS: the zip, nothing written to the folder.
        with pg.expect_download() as dl:
            pg.click("#btn-codesys-download")
        self.assertEqual(dl.value.suggested_filename, "rtd-monitor_codesys.zip")
        # Back to OpenPLC: every entry gets a location, the names stay.
        pg.select_option('select[data-target="1"]', "openplc")
        pg.wait_for_selector("#modal[open]")
        self.assertIn("get a location, per type", pg.inner_text("#modal-text"))
        pg.click("#modal-buttons button.primary")
        pg.wait_for_selector("#banner:has-text('targets OpenPLC now')")
        pg.wait_for_selector("#tree #nav-codesys", state="detached")
        self.checked()
        self.assertEqual(pg.inner_text("#problem-list"), "No problems.")
        self.assertTrue(pg.is_visible('input[data-path="master.scan_watchdog_ms"]'))
        self.assertFalse(pg.is_visible("#btn-codesys-build"))
        # One undo step brings CODESYS back.
        pg.evaluate("() => document.activeElement && document.activeElement.blur()")
        pg.keyboard.press("Control+z")
        pg.wait_for_selector("#tree #nav-codesys")

    def test_keep_marks_the_values(self):
        pg = self.page
        self.open()
        self.to_codesys("keep")
        # Kept: shown, marked, and in Problems with Remove.
        self.assertTrue(pg.is_visible('input[data-path="master.scan_watchdog_ms"]'))
        self.assertIn("not used by CODESYS", pg.inner_text('[data-unused-for="master.scan_watchdog_ms"]'))
        self.assertIn("'scan_watchdog_ms' is not used by CODESYS", pg.inner_text("#problem-list"))
        pg.click('#problem-list [data-problem-remove="master.scan_watchdog_ms"]')
        self.assertIsNone(pg.evaluate("() => S.config.master.scan_watchdog_ms || null"))
        self.assertFalse(pg.is_visible('input[data-path="master.scan_watchdog_ms"]'))
        # The PDO table keeps the location column while entries have locations.
        tree_node(pg, 0, "pdos")
        loc = 'input[data-path="nodes[0].tx_pdos[0].entries[0].iec_location"]'
        pg.wait_for_selector(loc)
        self.assertIn("not used by CODESYS", pg.inner_text('[data-unused-for="nodes[0].tx_pdos[0].entries[0].iec_location"]'))
        pg.click('[data-unused-remove="nodes[0].tx_pdos[0].entries[0].iec_location"]')
        self.assertFalse(pg.is_visible(loc))

    def test_leftover_value_in_a_codesys_config(self):
        pg = self.page
        cfg = self.cfg
        cfg["codesys"] = {}
        cfg["networks"][0]["master"]["on_plc_stop"] = "keep"
        self.write_config()
        self.open()
        self.checked()
        self.assertTrue(pg.is_visible('select[data-path="master.on_plc_stop"]'))
        self.assertIn("not used by CODESYS", pg.inner_text('[data-unused-for="master.on_plc_stop"]'))
        self.assertIn("'on_plc_stop' is not used by CODESYS", pg.inner_text("#problem-list"))
        pg.click('[data-unused-remove="master.on_plc_stop"]')
        self.assertFalse(pg.is_visible('select[data-path="master.on_plc_stop"]'))

    def test_build_without_codesys(self):
        pg = self.page
        self.cfg["codesys"] = {"project": "C:\\Projects\\cell.project"}
        self.write_config()
        self.open()
        self.assertFalse(pg.evaluate("() => S.state.codesys_found"))
        pg.click("#btn-codesys-build")
        pg.wait_for_selector("#modal[open]")
        self.assertIn("CODESYS was not found on this PC", pg.inner_text("#modal-text"))
        with pg.expect_download() as dl:
            pg.click('#modal-buttons button[data-value="download"]')
        self.assertEqual(dl.value.suggested_filename, "rtd-monitor_codesys.zip")

    def test_commission_connects_through_an_adapter(self):
        pg = self.page
        self.cfg["codesys"] = {}
        self.write_config()
        self.open()
        self.assertTrue(pg.evaluate("() => connAdapter()"))


class NewCodesysConfig(OnlineBase):
    def test_new_standalone_codesys(self):
        pg = self.page
        folder = os.path.join(self.dir, "cell")
        pg.goto(self.server.url)
        pg.wait_for_selector("#start-new")
        new_config(pg, folder, "codesys")
        pg.wait_for_selector("#editor:not([hidden])")
        pg.wait_for_selector("#tree #nav-codesys")
        self.assertEqual(pg.input_value('select[data-target="1"]'), "codesys")
        cfg = pg.evaluate("() => fileConfig()")
        self.assertEqual((cfg["schema_version"], cfg["codesys"]), (2, {}))
        self.assertNotIn("type", cfg["networks"][0]["adapter"])
        self.assertTrue(pg.evaluate("() => S.dirty"))


if __name__ == "__main__":
    import unittest
    unittest.main()
