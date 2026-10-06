"""Several CAN networks in the configurator page (add-several-can-networks
tasks 6.2-6.5): the network bar, checks and suggestions across networks, the
network picker of the online, scan and trace views against a fake plugin
that runs two networks, and the exports per network. Needs Playwright, like
test_configurator_page.py.

With CANOPEN_SCREENSHOTS=DIR the tests also save screenshots of the network
bar in light and dark mode there (task 6.2)."""

import json
import os
import shutil
import threading
import unittest
import zipfile

from openplc_canopen_deploy import diag
from openplc_canopen_deploy.configurator import server as srv

from .fake_diag import TOKEN, TWO_NETWORKS, FakePlugin
from .helpers import PINGPONG, REPO, tmpdir
from .test_configurator_page import REQUIRED, RTD, load, sync_playwright

TWO = os.path.join(REPO, "config", "two-networks")
SHOTS = os.environ.get("CANOPEN_SCREENSHOTS")


@unittest.skipIf(sync_playwright is None and not REQUIRED, "Playwright for Python is not installed")
class NetworksPage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        exe = os.environ.get("CANOPEN_CHROMIUM")
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
        self.cfg_dir = os.path.join(self.dir, "cfg")
        os.environ["OPENPLC_CANOPEN_CONFIG_DIR"] = self.cfg_dir
        self.addCleanup(os.environ.pop, "OPENPLC_CANOPEN_CONFIG_DIR", None)
        # A standalone config folder: no editor project addresses to clash with.
        self.folder = os.path.join(self.dir, "plant")
        os.makedirs(self.folder)
        shutil.copy(os.path.join(TWO, "cpp-slave.eds"), self.folder)
        self.server = srv.Server()
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.context = self.browser.new_context(accept_downloads=True)
        self.addCleanup(self.context.close)
        self.page = self.context.new_page()
        self.page.set_default_timeout(10000)
        self.errors = []
        self.page.on("pageerror", lambda e: self.errors.append(str(e)))

    def tearDown(self):
        self.assertEqual(self.errors, [])

    # -- helpers ------------------------------------------------------------
    @property
    def config_path(self):
        return os.path.join(self.folder, "canopen.json")

    def write(self, cfg):
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)

    def two(self, diagnostics=False):
        cfg = load(os.path.join(TWO, "canopen_config.json"))
        cfg["networks"][1]["nodes"][0]["name"] = "drive"
        if diagnostics:
            cfg["diagnostics"] = {"token_sha256": diag.hash_token(TOKEN), "allow_changes": True}
        return cfg

    def remember(self, host):
        os.makedirs(self.cfg_dir, exist_ok=True)
        with open(os.path.join(self.cfg_dir, "online.json"), "w") as f:
            json.dump({"projects": {self.folder: {"host": host, "token": TOKEN}}}, f)

    def open(self):
        pg = self.page
        pg.goto(self.server.url)
        pg.click("#start-standalone")
        pg.fill("#browser-path", self.folder)
        pg.click("#browser-open")
        pg.wait_for_selector("#editor:not([hidden])")
        self.settled()

    def settled(self):
        self.page.wait_for_function("() => document.body.dataset.checking === '0'")

    def tabs(self):
        """The tab labels (without their error counts)."""
        return self.page.evaluate("() => [...document.querySelectorAll('#net-bar [data-net]')]"
                                  ".map((t) => t.firstChild.textContent)")

    def save(self):
        self.settled()
        self.page.click("#btn-save")
        self.page.wait_for_selector("#banner:has-text('Saved')")

    def answer(self, value):
        self.page.click('#modal-buttons button[data-value="%s"]' % value)

    def shot(self, name):
        if not SHOTS:
            return
        os.makedirs(SHOTS, exist_ok=True)
        self.page.set_viewport_size({"width": 1280, "height": 800})
        for theme in ("light", "dark"):
            self.page.evaluate("t => document.documentElement.dataset.theme = t", theme)
            self.page.wait_for_timeout(100)
            self.page.screenshot(path=os.path.join(SHOTS, "%s-%s.png" % (name, theme)))

    # -- network bar (6.1, 6.2) ---------------------------------------------
    def test_add_rename_remove_and_saved_versions(self):
        pg = self.page
        cfg = load(os.path.join(PINGPONG, "canopen_config.json"))
        self.write(cfg)
        self.open()
        # One network: only the add button, the page as before.
        self.assertEqual(self.tabs(), [])
        self.assertEqual(pg.locator("#net-bar button").all_inner_texts(), ["Add network"])
        self.assertEqual(pg.inner_text("#view h2"), "Bus and master")
        # Saved unchanged: version 1, the same content.
        self.save()
        self.assertEqual(load(self.config_path), srv.canonical(cfg))
        pg.click('#net-bar button[data-net-action="add"]')
        self.assertEqual(self.tabs(), ["vcan0", "network 2"])
        self.assertEqual(pg.input_value('input[data-path="adapter.interface"]'), "")
        self.assertEqual(pg.inner_text("#node-list"), "No nodes yet")
        self.settled()
        self.assertIn("Network network 2", pg.inner_text("#problem-list"))
        pg.fill('input[data-path="adapter.interface"]', "vcan1")
        self.assertEqual(self.tabs(), ["vcan0", "vcan1"])
        # Rename: refused names are said, a good one is kept.
        pg.click('#net-bar button[data-net-action="rename"]')
        pg.fill('input[data-net="name"]', "VCAN0")
        self.answer("rename")
        pg.wait_for_selector("#modal-text:has-text('already named')")
        pg.fill('input[data-net="name"]', "drives")
        self.answer("rename")
        self.assertEqual(self.tabs(), ["vcan0", "drives"])
        # A node on drives, and online access once for both networks.
        pg.set_input_files("#eds-input", os.path.join(PINGPONG, "cpp-slave.eds"))
        pg.wait_for_selector('#node-list li[data-node="0"]')
        pg.click('button[data-view="bus"]')
        self.assertEqual(pg.locator('[data-section="online"] legend').inner_text(), "Online access (all networks)")
        pg.check('input[data-online="enable"]')
        pg.wait_for_selector('input[data-path="master.diagnostics.port"]')
        pg.fill('input[data-path="master.diagnostics.port"]', "7600")
        pg.click('#net-bar [data-net="0"]')
        self.assertEqual(pg.input_value('input[data-path="master.diagnostics.port"]'), "7600")
        self.assertEqual(pg.inner_text('#node-list li[data-node="0"]').split()[0], "2")
        self.shot("networks-bar")
        self.save()
        saved = load(self.config_path)
        self.assertEqual(saved["schema_version"], 2)
        self.assertEqual([n.get("name") for n in saved["networks"]], [None, "drives"])
        self.assertEqual(saved["networks"][1]["adapter"]["interface"], "vcan1")
        self.assertEqual(saved["networks"][1]["nodes"][0]["eds"], "cpp-slave.eds")
        self.assertEqual(saved["diagnostics"]["port"], 7600)
        self.assertNotIn("diagnostics", saved["networks"][0]["master"])
        # Remove drives: asked, naming it and its node; back to version 1.
        pg.click('#net-bar [data-net="1"]')
        pg.click('#net-bar button[data-net-action="remove"]')
        self.assertIn("Remove network drives and its 1 node?", pg.inner_text("#modal-text"))
        self.answer("remove")
        self.assertEqual(self.tabs(), [])
        self.save()
        saved = load(self.config_path)
        self.assertEqual(saved["schema_version"], 1)
        self.assertEqual(saved["master"]["diagnostics"]["port"], 7600)
        self.assertEqual(saved["nodes"], cfg["nodes"])

    # -- checks across networks (6.3) ---------------------------------------
    def test_suggestions_and_clashes_across_networks(self):
        pg = self.page
        cfg = self.two()
        cfg["networks"][0]["nodes"][0]["emcy_code_location"] = "%IW100"
        self.write(cfg)
        self.open()
        self.assertEqual(self.tabs(), ["io", "drives"])
        self.assertEqual(pg.inner_text("#view h2"), "Bus and master: network io")
        pg.click('#net-bar [data-net="1"]')
        pg.click('#node-list li[data-node="0"]')
        pg.click('button[data-suggest="emcy"]')
        pg.wait_for_function("() => document.querySelector('input[data-path=\"nodes[0].emcy_code_location\"]').value")
        self.assertEqual(pg.input_value('input[data-path="nodes[0].emcy_code_location"]'), "%IW101")
        # A location io uses, and io's interface: errors naming both networks.
        pg.fill('input[data-path="nodes[0].status_location"]', "%IX10.0")
        self.settled()
        problems = pg.inner_text("#problem-list")
        self.assertIn("networks[0] (io) node 2 (pingpong) status_location and networks[1] (drives) node 2 (drive) "
                      "status_location both map to %IX10.0", problems)
        self.assertIn("invalid", pg.get_attribute('input[data-path="nodes[0].status_location"]', "class"))
        self.assertEqual(pg.inner_text('#net-bar [data-net="1"] .count'), "1")
        pg.click('button[data-view="bus"]')
        pg.fill('input[data-path="adapter.interface"]', "vcan0")
        self.settled()
        self.assertIn("vcan0", pg.inner_text("#problem-list"))
        self.assertTrue(pg.is_disabled("#btn-save"))
        self.assertIn("Network io, CAN adapter: networks[0] (io) and networks[1] (drives) both use interface vcan0",
                      pg.inner_text("#problem-list"))
        # A problem of the other tab opens it.
        pg.click("#problem-list li:has-text('Network io, Node 2 pingpong')")
        pg.wait_for_selector('#net-bar [data-net="0"].active')
        pg.wait_for_selector('#node-list li[data-node="0"].active')

    # -- network picker (6.4) -----------------------------------------------
    def test_online_scan_and_trace_on_the_picked_network(self):
        pg = self.page
        self.write(self.two(diagnostics=True))
        with FakePlugin(networks=TWO_NETWORKS, allow_changes=True, scan_polls=0) as fp:
            self.remember(fp.runtime)
            self.open()
            # The picker starts on the open tab.
            pg.click('#net-bar [data-net="1"]')
            pg.click('button[data-view="online"]')
            pg.wait_for_selector("text=Connected to")
            self.assertEqual(pg.input_value('select[data-online="network"]'), "drives")
            pg.wait_for_selector('td[data-online="bus"]:has-text("vcan1")')
            self.assertIn("drive", pg.inner_text('tr[data-online-node="2"]'))
            pg.click('tr[data-online-node="2"]')
            pg.fill('input[data-online="index"]', "0x1008")
            pg.select_option('select[data-online="type"]', "VISIBLE_STRING")
            pg.click('button[data-online="read"]')
            pg.wait_for_selector('[data-online="sdo-result"]:has-text("drive")')
            pg.click('button[data-nmt="preop"]')
            pg.wait_for_selector("#banner:has-text('Pre-operational sent')")
            self.assertEqual(fp.network("drives").status["nodes"][0]["state"], 127)
            self.assertEqual(fp.status["nodes"][0]["hold"], "none")
            ops = [q for q in fp.requests if q["op"] in ("sdo_read", "nmt")]
            self.assertEqual({q.get("network") for q in ops}, {"drives"})
            # The object dictionary of drives' node 2 (its EDS from the draft).
            pg.click('button[data-online-tab="od"]')
            pg.wait_for_selector('details[data-od-group="communication"]')
            # Picking io shows io and opens its tab.
            pg.select_option('select[data-online="network"]', "io")
            pg.wait_for_selector('td[data-online="bus"]:has-text("vcan0")')
            pg.wait_for_selector('#net-bar [data-net="0"].active')
            # Scan drives and add a found device there.
            pg.click('#net-bar [data-net="1"]')
            pg.click('button[data-view="scan"]')
            self.assertEqual(pg.input_value('select[data-online="network"]'), "drives")
            pg.click('button[data-online="scan"]')
            pg.wait_for_selector('tr[data-scan-node="41"]')
            self.assertEqual([q.get("network") for q in fp.requests if q["op"] == "scan"][-1], "drives")
            pg.set_input_files('tr[data-scan-node="41"] input[type="file"]', os.path.join(RTD, "rtd8.eds"))
            pg.wait_for_selector('tr[data-scan-node="41"]:has-text("added")')
            self.assertEqual(pg.evaluate("() => S.model.networks.map((n) => n.nodes.map((x) => x.node_id))"),
                             [[2], [2, 41]])
            # The trace records the picked network.
            pg.click('button[data-view="trace"]')
            self.assertEqual(pg.input_value('select[data-online="network"]'), "drives")
            pg.click('button[data-trace="start"]')
            pg.wait_for_selector("#trace-source:has-text('network drives')")
            self.assertEqual(fp.trace_starts[-1]["network"], "drives")
            pg.click('button[data-trace="stop"]')

    # -- exports (6.5) ------------------------------------------------------
    def test_exports_of_the_open_tab_or_all(self):
        pg = self.page
        self.write(self.two())
        self.open()
        pg.click('#net-bar [data-net="1"]')
        with pg.expect_download() as dl:
            pg.click("#btn-export-dbc")
        self.assertEqual(dl.value.suggested_filename, "plant_drives.dbc")
        with open(dl.value.path(), encoding="ascii") as f:
            text = f.read()
        self.assertIn("drive", text)
        self.assertNotIn("pingpong", text)
        pg.click('#node-list li[data-node="0"]')
        with pg.expect_download() as dl:
            pg.click('#node-list li[data-node="0"] button.export-dcf')
        self.assertEqual(dl.value.suggested_filename, "node_2.dcf")
        with open(dl.value.path(), encoding="utf-8") as f:
            self.assertIn("NodeName=drive", f.read())
        pg.click("#btn-export-all")
        self.assertIn("network drives, or of every network", pg.inner_text("#modal-text"))
        with pg.expect_download() as dl:
            self.answer("all")
        self.assertEqual(dl.value.suggested_filename, "plant_dcf.zip")
        with zipfile.ZipFile(dl.value.path()) as z:
            self.assertEqual(sorted(z.namelist()), ["drives/node_2.dcf", "io/node_2.dcf"])
        pg.click("#btn-export-all")
        with pg.expect_download() as dl:
            self.answer("tab")
        self.assertEqual(dl.value.suggested_filename, "plant_drives_dcf.zip")
        with zipfile.ZipFile(dl.value.path()) as z:
            self.assertEqual(z.namelist(), ["node_2.dcf"])


if __name__ == "__main__":
    unittest.main()
