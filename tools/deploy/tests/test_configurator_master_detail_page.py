"""Commission with a config as master and detail (commission-master-detail):
a network entry shows the Nodes table, a node entry only the node's page
with its one-line header; last heard from the bridge's status; EMCY 0x0000
clears the diagnosis flag. Against a fake plugin runtime; needs Playwright,
like test_configurator_page.py."""

from .fake_diag import FakePlugin
from .test_configurator_online_page import OnlineBase


class MasterDetail(OnlineBase):
    def node2(self, fp):
        return next(n for n in fp.status["nodes"] if n["node_id"] == 2)

    def test_node_page_alone_and_back(self):
        pg = self.page
        with FakePlugin() as fp:
            self.online(fp)
            pg.wait_for_selector('tr[data-online-node="2"]')
            self.assertIn("0.1 s ago", pg.inner_text('tr[data-online-node="2"]'))
            # A row opens the node's page alone, at the top, with its header.
            pg.click('tr[data-online-node="2"]')
            pg.wait_for_selector('[data-online="node-header"]')
            self.assertFalse(pg.is_visible('[data-online="nodes"]'))
            self.assertFalse(pg.is_visible('button[data-online="scan"]'))
            header = pg.inner_text('[data-online="node-header"]')
            for text in ("← Nodes", "pingpong", "OPERATIONAL", "last heard 0.1 s ago", "booted"):
                self.assertIn(text, header)
            self.assertEqual(pg.evaluate("document.scrollingElement.scrollTop"), 0)
            # The header follows the status.
            self.node2(fp)["last_heard_ms"] = 2500
            pg.wait_for_selector('[data-online="node-heard"]:has-text("2.5 s ago")')
            # The tab stays from node to node; back to the table with the row selected.
            pg.click('button[data-online-tab="od"]')
            pg.click('[data-online="back-to-nodes"]')
            pg.wait_for_selector('[data-online="nodes"]')
            self.assertFalse(pg.is_visible("#online-node"))
            self.assertIn("active", pg.get_attribute('tr[data-online-node="2"]', "class"))
            self.assertEqual(pg.evaluate("document.activeElement.dataset.openNode"), "2")
            # The tree: a node entry opens its page, the network entry the table.
            pg.click('#tree .open-net [data-node="0"] > .tree-row')
            pg.wait_for_selector('button[data-online-tab="od"][aria-selected="true"]')
            self.assertFalse(pg.is_visible('[data-online="nodes"]'))
            pg.click('#tree .open-net > .tree-row')
            pg.wait_for_selector('[data-online="nodes"]')
            self.assertFalse(pg.is_visible("#online-node"))

    def test_emcy_reset_clears_the_flag(self):
        pg = self.page
        with FakePlugin() as fp:
            self.online(fp)
            mark = '#tree .open-net [data-node="0"] .tree-mark'
            pg.wait_for_selector(mark + ".st-op")
            self.node2(fp)["emcy"] = {"code": 0x5000, "error_register": 0x01, "count": 4}
            pg.wait_for_selector(mark + " svg.st-flag:not(.cleared)")
            self.node2(fp)["emcy"] = {"code": 0x0000, "error_register": 0x00, "count": 5}
            pg.wait_for_selector(mark + " svg.st-flag.cleared")
            self.assertIn("error cleared", pg.inner_text('#tree .open-net [data-node="0"] .name .visually-hidden'))
            cell = pg.inner_text('[data-emcy-cleared="2"]')
            self.assertEqual(cell, "cleared (0x0000) (5)")

    def test_emcy_reset_alone_raises_no_flag(self):
        pg = self.page
        with FakePlugin() as fp:
            self.online(fp)
            mark = '#tree .open-net [data-node="0"] .tree-mark'
            pg.wait_for_selector(mark + ".st-op")
            self.node2(fp)["emcy"] = {"code": 0x0000, "error_register": 0x00, "count": 4}
            pg.wait_for_selector('[data-emcy-cleared="2"]')
            pg.wait_for_timeout(300)
            self.assertEqual(pg.locator(mark + " svg.st-flag").count(), 0)
