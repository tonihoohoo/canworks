"""One browser run through the whole configurator, with the keyboard, against
the fake plugin and the virtual example (polish-configurator-ux 7.1): every
view from the start page, a PDO entry removed and undone, every export from
the Export menu with its download, the runtime going away and coming back,
and the same walk in the dark theme, with the accessibility audit after each
view. Needs Playwright, like test_configurator_page.py."""
import json
import os
import shutil

from openplc_canopen_deploy import diag

from .fake_diag import TOKEN, FakePlugin
from .helpers import REPO
from .test_configurator_layout import FIT_CHECK, audit
from .test_configurator_online_page import OnlineBase

VIRTUAL = os.path.join(REPO, "examples", "virtual-plant")
NETWORKS = [{"name": "io", "interface": "sim0", "bitrate": 250000, "master_node_id": 1},
            {"name": "motion", "interface": "sim1", "bitrate": 500000, "master_node_id": 1}]
VIEWS = ["bus", "declarations", "online", "scan", "trace", "framelab", "simulation"]


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
        walk the header, then the side bar, then the page."""
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

    def view(self, name, where):
        """Opens a side bar view with the keyboard and audits it."""
        pg = self.page
        self.top()
        self.press_on('button[data-view="%s"]' % name)
        if name == "online":
            pg.wait_for_selector("text=changes allowed")
        elif name == "scan":
            self.press_on('button[data-online="scan"]')
            pg.wait_for_selector("tr[data-scan-node]")
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
        # Every node page, from the side bar.
        self.top()
        nodes = pg.eval_on_selector_all("#node-list [data-node]", "es => es.map(e => e.dataset.node)")
        self.assertEqual(nodes, ["0", "1", "2"])
        for k in nodes:
            self.top()
            self.press_on('#node-list [data-node="%s"]' % k)
            pg.wait_for_selector('#view h2:has-text("Node")')
            self.assertEqual(pg.get_attribute('#node-list [data-node="%s"]' % k, "aria-current"), "true")
            self.check("node %s in %s" % (k, theme))

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
            self.top()
            self.press_on('#node-list [data-node="0"]')
            pg.wait_for_selector('#view h2:has-text("Node 5")')
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
                                 ("btn-export-dbc", ".dbc"), ("btn-export-html", ".html")):
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
            self.assertEqual(len(downloads), 4)
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
