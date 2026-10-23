"""The OpenPLC connection in a real browser (modbus-connections; spec
canopen-configurator "Plugin configs", "OpenPLC project page"): a plugin
config in an editor project put onto canworks-bridge with the Project page's
button, which adds the OpenPLC connection, its Settings on the bridge page
and the Function blocks section, Save writing
the editor files and the Project page's facts, the question when canworks'
own editor files were changed elsewhere, and Use canworks.* in main
(openplc-modbus-followups). Needs Playwright, like test_configurator_page.py."""

import json
import os

from canworks import editorproject, mainmove, openplcmodbus

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
        # The line says the plugin was removed; the button puts it onto the
        # bridge with an OpenPLC connection (an editor project).
        self.assertIn("which was removed", pg.inner_text("[data-plugin-target]"))
        self.assertEqual(pg.input_value('select[data-target="1"]'), "plugin")
        self.assertEqual(pg.inner_text("[data-switch-modbus]"), "Use with canworks-bridge")
        pg.click("[data-switch-modbus]")
        pg.wait_for_selector("#banner:has-text('targets Modbus bridge now')")
        self.assertIn("OpenPLC connection", pg.inner_text("#banner"))
        self.assertEqual(pg.locator("[data-plugin-target]").count(), 0)
        self.assertEqual(pg.input_value('select[data-target="1"]'), "bridge")
        self.assertEqual(pg.eval_on_selector_all('select[data-target="1"] option', "os => os.map(o => o.value)"),
                         ["bridge", "codesys"])
        self.assertEqual(pg.evaluate("() => projectTarget()"), "bridge")
        self.assertIn("Modbus bridge", pg.inner_text("[data-target-mark]"))

        # The bridge page: the OpenPLC connection first, with its poll in
        # Settings; the server fields stay plain bridge settings.
        pg.wait_for_selector("#tree #nav-bridge")
        tree_view(pg, "bridge")
        pg.wait_for_selector("h2:has-text('Modbus bridge')")
        row = pg.inner_text('[data-connection][data-conn-kind="openplc"]')
        self.assertIn("OpenPLC", row)
        self.assertIn("In sync", row)
        self.assertEqual(pg.input_value('input[data-path="bridge.connections[0].address"]'), "127.0.0.1")
        self.assertEqual(pg.input_value('input[data-path="bridge.listen"]'), "127.0.0.1")
        self.assertEqual(pg.inner_text("[data-bridge-who]"), "127.0.0.1")
        self.assertEqual(pg.inner_text("[data-bridge-status-fixed]"), "%IB4")
        self.assertEqual(pg.locator('select[data-path="bridge.on_client_loss"] option[value="preop"]').count(), 1)
        pg.click('[data-conn-settings-of="0"] > summary')
        pg.fill('input[data-path="bridge.connections[0].poll_ms"]', "20")
        self.checked()
        self.assertEqual(pg.text_content("#problem-list").strip(), "No problems.")

        # The switch turned the function blocks' mailboxes on, placed after the data;
        # a count change moves them, and the page says the editor needs Update declarations.
        pg.wait_for_selector('[data-bridge-mailboxes="1"]')
        self.assertIn("Update declarations", pg.inner_text("[data-bridge-mailbox-update]"))
        pg.wait_for_selector('[data-bridge-mailbox-cost]:has-text("per poll")')
        self.assertIn("(budget 40)", pg.inner_text("[data-bridge-mailbox-cost]"))
        pg.fill('input[data-path="bridge.mailboxes.cyclic_jobs"]', "16")
        pg.press('input[data-path="bridge.mailboxes.cyclic_jobs"]', "Tab")
        pg.wait_for_selector('[data-bridge-mailbox-cost]:has-text("275 input")')
        self.checked()
        self.assertEqual(pg.text_content("#problem-list").strip(), "No problems.")
        pg.fill('input[data-path="bridge.mailboxes.cyclic_jobs"]', "")
        pg.press('input[data-path="bridge.mailboxes.cyclic_jobs"]', "Tab")
        self.checked()
        # The expected receive rate at the 20 ms poll: 9 frames per batch, one batch per two polls.
        pg.wait_for_selector('[data-bridge-mailbox-cost]:has-text("about 225 CAN frames/s")')
        pg.fill('input[data-path="bridge.mailboxes.receive_blocks"]', "2")
        pg.press('input[data-path="bridge.mailboxes.receive_blocks"]', "Tab")
        pg.wait_for_selector('[data-bridge-mailbox-cost]:has-text("about 525 CAN frames/s at this poll (21 per batch")')
        self.checked()
        self.assertEqual(pg.text_content("#problem-list").strip(), "No problems.")
        pg.fill('input[data-path="bridge.mailboxes.receive_blocks"]', "")
        pg.press('input[data-path="bridge.mailboxes.receive_blocks"]', "Tab")
        self.checked()

        # Save writes the editor files; the Project page shows the facts.
        pg.click("#btn-save")
        pg.wait_for_selector("#banner:has-text('reopen the project')")
        remote = os.path.join(self.project, "devices", "remote", "canworks.json")
        programs = os.path.join(self.project, "pous", "programs")
        self.assertEqual(load(remote)["modbusTcpConfig"]["port"], 1502)
        self.assertTrue(os.path.isfile(os.path.join(programs, "canworks_in.st")))
        self.assertTrue(os.path.isfile(os.path.join(programs, "canworks_out.st")))
        conn = load(self.config_path)["bridge"]["connections"][0]
        self.assertEqual((conn["kind"], conn["poll_ms"]), ("openplc", 20))
        # The facts are in the connection's Settings, next to the poll; the
        # Project page has the editor project and what Save writes into it.
        tree_view(pg, "bridge")
        facts = pg.inner_text('[data-conn-settings-of="0"] [data-openplc-facts]')
        self.assertIn("every 20 ms", facts)
        self.assertIn("127.0.0.1:1502", facts)
        tree_view(pg, "project")
        editor = pg.inner_text('[data-editor-project="project"]')
        self.assertIn("devices/remote/canworks.json", editor)
        self.assertEqual(pg.locator("[data-openplc-facts]").count(), 0)

        # Export ▾: the network files only (modbus-connections).
        pg.click("#menu-export > summary")
        shown = pg.eval_on_selector_all("#menu-export button.item", "bs => bs.filter(b => !b.hidden).map(b => b.textContent)")
        self.assertEqual(shown, ["All DCFs", "This node's DCF", "DBC", "Documentation"])
        pg.click("#menu-export > summary")

        # canworks_in.st changed in the editor: Save asks before writing it again.
        changed = os.path.join(programs, "canworks_in.st")
        with open(changed, "a", encoding="utf-8") as f:
            f.write("(* mine *)\n")
        tree_view(pg, "bridge")
        pg.fill('input[data-path="bridge.connections[0].poll_ms"]', "10")
        self.checked()
        pg.click("#btn-save")
        pg.wait_for_selector("[data-editor-changed]")
        self.assertIn("pous/programs/canworks_in.st", pg.inner_text("[data-editor-changed]"))
        pg.click('#modal-buttons button[data-value="cancel"]')
        self.assertEqual(load(self.config_path)["bridge"]["connections"][0]["poll_ms"], 20)
        pg.click("#btn-save")
        pg.wait_for_selector("[data-editor-changed]")
        pg.click('#modal-buttons button[data-value="overwrite"]')
        pg.wait_for_selector("#banner:has-text('Saved')")
        self.assertEqual(load(self.config_path)["bridge"]["connections"][0]["poll_ms"], 10)
        with open(changed, encoding="utf-8") as f:
            self.assertNotIn("(* mine *)", f.read())

        # main still declares a value at the plugin's location: the Project
        # page offers the move, which writes the use as canworks.<name>.
        cfg = load(self.config_path)
        name = [d["name"] for d, _ in openplcmodbus._typed(editorproject.declarations(cfg, self.config_path))][0]
        main = os.path.join(self.project, mainmove.MAIN)
        with open(main, "w", encoding="utf-8") as f:
            f.write("PROGRAM main\n  VAR\n    %s : INT AT %%IW100;\n  END_VAR\n\nx := %s;\n\nEND_PROGRAM\n" % (name, name))
        pg.reload()
        tree_view(pg, "project")
        pg.wait_for_selector("[data-old-main='1']")
        self.assertIn("%IW100", pg.inner_text("[data-old-main]"))
        pg.click("[data-move-main]")
        pg.wait_for_selector("[data-main-moved='1']")
        self.assertIn("canworks/main-before-move.st", pg.inner_text("#banner"))
        pg.wait_for_function("() => !document.querySelector('[data-old-main]')")
        with open(main, encoding="utf-8") as f:
            self.assertIn("x := canworks.%s;" % name, f.read())

        # canworks_in made by an older canworks: Save is on without a change
        # and writes it again (openplc-outdated-editor-files).
        with open(changed, "w", encoding="utf-8") as f:
            f.write("PROGRAM canworks_in\nEND_PROGRAM\n")
        stamp = os.path.join(self.project, openplcmodbus.STAMP)
        with open(stamp, encoding="utf-8") as f:
            stamps = json.load(f)
        stamps["pous/programs/canworks_in.st"] = openplcmodbus._sha(changed)
        with open(stamp, "w", encoding="utf-8") as f:
            json.dump(stamps, f)
        pg.reload()
        tree_view(pg, "project")
        pg.wait_for_selector("[data-outdated='1']")
        self.assertIn("pous/programs/canworks_in.st", pg.inner_text("[data-outdated]"))
        self.assertTrue(pg.is_enabled("#btn-save"))
        self.assertEqual(pg.get_attribute("#btn-save", "title"),
                         "The editor files are from an older canworks; Save writes them again")
        self.checked()
        self.assertIn("made by an older canworks", pg.inner_text("#problem-list"))
        pg.click("[data-save-outdated]")
        pg.wait_for_function("() => !document.querySelector('[data-outdated]')")
        pg.wait_for_function("() => document.querySelector('#btn-save').disabled")
        with open(changed, encoding="utf-8") as f:
            self.assertIn("canworks.ok :=", f.read())


if __name__ == "__main__":
    import unittest
    unittest.main()
