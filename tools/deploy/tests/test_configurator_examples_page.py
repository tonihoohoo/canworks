"""The shipped examples in a real browser (fix-gui-test-findings task 8.1):
every view of every network of examples/virtual-plant, gantry-cell and j1939
at 1280 px, with nothing clipped or scrolling sideways (the layout test's
FIT_CHECK, and scroll boxes), no console error, page error or HTTP error answer, and no
"decoding without the config's PDOs" note. One configurator and one page
load per example; the failures of all views are reported together, each
named by example, network and view. Needs Playwright, like
test_configurator_page.py."""

import os
import re
import shutil
import tempfile
import threading
import unittest

from canworks.configurator import server as srv

from .helpers import REPO, node_tab, tree_entry, tree_net
from .test_configurator_layout import FIT_CHECK
from .test_configurator_page import REQUIRED, sync_playwright

DECODING_NOTE = re.compile(r"decoding without the config's", re.I)

# Scroll boxes around wide tables (the J1939 signal tables) that scroll
# sideways; FIT_CHECK looks at the tables themselves.
SCROLL_BOXES = r"""() => [...document.querySelectorAll("#view .table-scroll, #view .fx-scroll")]
  .filter((e) => e.offsetParent !== null && e.scrollWidth > e.clientWidth + 1)
  .map((e) => ["box scrolls sideways", (e.querySelector("caption, th") || e).textContent.trim().slice(0, 40)])"""

# The node pages' collapsed PDO settings and pickers, opened so their fields are checked too.
OPEN_SECTIONS = "() => document.querySelectorAll('details[data-pdo-settings], details[data-picker]').forEach((d) => { d.open = true; })"


@unittest.skipIf(sync_playwright is None and not REQUIRED, "Playwright for Python is not installed")
class Sweep:
    """The example (a folder under examples/) copied to a temporary folder
    and opened as an editor project, or as a standalone config when it has
    no project.json."""

    example = None

    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        exe = os.environ.get("CANWORKS_CHROMIUM")
        try:
            cls.browser = cls.pw.chromium.launch(**({"executable_path": exe} if exe else {}))
        except Exception as e:  # pragma: no cover
            cls.pw.stop()
            if REQUIRED:
                raise
            raise unittest.SkipTest("no Chromium for Playwright: %s" % e)
        cls.dir = tempfile.mkdtemp(prefix="canworks-examples-page-")
        cls.env = os.environ.get("CANWORKS_CONFIG_DIR")
        os.environ["CANWORKS_CONFIG_DIR"] = os.path.join(cls.dir, "cfg")
        cls.project = os.path.join(cls.dir, cls.example)
        shutil.copytree(os.path.join(REPO, "examples", cls.example), cls.project)
        cls.server = srv.Server()
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.context = cls.browser.new_context(viewport={"width": 1280, "height": 800})
        cls.page = cls.context.new_page()
        cls.page.set_default_timeout(10000)
        cls.events = []
        cls.page.on("pageerror", lambda e: cls.events.append("page error: %s" % e))
        cls.page.on("console", lambda m: cls.events.append("console error: %s at %s" % (m.text, m.location.get("url")))
                    if m.type == "error" else None)
        cls.page.on("response", lambda r: cls.events.append("HTTP %d: %s" % (r.status, r.url)) if r.status >= 400 else None)

    @classmethod
    def tearDownClass(cls):
        cls.context.close()
        cls.browser.close()
        cls.pw.stop()
        cls.server.shutdown()
        cls.server.server_close()
        if cls.env is None:
            os.environ.pop("CANWORKS_CONFIG_DIR", None)
        else:
            os.environ["CANWORKS_CONFIG_DIR"] = cls.env
        shutil.rmtree(cls.dir, ignore_errors=True)

    def open(self):
        pg = self.page
        standalone = not os.path.isfile(os.path.join(self.project, "project.json"))
        pg.click("#start-open")
        pg.fill("[data-folder=path]", self.project)
        pg.click("[data-folder=dialog] [data-value=use]")
        pg.wait_for_selector("#editor:not([hidden])")

    def settle(self, view):
        """Waits for what the view loads after it opens."""
        pg = self.page
        if view == "trace":
            pg.wait_for_selector("#trace-source:not(:has-text('Loading'))")
        elif view == "framelab":
            pg.wait_for_selector("#fx-lab-examples:not(:has-text('Loading'))")
        elif view == "simulation":
            pg.wait_for_selector("#sim-body")
        elif ":node:" in view:
            pg.wait_for_selector('#view h2:has-text("Node")')
            pg.evaluate(OPEN_SECTIONS)
        pg.wait_for_function("() => document.body.dataset.checking !== '1'")
        pg.wait_for_timeout(300)

    def check(self, where, found):
        """The view as it is now: its layout, the events since the last
        check and a decoding note."""
        for f in self.page.evaluate(FIT_CHECK) + self.page.evaluate(SCROLL_BOXES):
            found.append("%s: %s" % (where, " ".join(str(x) for x in f)))
        found += ["%s: %s" % (where, e) for e in self.events]
        del self.events[:]
        text = self.page.inner_text("body")
        for line in text.splitlines():
            if DECODING_NOTE.search(line):
                found.append("%s: decoding note: %s" % (where, line.strip()))

    def views(self):
        """The tree entries of the open network that open a page (Bus, its
        nodes, PDO links, CAN messages), as their tree keys."""
        return self.page.eval_on_selector_all(
            "#tree .open-net [role=group] > [role=treeitem]",
            "es => es.filter((e) => e.dataset.view || e.dataset.node !== undefined).map((e) => e.dataset.key)")

    def visit(self, key, where, found):
        """Opens the tree entry `key` and checks its page; a node page on each of its tabs."""
        pg = self.page
        tree_entry(pg, key)
        if ":node:" not in key:
            self.settle(pg.get_attribute('#tree [data-key="%s"]' % key, "data-view") or "bus")
            self.check(where, found)
            return
        pg.wait_for_selector('[data-node-heading="%s"]' % key.rsplit(":", 1)[1])
        for tab in pg.eval_on_selector_all(".node-tabs [data-node-tab]", "bs => bs.map((b) => b.dataset.nodeTab)"):
            node_tab(pg, tab)
            self.settle(key)
            self.check("%s, tab %s" % (where, tab), found)

    def test_every_network_and_view(self):
        pg = self.page
        found = []
        pg.goto(self.server.url)
        pg.wait_for_selector("#start:not([hidden])")
        self.check("%s, start page" % self.example, found)
        self.open()
        nets = pg.evaluate("() => S.model.networks.map((n, i) => n.name || String(i + 1))")
        seen = 0
        for i, net in enumerate(nets):
            tree_net(pg, i)
            for key in self.views():
                self.visit(key, "%s, network %s, %s" % (self.example, net, key), found)
                seen += 1
        # The config-wide entries after the networks: Online access, Gateway, Modbus bridge.
        for key in pg.eval_on_selector_all("#tree > [role=treeitem][data-view]", "es => es.map((e) => e.dataset.key)"):
            self.visit(key, "%s, %s" % (self.example, key), found)
            seen += 1
        self.assertGreater(seen, len(nets))
        self.assertEqual(found, [], "\n" + "\n".join(found))


class VirtualPlant(Sweep, unittest.TestCase):
    example = "virtual-plant"


class GantryCell(Sweep, unittest.TestCase):
    example = "gantry-cell"


class J1939(Sweep, unittest.TestCase):
    example = "j1939"


class PdoLink(Sweep, unittest.TestCase):
    example = "pdo-link"
