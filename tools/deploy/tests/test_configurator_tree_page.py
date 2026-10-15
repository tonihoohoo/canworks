"""The configurator's network tree and node tabs in a real browser
(network-tree-and-node-tabs): the tree of every network, its keyboard and
menu, problem badges and problem links to a node's tab, simulated and absent
marks, the node tabs, the tree in Commission and the narrow layout. Needs
Playwright, like test_configurator_page.py."""

import os
import shutil
import threading
import unittest

from canworks.configurator import server as srv

from .fake_diag import FakePlugin
from .helpers import REPO, add_network, net_action, node_tab, tmpdir, tree_entry, tree_net, tree_node, tree_view
from .test_configurator_layout import FIT_CHECK, audit
from .test_configurator_online_page import OnlineBase
from .test_configurator_page import REQUIRED, sync_playwright

PLANT = os.path.join(REPO, "examples", "virtual-plant", "canworks")
DIO = os.path.join(PLANT, "dio16.eds")


@unittest.skipIf(sync_playwright is None and not REQUIRED, "Playwright for Python is not installed")
class Tree(unittest.TestCase):
    """The virtual plant: networks io (nodes 5, 6, 7, simulated), motion (a
    CiA 402 drive), cell (a slave network) and host (node 20 absent)."""

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

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def setUp(self):
        self.dir = tmpdir(self)
        os.environ["CANWORKS_CONFIG_DIR"] = os.path.join(self.dir, "cfg")
        self.addCleanup(os.environ.pop, "CANWORKS_CONFIG_DIR", None)
        self.folder = os.path.join(self.dir, "plant")
        shutil.copytree(PLANT, self.folder)
        self.server = srv.Server()
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.context = self.browser.new_context(viewport={"width": 1440, "height": 900})
        self.addCleanup(self.context.close)
        self.page = self.context.new_page()
        self.page.set_default_timeout(10000)
        self.errors = []
        self.page.on("pageerror", lambda e: self.errors.append(str(e)))
        self.open()

    def tearDown(self):
        self.assertEqual(self.errors, [])

    def open(self):
        pg = self.page
        pg.goto(self.server.url)
        pg.click("#start-standalone")
        pg.fill("#browser-path", self.folder)
        pg.click("#browser-open")
        pg.wait_for_selector('#tree [data-key="0:node:0"]')

    def settled(self):
        self.page.wait_for_function("() => document.body.dataset.checking === '0'")

    def names(self, sel):
        return [t.strip() for t in self.page.locator(sel).all_inner_texts()]

    def test_entries_and_marks(self):
        pg = self.page
        top = pg.evaluate("() => [...document.querySelectorAll('#tree > li')].map((li) => li.dataset.key)")
        self.assertEqual(top, ["0", "1", "2", "3", "access", "gateway", "addnet"])
        self.assertIn("CANopen slave", pg.inner_text('#tree [data-key="2"] > .tree-row .proto'))
        io = pg.evaluate("() => [...document.querySelectorAll('#tree [data-key=\"0\"] > ul > li > .tree-row .name')].map((e) => e.textContent)")
        self.assertEqual(io, ["Bus and master", "5 rtd (simulated)", "6 dio (simulated)", "7 new_io (simulated)",
                              "+ Add node…", "PDO links", "CAN messages"])
        # Simulated nodes hollow, a node switched off on a simulated network dashed.
        self.assertEqual(pg.get_attribute('#tree [data-key="0:node:0"] .tree-mark', "class"), "tree-mark sim")
        self.assertEqual(pg.get_attribute('#tree [data-key="3:node:0"] .tree-mark', "class"), "tree-mark absent")
        self.assertIn("(absent)", pg.inner_text('#tree [data-key="3:node:0"] .name'))
        # The slave network has its device in place of nodes.
        self.assertEqual(pg.locator('#tree [data-key="2"] [data-slave]').count(), 1)
        # The live state from commission-workspace sets a mark without a redraw.
        pg.evaluate("() => { document.querySelector('#tree [data-key=\"0:node:1\"]').dataset.probe = '1'; setNodeMark('io', 6, 'absent', 'absent'); }")
        self.assertEqual(pg.get_attribute('#tree [data-key="0:node:1"][data-probe] .tree-mark', "class"), "tree-mark absent")
        pg.evaluate("() => setNodeMark('io', 6, null)")
        self.assertEqual(pg.get_attribute('#tree [data-key="0:node:1"] .tree-mark', "class"), "tree-mark sim")
        audit(pg, "tree")

    def test_node_tabs(self):
        pg = self.page
        tree_node(pg, 0)
        tabs = self.names(".node-tabs [role=tab]")
        self.assertEqual(tabs, ["General", "PDOs", "SDOs", "Supervision", "Simulation", "Notes", "Advanced"])
        self.assertEqual(pg.get_attribute('.node-tabs [data-node-tab="general"]', "aria-selected"), "true")
        audit(pg, "node General tab")
        # A tab stays when another node opens, and after a reload.
        node_tab(pg, "supervision")
        self.assertTrue(pg.is_visible('select[data-supervision="0"]'))
        tree_node(pg, 1)
        pg.wait_for_selector('[data-node-tab-panel="supervision"]')
        self.assertTrue(pg.is_visible('select[data-supervision="1"]'))
        pg.reload()
        pg.wait_for_selector('#tree [data-key="0:node:0"]')
        tree_node(pg, 2)
        pg.wait_for_selector('[data-node-tab-panel="supervision"]')
        # CiA 402 only for the drive; a node without the tab opens General.
        tree_net(pg, 1)
        tree_node(pg, 0, "cia402")
        self.assertIn("CiA 402", self.names(".node-tabs [role=tab]"))
        tree_net(pg, 0)
        tree_node(pg, 0)
        self.assertNotIn("CiA 402", self.names(".node-tabs [role=tab]"))
        pg.wait_for_selector('[data-node-tab-panel="general"]')
        # Each field's problems count on the tab that holds it.
        tabs_of = pg.evaluate("() => ['heartbeat_ms', 'guard_time_ms', 'heartbeat_consumer', 'emcy_cob_id', 'tx_pdos[0].cob_id', "
                              "'sdo[1].value', 'axis.unit', 'name', 'check'].map(nodeTabOfPath)")
        self.assertEqual(tabs_of, ["supervision", "supervision", "advanced", "supervision", "pdos", "sdos", "cia402", "general", "advanced"])
        # Arrow keys move between the tabs.
        pg.focus('.node-tabs [data-node-tab="general"]')
        pg.keyboard.press("ArrowRight")
        pg.wait_for_selector('[data-node-tab-panel="pdos"]')
        self.assertEqual(pg.evaluate("() => document.activeElement.dataset.nodeTab"), "pdos")

    def test_pdos_sdos_notes_and_simulation_tabs(self):
        pg = self.page
        tree_node(pg, 0, "pdos")
        # Each PDO: its mapping, and its settings behind a one-line summary.
        settings = pg.locator("details[data-pdo-settings]")
        self.assertGreater(settings.count(), 0)
        self.assertFalse(pg.evaluate("() => document.querySelector('details[data-pdo-settings]').open"))
        self.assertIn("COB-ID 0x", pg.inner_text("[data-pdo-summary]"))
        cols = pg.evaluate("() => getComputedStyle(document.querySelector('.pdo-columns')).gridTemplateColumns.split(' ').length")
        self.assertEqual(cols, 2)
        audit(pg, "node PDOs tab")
        # SDOs: both lists, even when empty.
        node_tab(pg, "sdos")
        self.assertEqual(pg.locator('[data-node-tab-panel="sdos"] details.section').count(), 2)
        # Notes: own notes first; all notes, with search.
        node_tab(pg, "notes")
        pg.click('[data-notes-view-pick="all"]')
        pg.wait_for_selector('[data-notes-view="all"]')
        rows = pg.locator("[data-note-row]").count()
        self.assertGreater(rows, 0)
        pg.fill("[data-notes-search]", "zzzz-none")
        pg.wait_for_selector("[data-notes-empty]:has-text('No note matches.')")
        pg.fill("[data-notes-search]", "")
        self.assertEqual(pg.locator("[data-note-row]").count(), rows)
        self.assertTrue(pg.is_visible("[data-export-notes]"))
        # Simulation: the node's part of simulation.json.
        node_tab(pg, "simulation")
        pg.wait_for_selector('[data-node-sim="5"]')
        audit(pg, "node Simulation tab")

    def test_problem_badges_and_links(self):
        pg = self.page
        tree_node(pg, 0)
        self.settled()
        self.assertEqual(pg.locator("#tree .tree-badge").count(), 0)
        # Node 6's TPDO 1 on node 5's COB-ID: an error on node 6's PDOs tab.
        cob = pg.evaluate("() => S.config.nodes[0].tx_pdos[0].cob_id")
        tree_node(pg, 1, "pdos")
        pg.click("details[data-pdo-settings] > summary")
        pg.fill('input[data-path="nodes[1].tx_pdos[0].cob_id"]', str(cob))
        pg.keyboard.press("Tab")
        self.settled()
        pg.wait_for_selector('#tree [data-key="0:node:1"] .tree-badge')
        self.assertIn("error", pg.inner_text('#tree [data-key="0:node:1"] .tree-badge'))
        self.assertTrue(pg.is_visible('.node-tabs [data-node-tab="pdos"] .tree-badge'))
        # Another node and tab open; the problem link goes to the field.
        tree_node(pg, 0, "general")
        pg.locator("#problem-list button", has_text="COB").first.click()
        pg.wait_for_selector('[data-node-heading="1"]')
        pg.wait_for_selector('[data-node-tab-panel="pdos"]')
        self.assertTrue(pg.evaluate("() => document.querySelector('details[data-pdo-settings]').open"))
        pg.wait_for_function("() => document.activeElement && document.activeElement.dataset.path === 'nodes[1].tx_pdos[0].cob_id'")
        # A folded network shows the sum of its entries.
        pg.click('#tree [data-key="0"] > .tree-row .twist')
        pg.wait_for_selector('#tree [data-key="0"][aria-expanded="false"]')
        self.assertIn("error", pg.inner_text('#tree [data-key="0"] > .tree-row .tree-badge'))
        # A problem link unfolds it again.
        pg.locator("#problem-list button", has_text="COB").first.click()
        pg.wait_for_selector('#tree [data-key="0"][aria-expanded="true"]')

    def test_keyboard(self):
        pg = self.page
        pg.focus('#tree [tabindex="0"]')
        # Type-ahead to a node by its ID, Enter opens it.
        pg.keyboard.type("6")
        self.assertEqual(pg.evaluate("() => document.activeElement.dataset.key"), "0:node:1")
        pg.keyboard.press("Enter")
        pg.wait_for_selector('[data-node-heading="1"]')
        # The tree keeps one Tab stop.
        self.assertEqual(pg.locator('#tree [tabindex="0"]').count(), 1)
        # Left goes to the network, Left again folds it; kept after a reload.
        pg.focus('#tree [data-key="0:node:1"]')
        pg.keyboard.press("ArrowLeft")
        self.assertEqual(pg.evaluate("() => document.activeElement.dataset.key"), "0")
        pg.keyboard.press("ArrowLeft")
        pg.wait_for_selector('#tree [data-key="0"][aria-expanded="false"]')
        self.assertEqual(pg.locator('#tree [data-key="0:node:1"]').count(), 0)
        pg.keyboard.press("ArrowDown")
        self.assertEqual(pg.evaluate("() => document.activeElement.dataset.key"), "1")
        pg.wait_for_timeout(300)
        pg.reload()
        pg.wait_for_selector('#tree [data-key="1:node:0"]')
        self.assertEqual(pg.get_attribute('#tree [data-key="0"]', "aria-expanded"), "false")
        pg.focus('#tree [data-key="0"]')
        pg.keyboard.press("ArrowRight")
        pg.wait_for_selector('#tree [data-key="0"][aria-expanded="true"]')
        # Shift+F10 opens the network's menu.
        pg.keyboard.press("Shift+F10")
        pg.wait_for_selector('#modal-buttons [data-value="rename"]')
        pg.keyboard.press("Escape")

    def test_network_menu_and_add_node(self):
        pg = self.page
        # File chooser interception goes on with the first "filechooser" listener, sent without
        # waiting for an answer; a click right after expect_file_chooser() could reach the
        # page first and open no chooser. A listener from the start keeps it on.
        pg.on("filechooser", lambda _: None)
        # Rename from the menu.
        net_action(pg, 1, "rename")
        pg.fill('#modal-extra input[data-net="name"]', "axes")
        pg.click('#modal-buttons [data-value="rename"]')
        pg.wait_for_selector('#tree [data-key="1"] > .tree-row .name:text-is("axes")')
        # Add node… under the second network adds it there.
        with pg.expect_file_chooser() as fc:
            tree_entry(pg, "1:add")
        fc.value.set_files(DIO)
        pg.wait_for_selector('#tree [data-key="1:node:1"]')
        self.assertEqual(pg.evaluate("() => [S.net, S.config.nodes.length]"), [1, 2])
        pg.wait_for_selector('[data-node-tab-panel="general"]')
        self.assertEqual(pg.evaluate("() => document.activeElement.dataset.path"), "nodes[1].name")
        # The tree follows the name as it is typed.
        pg.keyboard.type("valves")
        pg.wait_for_selector('#tree [data-key="1:node:1"] .name:has-text("valves")')
        # Add a network, then remove it from its menu.
        add_network(pg)
        pg.click('#modal-buttons [data-value="canopen"], #modal-buttons .primary')
        pg.wait_for_selector('#tree [data-key="4"]')
        net_action(pg, 4, "remove")
        pg.click("#modal-buttons .danger")
        pg.wait_for_selector('#tree [data-key="4"]', state="detached")

    def test_online_access_entry(self):
        pg = self.page
        tree_view(pg, "access")
        pg.wait_for_selector("#view h2:text-is('Online access')")
        self.assertTrue(pg.is_visible('#view [data-section="online"]'))
        tree_view(pg, "bus")
        pg.wait_for_selector('#view [data-section="online"]', state="detached")

    def test_layout_fits(self):
        pg = self.page
        for width in (1000, 1280, 1440, 1600):
            pg.set_viewport_size({"width": width, "height": 900})
            if width <= 1100:
                self.assertTrue(pg.is_visible("#tree-toggle"))
                continue
            tree_net(pg, 1)
            for tab in ("general", "pdos", "sdos", "supervision", "cia402", "simulation", "notes", "advanced"):
                tree_node(pg, 0, tab)
                self.assertEqual(pg.evaluate(FIT_CHECK), [], "%d px, %s" % (width, tab))
            tree_net(pg, 0)

    def test_narrow_window(self):
        pg = self.page
        pg.set_viewport_size({"width": 900, "height": 800})
        self.assertFalse(pg.is_visible("#tree"))
        self.assertIn("▾", pg.inner_text("#tree-toggle"))
        pg.click("#tree-toggle")
        self.assertTrue(pg.is_visible("#tree"))
        self.assertEqual(pg.get_attribute("#tree-toggle", "aria-expanded"), "true")
        tree_entry(pg, "0:node:1")
        pg.wait_for_selector('[data-node-heading="1"]')
        self.assertFalse(pg.is_visible("#tree"))
        self.assertIn("6 dio", pg.inner_text("#tree-toggle"))
        # Escape closes it too.
        pg.click("#tree-toggle")
        pg.keyboard.press("Escape")
        self.assertFalse(pg.is_visible("#tree"))


class CommissionTree(OnlineBase):
    """Commission with a config: the same tree, networks and nodes only."""

    def test_tree_in_commission(self):
        from canworks import diag
        from .fake_diag import TOKEN
        pg = self.page
        with FakePlugin() as fp:
            self.write_config({"token_verifier": diag.token_verifier(TOKEN), "allow_changes": False})
            self.remember(fp.runtime)
            self.open()
            pg.click('#ws [data-ws="commission"]')
            pg.wait_for_selector('tr[data-online-node="2"]')
            self.assertTrue(pg.is_visible("#tree"))
            keys = pg.evaluate("() => [...document.querySelectorAll('#tree [role=treeitem]')].map((e) => e.dataset.key)")
            self.assertEqual(keys, ["0", "0:node:0"])
            self.assertEqual(pg.locator("#tree .net-menu").count(), 0)
            tree_entry(pg, "0:node:0")
            pg.wait_for_function("() => S.onlineNode === 2")
            self.assertEqual(pg.get_attribute('#tree [data-key="0:node:0"]', "aria-selected"), "true")
            tree_entry(pg, "0")
            pg.wait_for_function("() => S.onlineNode === null")
            audit(pg, "Commission tree")
