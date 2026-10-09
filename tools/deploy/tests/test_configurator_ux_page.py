"""The configurator's UX fixes in a real browser (polish-configurator-ux):
the node list never exports, export checks replace the Problems pane, no
"null" text, commissioning mode, safe dialog defaults, undo, keyboard
access, the header menus, the node page sections, busy states, the online
view's stale values and the wording. Needs Playwright, like
test_configurator_page.py."""

import os
import shutil
import time

from canworks import diag
from canworks.bustrace import formats
from canworks.bustrace.model import Frame

from .fake_diag import TOKEN, FakePlugin
from .helpers import PINGPONG
from .test_bustrace import sample_trace, written
from .test_configurator_layout import Layout, audit, load
from .test_configurator_online_page import OnlineBase
from .test_configurator_page import RTD, fake_editor_cli

NO_NODES = "No nodes yet. Add a node from its EDS, or turn on Online access for a scan-only configuration."
TEXT_NODES = """() => [...document.querySelectorAll('#editor, header, #banner')].flatMap((root) => {
  const out = [];
  const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  while (w.nextNode()) { const t = w.currentNode.textContent.trim(); if (t === 'null' || t === 'undefined') out.push(w.currentNode.parentElement.outerHTML.slice(0, 80)); }
  return out;
})"""



class Probes(Layout):
    """On the layout test's project: three nodes, five problems, four of them errors."""

    def setUp(self):
        super().setUp()
        self.cfg["nodes"][2]["tx_pdos"][0]["timeout_ms"] = 500
        self.write_config()

    def problems(self):
        return self.page.inner_text("#problem-count")

    def active(self):
        return self.page.evaluate("() => { const a = document.activeElement; return a ? (a.dataset.path || a.id || a.textContent.trim().slice(0, 40)) : null; }")

    def open_sections(self):
        self.page.evaluate("() => document.querySelectorAll('details.section, details[data-picker]').forEach((d) => { d.open = true; })")
        self.page.wait_for_timeout(50)

    # -- 1.1 / 1.2 the node list and the export checks ------------------------
    def test_node_item_click_never_exports(self):
        pg = self.page
        self.open()
        pg.wait_for_selector("#problem-count:has-text('5 problems')")
        downloads = []
        pg.on("download", lambda d: downloads.append(d))
        for k in range(3):
            item = pg.locator('#node-list [data-node="%d"]' % k)
            item.hover()
            box = item.bounding_box()
            pg.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            pg.wait_for_selector('#view h2:has-text("Node")')
            self.assertEqual(pg.get_attribute('#node-list [data-node="%d"]' % k, "aria-current"), "true")
        pg.wait_for_timeout(500)
        self.assertEqual(downloads, [])
        self.assertEqual(self.problems(), "5 problems")
        self.assertEqual(pg.locator("#node-list .export-dcf").count(), 0)
        # The export is on the node page and in the Export menu.
        self.assertTrue(pg.is_visible('button[data-export-dcf="2"]'))
        self.assertFalse(pg.is_disabled("#btn-export-node"))
        pg.click('button[data-view="bus"]')
        self.assertTrue(pg.is_disabled("#btn-export-node"))

    def test_failed_export_keeps_the_count(self):
        pg = self.page
        self.open()
        pg.wait_for_selector("#problem-count:has-text('5 problems')")
        downloads = []
        pg.on("download", lambda d: downloads.append(d))
        for menu, button, text in (("export", "#btn-export-all", "DCF export stopped"), ("export", "#btn-export-dbc", "DBC export stopped"),
                                   ("export", "#btn-export-html", "Documentation export stopped")):
            pg.evaluate("() => { document.querySelector('#menu-export').open = true; }")
            pg.click(button)
            pg.wait_for_selector("#banner.error:has-text('%s')" % text)
            self.assertEqual(pg.get_attribute("#banner", "role"), "alert")
            self.assertNotIn("8 problems", self.problems())
            self.assertTrue(pg.is_disabled("#btn-save"))
            self.assertIn("in Problems", pg.get_attribute("#btn-save", "title"))
            self.assertNotIn("error", pg.inner_text("#btn-save"))
        self.assertEqual(downloads, [])
        self.node(0)
        pg.wait_for_selector("#problem-count:has-text('5 problems')")

    # -- 1.3 no "null" anywhere ----------------------------------------------
    def test_no_null_text_on_any_view(self):
        pg = self.page
        self.cfg["nodes"][1]["axis"] = {"cyclic": True}
        self.write_config({"token_verifier": diag.token_verifier(TOKEN), "allow_changes": True})
        with FakePlugin(allow_changes=True) as fp:
            self.remember(fp.runtime)
            self.open()
            for view in ("bus", "declarations", "online", "scan", "trace", "framelab", "simulation"):
                pg.click('button[data-view="%s"]' % view)
                pg.wait_for_timeout(600)
                if view == "online":
                    pg.wait_for_selector("text=changes allowed")
                    pg.click('tr[data-online-node="2"]')
                    pg.wait_for_selector('button[data-online="write"]')
                self.assertEqual(pg.evaluate(TEXT_NODES), [], view)
            for k in range(3):
                self.node(k)
                self.assertEqual(pg.evaluate(TEXT_NODES), [], "node %d" % k)

    # -- 1.4 commissioning shows no config -----------------------------------
    def test_commission_mode_hides_the_config(self):
        pg = self.page
        pg.goto(self.server.url)
        pg.click("#start-commission")
        pg.wait_for_selector("#editor:not([hidden])")
        pg.wait_for_selector('button[data-view="online"].active')
        self.assertTrue(pg.is_hidden("#menu-project"))
        self.assertTrue(pg.is_hidden("#menu-export"))
        self.assertTrue(pg.is_hidden("#btn-save"))
        self.assertTrue(pg.is_hidden("#btn-reload"))
        self.assertTrue(pg.is_visible("#btn-close"))
        self.assertTrue(pg.is_hidden("#problems"))
        self.assertTrue(pg.is_hidden("#node-list"))
        self.assertTrue(pg.is_hidden('button[data-view="bus"]'))
        self.assertTrue(pg.is_hidden('button[data-view="declarations"]'))
        self.assertTrue(pg.is_hidden('button[data-view="simulation"]'))
        shown = [b.text_content().strip() for b in pg.query_selector_all("#side .nav-item") if b.is_visible()]
        self.assertEqual(shown, ["Online", "Scan the bus", "Trace", "Frame lab"])
        self.assertNotIn("nodes", pg.inner_text("#side"))
        audit(pg, "commissioning")
        pg.click("#btn-close")
        pg.wait_for_selector("#start:not([hidden])")

    # -- 2.1 safe dialog defaults --------------------------------------------
    def test_remove_node_dialog_defaults_to_keep(self):
        pg = self.page
        self.open()
        self.node(2)
        pg.click('button[data-remove-node="2"]')
        pg.wait_for_selector("#modal[open]")
        labels = [b.text_content().strip() for b in pg.query_selector_all("#modal-buttons button")]
        self.assertEqual(labels, ["Keep the node", "Remove node"])
        self.assertEqual(self.active(), "Keep the node")
        self.assertIn("danger", pg.get_attribute('#modal-buttons button[data-value="remove"]', "class"))
        pg.keyboard.press("Enter")
        pg.wait_for_selector("#modal[open]", state="hidden")
        self.assertEqual(pg.locator('#node-list [data-node]').count(), 3)
        pg.click('button[data-remove-node="2"]')
        pg.wait_for_selector("#modal[open]")
        pg.keyboard.press("Escape")
        pg.wait_for_selector("#modal[open]", state="hidden")
        self.assertEqual(pg.locator('#node-list [data-node]').count(), 3)
        # Close with unsaved changes: Cancel focused, "Close without saving" last.
        self.fill_path("nodes[2].name", "rtd2")
        pg.click("#btn-close")
        pg.wait_for_selector("#modal[open]")
        labels = [b.text_content().strip() for b in pg.query_selector_all("#modal-buttons button")]
        self.assertEqual(labels, ["Cancel", "Close without saving"])
        self.assertEqual(self.active(), "Cancel")
        pg.keyboard.press("Enter")
        pg.wait_for_selector("#modal[open]", state="hidden")
        self.assertTrue(pg.is_visible("#editor"))

    # -- 2.2 undo -------------------------------------------------------------
    def test_undo_restores_a_removed_entry(self):
        pg = self.page
        self.open()
        self.node(2)
        path = "nodes[2].tx_pdos[0].entries[0]"
        self.assertEqual(pg.input_value('input[data-path="%s.iec_location"]' % path), "%IW320")
        pg.click('tr[data-path="%s"] button[title="Remove"]' % path)
        pg.wait_for_selector("#banner [data-removed]:has-text('Removed')")
        self.assertIn("from TPDO 1", pg.inner_text("#banner"))
        self.assertNotEqual(pg.input_value('input[data-path="%s.iec_location"]' % path), "%IW320")
        pg.click("#banner button[data-undo]")
        pg.wait_for_selector('input[data-path="%s.iec_location"]' % path)
        self.assertEqual(pg.input_value('input[data-path="%s.iec_location"]' % path), "%IW320")
        self.assertEqual(pg.input_value('input[data-path="nodes[2].tx_pdos[0].timeout_ms"]'), "500")
        self.assertTrue(pg.is_hidden("#banner"))

    def test_undo_typing_and_reload(self):
        pg = self.page
        self.open()
        self.node(2)
        self.assertEqual(pg.input_value('input[data-path="nodes[2].name"]'), "rtd")
        self.fill_path("nodes[2].name", "rtd2")
        pg.wait_for_selector('#node-list [data-node="2"]:has-text("rtd2")')  # the side bar follows the field
        pg.click('button[data-view="bus"]')
        pg.wait_for_selector("#btn-save:has-text('Save')")  # the config's errors keep it disabled
        self.assertIn("errors in Problems", pg.get_attribute("#btn-save", "title"))
        pg.keyboard.press("Control+z")
        pg.wait_for_selector('#node-list [data-node="2"]:has-text("5 rtd")')
        self.assertEqual(pg.input_value('input[data-path="nodes[2].name"]'), "rtd")
        self.assertEqual(pg.inner_text("#btn-save"), "Saved")
        self.assertTrue(pg.is_disabled("#btn-save"))
        pg.keyboard.press("Control+Shift+z")
        pg.wait_for_selector('#node-list [data-node="2"]:has-text("rtd2")')
        self.assertEqual(pg.inner_text("#btn-save"), "Save")
        self.assertEqual(pg.evaluate("() => S.view"), "bus")  # redo returns to where the edit was made
        # A typed value is one step while the field has focus.
        self.node(2)
        pg.focus('input[data-path="nodes[2].name"]')
        pg.keyboard.press("Control+z")
        pg.wait_for_selector('#node-list [data-node="2"]:has-text("5 rtd")')
        # Reload from disk empties the history.
        pg.keyboard.press("Control+Shift+z")
        pg.wait_for_selector('#node-list [data-node="2"]:has-text("rtd2")')
        pg.click("#btn-reload")
        pg.click('#modal-buttons button[data-value="reload"]')
        pg.wait_for_selector('#node-list [data-node="2"]:has-text("5 rtd")')
        pg.keyboard.press("Control+Shift+z")
        pg.wait_for_timeout(300)
        self.assertEqual(pg.inner_text('#node-list [data-node="2"]').split("\n")[0].strip(), "5 rtd")
        self.assertEqual(pg.inner_text("#btn-save"), "Saved")

    # -- 2.3 pre-operational asks; 5.3 stale values ---------------------------
    def test_preoperational_asks_and_values_go_stale(self):
        pg = self.page
        with FakePlugin(allow_changes=True) as fp:
            self.online(fp, allow=True)
            pg.wait_for_selector("text=changes allowed")
            self.assertEqual(pg.get_attribute("#online-conn", "aria-live"), "polite")
            pg.click('tr[data-online-node="2"]')
            pg.wait_for_selector('button[data-nmt="preop"]')
            pg.click('button[data-nmt="preop"]')
            pg.wait_for_selector("#modal[open]")
            self.assertIn("PDOs stop", pg.inner_text("#modal-text"))
            self.assertEqual(self.active(), "Cancel")
            pg.keyboard.press("Enter")
            pg.wait_for_selector("#modal[open]", state="hidden")
            pg.wait_for_timeout(300)
            self.assertEqual([q for q in fp.requests if q["op"] == "nmt"], [])
            pg.click('button[data-nmt="preop"]')
            pg.click('#modal-buttons button[data-value="go"]')
            pg.wait_for_selector("#banner:has-text('Pre-operational sent')")
            # The runtime stops answering: values grey out with their age.
            fp.outage()
            pg.wait_for_selector("#online-conn:has-text('Not connected')", timeout=8000)
            pg.wait_for_selector("#online-live.stale")
            pg.wait_for_selector("[data-online=stale-age]:has-text('Last data')")
            self.assertTrue(pg.is_visible('tr[data-online-node="2"]'))
            pg.wait_for_function("() => /Last data [1-9]\\d* s ago/.test(document.querySelector('[data-online=stale-age]').textContent)", timeout=8000)
            fp.restart()
            pg.wait_for_selector("#online-conn:has-text('Connected to')", timeout=8000)
            pg.wait_for_selector("#online-live:not(.stale)")

    # -- 3.1 / 3.2 / 3.3 keyboard and announcements ---------------------------
    def test_lists_and_tabs_by_keyboard(self):
        pg = self.page
        with FakePlugin(allow_changes=True) as fp:
            self.online(fp, allow=True)
            pg.wait_for_selector("text=changes allowed")
            pg.click('button[data-view="bus"]')
            pg.wait_for_selector("#problem-count:has-text('5 problems')")
            self.assertEqual(pg.get_attribute("#problem-count", "aria-live"), "polite")
            # Tab from Save reaches every node, Enter opens it.
            pg.focus("#btn-save")
            seen = []
            for _ in range(12):
                pg.keyboard.press("Tab")
                node = pg.evaluate("() => document.activeElement.dataset.node")
                if node is not None:
                    seen.append(node)
                    if len(seen) == 3:
                        break
            self.assertEqual(seen, ["0", "1", "2"])
            pg.keyboard.press("Enter")
            pg.wait_for_selector('#view h2:has-text("Node 5 rtd")')
            # Problems: Enter on the first one focuses its field.
            pg.focus("#problem-list li button >> nth=0")
            pg.wait_for_function("() => document.body.dataset.checking === '0'")
            pg.wait_for_timeout(300)
            self.assertEqual(pg.evaluate("() => document.activeElement.closest('#problem-list') !== null"), True)
            pg.keyboard.press("Enter")
            pg.wait_for_function("() => (document.activeElement.dataset.path || '').startsWith('nodes[')")
            self.assertEqual(pg.get_attribute("#problems", "aria-label"), "Problems")
            # Online rows: Tab to a row, Enter opens the node.
            pg.click('button[data-view="online"]')
            pg.wait_for_selector("text=changes allowed")
            pg.focus('tr[data-online-node="2"]')
            self.assertEqual(pg.get_attribute('tr[data-online-node="2"]', "role"), "button")
            pg.keyboard.press("Enter")
            pg.wait_for_selector('button[data-online="write"]')
            # Node tabs: Right moves to the object dictionary.
            pg.focus('button[data-online-tab="overview"]')
            pg.keyboard.press("ArrowRight")
            pg.wait_for_selector('details[data-od-group="communication"]')
            self.assertEqual(pg.get_attribute('button[data-online-tab="od"]', "aria-selected"), "true")
            self.assertEqual(pg.get_attribute("#online-node-panel", "role"), "tabpanel")
            pg.keyboard.press("Home")
            pg.wait_for_selector('button[data-nmt="start"]')
            # Scan rows and the progress line.
            pg.click('button[data-view="scan"]')
            pg.click('button[data-online="scan"]')
            pg.wait_for_selector("tr[data-scan-node]")
            self.assertEqual(pg.get_attribute("[data-online=scan-progress]", "aria-live"), "polite")
        # Trace tabs: Right from Frames selects Identifiers; axe finds no aria-pressed on a tab.
        path = os.path.join(self.dir, "sample.log")
        with open(path, "wb") as f:
            f.write(written(sample_trace(), formats.format_of(path)))
        pg.click('button[data-view="trace"]')
        pg.wait_for_selector("#trace-source:not(:has-text('Loading'))")
        pg.set_input_files('input[data-trace="open-input"]', path)
        pg.wait_for_selector("#trace-rows .trace-row")
        pg.focus('button[data-trace-tab="frames"]')
        pg.keyboard.press("ArrowRight")
        pg.wait_for_selector("#trace-ids")
        self.assertEqual(pg.get_attribute('button[data-trace-tab="ids"]', "aria-selected"), "true")
        self.assertEqual(pg.locator('[role=tab][aria-pressed]').count(), 0)
        pg.keyboard.press("Home")
        pg.wait_for_selector("#trace-rows .trace-row")
        # Home, End, Page Down and Page Up in the frame list.
        pg.click("#trace-rows .trace-row >> nth=0")
        pg.keyboard.press("End")
        pg.wait_for_function("() => { const r = document.querySelectorAll('#trace-rows .trace-row'); return r.length && r[r.length - 1].classList.contains('selected'); }")
        pg.keyboard.press("Home")
        pg.wait_for_function("() => document.querySelector('#trace-rows .trace-row').classList.contains('selected')")
        pg.keyboard.press("PageDown")
        pg.wait_for_function("() => !document.querySelector('#trace-rows .trace-row').classList.contains('selected')")
        pg.keyboard.press("PageUp")
        pg.wait_for_function("() => document.querySelector('#trace-rows .trace-row').classList.contains('selected')")
        audit(pg, "trace with a file")
        # The decoding note uses the Problems pane's words, without a path.
        note = pg.inner_text("[data-trace=warning]")
        self.assertTrue(note.startswith("Decoding without the config's PDOs: "), note)
        self.assertIn("Node 5 rtd, TPDO 2, 0x6150:1: type UNSIGNED8 (8 bit) does not fit location %IW320 (16 bit)", note)
        self.assertNotIn(self.dir, note)
        self.assertNotIn("nodes[", note)
        # Simulation rows are buttons too.
        pg.click('button[data-view="simulation"]')
        pg.wait_for_selector("#sim-body")
        self.assertEqual(pg.get_attribute("#sim-body", "role"), "tabpanel")

    # -- fix-gui-test-findings: keyboard reach and focus return -------------
    def test_keyboard_walk(self):
        pg = self.page
        self.open()
        pg.click("#btn-close")
        pg.wait_for_selector("#start:not([hidden])")
        # Folder entries and Recent are buttons in the Tab order; Enter on Recent opens it.
        pg.wait_for_function("() => S.browserPath !== null")  # the home folder's listing is in
        pg.fill("#browser-path", self.dir)
        pg.click("#browser-go")
        pg.wait_for_selector("#browser-list button.folder:has-text('rtd-monitor')")
        pg.focus("#browser-list li:last-child button")
        pg.keyboard.press("Tab")
        self.assertEqual(pg.evaluate("() => document.activeElement.closest('#recent') !== null"), True)
        self.assertIn(self.project, pg.evaluate("() => document.activeElement.textContent"))
        # ↑ reaching "/" is disabled: the focus moves to the path field.
        pg.fill("#browser-path", os.path.dirname(self.dir))
        pg.click("#browser-go")
        pg.wait_for_function("(p) => document.querySelector('#browser-path').value === p", arg=os.path.dirname(self.dir))
        for _ in range(12):
            if pg.is_disabled("#browser-up"):
                break
            pg.focus("#browser-up")
            pg.keyboard.press("Enter")
            pg.wait_for_timeout(150)
        self.assertEqual(pg.input_value("#browser-path"), "/")
        self.assertEqual(self.active(), "browser-path")
        pg.focus("#recent button.folder")
        pg.keyboard.press("Enter")
        pg.wait_for_selector("#editor:not([hidden])")
        # Enter and Space on a node keep the focus on it.
        pg.focus('#node-list [data-node="1"]')
        pg.keyboard.press("Enter")
        pg.wait_for_selector('#view h2:has-text("Node 23")')
        self.assertEqual(pg.evaluate("() => document.activeElement.dataset.node"), "1")
        pg.keyboard.press("Tab")
        pg.keyboard.press("Space")
        pg.wait_for_selector('#view h2:has-text("Node 5")')
        self.assertEqual(pg.evaluate("() => document.activeElement.dataset.node"), "2")
        # Tab from the last node reaches "Add node from EDS…"; Enter opens the file picker.
        pg.keyboard.press("Tab")
        self.assertEqual(self.active(), "eds-input")
        with pg.expect_file_chooser() as fc:
            pg.keyboard.press("Space")
        fc.value.set_files(os.path.join(RTD, "rtd8.eds"))
        pg.wait_for_selector('#node-list [data-node="3"]')
        # Startup SDO writes: ↓ and ↑ keep the focus with the moved write; Add focuses its value.
        self.node(2)
        first = pg.inner_text('#view tr[data-path="nodes[2].sdo[0]"] > td >> nth=0')
        pg.focus('tr[data-path="nodes[2].sdo[0]"] button[title="Down"]')
        pg.keyboard.press("Enter")
        self.assertEqual(pg.inner_text('#view tr[data-path="nodes[2].sdo[1]"] > td >> nth=0'), first)
        self.assertEqual(pg.evaluate("() => [document.activeElement.closest('tr').dataset.path, document.activeElement.title]"),
                         ["nodes[2].sdo[1]", "Down"])
        pg.keyboard.press("Shift+Tab")
        pg.keyboard.press("Enter")  # ↑ to the top: its ↑ is disabled, so the focus is on its ↓
        self.assertEqual(pg.inner_text('#view tr[data-path="nodes[2].sdo[0]"] > td >> nth=0'), first)
        self.assertEqual(pg.evaluate("() => [document.activeElement.closest('tr').dataset.path, document.activeElement.title]"),
                         ["nodes[2].sdo[0]", "Down"])
        count = pg.locator('#view tr[data-path^="nodes[2].sdo["]').count()
        pg.click('details[data-section="sdo"] button[data-sdo] >> nth=0')
        self.assertEqual(self.active(), "nodes[2].sdo[%d].value" % count)
        # Menus close when the focus leaves them, and on Escape from outside.
        pg.focus("#menu-export > summary")
        pg.keyboard.press("Enter")
        pg.wait_for_selector("#menu-export[open]")
        for _ in range(8):
            pg.keyboard.press("Tab")
            if pg.evaluate("() => !document.querySelector('#menu-export').contains(document.activeElement)"):
                break
        pg.wait_for_selector("#menu-export:not([open])")
        pg.evaluate("() => { document.querySelector('#menu-export').open = true; }")
        pg.keyboard.press("Escape")
        pg.wait_for_selector("#menu-export:not([open])")

    # -- fix-gui-test-findings: exports ---------------------------------------
    def test_export_running_state_and_repeated_failures(self):
        pg = self.page
        self.open()
        pg.wait_for_selector("#problem-count:has-text('5 problems')")
        # Slow exports, and a DBC export that fails with a new finding each time.
        pg.evaluate("""() => {
          const f = window.fetch;
          let n = 0;
          window.fetch = (u, o) => {
            if (!String(u).includes('/api/export_')) return f(u, o);
            const r = String(u).endsWith('/api/export_dbc')
              ? Promise.resolve(new Response(JSON.stringify({ items: [{ level: 'error', message: 'DBC finding ' + (++n), paths: [] }], errors: 1 }),
                  { headers: { 'Content-Type': 'application/json' } }))
              : f(u, o);
            return new Promise((done) => setTimeout(() => done(r), 700));
          };
        }""")
        for k in range(3):
            pg.evaluate("() => { document.querySelector('#menu-export').open = true; }")
            pg.click("#btn-export-dbc")
            pg.wait_for_selector("#menu-export > summary:has-text('Exporting…')")
            self.assertEqual(pg.get_attribute("#menu-export > summary", "aria-busy"), "true")
            pg.wait_for_selector("#banner.error:has-text('DBC export stopped')")
            pg.wait_for_selector("#menu-export > summary:text-is('Export')")
            texts = pg.eval_on_selector_all("#problem-list li", "ls => ls.map((l) => l.textContent)")
            self.assertEqual([t for t in texts if "DBC finding" in t], ["DBC finding %d" % (k + 1)], texts)
            self.assertEqual(self.problems(), "6 problems")
        # A failing DCF export replaces the DBC export's finding too.
        pg.evaluate("() => { document.querySelector('#menu-export').open = true; }")
        pg.click("#btn-export-all")
        pg.wait_for_selector("#banner.error:has-text('DCF export stopped')")
        self.assertNotIn("DBC finding", pg.inner_text("#problem-list"))

    # -- 4.2 node page sections ----------------------------------------------
    def test_node_page_sections(self):
        pg = self.page
        self.open()
        pg.click('#node-list [data-node="2"]')
        pg.wait_for_selector(".section-index")
        labels = pg.eval_on_selector_all(".section-index a", "as => as.map(a => a.textContent)")
        self.assertEqual(labels, ["Node", "Supervision", "Emergency", "Axis", "Advanced", "Inputs", "Outputs", "Startup SDO writes", "SDO variables"])
        # Node 5 has startup SDO writes: that section is open with its count.
        self.assertEqual(pg.get_attribute('details[data-section="sdo"]', "open"), "")
        self.assertRegex(pg.inner_text('details[data-section="sdo"] > summary'), r"\d+ entr")
        pg.click('.section-index a[data-section="sec-vars"]')
        pg.wait_for_function("() => document.querySelector('.section-index a[data-section=\"sec-vars\"]').getAttribute('aria-current') === 'true'")
        pg.wait_for_function("() => document.querySelector('#sec-vars').getBoundingClientRect().top < 200")
        # Node 23 has none: both sections are folded, with "none" and an add action on the summary line.
        pg.click('#node-list [data-node="1"]')
        pg.wait_for_selector('#view h2:has-text("Node 23")')
        for key in ("sdo", "sdo_variables"):
            d = pg.locator('details[data-section="%s"]' % key)
            self.assertIsNone(d.get_attribute("open"))
            self.assertIn("none", d.locator("summary").inner_text())
            self.assertTrue(pg.is_visible('button[data-section-add="%s"]' % key))
            self.assertEqual(d.locator("summary button").count(), 0)
        # The summary's Add opens the section on its picker.
        pg.click('button[data-section-add="sdo"]')
        pg.wait_for_selector('details[data-section="sdo"][open]')
        self.assertEqual(self.active(), "")  # the filter field, which has no data-path and no id
        self.assertEqual(pg.evaluate("() => document.activeElement.getAttribute('aria-label')"), "Filter SDO objects")
        # Node 0 (pingpong) has SDO variables: its section opens by itself.
        pg.click('#node-list [data-node="0"]')
        pg.wait_for_selector('details[data-section="sdo_variables"][open]')
        self.assertIn("2 entries", pg.inner_text('details[data-section="sdo_variables"] summary'))
        # "Add entry…" on a PDO adds to that PDO, listing only that direction.
        pg.click('button[data-add-entry="nodes[0].tx_pdos[0]"]')
        pg.wait_for_selector('details[data-picker="input"][open]')
        self.assertIn("Adding to TPDO 1", pg.inner_text('[data-picker-target="input"]'))
        self.assertEqual(pg.locator('details[data-picker="input"] button[data-add="0x6200:1"]').count(), 0)
        pg.click('details[data-picker="input"] button[data-add="0x1001:0"]')
        pg.wait_for_selector('tr[data-path="nodes[0].tx_pdos[0].entries[1]"]')
        self.assertEqual(pg.inner_text('tr[data-path="nodes[0].tx_pdos[0].entries[1]"] td >> nth=0'), "0x1001:0")
        self.assertRegex(pg.input_value('input[data-path="nodes[0].tx_pdos[0].entries[1].iec_location"]'), r"^%I")
        self.assertEqual(pg.locator("text=Map an object").count(), 0)

    # -- 4.3 the side bar and the focus --------------------------------------
    def test_add_node_focuses_its_name(self):
        pg = self.page
        self.open()
        pg.set_input_files("#eds-input", os.path.join(RTD, "rtd8.eds"))
        pg.wait_for_selector('#view h2:has-text("Node 3 rtd8")')  # the first free ID after the master's
        self.assertEqual(self.active(), "nodes[3].name")
        pg.keyboard.type("x")
        pg.wait_for_selector('#node-list [data-node="3"]:has-text("rtd8x")')

    # -- 5.1 wording ----------------------------------------------------------
    def test_empty_config_wording(self):
        pg = self.page
        folder = os.path.join(self.dir, "empty")
        os.makedirs(folder)
        pg.goto(self.server.url)
        pg.click("#start-new")
        pg.fill("#browser-path", folder)
        pg.click("#browser-open")
        pg.wait_for_selector("#problem-list li")
        self.assertEqual(pg.inner_text("#problem-list").strip(), NO_NODES)
        self.assertEqual(pg.inner_text("#problem-count"), "1 problem")
        self.assertNotIn(self.dir, pg.inner_text("#problems") + pg.inner_text("#view"))
        self.assertEqual(pg.inner_text("#btn-save"), "Saved")

    # -- 5.2 busy states ------------------------------------------------------
    def test_double_click_on_save_saves_once(self):
        pg = self.page
        self.cfg["nodes"] = self.cfg["nodes"][:1]
        self.write_config()
        self.open()
        self.node(0)
        self.fill_path("nodes[0].name", "pong")
        pg.wait_for_function("() => document.body.dataset.checking === '0'")
        pg.evaluate("""() => {
          window.saves = 0;
          const f = window.fetch;
          window.fetch = (u, o) => {
            if (String(u).endsWith('/api/save')) { window.saves++; return new Promise((r) => setTimeout(() => r(f(u, o)), 700)); }
            return f(u, o);
          };
        }""")
        pg.evaluate("() => { const b = document.querySelector('#btn-save'); b.click(); b.click(); }")
        pg.wait_for_selector("#btn-save:has-text('Saving…')")
        self.assertTrue(pg.is_disabled("#btn-save"))
        pg.wait_for_selector("#banner:has-text('Saved')")
        self.assertEqual(pg.evaluate("() => window.saves"), 1)
        self.assertEqual(pg.inner_text("#btn-save"), "Saved")
        self.assertEqual(load(self.config_path)["nodes"][0]["name"], "pong")

    # -- 5.4 labels -----------------------------------------------------------
    def test_old_labels_are_gone(self):
        pg = self.page
        self.open()
        pg.click('button[data-view="trace"]')
        pg.wait_for_selector("#trace-source:not(:has-text('Loading'))")
        self.assertEqual(pg.inner_text("[data-trace=save]"), "Save to traces folder")
        self.assertEqual(pg.inner_text("[data-trace=export]"), "Download")
        self.assertEqual(pg.get_attribute("[data-trace=save-format]", "aria-label"), "Format of the saved file")
        self.assertEqual(pg.get_attribute("[data-trace=export-format]", "aria-label"), "Format of the downloaded file")
        pg.click('button[data-view="framelab"]')
        pg.evaluate("() => document.querySelectorAll('details.fx-lab-section').forEach((d) => { d.open = true; })")
        pg.wait_for_selector("[data-fx-arb=go]")
        self.assertEqual(pg.inner_text("[data-fx-arb=go]"), "Run both")
        self.assertEqual(pg.locator("text=Send both").count(), 0)
        pg.fill("[data-fx=lab-frame]", "701#00")
        pg.keyboard.press("Enter")
        pg.wait_for_selector("[data-fx=box]")
        self.assertEqual(pg.get_attribute("[data-fx=box]", "aria-label"), "Selected field")


class CleanProject(OnlineBase):
    """The ping-pong project without problems: every export downloads."""

    def test_every_export_from_the_menu(self):
        pg = self.page
        self.open()
        pg.wait_for_function("() => document.body.dataset.checking === '0'")
        names = []
        for button in ("#btn-export-all", "#btn-export-dbc", "#btn-export-html"):
            pg.evaluate("() => { document.querySelector('#menu-export').open = true; }")
            with pg.expect_download() as dl:
                pg.click(button)
            names.append(dl.value.suggested_filename)
            pg.wait_for_function("() => !document.querySelector('#menu-export').open")  # a pick closes the menu
        self.assertEqual(names, ["rtd-monitor_dcf.zip", "rtd-monitor.dbc", "rtd-monitor.html"])
        pg.click('#node-list [data-node="0"]')
        pg.evaluate("() => { document.querySelector('#menu-export').open = true; }")
        with pg.expect_download() as dl:
            pg.click("#btn-export-node")
        self.assertEqual(dl.value.suggested_filename, "node_2.dcf")
        # The menu by keyboard: Enter opens, Down moves, Escape closes.
        pg.focus("#menu-export > summary")
        pg.keyboard.press("Enter")
        pg.wait_for_selector("#menu-export[open]")
        pg.keyboard.press("ArrowDown")
        self.assertEqual(pg.evaluate("() => document.activeElement.id"), "btn-export-all")
        pg.keyboard.press("ArrowDown")
        self.assertEqual(pg.evaluate("() => document.activeElement.id"), "btn-export-node")
        pg.keyboard.press("Escape")
        pg.wait_for_selector("#menu-export:not([open])")
        self.assertEqual(pg.evaluate("() => document.activeElement.tagName"), "SUMMARY")
        # One menu at a time (standalone mode has both).
        pg.evaluate("() => { document.querySelector('#menu-export').open = true; }")
        pg.click("#view")
        pg.wait_for_selector("#menu-export:not([open])")

    def test_trace_clear_and_close_ask(self):
        pg = self.page
        with FakePlugin(allow_changes=True) as fp:
            self.online(fp, allow=True)
            pg.click('button[data-view="trace"]')
            pg.wait_for_selector("#trace-source:not(:has-text('Loading'))")
            pg.click("[data-trace=start]")
            pg.wait_for_selector("#trace-source:has-text('recording')")
            now = int(time.time() * 1e6)
            fp.push([Frame(now + i * 1000, 0x182, bytes([i, 0, 0, 0])) for i in range(30)])
            pg.wait_for_selector("#trace-rows .trace-row")
            pg.click("[data-trace=stop]")
            pg.wait_for_selector("[data-trace=start]:not([disabled])")
            pg.click("[data-trace=clear]")
            pg.wait_for_selector("#modal[open]")
            self.assertIn("lost unless it was saved to the traces folder or downloaded", pg.inner_text("#modal-text"))
            self.assertEqual(pg.evaluate("() => document.activeElement.textContent.trim()"), "Keep the recording")
            pg.keyboard.press("Enter")
            pg.wait_for_selector("#modal[open]", state="hidden")
            self.assertGreater(pg.locator("#trace-rows .trace-row").count(), 0)
            # Closing the folder with an unsaved recording asks first.
            pg.click("#btn-close")
            pg.wait_for_selector("#modal[open]")
            self.assertIn("recording", pg.inner_text("#modal-text"))
            pg.click('#modal-buttons button[data-value="cancel"]')
            pg.wait_for_selector("#modal[open]", state="hidden")
            # Downloaded: no question any more.
            with pg.expect_download():
                pg.click("[data-trace=export]")
            pg.wait_for_selector("#banner:has-text('Downloaded')")
            pg.click("#btn-close")
            pg.wait_for_selector("#start:not([hidden])")

    def test_new_project_dialog_focuses_its_first_field(self):
        pg = self.page
        os.environ["OPENPLC_CLI"] = fake_editor_cli(self.dir)
        self.addCleanup(os.environ.pop, "OPENPLC_CLI", None)
        folder = os.path.join(self.dir, "standalone")
        os.makedirs(folder)
        shutil.copy(os.path.join(PINGPONG, "cpp-slave.eds"), folder)
        shutil.copy(self.config_path, os.path.join(folder, "canworks.json"))
        pg.goto(self.server.url)
        pg.click("#start-standalone")
        pg.fill("#browser-path", folder)
        pg.click("#browser-open")
        pg.wait_for_selector("#menu-project:not([hidden])")
        pg.evaluate("() => { document.querySelector('#menu-project').open = true; }")
        pg.click("#btn-new-project")
        pg.wait_for_selector("#modal[open]")
        self.assertEqual(pg.evaluate("() => document.activeElement.getAttribute('aria-label')"), "Parent folder")
        labels = [b.text_content().strip() for b in pg.query_selector_all("#modal-buttons button")]
        self.assertEqual(labels, ["Cancel", "Create project"])
        pg.keyboard.press("Escape")
        pg.wait_for_selector("#modal[open]", state="hidden")
