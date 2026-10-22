"""One EDS picker (one-eds-picker): the EDS dialog and the EDS field on a
node's General tab, the slave page and the Add node dialog's list, the EDS
library, the keyboard, and the notes next to a picked EDS. Needs
Playwright, like test_configurator_page.py."""

import json
import os
import shutil

from .helpers import REPO, browse_eds, tmpdir, tree_node, tree_view
from .test_configurator_online_page import OnlineBase
from .test_configurator_page import RTD, load

FIXTURES = os.path.join(REPO, "test", "fixtures", "eds")
GATEWAY = os.path.join(REPO, "config", "gateway")
DIALOG = '[data-eds="dialog"]'
NOTE = {"text": "How often the module says it is alive"}


class EdsPicker(OnlineBase):
    def setUp(self):
        super().setUp()
        shutil.copy(os.path.join(RTD, "rtd8.eds"), os.path.join(self.project, "canworks"))

    def library(self, notes=True, datasheet=False):
        """An EDS library with fixed-io.eds, its notes file and maybe a datasheet notes file."""
        lib = tmpdir(self)
        shutil.copy(os.path.join(FIXTURES, "fixed-io.eds"), lib)
        doc = {"format": "canworks-notes.v1", "eds": {"file": "fixed-io.eds"}, "objects": {"0x1017": NOTE}}
        if notes:
            with open(os.path.join(lib, "fixed-io.eds.notes.json"), "w") as f:
                json.dump(doc, f)
        if datasheet:
            with open(os.path.join(lib, "fixed-io.eds.datasheet.notes.json"), "w") as f:
                json.dump(doc, f)
        self.remember("127.0.0.1:1", library=lib)
        return lib

    def options(self):
        return self.page.eval_on_selector_all(DIALOG + ' [data-eds="list"] optgroup', """gs => gs.map((g) =>
            [g.label, [...g.querySelectorAll("option")].map((o) => o.textContent)])""")

    def test_node_general_tab(self):
        pg = self.page
        self.open()
        tree_node(pg, 0, "general")
        field = '#view button[data-path="nodes[0].eds"]'
        self.assertIn("cpp-slave.eds", pg.inner_text("#view .eds-field"))
        self.assertEqual(pg.inner_text(field), "Change EDS…")
        # No EDS dropdown and no browser file input for an EDS.
        self.assertEqual(pg.locator('#view select[data-path="nodes[0].eds"]').count(), 0)
        self.assertEqual(pg.locator('input[type=file][accept*=".eds"]:visible').count(), 0)
        # Cancel (Escape) changes nothing, and the focus is back on Change EDS….
        pg.click(field)
        pg.wait_for_selector(DIALOG + "[open]")
        groups = dict(self.options())
        self.assertIn("RTD-8 temperature input module (rtd8.eds)", groups["In this project"])
        self.assertEqual(pg.input_value('[data-eds="list"]'), "cpp-slave.eds")
        pg.select_option('[data-eds="list"]', "rtd8.eds")
        pg.keyboard.press("Escape")
        pg.wait_for_selector(DIALOG, state="detached")
        self.assertEqual(pg.evaluate("() => [S.config.nodes[0].eds, S.dirty]"), ["cpp-slave.eds", False])
        self.assertEqual(pg.evaluate("() => document.activeElement.dataset.path"), "nodes[0].eds")
        # Enter on an entry uses it.
        pg.click(field)
        pg.select_option('[data-eds="list"]', "rtd8.eds")
        pg.focus('[data-eds="list"]')
        pg.keyboard.press("Enter")
        pg.wait_for_selector(DIALOG, state="detached")
        self.assertEqual(pg.evaluate("() => [S.config.nodes[0].eds, S.dirty]"), ["rtd8.eds", True])
        self.assertIn("RTD-8", pg.inner_text("#view .eds-field"))

    def test_library_notes_come_with_the_eds(self):
        pg = self.page
        self.library(datasheet=True)
        self.open()
        tree_node(pg, 0, "general")
        pg.click('#view button[data-path="nodes[0].eds"]')
        pg.wait_for_selector(DIALOG + ' optgroup[label="EDS library"]', state="attached")
        self.assertTrue(any(t.endswith("(fixed-io.eds)") for t in dict(self.options())["EDS library"]))
        # A double-click on the library file uses it: imported with its notes, the datasheet notes named.
        pg.dblclick(DIALOG + ' option[value$="fixed-io.eds"]')
        pg.wait_for_selector(DIALOG, state="detached")
        pg.wait_for_function("() => S.config.nodes[0].eds === 'fixed-io.eds'")
        pg.wait_for_selector("#banner [data-notes-came]")
        self.assertIn("fixed-io.eds.datasheet.notes.json", pg.inner_text("#banner [data-datasheet-notes]"))
        self.assertEqual(pg.evaluate("() => S.model.notes['fixed-io.eds']['0x1017']"), NOTE)
        pg.wait_for_function("() => document.body.dataset.checking === '0'")
        pg.click("#btn-save")
        pg.wait_for_selector("#banner:has-text('Saved')")
        saved = load(os.path.join(self.project, "canworks", "fixed-io.eds.notes.json"))
        self.assertEqual(saved["objects"]["0x1017"]["text"], NOTE["text"])

    def test_browse_keeps_the_configs_notes(self):
        pg = self.page
        lib = self.library()
        # The config already has its own notes for fixed-io.eds.
        canworks = os.path.join(self.project, "canworks")
        shutil.copy(os.path.join(FIXTURES, "fixed-io.eds"), canworks)
        mine = {"format": "canworks-notes.v1", "eds": {"file": "fixed-io.eds"}, "objects": {"0x1017": {"text": "mine"}}}
        with open(os.path.join(canworks, "fixed-io.eds.notes.json"), "w") as f:
            json.dump(mine, f)
        self.open()
        pg.click('#tree .open-net [data-action="add-node"] > .tree-row')
        pg.wait_for_selector('[data-add-node="dialog"][open]')
        # Browse… lists the folder's EDS files; the same file is used as the config's.
        with open(os.path.join(lib, "fixed-io.eds"), "a") as f:
            f.write("\n")  # another file under the same name
        browse_eds(pg, os.path.join(lib, "fixed-io.eds"))
        pg.click('#modal button[data-value="replace"]')
        pg.wait_for_function("() => document.querySelector('[data-add-node=eds]').value === 'fixed-io.eds'")
        pg.click('[data-add-node="add"]')
        pg.wait_for_selector('[data-add-node="dialog"]', state="detached")
        pg.wait_for_selector("#banner [data-notes-kept]")
        self.assertIsNone(pg.evaluate("() => (S.model.notes || {})['fixed-io.eds'] || null"))

    def test_slave_page(self):
        pg = self.page
        canworks = os.path.join(self.project, "canworks")
        for name in ("cpp-slave.eds", "openplc-gateway.eds"):
            shutil.copy(os.path.join(GATEWAY, name), canworks)
        # The description the slave's EDS was built from: it was built here.
        shutil.copy(os.path.join(GATEWAY, "gateway_eds.json"), os.path.join(canworks, "openplc-gateway.eds.json"))
        cfg = load(os.path.join(GATEWAY, "canopen_config.json"))
        with open(self.config_path, "w") as f:
            json.dump(cfg, f)
        self.open()
        slave = next(i for i, n in enumerate(cfg["networks"]) if n.get("role") == "slave")
        pg.click('#tree [data-key="%d"] [data-slave] > .tree-row' % slave)
        pg.wait_for_selector('#view button[data-path="slave.eds"]')
        self.assertIn("openplc-gateway.eds", pg.inner_text("#view .eds-field"))
        self.assertEqual(pg.locator('input[type=file][accept*=".eds"]:visible').count(), 0)
        pg.click('#view button[data-path="slave.eds"]')
        groups = self.options()
        self.assertEqual(groups[0][0], "Built here")
        self.assertTrue(any("openplc-gateway.eds" in t for t in groups[0][1]), groups)
        self.assertEqual(pg.evaluate("() => document.querySelector('[data-eds=list]').selectedOptions[0].textContent").endswith("(openplc-gateway.eds)"), True)
        pg.click(DIALOG + ' [data-eds="cancel"]')
        pg.wait_for_selector(DIALOG, state="detached")
        self.assertFalse(pg.evaluate("() => S.dirty"))
        self.assertEqual(pg.evaluate("() => document.activeElement.dataset.path"), "slave.eds")
