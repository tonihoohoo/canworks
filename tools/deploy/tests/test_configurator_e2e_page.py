"""One browser run through the whole configurator, with the keyboard, against
the fake plugin and the virtual example (polish-configurator-ux 7.1): every
view from the start page, a PDO entry removed and undone, every export from
the Export menu with its download, the runtime going away and coming back,
and the same walk in the dark theme, with the accessibility audit after each
view. Needs Playwright, like test_configurator_page.py."""
import json
import os
import shutil

from canworks import diag

from .fake_diag import TOKEN, FakePlugin
from .helpers import REPO
from .test_configurator_layout import FIT_CHECK, audit
from .test_configurator_online_page import OnlineBase

VIRTUAL = os.path.join(REPO, "examples", "virtual-plant")
NETWORKS = [{"name": "io", "interface": "sim0", "bitrate": 250000, "master_node_id": 1},
            {"name": "motion", "interface": "sim1", "bitrate": 500000, "master_node_id": 1}]
VIEWS = ["bus", "declarations", "online", "trace", "framelab", "simulation"]


class EndToEnd(OnlineBase):
    def setUp(self):
        super().setUp()
        # The virtual example as the project, with online access for the fake plugin.
        shutil.rmtree(self.project)
        shutil.copytree(VIRTUAL, self.project)
        with open(self.config_path, encoding="utf-8") as f:
            self.cfg = json.load(f)
        self.cfg["diagnostics"] = {"token_verifier": diag.token_verifier(TOKEN), "allow_changes": True}
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(self.cfg, f, indent=2)
        self.page.set_viewport_size({"width": 1280, "height": 800})
        self.report = []

    def write_config(self, diagnostics=None):
        pass  # the example's own file, written in setUp

    # -- keyboard helpers --------------------------------------------------
    def active(self, what):
        return self.page.evaluate("(w) => { const a = document.activeElement; return w === 'id' ? a.id : w === 'tag' ? a.tagName : a.dataset[w]; }", what)

    def top(self):
        """Puts the focus on the header's first action, so the next Tabs
        walk the header, then the network tree, then the page."""
        self.page.focus("#btn-reload")

    def tab_to(self, selector, limit=120):
        """Tabs until the focused element matches `selector`."""
        pg = self.page
        for _ in range(limit):
            if pg.evaluate("(s) => document.activeElement.matches(s)", selector):
                return
            pg.keyboard.press("Tab")
        self.fail("Tab never reached %s" % selector)

    def press_on(self, selector, key="Enter"):
        self.tab_to(selector)
        self.page.keyboard.press(key)

    def tab_back_to(self, selector, limit=30):
        """Shift+Tabs until the focused element matches `selector`."""
        pg = self.page
        for _ in range(limit):
            if pg.evaluate("(s) => document.activeElement.matches(s)", selector):
                return
            pg.keyboard.press("Shift+Tab")
        self.fail("Shift+Tab never reached %s" % selector)

    def workspace(self, ws):
        """Switches workspace with the keyboard: the switch is before the header's actions."""
        pg = self.page
        if pg.evaluate("() => workspace()") == ws:
            return
        self.top()
        self.tab_back_to('#ws [data-ws="%s"]' % ws)
        pg.keyboard.press("Enter")
        pg.wait_for_selector('#ws [data-ws="%s"][aria-pressed="true"]' % ws)

    def tree_to(self, key):
        """Tabs into the network tree (one tab stop), walks it with the arrow
        keys to the entry `key` and opens it with Enter."""
        pg = self.page
        self.top()
        self.tab_to('#tree [role=treeitem][tabindex="0"]')
        pg.keyboard.press("Home")
        for _ in range(60):
            if self.active("key") == key:
                pg.keyboard.press("Enter")
                return
            pg.keyboard.press("ArrowDown")
        self.fail("no tree entry %s" % key)

    def node_tab_key(self, name):
        """Tabs to the node page's selected tab, then the arrow keys to tab `name`."""
        pg = self.page
        self.top()
        self.tab_to('.node-tabs [role=tab][aria-selected="true"]')
        pg.keyboard.press("Home")
        for _ in range(10):
            if self.active("nodeTab") == name:
                pg.wait_for_selector('[data-node-tab-panel="%s"]' % name)
                return
            pg.keyboard.press("ArrowRight")
        self.fail("no node tab %s" % name)

    def tool_tab(self, name):
        """The header's tabs: Tab reaches the selected one, the arrow keys the others."""
        pg = self.page
        self.top()
        self.tab_to('#tool-tabs [role=tab][tabindex="0"]')
        for _ in range(8):
            if self.active("view") == name:
                return
            pg.keyboard.press("ArrowRight")
        self.fail("no tab %s" % name)

    def view(self, name, where):
        """Opens a view with the keyboard and audits it: the workspace
        switch, then a tool tab or a page from the network tree."""
        pg = self.page
        if name == "online":
            self.workspace("commission")
            self.tool_tab("online")  # the workspace comes back on its last page
        elif name == "bus":
            self.workspace("configure")
            if not pg.is_visible("#side"):
                self.tool_tab("network")
            self.tree_to(pg.get_attribute('#tree .open-net [data-view="bus"]', "data-key"))
            pg.wait_for_selector('#tree .open-net [data-view="bus"].selected')
        else:
            self.tool_tab(name)
        if name == "online":
            pg.wait_for_selector("text=changes allowed")
        elif name == "trace":
            pg.wait_for_selector("#trace-source:not(:has-text('Loading'))")
        elif name == "simulation":
            pg.wait_for_selector("#sim-body")
        self.check(where)

    def check(self, where):
        self.page.wait_for_timeout(200)
        self.assertEqual(self.page.evaluate(FIT_CHECK), [], where)
        audit(self.page, where, self.report)

    def walk(self, theme):
        pg = self.page
        for name in VIEWS:
            self.view(name, "%s in %s" % (name, theme))
        # Every node page and each of its tabs, from the network tree.
        self.workspace("configure")
        if not pg.is_visible("#side"):
            self.tool_tab("network")
        keys = pg.eval_on_selector_all("#tree .open-net [data-node]", "es => es.map(e => e.dataset.key)")
        self.assertEqual(sorted(k.rsplit(":", 1)[1] for k in keys), ["0", "1", "2"])
        for key in keys:
            k = key.rsplit(":", 1)[1]
            self.tree_to(key)
            pg.wait_for_selector('[data-node-heading="%s"]' % k)
            self.assertEqual(pg.get_attribute('#tree [data-key="%s"]' % key, "aria-selected"), "true")
            tabs = pg.eval_on_selector_all(".node-tabs [role=tab]", "bs => bs.map((b) => b.dataset.nodeTab)")
            for tab in tabs:
                self.node_tab_key(tab)
                self.check("node %s, tab %s in %s" % (k, tab, theme))

    def test_walk_everything(self):
        pg = self.page
        with FakePlugin(allow_changes=True, networks=NETWORKS) as fp:
            self.remember(fp.runtime)
            # -- the start page, with the keyboard --------------------------
            pg.emulate_media(color_scheme="light")
            pg.goto(self.server.url)
            self.check("start page")
            self.press_on("#start-project")
            pg.wait_for_selector("#browser-path")
            pg.fill("#browser-path", self.project)  # the path field completes what is typed
            self.press_on("#browser-open")
            pg.wait_for_selector("#editor:not([hidden])")
            pg.wait_for_function("() => document.body.dataset.checking === '0'")
            self.assertEqual(pg.inner_text("#problem-count").strip(), "none")
            self.walk("light")

            # -- remove a PDO entry and undo it -------------------------------
            self.workspace("configure")
            self.tree_to(pg.get_attribute('#tree .open-net [data-node="0"]', "data-key"))
            pg.wait_for_selector('#view h2:has-text("Node 5")')
            self.node_tab_key("pdos")
            path = "nodes[0].tx_pdos[0].entries[0]"
            location = pg.input_value('input[data-path="%s.iec_location"]' % path)
            self.assertTrue(location.startswith("%I"), location)
            self.press_on('tr[data-path="%s"] button[title="Remove"]' % path)
            pg.wait_for_selector("#banner [data-removed]:has-text('Removed')")
            self.assertNotEqual(pg.input_value('input[data-path="%s.iec_location"]' % path), location)
            self.top()
            pg.keyboard.press("Control+z")
            pg.wait_for_function("(a) => { const i = document.querySelector('input[data-path=\"%s.iec_location\"]'); return i && i.value === a; }" % path, arg=location)
            self.assertTrue(pg.is_hidden("#banner"))
            pg.wait_for_function("() => document.body.dataset.checking === '0'")
            self.assertEqual(pg.inner_text("#btn-save").strip(), "Saved")

            # -- every export from the Export menu ----------------------------
            downloads = []
            for item, expect in (("btn-export-node", "node_5.dcf"), ("btn-export-all", "_dcf.zip"),
                                 ("btn-export-dbc", ".dbc"), ("btn-export-html", ".html"),
                                 ("btn-export-codesys", "_codesys.zip")):
                self.top()
                self.press_on("#menu-export > summary")
                pg.wait_for_selector("#menu-export[open]")
                pg.keyboard.press("ArrowDown")  # Down enters the open menu on its first item
                self.assertEqual(self.active("id"), "btn-export-all")
                while self.active("id") != item:
                    pg.keyboard.press("ArrowDown")
                with pg.expect_download() as dl:
                    pg.keyboard.press("Enter")
                    if item == "btn-export-all":
                        pg.wait_for_selector("#modal[open]")
                        self.assertEqual(pg.evaluate("() => document.activeElement.dataset.value"), "cancel")
                        self.press_on('#modal-buttons button[data-value="all"]')
                pg.wait_for_selector("#menu-export:not([open])")
                name = dl.value.suggested_filename
                self.assertTrue(name.endswith(expect) or name == expect, name)
                downloads.append(name)
                pg.wait_for_selector("#banner:has-text('Exported')")
            self.assertEqual(len(downloads), 5)
            self.assertEqual(pg.inner_text("#problem-count").strip(), "none")

            # -- the runtime goes away and comes back -------------------------
            self.view("online", "online before the outage")
            pg.wait_for_selector("tr[data-online-node]")
            fp.outage()
            pg.wait_for_selector("#online-conn:has-text('Not connected')", timeout=8000)
            pg.wait_for_selector("#online-live.stale")
            pg.wait_for_selector("[data-online=stale-age]:has-text('Last data')")
            self.assertTrue(pg.is_visible("tr[data-online-node]"))
            pg.wait_for_function("() => /Last data [1-9]\\d* s ago/.test(document.querySelector('[data-online=stale-age]').textContent)", timeout=8000)
            self.check("online during the outage")
            fp.restart()
            pg.wait_for_selector("#online-conn:has-text('Connected to')", timeout=8000)
            pg.wait_for_selector("#online-live:not(.stale)")

            # -- the same walk with the operating system set to dark ----------
            pg.emulate_media(color_scheme="dark")
            self.assertEqual(pg.evaluate("getComputedStyle(document.documentElement).colorScheme"), "dark")
            self.walk("dark")
            self.top()
            self.press_on("#btn-close")
            pg.wait_for_selector("#start:not([hidden])")
            self.check("start page in dark")
        self.assertEqual([f for f in self.report if f["impact"] == "moderate" and f["id"] == "color-contrast"], [])


if __name__ == "__main__":
    import unittest
    unittest.main()
