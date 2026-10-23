"""The CODESYS target in a real browser (spec canopen-configurator "Project
target", "Only what the target uses is shown", "Switching the target",
"Variable names of PDO entries", "CODESYS settings", "CODESYS actions",
"Target of a new config", "Commission in a CODESYS project", "Placeholder
look", "CODESYS project file dialog", "New project name in the file
dialog", "PLC devices installed in CODESYS"): an OpenPLC
project switched to CODESYS and back, what the page hides, a leftover value
with Remove, the CODESYS page and Bus page settings, Download for CODESYS,
Build without CODESYS, Browse… and the PLC device list, Build creating a
new project, and a new CODESYS config from the start page. Needs
Playwright, like test_configurator_page.py."""

import json
import os
import shutil
from unittest import mock

from canworks.codesys import plan as cplan

from canworks.configurator import server as srv

from .helpers import REPO, export_program, tree_node, tree_view, new_config, add_node
from .test_configurator_online_page import OnlineBase
from .test_configurator_page import LINT, load

EXAMPLE = os.path.join(REPO, "examples", "modbus-bridge")
DEVICES = os.path.join(os.path.dirname(__file__), "data", "codesys-devices", "Devices")


class CodesysPage(OnlineBase):
    def setUp(self):
        super().setUp()
        # The example as an OpenPLC project.
        cfg = load(os.path.join(EXAMPLE, "canworks.json"))
        self.cfg = srv.Session().switch_target(cfg, "openplc_modbus")["config"]
        for name in ("rtd8.eds", "dio16.eds"):
            shutil.copy(os.path.join(EXAMPLE, name), os.path.join(self.project, "canworks"))
        self.write_config()

    def write_config(self, diagnostics=None):
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(self.cfg, f, indent=2)

    def checked(self):
        self.page.wait_for_function("() => document.body.dataset.checking === '0'")

    def to_codesys(self):
        # No question: what CODESYS does not use goes, the banner says so (target-cleans-up).
        pg = self.page
        tree_view(pg, "project")
        self.assertEqual(pg.input_value('select[data-target="1"]'), "openplc_modbus")
        self.assertEqual(pg.locator("#tree #nav-codesys").count(), 0)
        pg.select_option('select[data-target="1"]', "codesys")
        pg.wait_for_selector("#banner:has-text('targets CODESYS now')")
        self.assertFalse(pg.evaluate("() => document.querySelector('#modal').open"))
        self.assertIn("CODESYS does not use removed", pg.inner_text("#banner"))
        pg.wait_for_selector("#tree #nav-codesys")
        tree_view(pg, "bus")
        self.checked()

    def test_eds_corrections_for_codesys(self):
        # "Import an EDS": CODESYS gets the DCFs built from the corrected
        # copy; their REAL values are decimals again, so that kind is left out.
        pg = self.page
        self.open()
        self.to_codesys()

        def upload(eds):
            n = pg.evaluate("() => S.config.nodes.length")
            add_node(pg, eds)
            pg.wait_for_selector('[data-node-heading="%d"]' % n)
        upload(os.path.join(LINT, "nodeid-suffix.eds"))
        report = pg.locator('#banner [data-report="corrections"]')
        self.assertIn("nodeid-suffix.eds is kept as imported. The DCFs exported to CODESYS are built from a corrected "
                      "copy:", report.inner_text())
        self.assertEqual(report.locator("li").all_text_contents(),
                         ['3 values written "<number>+$NODEID" are read as "$NODEID+<number>"'])
        upload(os.path.join(LINT, "real-decimal.eds"))
        self.assertEqual(pg.locator('#banner [data-report]').count(), 0)

    def test_switch_hides_and_back(self):
        pg = self.page
        self.open()
        self.assertEqual(pg.inner_text("[data-target-mark]"), " · OpenPLC")
        self.assertTrue(pg.is_visible('select[data-path="master.eds_lint"]'))
        self.to_codesys()
        self.assertEqual(pg.inner_text("[data-target-mark]"), " · CODESYS")
        self.assertEqual(pg.text_content("#problem-list").strip(), "No problems.")
        # The Bus page: no EDS lint, bus diagnostics or simulation; the CODESYS settings.
        for path in ("master.eds_lint", "master.bus_state_location", "adapter.type",
                     "adapter.simulate"):
            self.assertFalse(pg.is_visible('[data-path="%s"]' % path), path)
        self.assertEqual(pg.locator('select[data-path="master.sync_source"] option[value="plc_cycle"]').count(), 0)
        self.assertEqual([o for o in pg.eval_on_selector_all('select[data-path="protocol"] option', "os => os.map(o => o.value)")], [""])
        self.assertEqual(pg.eval_on_selector_all('select[data-path="role"] option', "os => os.map(o => o.value)"), [""])
        pg.fill('input[data-path="codesys.net_id"]', "0")
        self.assertEqual(pg.evaluate("() => S.config.codesys"), {"net_id": 0})
        # The tree: no CAN messages; the Project page: no Online access.
        self.assertEqual(pg.locator('#tree [data-view="raw"]').count(), 0)
        tree_view(pg, "project")
        self.assertEqual(pg.locator('#view [data-section="online"]').count(), 0)
        tree_view(pg, "bus")
        self.assertFalse(pg.is_visible('#tool-tabs [data-view="declarations"]'))
        # The header: Build with no ▾; Download in Export ▾ → For the program, alone;
        # no editor project section and no Copy as ST call (no canworks blocks in CODESYS).
        self.assertTrue(pg.is_visible("#btn-codesys-build"))
        self.assertEqual(pg.locator("#menu-target, #menu-project").count(), 0)
        pg.click("#menu-export > summary")
        shown = pg.eval_on_selector_all("#menu-export [data-export-program]", "bs => bs.filter(b => !b.hidden).map(b => b.dataset.exportProgram)")
        self.assertEqual(shown, ["codesys"])
        pg.click("#menu-export > summary")
        self.assertFalse(pg.evaluate("() => stCallsShown()"))
        # The node's PDOs: a Variable column with the names, no PLC location column.
        tree_node(pg, 1, "pdos")
        pg.wait_for_selector('input[data-path="nodes[1].tx_pdos[0].entries[0].name"]')
        self.assertEqual(pg.locator('input[data-path$=".iec_location"]').count(), 0)
        self.assertNotIn("PLC location", pg.inner_text(".pdo table thead"))
        self.assertEqual(pg.input_value('input[data-path="nodes[1].tx_pdos[0].entries[0].name"]'), "Read_input_8_bit_1")
        pg.fill('input[data-path="nodes[1].tx_pdos[0].entries[0].name"]', "door_open")
        self.checked()
        self.assertEqual(pg.text_content("#problem-list").strip(), "No problems.")
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
        self.assertNotIn("bridge", saved)
        # Download for CODESYS: the zip, nothing written to the folder.
        with pg.expect_download() as dl:
            export_program(pg, "codesys")
        self.assertEqual(dl.value.suggested_filename, "rtd-monitor_codesys.zip")
        # Back to OpenPLC: every entry gets a location, the names stay.
        tree_view(pg, "project")
        pg.select_option('select[data-target="1"]', "openplc_modbus")
        pg.wait_for_selector("#banner:has-text('targets OpenPLC now')")
        self.assertIn("got a location", pg.inner_text("#banner"))
        pg.wait_for_selector("#tree #nav-codesys", state="detached")
        self.checked()
        self.assertEqual(pg.text_content("#problem-list").strip(), "No problems.")
        self.assertFalse(pg.is_visible("#btn-codesys-build"))
        self.assertIsNone(pg.evaluate("() => unusedWhy('master.eds_lint')"))  # the Bus page shows it again
        # One undo step brings CODESYS back: the banner's Undo, on the Project page.
        pg.click("#banner [data-undo]")
        pg.wait_for_selector("#tree #nav-codesys")
        self.assertEqual(pg.input_value('select[data-target="1"]'), "codesys")


    def test_leftover_values_in_a_codesys_config(self):
        """Values CODESYS does not use: hidden, no bar, no problem, no unsaved
        mark; save leaves them out and says how many (target-cleans-up)."""
        pg = self.page
        cfg = self.cfg
        cfg.pop("bridge", None)
        cfg["codesys"] = {}
        cfg["networks"][0]["master"]["on_plc_stop"] = "keep"
        cfg["networks"][0]["nodes"][0]["tx_pdos"][0]["entries"][0]["iec_location"] = "%IW100"
        cfg["networks"][0]["nodes"][0]["simulate"] = True
        self.write_config()
        self.open()
        self.checked()
        self.assertFalse(pg.is_visible('select[data-path="master.on_plc_stop"]'))
        self.assertEqual(pg.text_content("#problem-list").strip(), "No problems.")
        self.assertTrue(pg.is_hidden("[data-unsaved]"))
        self.assertNotIn("not used by CODESYS", pg.inner_text("#view"))
        self.assertEqual(pg.locator("#show-all-fields").count(), 0)
        # A leftover simulate gives no Simulation tab and no simulated mark;
        # a leftover location no PLC location column.
        tree_node(pg, 0, "pdos")
        self.assertEqual(pg.locator('.node-tabs [data-node-tab="simulation"]').count(), 0)
        self.assertEqual(pg.locator("#tree [data-sim-badge]").count(), 0)
        self.assertEqual(pg.locator('input[data-path="nodes[0].tx_pdos[0].entries[0].iec_location"]').count(), 0)
        self.assertNotIn("PLC location", pg.inner_text("#node-panel thead"))
        # CODESYS reads the emergencies itself: no EMCY section.
        tree_node(pg, 0, "supervision")
        pg.wait_for_selector('[data-supervision="0"]')
        self.assertEqual(pg.locator("[data-emcy-section]").count(), 0)
        self.assertNotIn("Emergency", pg.inner_text("#node-panel"))
        # Any edit, then save.
        tree_view(pg, "bus")
        pg.fill('input[data-path="codesys.net_id"]', "0")
        self.checked()
        pg.click("#btn-save")
        pg.wait_for_selector("#banner:has-text('Saved')")
        self.assertRegex(pg.inner_text("#banner"), r"\d+ settings? CODESYS does not use left out")
        saved = load(self.config_path)
        net = saved["networks"][0]
        self.assertNotIn("on_plc_stop", net["master"])
        self.assertNotIn("simulate", net["nodes"][0])
        self.assertNotIn("iec_location", net["nodes"][0]["tx_pdos"][0]["entries"][0])
        self.assertTrue(pg.is_hidden("[data-unsaved]"))

    def test_build_without_codesys(self):
        pg = self.page
        self.cfg.pop("bridge", None)
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

    def with_codesys(self):
        """CODESYS 'installed' in a temp folder with the test device
        repository; a runner stands in for CODESYS and keeps the plans."""
        root = os.path.join(self.dir, "Program Files")
        install = os.path.join(root, "CODESYS 3.5.22.40", "CODESYS")
        os.makedirs(os.path.join(install, "Common"))
        os.makedirs(os.path.join(install, "Profiles"))
        open(os.path.join(install, "Common", "CODESYS.exe"), "w").close()
        open(os.path.join(install, "Profiles", "CODESYS V3.5 SP22.profile.xml"), "w").close()
        patches = [mock.patch.dict(os.environ, {"PROGRAMFILES": root}), mock.patch.object(srv, "_codesys_devices", None),
                   mock.patch("canworks.codesys.run.repository_roots", return_value=[DEVICES])]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        plans = []

        def runner(line):
            folder = os.path.dirname(line.split('--runscript="')[1].rstrip('"'))
            plans.append(load(os.path.join(folder, cplan.PLAN_NAME)))
            with open(os.path.join(folder, cplan.REPORT_NAME), "w", encoding="utf-8") as f:
                f.write("result: ok\nwarnings: 0\n\ndevice   PLC (only device)\n")
        self.server.codesys_runner = runner
        return plans

    def browse(self, folder):
        """Browse… to `folder`, which has a subfolder `old`."""
        pg = self.page
        pg.click("[data-codesys-browse]")
        pg.wait_for_selector('dialog[data-folder="dialog"][open]')
        self.assertFalse(pg.is_visible('dialog[data-folder="dialog"] button[data-value="use"]'))
        pg.fill('[data-folder="path"]', folder)
        pg.press('[data-folder="path"]', "Enter")
        # The folder's own listing, not the start folder's (the path field already says the folder).
        pg.wait_for_selector('[data-folder-path="%s"]' % os.path.join(folder, "old"))

    def test_browse_and_device_list(self):
        pg = self.page
        self.with_codesys()
        projects = os.path.join(self.dir, "projects")
        os.makedirs(os.path.join(projects, "old"))
        open(os.path.join(projects, "cell.project"), "w").close()
        self.cfg.pop("bridge", None)
        self.cfg["codesys"] = {}
        self.write_config()
        self.open()
        tree_view(pg, "codesys")
        pg.wait_for_selector("[data-codesys-browse]")
        # Placeholders look like placeholders, and the examples say so.
        self.assertEqual(pg.get_attribute('input[data-path="codesys.project"]', "placeholder"), "e.g. C:\\Projects\\cell.project")
        self.assertEqual(pg.evaluate("() => getComputedStyle(document.querySelector('input[data-path=\"codesys.project\"]'), '::placeholder').fontStyle"), "italic")
        # An existing project: picked in the list; no PLC device asked.
        self.browse(projects)
        self.assertIn("1 .project file", pg.inner_text("[data-folder=here]"))
        pg.click('[data-file-path="%s"]' % os.path.join(projects, "cell.project"))
        pg.wait_for_selector('dialog[data-folder="dialog"]', state="detached")
        self.assertEqual(pg.input_value('input[data-path="codesys.project"]'), os.path.join(projects, "cell.project"))
        pg.wait_for_selector("[data-codesys-existing]")
        # The path field takes the row's width beside Browse…, so a long path shows.
        width = pg.evaluate("() => document.querySelector('input[data-path=\"codesys.project\"]').getBoundingClientRect().width")
        self.assertGreater(width, 300)
        # A new one: named in the dialog; the installed PLCs to pick from.
        self.browse(projects)
        pg.fill('[data-folder="new-name"]', "cell")
        pg.click('[data-folder="create"]')
        self.assertIn("exists already", pg.inner_text('dialog[data-folder="dialog"]'))
        pg.fill('[data-folder="new-name"]', "line2")
        pg.press('[data-folder="new-name"]', "Enter")
        pg.wait_for_selector('dialog[data-folder="dialog"]', state="detached")
        self.assertEqual(pg.input_value('input[data-path="codesys.project"]'), os.path.join(projects, "line2.project"))
        pg.wait_for_selector("select[data-codesys-device]")
        self.assertEqual(pg.eval_on_selector_all("select[data-codesys-device] option", "os => os.map(o => o.textContent)"),
                         ["Choose the PLC…", "CODESYS Control RTE V3 3.5.22.40", "CODESYS Control Win V3 x64 3.5.22.40",
                          "CODESYS Control Win V3 x64 3.5.21.0", "Other (type TYPE:ID:VERSION)…"])
        pg.select_option("select[data-codesys-device]", label="CODESYS Control Win V3 x64 3.5.22.40")
        self.assertEqual(pg.evaluate("() => S.model.top.codesys.create"), "4096:0000 0004:3.5.22.40")
        # A typed name gets .project.
        pg.fill('input[data-path="codesys.project"]', os.path.join(projects, "line3"))
        pg.press('input[data-path="codesys.project"]', "Tab")
        self.assertEqual(pg.evaluate("() => S.model.top.codesys.project"), os.path.join(projects, "line3.project"))

    def test_build_asks_for_a_new_project(self):
        pg = self.page
        plans = self.with_codesys()
        project = os.path.join(self.dir, "new.project")
        self.cfg.pop("bridge", None)
        self.cfg["codesys"] = {"project": project}
        self.write_config()
        self.open()
        self.assertTrue(pg.evaluate("() => S.state.codesys_found"))
        pg.click("#btn-codesys-build")
        pg.wait_for_selector("#modal[open] [data-codesys-new]")
        self.assertIn("new.project does not exist. Create a new CODESYS project?", pg.inner_text("#modal-text"))
        # Cancel changes nothing.
        pg.click('#modal-buttons button[data-value="cancel"]')
        self.assertFalse(pg.evaluate("() => S.dirty"))
        self.assertEqual(plans, [])
        pg.click("#btn-codesys-build")
        pg.wait_for_selector("#modal[open] [data-codesys-new]")
        pg.click('#modal-buttons button[data-value="create"]')
        self.assertIn("Pick the PLC device", pg.inner_text("#modal-text"))
        pg.select_option("#modal-extra select[data-codesys-device]", label="CODESYS Control RTE V3 3.5.22.40")
        pg.click('#modal-buttons button[data-value="create"]')
        pg.wait_for_selector("#modal[open] [data-codesys-report]", timeout=60000)
        self.assertIn("CODESYS built the bus into PLC (only device).", pg.inner_text("#modal-text"))
        self.assertEqual(load(self.config_path)["codesys"]["create"], "4096:0000 0002:3.5.22.40")
        self.assertEqual(plans[0]["create"], {"path": project, "device": {"type": 4096, "id": "0000 0002",
                                                                         "version": "3.5.22.40"}})

    def test_commission_connects_through_an_adapter(self):
        pg = self.page
        self.cfg.pop("bridge", None)
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
        tree_view(pg, "project")
        self.assertEqual(pg.input_value('select[data-target="1"]'), "codesys")
        cfg = pg.evaluate("() => fileConfig()")
        self.assertEqual((cfg["schema_version"], cfg["codesys"]), (2, {}))
        self.assertNotIn("type", cfg["networks"][0]["adapter"])
        # save-anytime: Create wrote it, so the page opens it saved.
        self.assertFalse(pg.evaluate("() => S.dirty"))
        self.assertEqual(load(os.path.join(folder, "canworks.json"))["codesys"], {})


if __name__ == "__main__":
    import unittest
    unittest.main()
