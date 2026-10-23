"""The usability hunt's smaller fixes in a real browser (ux-cleanup): the
Supervision tab's PLC signals with Suggest all and the folder dialog's
tags and selection. Needs
Playwright, like test_configurator_page.py."""

import os
import shutil

from canworks.configurator import server as srv

from .helpers import node_tab, tree_view
from . import test_configurator_page as base
from .test_configurator_commissioning_page import Page as CommissionPage
from .test_configurator_page import FIXTURE, RTD

SIGNALS = ("status_location", "state_location", "nmt_command_location", "boot_error_location")


class Cleanup(base.Page):
    def node(self):
        self.open_from_start("#start-open", self.project)
        self.fill("adapter.interface", "can0")
        self.add_node(os.path.join(RTD, "rtd8.eds"))

    def test_suggest_all_fills_every_empty_signal(self):
        pg = self.page
        self.node()
        node_tab(pg, "supervision")
        self.assertEqual(pg.inner_text("[data-plc-signals] legend"), "PLC signals")
        self.fill("nodes[0].state_location", "%IB120")
        pg.click("[data-suggest-all]")
        pg.wait_for_function("(keys) => keys.every((k) => S.config.nodes[0][k])", arg=list(SIGNALS))
        got = pg.evaluate("(keys) => keys.map((k) => S.config.nodes[0][k])", list(SIGNALS))
        self.assertEqual(got[1], "%IB120")  # a filled one stays
        self.assertEqual(len(set(got)), 4)
        self.assertTrue(got[0].startswith("%IX") and got[2].startswith("%QB") and got[3].startswith("%IB"))

    def test_folder_dialog_tags_and_selection(self):
        pg = self.page
        where = os.path.join(self.dir, "work")
        shutil.copytree(FIXTURE, os.path.join(where, "plant"))
        os.makedirs(os.path.join(where, "cell"))
        shutil.copy(os.path.join(RTD, "canopen_config.json"), os.path.join(where, "cell", srv.CONFIG))
        os.makedirs(os.path.join(where, "other"))
        pg.click("#start-open")
        pg.fill("[data-folder=path]", where)
        pg.press("[data-folder=path]", "Enter")
        plant = '[data-folder-path="%s"]' % os.path.join(where, "plant")
        pg.wait_for_selector(plant)
        tags = pg.eval_on_selector_all("[data-folder-path]", "(bs) => bs.map((b) => b.querySelector('[data-folder-kind]')?.textContent || '')")
        self.assertEqual(tags, ["canworks config", "", "OpenPLC project"])
        # Not an EDS folder pick: no EDS count line.
        self.assertFalse(pg.is_visible("[data-folder=here]"))
        # One click selects without entering; Use this folder takes it.
        pg.click(plant)
        self.assertEqual(pg.get_attribute(plant, "aria-pressed"), "true")
        self.assertEqual(pg.input_value("[data-folder=path]"), where)
        pg.click("[data-folder=dialog] [data-value=use]")
        pg.wait_for_selector("#editor:not([hidden])")
        self.assertEqual(pg.evaluate("S.state.folder"), os.path.join(where, "plant"))
        # The mode badge names the folder, the path in its tooltip.
        self.assertIn("project plant", pg.inner_text("#mode"))
        self.assertIn(os.path.join(where, "plant"), pg.get_attribute("#mode", "title"))

    def test_store_commands_are_never_startup_writes(self):
        pg = self.page
        self.node()
        for ix in ("0x1010", "0x1011"):
            pg.evaluate("(ix) => addSdo(0, ix, 1)", ix)
            pg.wait_for_selector("#banner:has-text('never a startup write')")
        self.assertEqual(pg.evaluate("() => (S.config.nodes[0].sdo || []).filter((w) => [0x1010, 0x1011].includes(Number(w.index))).length"), 0)

    def test_simulated_network_folds_the_adapter_and_pdo_words(self):
        pg = self.page
        self.node()
        node_tab(pg, "pdos")
        self.assertIn("Inputs (TPDOs, device to Modbus registers)", pg.inner_text("#node-panel"))
        pg.evaluate("() => { setPath('adapter.simulate', true); render(); }")
        tree_view(pg, "bus")
        adapter = "details[data-advanced=adapter]"
        pg.wait_for_selector(adapter)
        self.assertFalse(pg.evaluate("(s) => document.querySelector(s).open", adapter))
        self.assertIn("not used while the network is simulated", pg.inner_text(adapter + " > summary"))

    def test_disabled_primary_is_not_a_selected_segment(self):
        pg = self.page
        self.node()
        for theme in ("light", "dark"):
            pg.evaluate("(t) => { document.documentElement.dataset.theme = t; }", theme)
            fills = pg.evaluate("""() => {
                const b = document.createElement('button'); b.className = 'primary'; b.disabled = true; b.textContent = 'Saved';
                document.body.append(b);
                const off = getComputedStyle(b).backgroundColor; b.remove();
                return [off, getComputedStyle(document.querySelector('#ws button[aria-pressed=true]')).backgroundColor]; }""")
            self.assertNotEqual(fills[0], fills[1], theme)


    def test_walk_fixes(self):
        # Found walking the page at several window sizes: a stray "null" in
        # Online access and a header
        # that took two rows in a 911 x 512 window.
        pg = self.page
        self.node()
        pg.evaluate("() => { setPath('adapter.simulate', true); render(); }")
        pg.click('[data-open-project]')
        pg.wait_for_selector('[data-section=online]')
        self.assertEqual(pg.evaluate("""() => [...document.querySelector('[data-section=online]').childNodes]
            .filter((n) => n.nodeType === 3 && n.textContent.trim()).map((n) => n.textContent)"""), [])
        pg.set_viewport_size({"width": 911, "height": 512})
        pg.wait_for_timeout(300)
        tops = pg.evaluate("""() => [...document.querySelectorAll('header .top-row > *')].filter((e) => e.offsetParent && !e.classList.contains('spacer') && e.getBoundingClientRect().width > 2)
            .map((e) => [e.id || e.className, Math.round(e.getBoundingClientRect().top), Math.round(e.getBoundingClientRect().width)])""")
        tops = [t[1] for t in tops]
        self.assertLess(max(tops) - min(tops), 12, tops)
        self.assertEqual(pg.inner_text("[data-sim=line]").strip(), "Simulated")


class Parameters(CommissionPage):
    def test_restore_names_and_file_buttons(self):
        # ux-cleanup "Parameters names and file buttons".
        pg = self.page
        self.open_node(5, "params", "rtd8.eds")
        pg.wait_for_selector('button[data-online="restore"]')
        self.assertEqual(pg.inner_text('button[data-online="restore"]'), "Restore from backup…")
        # The 0x1011 box comes with the device's data, after the restore button.
        pg.wait_for_selector('button[data-online="restore-defaults"]')
        self.assertEqual(pg.inner_text('button[data-online="restore-defaults"]'), "Factory defaults (0x1011)…")
        self.assertTrue(pg.is_visible("fieldset.changes-device"))
        # Every file choice is a styled button with the file name next to it.
        self.assertEqual(pg.eval_on_selector_all('input[type="file"]', "(xs) => xs.filter((x) => x.offsetParent && !x.closest('.file-button')).length"), 0)


for _name in [n for n in dir(base.Page) if n.startswith("test_")]:
    setattr(Cleanup, _name, None)
