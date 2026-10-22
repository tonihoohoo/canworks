"""The Modbus bridge target and page in a real browser (spec
canopen-configurator, "Project target", "Only what the target uses is
shown", "Switching the target", "Bridge settings panel",
"Register map preview and export", "Node-RED flow export on the bridge page"): an OpenPLC project with two nodes
switched to the bridge and packed, a live list added and suggested, the map
filtered and exported as the ST list and Node-RED flow canworks-deploy writes, the plc_cycle
problem, and the switch back with the per-type repack. Needs Playwright,
like test_configurator_page.py."""

import json
import os
import shutil

from canworks import modbusmap, nodered
from canworks.configurator import server as srv

from .helpers import REPO, tree_view
from .test_configurator_layout import FIT_CHECK, audit
from .test_configurator_online_page import OnlineBase
from .test_configurator_page import load

EXAMPLE = os.path.join(REPO, "examples", "modbus-bridge")


class BridgePage(OnlineBase):
    def setUp(self):
        super().setUp()
        # The example as an OpenPLC project: no bridge, per-type locations from 100.
        cfg = load(os.path.join(EXAMPLE, "canworks.json"))
        del cfg["bridge"]
        self.cfg = srv.Session().pack_openplc(cfg)["config"]
        for name in ("rtd8.eds", "dio16.eds"):
            shutil.copy(os.path.join(EXAMPLE, name), os.path.join(self.project, "canworks"))
        self.write_config()

    def write_config(self, diagnostics=None):
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(self.cfg, f, indent=2)

    def checked(self):
        self.page.wait_for_function("() => document.body.dataset.checking === '0'")

    def to_bridge(self):
        pg = self.page
        tree_view(pg, "project")
        self.assertEqual(pg.input_value('select[data-target="1"]'), "openplc")
        self.assertEqual(pg.locator("#tree #nav-bridge").count(), 0)
        pg.select_option('select[data-target="1"]', "bridge")
        pg.wait_for_selector("#banner:has-text('Modbus bridge now')")
        self.assertFalse(pg.evaluate("() => document.querySelector('#modal').open"))
        pg.wait_for_selector("#tree #nav-bridge")
        tree_view(pg, "bus")
        self.checked()

    def test_switch_pack_and_export_st(self):
        pg = self.page
        self.open()
        self.to_bridge()
        tree_view(pg, "bridge")
        pg.wait_for_selector("h2:has-text('Modbus bridge')")
        # Writers is required: the switch starts it empty (nobody writes) and
        # the hint names how to let every host write.
        self.assertEqual(pg.evaluate("() => S.model.top.bridge.writers"), [])
        self.assertEqual(pg.text_content("#problem-list").strip(), "No problems.")
        self.assertEqual(pg.get_attribute('input[data-path="bridge.writers"]', "placeholder"), "nobody writes")
        self.assertIn("0.0.0.0/0, ::/0", pg.inner_text('label:has(input[data-path="bridge.writers"])'))
        pg.fill('input[data-path="bridge.writers"]', "0.0.0.0/0, ::/0")
        self.assertEqual(pg.evaluate("() => S.model.top.bridge.writers"), ["0.0.0.0/0", "::/0"])
        pg.fill('input[data-path="bridge.writers"]', "")
        self.assertEqual(pg.evaluate("() => S.model.top.bridge.writers"), [])  # empty: nobody, never missing
        pg.fill('input[data-path="bridge.writers"]', "192.168.10.0/24, 192.168.20.5")
        pg.fill('input[data-path="bridge.max_clients_per_address"]', "2")
        self.checked()
        self.assertEqual(pg.text_content("#problem-list").strip(), "No problems.")
        self.assertEqual(pg.input_value('input[data-path="bridge.listen"]'), "0.0.0.0")
        self.assertEqual(pg.input_value('input[data-bridge="port"]'), "502")
        tree_view(pg, "project")
        self.assertEqual(pg.input_value('select[data-target="1"]'), "bridge")
        self.assertEqual(pg.locator('#view select[data-target="1"]').count(), 1)
        tree_view(pg, "bridge")
        self.assertEqual(pg.locator('#view select[data-target="1"]').count(), 0)
        pg.wait_for_selector('#bridge-map tr[data-bridge-row="rtd.0x7130:1"]')
        self.assertIn("Input registers", pg.inner_text('tr[data-bridge-row="rtd.0x7130:1"]'))
        # Packed: the rtd's four words are input registers 0-3, the dio's outputs from holding register 0.
        self.assertIn("%IW6", pg.inner_text('tr[data-bridge-row="rtd.0x7130:4"]'))
        self.assertIn("%QB0", pg.inner_text('tr[data-bridge-row="dio.0x6200:1"]'))

        # A live list for the network "field", placed by Suggest after the packed data.
        pg.click('button[data-bridge="add-live-list"]')
        pg.wait_for_selector('tr[data-live-list="0"]')
        self.assertEqual(pg.input_value('select[data-path="bridge.live_lists[0].network"]'), "field")
        pg.fill('input[data-path="bridge.live_lists[0].location"]', "")
        pg.click('button[data-bridge-suggest="live_list:0"]')
        pg.wait_for_function("() => document.querySelector('input[data-path=\"bridge.live_lists[0].location\"]').value === '%IB24'")
        self.checked()
        row = pg.wait_for_selector('#bridge-map tr[data-bridge-row="bridge.live_list.field"]')
        self.assertIn("12..19", row.inner_text())
        self.assertIn("8 registers", row.inner_text())
        self.assertEqual(pg.text_content("#problem-list").strip(), "No problems.")

        # The filter, and the suggested client channels.
        pg.fill('input[data-bridge="filter"]', "live")
        self.assertEqual(pg.locator("#bridge-map tr[data-bridge-row]").count(), 1)
        pg.fill('input[data-bridge="filter"]', "")
        self.assertIn("read input registers", pg.inner_text('[data-bridge="channels"]'))
        self.assertIn("write holding registers", pg.inner_text('[data-bridge="channels"]'))

        pg.click("#btn-save")
        pg.wait_for_selector("#banner:has-text('Saved')")
        saved = load(self.config_path)
        self.assertEqual(saved["schema_version"], 2)
        self.assertEqual(saved["bridge"], {"listen": "0.0.0.0:502", "writers": ["192.168.10.0/24", "192.168.20.5"],
                                           "max_clients_per_address": 2,
                                           "live_lists": [{"network": "field", "location": "%IB24"}]})

        # Export ST variables: the file canworks-deploy --export-modbus-map map.st writes.
        tree_view(pg, "bridge")
        pg.wait_for_selector('#bridge-map tr[data-bridge-row]')
        with pg.expect_download() as dl:
            pg.click('button[data-bridge-export="st"]')
        self.assertEqual(dl.value.suggested_filename, "rtd-monitor_modbus.st")
        with open(dl.value.path(), encoding="utf-8") as f:
            self.assertEqual(f.read(), modbusmap.to_st(saved, modbusmap.register_map(saved)))
        pg.wait_for_selector("#banner:has-text('Exported rtd-monitor_modbus.st')")

        # Export Node-RED flow: the file canworks-deploy --export-nodered rtd-monitor_node-red.json writes,
        # with the note that the writers have no loopback address.
        with pg.expect_download() as dl:
            pg.click('button[data-bridge-export="nodered"]')
        self.assertEqual(dl.value.suggested_filename, "rtd-monitor_node-red.json")
        with open(dl.value.path(), encoding="utf-8") as f:
            self.assertEqual(f.read(), nodered.to_json(nodered.flow(saved, "rtd-monitor")[0]))
        pg.wait_for_selector("#banner:has-text('Exported rtd-monitor_node-red.json')")
        self.assertIn("no loopback address", pg.inner_text("#banner"))

        # A stopped register map export: each finding its own Problems row, no message bar.
        pg.evaluate("""() => {
          const f = window.fetch;
          window.fetch = (u, o) => String(u).endsWith('/api/bridge/export')
            ? Promise.resolve(new Response(JSON.stringify({ errors: 2, items: [
                { level: 'error', message: 'map finding A', paths: [] }, { level: 'error', message: 'map finding B', paths: [] }] }),
                { headers: { 'Content-Type': 'application/json' } }))
            : f(u, o);
        }""")
        pg.click('button[data-bridge-export="csv"]')
        pg.wait_for_selector("#problems-bars .notice-error:has-text('Register map export stopped')")
        self.assertTrue(pg.is_hidden("#banner"))
        texts = pg.eval_on_selector_all("#problem-list li", "ls => ls.map((l) => l.textContent)")
        self.assertEqual([t for t in texts if "map finding" in t], ["map finding A", "map finding B"], texts)
        tree_view(pg, "bridge")
        pg.wait_for_selector('#bridge-map tr[data-bridge-row]')

        # Fits and is accessible, in the dark theme too.
        pg.emulate_media(color_scheme="dark")
        pg.set_viewport_size({"width": 1000, "height": 800})
        pg.wait_for_timeout(300)
        self.assertEqual(pg.evaluate(FIT_CHECK), [])
        audit(pg, "Modbus bridge page")

    def test_example_live_list_follows_the_network(self):
        """The example as it is: defaults written out show as the default,
        a network rename carries the live list along, a removal takes it."""
        pg = self.page
        self.cfg = load(os.path.join(EXAMPLE, "canworks.json"))
        self.write_config()
        self.open()
        tree_view(pg, "bridge")
        pg.wait_for_selector("h2:has-text('Modbus bridge')")
        for path, label in (("bridge.word_order", "High word first"), ("bridge.on_client_loss", "Stop")):
            self.assertEqual(pg.eval_on_selector('select[data-path="%s"]' % path,
                                                 "s => s.selectedOptions[0].textContent"), label)
        self.assertNotIn("as in the file", pg.inner_text("#view"))
        add = 'button[data-bridge="add-live-list"]'
        self.assertTrue(pg.is_disabled(add))
        self.assertIn("Every CANopen master network has a live list", pg.get_attribute(add, "title"))
        pg.click('#tree [data-net-menu="0"]')
        pg.click('#modal-buttons [data-value="rename"]')
        pg.fill('#modal-extra input[data-net="name"]', "plant")
        pg.press('#modal-extra input[data-net="name"]', "Enter")
        self.assertEqual(pg.evaluate("() => S.model.top.bridge.live_lists[0].network"), "plant")
        self.checked()
        self.assertEqual(pg.text_content("#problem-list").strip(), "No problems.")
        # A second network, then the first removed: its live list goes with it.
        pg.click('#tree [data-action="add-network"] > .tree-row')
        pg.click('#modal button[data-value="canopen"]')
        pg.click('#tree [data-net-menu="0"]')
        pg.click('#modal-buttons [data-value="remove"]')
        self.assertIn("Its Modbus bridge live list is removed too", pg.inner_text("#modal-text"))
        pg.click('#modal button[data-value="remove"]')
        self.assertIsNone(pg.evaluate("() => S.model.top.bridge.live_lists || null"))

    def test_plc_cycle_and_back_to_openplc(self):
        pg = self.page
        self.open()
        self.to_bridge()
        # The master's PLC stop field; the bridge has no PLC scan, so no scan watchdog and no PLC cycle SYNC.
        self.assertEqual(pg.input_value('select[data-path="master.on_plc_stop"]'), "")
        pg.select_option('select[data-path="master.on_plc_stop"]', "stop")
        self.assertIn("NMT STOP", pg.inner_text('label:has(select[data-path="master.on_plc_stop"])'))
        pg.select_option('select[data-path="master.on_plc_stop"]', "")
        self.assertIsNone(pg.evaluate("() => S.config.master.on_plc_stop || null"))
        self.assertFalse(pg.is_visible('input[data-path="master.scan_watchdog_ms"]'))
        self.assertEqual(pg.locator('select[data-path="master.sync_source"] option[value="plc_cycle"]').count(), 0)
        # A watchdog the config still has stays hidden; no problem, save leaves it out.
        pg.evaluate("() => { S.config.master.scan_watchdog_ms = 250; changed(true); }")
        self.checked()
        self.assertFalse(pg.is_visible('input[data-path="master.scan_watchdog_ms"]'))
        self.assertEqual(pg.text_content("#problem-list").strip(), "No problems.")
        self.assertEqual(pg.locator("[data-unused-bar]").count(), 0)
        pg.evaluate("() => { delete S.config.master.scan_watchdog_ms; changed(true); }")
        self.checked()
        # A PLC cycle SYNC the config still has is an error, shown as the config's value.
        pg.evaluate("() => { S.config.master.sync_source = 'plc_cycle'; delete S.config.master.sync_period_us; changed(true); }")
        self.checked()
        self.assertIn("needs a PLC cycle, which the Modbus bridge does not have", pg.inner_text("#problem-list"))
        self.assertIn("needs a PLC cycle", pg.inner_text('.field-msg[data-for="master.sync_source"]'))
        self.assertEqual(pg.input_value('select[data-path="master.sync_source"]'), "plc_cycle")
        pg.select_option('select[data-path="master.sync_source"]', "")
        pg.fill('input[data-path="master.sync_period_us"]', "20")
        self.checked()
        self.assertEqual(pg.text_content("#problem-list").strip(), "No problems.")

        # Back to OpenPLC: the bridge object goes, the locations are per type again.
        tree_view(pg, "project")
        pg.select_option('select[data-target="1"]', "openplc")
        pg.wait_for_selector("#banner:has-text('targets OpenPLC now')")
        pg.wait_for_selector("#tree #nav-bridge", state="detached")
        self.checked()
        self.assertEqual(pg.text_content("#problem-list").strip(), "No problems.")
        # The switch and its repack are one step: undo brings the bridge back, redo removes it.
        pg.evaluate("() => document.activeElement && document.activeElement.blur()")
        pg.keyboard.press("Control+z")
        pg.wait_for_selector("#tree #nav-bridge")
        pg.keyboard.press("Control+Shift+z")
        pg.wait_for_selector("#tree #nav-bridge", state="detached")
        self.checked()
        pg.click("#btn-save")
        pg.wait_for_selector("#banner:has-text('Saved')")
        saved = load(self.config_path)
        self.assertNotIn("bridge", saved)
        # Repacked per type exactly as the project was before the switch.
        self.assertEqual(saved, self.cfg)


if __name__ == "__main__":
    import unittest
    unittest.main()
