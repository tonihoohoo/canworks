"""OpenPLC through Modbus in a real browser (add-openplc-modbus-target,
spec canopen-configurator "Project target", "Saving an OpenPLC through
Modbus project"): a plugin config switched with the Project page's button,
the bridge page's OpenPLC settings, Save writing the editor files and the
Project page's facts, and the question when canworks' own editor files were
changed elsewhere. Needs Playwright, like test_configurator_page.py."""

import json
import os

from .helpers import tree_view
from .test_configurator_online_page import OnlineBase
from .test_configurator_page import load


class OpenplcModbusPage(OnlineBase):
    def checked(self):
        self.page.wait_for_function("() => document.body.dataset.checking === '0'")

    def test_switch_save_and_changed_files(self):
        pg = self.page
        # A config of the removed plugin: neither `bridge` nor `codesys`.
        cfg = load(self.config_path)
        del cfg["bridge"]
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
        self.open()
        tree_view(pg, "project")
        # The line says the plugin was removed, the button switches.
        self.assertIn("which was removed", pg.inner_text("[data-plugin-target]"))
        self.assertEqual(pg.input_value('select[data-target="1"]'), "plugin")
        pg.click("[data-switch-modbus]")
        pg.wait_for_selector("#banner:has-text('targets OpenPLC now')")
        self.assertEqual(pg.locator("[data-plugin-target]").count(), 0)
        self.assertEqual(pg.input_value('select[data-target="1"]'), "openplc_modbus")
        self.assertEqual(pg.locator('select[data-target="1"] option[value="plugin"]').count(), 0)
        self.assertEqual(pg.evaluate("() => projectTarget()"), "openplc_modbus")

        # The bridge page: OpenPLC's poll and names, no server or client settings.
        pg.wait_for_selector("#tree #nav-bridge")
        tree_view(pg, "bridge")
        pg.wait_for_selector("h2:has-text('Modbus bridge for OpenPLC')")
        self.assertTrue(pg.is_visible('[data-bridge-openplc] input[data-path="bridge.openplc.poll_ms"]'))
        self.assertEqual(pg.locator('input[data-path="bridge.listen"]').count(), 0)
        self.assertEqual(pg.locator('input[data-path="bridge.writers"]').count(), 0)
        self.assertEqual(pg.inner_text("[data-bridge-status-fixed]"), "%IB4")
        self.assertEqual(pg.locator('select[data-path="bridge.on_client_loss"] option[value="preop"]').count(), 1)
        pg.fill('input[data-path="bridge.openplc.poll_ms"]', "20")
        self.checked()
        self.assertEqual(pg.text_content("#problem-list").strip(), "No problems.")

        # Save writes the editor files; the Project page shows the facts.
        pg.click("#btn-save")
        pg.wait_for_selector("#banner:has-text('reopen the project')")
        remote = os.path.join(self.project, "devices", "remote", "canworks.json")
        programs = os.path.join(self.project, "pous", "programs")
        self.assertEqual(load(remote)["modbusTcpConfig"]["port"], 1502)
        self.assertTrue(os.path.isfile(os.path.join(programs, "canworks_in.st")))
        self.assertTrue(os.path.isfile(os.path.join(programs, "canworks_out.st")))
        self.assertEqual(load(self.config_path)["bridge"]["openplc"], {"poll_ms": 20})
        tree_view(pg, "project")
        facts = pg.inner_text("[data-openplc-facts]")
        self.assertIn("every 20 ms", facts)
        self.assertIn("127.0.0.1:1502", facts)
        self.assertIn("devices/remote/canworks.json", facts)

        # canworks_in.st changed in the editor: Save asks before writing it again.
        changed = os.path.join(programs, "canworks_in.st")
        with open(changed, "a", encoding="utf-8") as f:
            f.write("(* mine *)\n")
        tree_view(pg, "bridge")
        pg.fill('input[data-path="bridge.openplc.poll_ms"]', "10")
        self.checked()
        pg.click("#btn-save")
        pg.wait_for_selector("[data-editor-changed]")
        self.assertIn("pous/programs/canworks_in.st", pg.inner_text("[data-editor-changed]"))
        pg.click('#modal-buttons button[data-value="cancel"]')
        self.assertEqual(load(self.config_path)["bridge"]["openplc"], {"poll_ms": 20})
        pg.click("#btn-save")
        pg.wait_for_selector("[data-editor-changed]")
        pg.click('#modal-buttons button[data-value="overwrite"]')
        pg.wait_for_selector("#banner:has-text('Saved')")
        self.assertEqual(load(self.config_path)["bridge"]["openplc"], {"poll_ms": 10})
        with open(changed, encoding="utf-8") as f:
            self.assertNotIn("(* mine *)", f.read())


if __name__ == "__main__":
    import unittest
    unittest.main()
