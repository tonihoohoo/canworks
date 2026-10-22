"""Save always saves (save-anytime): a draft with errors is written and the
hand-off steps refuse it instead, New config writes its folder, a new node
starts supervised, and the supervision problem has quick fixes. Needs
Playwright, like test_configurator_page.py."""

import json
import os
import shutil
import threading
import unittest

from canworks.configurator import server as srv

from .helpers import REPO, new_config, node_tab, tmpdir, tree_node, add_node
from .test_configurator_page import REQUIRED, load, sync_playwright

TWO = os.path.join(REPO, "config", "two-networks")


@unittest.skipIf(sync_playwright is None and not REQUIRED, "Playwright for Python is not installed")
class SaveAnytime(unittest.TestCase):
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
        os.makedirs(self.folder)
        shutil.copy(os.path.join(TWO, "cpp-slave.eds"), self.folder)
        self.server = srv.Server()
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.context = self.browser.new_context()
        self.addCleanup(self.context.close)
        self.page = self.context.new_page()
        self.page.set_default_timeout(10000)
        self.errors = []
        self.page.on("pageerror", lambda e: self.errors.append(str(e)))

    def tearDown(self):
        self.assertEqual(self.errors, [])

    def config(self, **node):
        """One network with node 2 (the ping-pong slave), `node` merged into it."""
        net = load(os.path.join(TWO, "canopen_config.json"))["networks"][0]
        n = dict(net["nodes"][0], **node)
        for k in [k for k, v in node.items() if v is None]:
            del n[k]
        return {"schema_version": 1, "adapter": net["adapter"], "master": net["master"], "nodes": [n]}

    def open(self, cfg):
        with open(os.path.join(self.folder, "canworks.json"), "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
        pg = self.page
        pg.goto(self.server.url)
        pg.click("#start-open")
        pg.fill("[data-folder=path]", self.folder)
        pg.click("[data-folder=dialog] [data-value=use]")
        pg.wait_for_selector("#editor:not([hidden])")
        self.settled()

    def settled(self):
        self.page.wait_for_function("() => document.body.dataset.checking === '0'")

    def saved(self):
        with open(os.path.join(self.folder, "canworks.json"), encoding="utf-8") as f:
            return json.load(f)

    def test_save_with_an_error(self):
        pg = self.page
        self.open(self.config())
        tree_node(pg, 0)
        pg.fill('input[data-path="nodes[0].node_id"]', "1")  # the master's
        self.settled()
        self.assertFalse(pg.is_disabled("#btn-save"))
        self.assertEqual(pg.inner_text("#btn-save"), "Save")
        pg.click("#btn-save")
        pg.wait_for_selector("#banner[data-notice=warning]")
        self.assertRegex(pg.inner_text("#banner"), r"Saved with 1 error: the runtime refuses this config until it is fixed")
        self.assertEqual(self.saved()["nodes"][0]["node_id"], 1)
        self.settled()
        self.assertEqual(pg.inner_text("#btn-save"), "Saved, 1 problem")
        self.assertTrue(pg.is_disabled("#btn-save"))

    def test_quick_fix_and_undo(self):
        pg = self.page
        self.open(self.config(heartbeat_ms=None, heartbeat_timeout_ms=None))
        item = pg.locator("#problem-list li", has_text="has no heartbeat or guarding")
        self.assertIn("Set the heartbeat period on Supervision", item.inner_text())
        self.assertNotIn("heartbeat_ms", item.inner_text())
        item.locator("[data-problem-fix=heartbeat]").click()
        self.settled()
        self.assertEqual(pg.locator("#problem-list li", has_text="has no heartbeat or guarding").count(), 0)
        pg.keyboard.press("Control+z")
        self.settled()
        self.assertEqual(pg.locator("#problem-list li", has_text="has no heartbeat or guarding").count(), 1)
        pg.locator("#problem-list [data-problem-fix=none]").click()
        pg.click("#btn-save")
        pg.wait_for_selector("#btn-save:has-text('Saved')")
        self.assertEqual(self.saved()["nodes"][0]["heartbeat_ms"], 0)

    def test_new_node_starts_supervised(self):
        pg = self.page
        cfg = self.config()
        cfg["nodes"] = []
        self.open(cfg)
        # An empty network is a warning with the empty state on its Bus page.
        self.assertEqual(pg.locator("#problem-list li.error").count(), 0)
        self.assertEqual(pg.locator("#problem-list li.warning", has_text="No nodes yet").count(), 1)
        pg.wait_for_selector("[data-empty-nodes]")
        add_node(pg, os.path.join(TWO, "cpp-slave.eds"))
        pg.wait_for_selector('input[data-path="nodes[0].name"]')
        self.settled()
        self.assertEqual(pg.locator("#problem-list li.error").count(), 0, pg.locator("#problem-list").inner_text())
        node_tab(pg, "supervision")
        self.assertEqual(pg.input_value('input[data-path="nodes[0].heartbeat_ms"]'), "1000")
        pg.wait_for_selector("[data-supervision-added]")

    def test_new_config_dialog_and_disk(self):
        pg = self.page
        pg.goto(self.server.url)
        pg.click("#start-new")
        pg.wait_for_selector("[data-new-config=form]")
        pg.fill("[data-new-config=name]", "")
        pg.click("#modal-buttons button[data-value=create]")
        pg.wait_for_selector("[data-new-config=form]")
        self.assertEqual(pg.inner_text("[data-new-config=name-error]"), "Give the new config a name: it becomes its folder.")
        self.assertEqual(pg.inner_text("#modal-text"), "New config")
        self.assertTrue(pg.evaluate("() => document.activeElement.dataset.newConfig === 'name'"))
        pg.click("#modal-buttons button[data-value=cancel]")
        path = os.path.join(self.dir, "line")
        new_config(pg, path, "bridge")
        pg.wait_for_selector("#editor:not([hidden])")
        with open(os.path.join(path, "canworks.json"), encoding="utf-8") as f:
            self.assertIn("bridge", json.load(f))
        pg.reload()
        pg.wait_for_selector("#editor:not([hidden])")
        self.settled()
        self.assertEqual(pg.get_attribute("[data-target-mark]", "data-target-mark"), "bridge")
        self.assertTrue(pg.inner_text("#btn-save").startswith("Saved"))

    def test_handoff_refused_with_an_error(self):
        pg = self.page
        cfg = self.config(node_id=1)  # the master's node ID
        net = {k: cfg[k] for k in ("adapter", "master", "nodes")}
        self.open({"schema_version": 2, "codesys": {}, "networks": [dict(net, name="io")]})
        pg.click("#menu-target > summary")
        pg.click("#btn-codesys-download")
        pg.wait_for_selector("[data-handoff-refused]")
        self.assertIn("The saved config has 1 error", pg.inner_text("[data-handoff-refused]"))
        pg.click("[data-handoff-refused] [data-open-problems]")
        self.assertTrue(pg.evaluate("() => document.querySelector('#problems-box').open"))


if __name__ == "__main__":
    unittest.main()
