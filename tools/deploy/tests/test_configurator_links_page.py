"""The PDO links page and the heartbeat watch in a real browser (spec
canopen-configurator, "Links table", "Heartbeat watch setting"): a link
added from node 10 TPDO 1 to node 20 with a dummy entry and the producer
watched, a size mismatch marked and refused, the link's removal asked for
with its producer TPDO, and the watch's default timeout. On a copy of
examples/pdo-link. Needs Playwright, like test_configurator_page.py."""

import json
import os
import shutil
import threading
import unittest

from canworks.configurator import server as srv

from .helpers import REPO, tmpdir, tree_node, tree_view
from .test_configurator_page import REQUIRED, sync_playwright

EXAMPLE = os.path.join(REPO, "examples", "pdo-link")


@unittest.skipIf(sync_playwright is None and not REQUIRED, "Playwright for Python is not installed")
class LinksPage(unittest.TestCase):
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
        self.folder = os.path.join(self.dir, "pdo-link")
        shutil.copytree(EXAMPLE, self.folder)
        self.server = srv.Server()
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.context = self.browser.new_context(viewport={"width": 1280, "height": 900})
        self.addCleanup(self.context.close)
        self.page = self.context.new_page()
        self.page.set_default_timeout(10000)
        self.errors = []
        self.page.on("pageerror", lambda e: self.errors.append(str(e)))

    def tearDown(self):
        self.assertEqual(self.errors, [])

    @property
    def path(self):
        return os.path.join(self.folder, "canworks.json")

    def config(self):
        with open(self.path, encoding="utf-8") as f:
            return json.load(f)

    def write(self, cfg):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)

    def open(self):
        pg = self.page
        pg.goto(self.server.url)
        pg.click("#start-open")
        pg.fill("[data-folder=path]", self.folder)
        pg.click("[data-folder=dialog] [data-value=use]")
        pg.wait_for_selector("#editor:not([hidden])")
        self.checked()

    def checked(self):
        self.page.wait_for_function("() => document.body.dataset.checking !== '1'")

    def test_add_link(self):
        cfg = self.config()
        del cfg["links"]
        del cfg["nodes"][1]["heartbeat_watch"]
        cfg["nodes"][0]["tx_pdos"][0]["entries"][1]["iec_location"] = "%IW101"
        self.write(cfg)
        pg = self.page
        self.open()
        tree_view(pg, "links")
        pg.wait_for_selector("h2:has-text('PDO links')")
        pg.click('button[data-link-new="1"]')
        pg.wait_for_selector('fieldset[data-link="0"]')
        self.assertEqual(pg.input_value('select[data-path="links[0].from.node"]'), "10")
        self.assertEqual(pg.inner_text('output[data-link-cob="0"]'), "0x18A")
        pg.select_option('select[data-link-add="0"]', "20")
        pg.wait_for_selector('select[data-path="links[0].to[0].rpdo"]')
        pg.select_option('select[data-path="links[0].to[0].rpdo"]', "2")
        pg.select_option('select[data-path="links[0].to[0].entries[0]"]', "0x6411:1")
        pg.select_option('select[data-path="links[0].to[0].entries[1]"]', "0x0003:0")
        self.checked()
        self.assertEqual(pg.inner_text("#problem-list"), "No problems.")
        self.assertTrue(pg.is_checked('input[data-link-watch="links[0].to[0]"]'))
        pg.click("#btn-save")
        pg.wait_for_selector("#btn-save:has-text('Saved')")
        saved = self.config()
        self.assertEqual(saved["links"], [{"from": {"node": 10, "tpdo": 1}, "to": [
            {"node": 20, "rpdo": 2, "entries": [{"index": "0x6411", "subindex": 1, "type": "INTEGER16"},
                                                 {"index": "0x0003", "subindex": 0, "type": "INTEGER16"}]}]}])
        self.assertEqual(saved["nodes"][1]["heartbeat_watch"], [{"node": 10}])

    def test_size_mismatch_marked(self):
        cfg = self.config()
        cfg["links"][0]["to"][0]["entries"][0] = {"index": "0x2001", "subindex": 0, "type": "UNSIGNED8"}
        self.write(cfg)
        pg = self.page
        self.open()
        tree_view(pg, "links")
        pg.wait_for_selector('fieldset[data-link="0"]')
        pg.wait_for_selector("#problem-list li.error")
        self.assertTrue(pg.is_visible('.link-pos.bad[data-link-pos="0"]'))
        problems = pg.inner_text("#problem-list")
        self.assertIn("PDO links", problems)
        self.assertIn("RPDO 2 maps 24 bits in 2 positions", problems)
        self.assertIn("32 bits in 2 positions", problems)
        self.assertNotIn("stick_to_valves: link", problems)  # the place, said once
        pg.fill('input[data-path="links[0].name"]', "stick_valves")
        self.checked()
        self.assertGreater(pg.locator("#problem-list li.error").count(), 0)

    def test_producer_removed_asks(self):
        pg = self.page
        self.open()
        tree_node(pg, 0, "pdos")
        pg.click('button[data-remove-pdo="nodes[0].tx_pdos[0]"]')
        pg.wait_for_selector("#modal[open]")
        self.assertIn("feeds link stick_to_valves", pg.inner_text("#modal-text"))
        pg.keyboard.press("Enter")  # the default: cancel
        pg.wait_for_selector("#modal", state="hidden")
        self.assertEqual(pg.evaluate("() => S.config.links.length"), 1)
        self.assertEqual(pg.evaluate("() => S.config.nodes[0].tx_pdos.length"), 1)
        pg.click('button[data-remove-pdo="nodes[0].tx_pdos[0]"]')
        pg.click('#modal button[data-value="remove"]')
        self.assertEqual(pg.evaluate("() => S.config.links"), None)

    def test_node_id_change_and_removal_follow(self):
        """Links and heartbeat watches follow a node ID; removing the node
        lists them and removes them with it."""
        pg = self.page
        self.open()
        tree_node(pg, 0, "general")
        pg.fill('#view input[data-path="nodes[0].node_id"]', "")
        pg.type('#view input[data-path="nodes[0].node_id"]', "11")
        self.assertEqual(pg.evaluate("() => S.config.links[0].from.node"), 11)
        self.assertEqual(pg.evaluate("() => S.config.nodes[1].heartbeat_watch"), [{"node": 11}])
        tree_node(pg, 1, "general")
        pg.fill('#view input[data-path="nodes[1].node_id"]', "21")
        self.assertEqual(pg.evaluate("() => S.config.links[0].to[0].node"), 21)
        self.checked()
        self.assertEqual(pg.inner_text("#problem-list"), "No problems.")
        tree_node(pg, 0, "general")
        pg.click('button[data-remove-node="0"]')
        pg.wait_for_selector("#modal[open]")
        text = pg.inner_text("#modal-text")
        self.assertIn("link stick_to_valves", text)
        self.assertIn("the heartbeat watch of node 21 valves", text)
        pg.click('#modal button[data-value="remove"]')
        self.assertIsNone(pg.evaluate("() => S.config.links || null"))
        self.assertIsNone(pg.evaluate("() => S.config.nodes[0].heartbeat_watch || null"))
        self.checked()
        self.assertEqual(pg.inner_text("#problem-list"), "No problems.")

    def test_watch_problem_wording(self):
        cfg = self.config()
        cfg["nodes"][1]["heartbeat_watch"] = [{"node": 99}]
        self.write(cfg)
        pg = self.page
        self.open()
        pg.wait_for_selector("#problem-list li.error")
        problems = pg.inner_text("#problem-list")
        self.assertIn("Node 20 valves: heartbeat watch: node 99 is not a configured node", problems)
        self.assertNotIn("heartbeat_watch", problems)

    def test_master_id_clash_names_the_node(self):
        pg = self.page
        self.open()
        pg.fill('input[data-path="master.node_id"]', "10")
        pg.wait_for_selector('input[data-path="master.node_id"].invalid')
        self.assertEqual(pg.inner_text('.field-msg[data-for="master.node_id"]'),
                         "Node 10 stick: node ID 10 is the master's node ID")

    def test_watch_default_timeout(self):
        pg = self.page
        self.open()
        tree_node(pg, 1, "supervision")
        pg.wait_for_selector('input[data-path="nodes[1].heartbeat_watch[0].timeout_ms"]')
        self.assertEqual(pg.get_attribute('input[data-path="nodes[1].heartbeat_watch[0].timeout_ms"]', "placeholder"),
                         "default (300 ms)")
        self.assertEqual(self.config()["nodes"][1]["heartbeat_watch"], [{"node": 10}])


if __name__ == "__main__":
    unittest.main()
