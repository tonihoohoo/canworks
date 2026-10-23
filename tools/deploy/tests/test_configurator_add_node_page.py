"""The Add node dialog (add-node-dialog): the project's EDS files as a list,
Browse…, the node ID check, the name, the EDS's default PDOs, the tab a new
node opens on, no message for a clean EDS, one name per PDO entry and the
"not mapped to the PLC" mark. Needs Playwright, like
test_configurator_page.py."""

import os
import shutil

from .helpers import REPO, add_node, browse_eds, tree_node
from .test_configurator_online_page import OnlineBase
from .test_configurator_page import RTD

DIALOG = '[data-add-node="dialog"]'


class AddNode(OnlineBase):
    def setUp(self):
        super().setUp()
        shutil.copy(os.path.join(RTD, "rtd8.eds"), os.path.join(self.project, "canworks"))

    def open_dialog(self):
        pg = self.page
        pg.click('#tree .open-net [data-action="add-node"] > .tree-row')
        pg.wait_for_selector(DIALOG + "[open]")

    def nodes(self):
        return self.page.evaluate("() => S.config.nodes.map((n) => [n.node_id, n.name, n.eds])")

    def test_pick_from_the_project_list(self):
        pg = self.page
        self.open()
        before = self.nodes()
        self.open_dialog()
        options = pg.eval_on_selector_all(DIALOG + ' [data-add-node="eds"] option', "os => os.map((o) => [o.value, o.textContent])")
        self.assertIn(["rtd8.eds", "RTD-8 temperature input module (rtd8.eds)"], options)
        self.assertTrue(any(v == "cpp-slave.eds" and "used by 1 node" in t for v, t in options), options)
        pg.select_option(DIALOG + ' [data-add-node="eds"]', "rtd8.eds")
        self.assertEqual(pg.input_value('[data-add-node="name"]'), "rtd_8_temperature_input_module")
        # The ID is checked as typed: the master's, a taken one, out of range.
        self.assertEqual(pg.input_value('[data-add-node="id"]'), "3")
        pg.fill('[data-add-node="id"]', "1")
        self.assertIn("master's node ID", pg.inner_text('[data-add-node="id-msg"]'))
        pg.fill('[data-add-node="id"]', "2")
        self.assertIn("taken by", pg.inner_text('[data-add-node="id-msg"]'))
        pg.click('[data-add-node="add"]')
        self.assertIn("taken by", pg.inner_text('[data-add-node="msg"]'))
        pg.fill('[data-add-node="id"]', "128")
        self.assertIn("1 to 127", pg.inner_text('[data-add-node="id-msg"]'))
        pg.fill('[data-add-node="id"]', "9")
        self.assertEqual(pg.inner_text('[data-add-node="id-msg"]'), "")
        pg.fill('[data-add-node="name"]', "temps")
        pg.click('[data-add-node="add"]')
        pg.wait_for_selector(DIALOG, state="detached")
        self.assertEqual(self.nodes(), before + [[9, "temps", "rtd8.eds"]])
        # The default PDOs: the four enabled TPDOs with their default mapping, each entry located;
        # the node opens on PDOs, and a clean EDS shows no message.
        pdos = pg.evaluate("() => S.config.nodes.at(-1).tx_pdos")
        self.assertEqual([p["number"] for p in pdos], [1, 2, 3, 4])
        self.assertEqual([(e["index"], e["subindex"]) for e in pdos[0]["entries"]],
                         [("0x7130", 1), ("0x6150", 1), ("0x7130", 2), ("0x6150", 2)])
        self.assertTrue(all(e["iec_location"].startswith("%I") for p in pdos for e in p["entries"]))
        self.assertEqual(len({e["iec_location"] for p in pdos for e in p["entries"]}), 16)
        pg.wait_for_selector('.node-tabs [data-node-tab="pdos"][aria-selected="true"]')
        self.assertFalse(pg.is_visible("#banner"))

    def test_without_default_pdos_opens_on_general(self):
        pg = self.page
        self.open()
        self.open_dialog()
        pg.select_option(DIALOG + ' [data-add-node="eds"]', "rtd8.eds")
        pg.uncheck('[data-add-node="map"]')
        pg.click('[data-add-node="add"]')
        pg.wait_for_selector(DIALOG, state="detached")
        self.assertIsNone(pg.evaluate("() => S.config.nodes.at(-1).tx_pdos || null"))
        pg.wait_for_selector('.node-tabs [data-node-tab="general"][aria-selected="true"]')
        self.assertEqual(pg.evaluate("document.activeElement.dataset.path"), "nodes[1].name")

    def test_browse_and_a_unique_name(self):
        pg = self.page
        self.open()
        self.open_dialog()
        browse_eds(pg, os.path.join(REPO, "test", "fixtures", "eds", "fixed-io.eds"))
        pg.wait_for_function("() => document.querySelector('[data-add-node=\"eds\"]').value === 'fixed-io.eds'")
        first = pg.input_value('[data-add-node="name"]')
        pg.click('[data-add-node="add"]')
        pg.wait_for_selector(DIALOG, state="detached")
        # The same device again: the list has it, the name gets a number.
        self.open_dialog()
        pg.select_option(DIALOG + ' [data-add-node="eds"]', "fixed-io.eds")
        self.assertEqual(pg.input_value('[data-add-node="name"]'), first + "_2")
        pg.click('[data-add-node="cancel"]')
        pg.wait_for_selector(DIALOG, state="detached")

    def test_one_name_per_entry_and_the_unmapped_mark(self):
        pg = self.page
        self.open()
        tree_node(pg, 0, "pdos")
        entry = 'input[data-path="nodes[0].tx_pdos[0].entries[0].name"]'
        pg.wait_for_function("(s) => document.querySelector(s).placeholder !== ''", arg=entry)
        placeholder = pg.get_attribute(entry, "placeholder")
        self.assertTrue(placeholder.startswith("pingpong_"), placeholder)
        self.assertNotIn("declared as", pg.inner_text("#view"))
        # An entry without a location: the mark, and Suggest fills one.
        loc = 'input[data-path="nodes[0].tx_pdos[0].entries[0].iec_location"]'
        pg.fill(loc, "")
        pg.evaluate("() => render()")
        mark = '[data-unmapped="nodes[0].tx_pdos[0].entries[0]"]'
        pg.wait_for_selector(mark)
        self.assertIn("not mapped to the PLC", pg.inner_text(mark))
        pg.click(mark + " button")
        pg.wait_for_selector(mark, state="detached")
        self.assertRegex(pg.input_value(loc), r"^%I")


class AddNodeCodesys(OnlineBase):
    def test_names_only_for_codesys(self):
        pg = self.page
        self.cfg.pop("bridge", None)
        self.cfg["codesys"] = {}
        self.write_config()
        shutil.copy(os.path.join(RTD, "rtd8.eds"), os.path.join(self.project, "canworks"))
        self.open()
        add_node(pg, os.path.join(RTD, "rtd8.eds"), map_pdos=True, node_id=9)
        entries = pg.evaluate("() => S.config.nodes.at(-1).tx_pdos[0].entries")
        self.assertTrue(all("iec_location" not in e for e in entries), entries)
        names = [e["name"] for p in pg.evaluate("() => S.config.nodes.at(-1).tx_pdos") for e in p["entries"]]
        self.assertEqual(len(set(names)), 16)
