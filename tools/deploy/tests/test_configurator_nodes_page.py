"""The Commission workspace's Nodes table with a config, against a fake
plugin runtime (commission-workspace tasks 6.1 and 6.3): the scan compared
with the config, its actions as draft edits, the node Status and Log tabs,
live state on the tree and Unlock. Needs Playwright, like
test_configurator_page.py."""

import copy

from .fake_diag import SCAN_RESULT, FakePlugin
from .test_configurator_online_page import OnlineBase, load

# A device the project's own EDS (cpp-slave.eds) matches, not in the config.
MATCHING = {"node_id": 5, "vendor_id": 0x360, "product_code": 0, "revision_number": 0, "serial_number": 0x51,
            "device_type": 0x191, "device_name": "pingpong", "match": "not configured"}


class NodesTable(OnlineBase):
    def scan(self, fp):
        pg = self.page
        pg.click('button[data-online="scan"]')
        # Node 2 is OPERATIONAL: the page asks first, names it, and Cancel is the default.
        pg.wait_for_selector("#modal:has-text('runs node 2 pingpong')")
        self.assertEqual(pg.evaluate("document.activeElement.dataset.value"), "cancel")
        pg.click('#modal button[data-value="scan"]')
        pg.wait_for_selector('[data-nodes="summary"] [data-nodes-filter]', timeout=20000)

    def test_scan_compares_and_add_to_config_with_undo(self):
        pg = self.page
        with FakePlugin(scan_polls=1) as fp:
            fp.force_running = True
            fp.scan_nodes = copy.deepcopy(SCAN_RESULT) + [MATCHING]
            self.online(fp)
            pg.wait_for_selector('tr[data-online-node="2"]')
            # Before a scan the table says what was heard; Scan needs no Allow changes.
            self.assertIn("Heard", pg.inner_text('tr[data-online-node="2"] td[data-compare]'))
            self.assertIn("Scan the bus to compare", pg.inner_text('[data-nodes="summary"]'))
            self.scan(fp)
            self.assertTrue(("scan", None) in fp.forced)
            self.assertEqual(" ".join(pg.inner_text('[data-nodes="summary"]').split()), "1 match · 3 not in config")
            self.assertIn("Match", pg.inner_text('tr[data-online-node="2"] td[data-compare]'))
            for id in (5, 40, 41):
                self.assertIn("Not in config", pg.inner_text('tr[data-not-in-config="%d"]' % id))
            # A summary part filters the table.
            pg.click('[data-nodes-filter="not_in_config"]')
            pg.wait_for_selector('tr[data-online-node="2"]', state="detached")
            pg.click('[data-nodes-filter="all"]')
            pg.wait_for_selector('tr[data-online-node="2"]')
            # Add to config: the matching EDS, the product name and the serial number, unsaved.
            pg.click('tr[data-not-in-config="5"] button[data-nodes-add]')
            pg.wait_for_selector('#banner:has-text("Added node 5")')
            pg.wait_for_selector('tr[data-draft-node="5"]')
            self.assertIn("Match", pg.inner_text('tr[data-draft-node="5"] td[data-compare]'))
            self.assertIn("cpp-slave.eds", pg.inner_text('tr[data-draft-node="5"]'))
            self.assertTrue(pg.is_visible("[data-unsaved]"))
            self.assertEqual(len(load(self.config_path)["nodes"]), 1)
            self.assertIn("Add to config", pg.inner_text('#log-panel [data-online="log"]'))
            # The tree has the new node, in Commission too.
            pg.wait_for_selector('#tree .open-net [data-node="1"]')
            # Undo takes it out again: the device is Not in config once more.
            pg.click('#banner button:has-text("Undo")')
            pg.wait_for_selector('tr[data-not-in-config="5"]')
            self.assertEqual(pg.locator('#tree .open-net [data-node="1"]').count(), 0)

    def test_identity_differs_and_take_serial(self):
        pg = self.page
        self.cfg["nodes"][0]["serial_number"] = 8
        with FakePlugin(scan_polls=1) as fp:
            self.online(fp)
            pg.wait_for_selector('tr[data-online-node="2"]')
            self.scan(fp)
            cell = 'tr[data-online-node="2"] td[data-compare]'
            self.assertIn("Identity differs", pg.inner_text(cell))
            self.assertIn("Serial number", pg.inner_text(cell))
            self.assertIn("1 differs", pg.inner_text('[data-nodes="summary"]'))
            # The tree marks the node too, in words for screen readers.
            mark = '#tree .open-net [data-node="0"] .tree-mark'
            pg.wait_for_selector(mark + ".cmp-identity_differs")
            self.assertIn("identity differs", pg.inner_text('#tree .open-net [data-node="0"] .name .visually-hidden'))
            pg.click('tr[data-online-node="2"] button[data-nodes-serial]')
            pg.wait_for_selector(cell + ':has-text("Match")')
            pg.click('#ws [data-ws="configure"]')
            pg.wait_for_selector("#log-panel", state="hidden")
            pg.click('#ws [data-ws="commission"]')
            pg.wait_for_selector("#log-panel:visible")
            self.assertIn("Take serial number 0x00000007", pg.inner_text('#log-panel [data-online="log"]'))

    def test_scan_cancelled_at_the_force_question(self):
        pg = self.page
        with FakePlugin(scan_polls=1) as fp:
            fp.force_running = True
            self.online(fp)
            pg.wait_for_selector('tr[data-online-node="2"]')
            pg.click('button[data-online="scan"]')
            pg.wait_for_selector("#modal:has-text('Scan anyway?')")
            pg.keyboard.press("Enter")
            pg.wait_for_selector('[data-online="scan-progress"]:has-text("Scan not started")')
            self.assertFalse([r for r in fp.requests if r["op"] == "scan"])

    def test_status_tab_log_tab_and_tree_state(self):
        pg = self.page
        with FakePlugin() as fp:
            self.online(fp)
            pg.click('tr[data-online-node="2"]')
            pg.wait_for_selector('button[data-online-tab="status"][aria-selected="true"]')
            self.assertEqual(pg.evaluate("document.activeElement.dataset.onlineTab"), "status")
            self.assertIn("OPERATIONAL", pg.inner_text('[data-online="node-status"]'))
            # Operational on the tree: shape and text.
            mark = '#tree .open-net [data-node="0"] .tree-mark'
            pg.wait_for_selector(mark + ".st-op")
            self.assertIn("operational", pg.inner_text('#tree .open-net [data-node="0"] .name .visually-hidden'))
            # The node stops answering: the mark, the announcement and the log follow.
            for n in fp.status["nodes"]:
                if n["node_id"] == 2:
                    n["state"] = 0
            pg.wait_for_selector(mark + ".st-unheard")
            pg.wait_for_selector('#tree-live:has-text("2 pingpong, not heard")')
            pg.click('button[data-online-tab="log"]')
            pg.wait_for_selector('[data-online="node-log-list"] li.event:has-text("not answering")')
            self.assertIn("Log 1", pg.inner_text('button[data-online-tab="log"]'))
            # The bottom panel's Log filters by kind.
            pg.click('#log-panel [data-log-filter="changes"]')
            self.assertNotIn("not answering", pg.inner_text('#log-panel [data-online="log"]'))
            pg.click('#log-panel [data-log-filter="events"]')
            self.assertIn("not answering", pg.inner_text('#log-panel [data-online="log"]'))

    def test_unlock_on_a_runtime_explains_where(self):
        pg = self.page
        with FakePlugin() as fp:
            self.online(fp)
            pg.click('tr[data-online-node="2"]')
            pg.wait_for_selector('[data-online="no-changes"]:has-text("Locked.")')
            pg.click('[data-online="no-changes"] button[data-unlock]')
            pg.wait_for_selector("#modal:has-text('Online access')")
            pg.click('#modal button[data-value="ok"]')
            self.assertEqual(pg.evaluate("document.activeElement.dataset.unlock !== undefined"), True)
            self.assertFalse(any(r["op"] == "nmt" for r in fp.requests))


class NodesAudit(OnlineBase):
    """axe-core and the layout check on the Nodes table, the comparison and
    the Status and Log tabs, and the keyboard path (commission-workspace 6.5)."""

    def test_audit_layout_and_keyboard(self):
        from .test_configurator_layout import FIT_CHECK, audit
        pg = self.page
        self.cfg["nodes"][0]["serial_number"] = 8  # Identity differs, with its field
        with FakePlugin(scan_polls=1) as fp:
            fp.scan_nodes = copy.deepcopy(SCAN_RESULT) + [MATCHING]
            self.online(fp)
            pg.wait_for_selector('tr[data-online-node="2"]')
            pg.click('button[data-online="scan"]')
            pg.click('#modal button[data-value="scan"]')
            pg.wait_for_selector('[data-nodes="summary"] [data-nodes-filter]', timeout=20000)
            for width in (1000, 1280, 1440):
                pg.set_viewport_size({"width": width, "height": 800})
                pg.wait_for_timeout(200)
                self.assertEqual(pg.evaluate(FIT_CHECK), [], "Nodes table at %d px" % width)
            for theme in ("light", "dark"):
                pg.evaluate("(t) => { document.documentElement.dataset.theme = t; }", theme)
                audit(pg, "Nodes table and comparison, %s" % theme)
            # Keyboard only: the node ID button opens the node, focus lands on the Status tab.
            pg.focus('tr[data-online-node="2"] button[data-open-node="2"]')
            pg.keyboard.press("Enter")
            pg.wait_for_selector('button[data-online-tab="status"][aria-selected="true"]')
            self.assertEqual(pg.evaluate("document.activeElement.dataset.onlineTab"), "status")
            pg.keyboard.press("End")
            pg.wait_for_selector('button[data-online-tab="log"][aria-selected="true"]')
            for theme in ("light", "dark"):
                pg.evaluate("(t) => { document.documentElement.dataset.theme = t; }", theme)
                audit(pg, "Log tab, %s" % theme)
            pg.keyboard.press("Home")
            pg.wait_for_selector('[data-online="node-status"]')
            for theme in ("light", "dark"):
                pg.evaluate("(t) => { document.documentElement.dataset.theme = t; }", theme)
                audit(pg, "Status tab, %s" % theme)
            for width in (1000, 1440):
                pg.set_viewport_size({"width": width, "height": 800})
                pg.wait_for_timeout(200)
                self.assertEqual(pg.evaluate(FIT_CHECK), [], "Status tab at %d px" % width)
            # Unlock on a runtime from the keyboard: the note, then focus back on Unlock….
            pg.focus('[data-online="no-changes"] button[data-unlock]')
            pg.keyboard.press("Enter")
            pg.wait_for_selector("#modal:has-text('Online access')")
            pg.keyboard.press("Enter")
            pg.wait_for_function("() => document.activeElement.dataset.unlock === 'no-changes'")
