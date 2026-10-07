"""Slave networks and the gateway in the configurator page (add-canopen-slave
tasks 4.1 and 6.8): the role switch, building, binding and exporting the
slave EDS, and the gateway page. Needs Playwright, like
test_configurator_page.py."""

import json
import os
import shutil
import threading
import unittest

from openplc_canopen_deploy.configurator import server as srv

from .helpers import PINGPONG, REPO, tmpdir
from .test_configurator_page import REQUIRED, load, sync_playwright

GATEWAY = os.path.join(REPO, "config", "gateway")


@unittest.skipIf(sync_playwright is None and not REQUIRED, "Playwright for Python is not installed")
class SlavePage(unittest.TestCase):
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
        os.environ["OPENPLC_CANOPEN_CONFIG_DIR"] = os.path.join(self.dir, "cfg")
        self.addCleanup(os.environ.pop, "OPENPLC_CANOPEN_CONFIG_DIR", None)
        self.folder = os.path.join(self.dir, "plant")
        os.makedirs(self.folder)
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

    @property
    def config_path(self):
        return os.path.join(self.folder, "canopen.json")

    def write(self, cfg):
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)

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

    def problems(self, none):
        # The check runs after a short pause, so wait for its result rather
        # than for "not checking" (which holds before it starts).
        try:
            self.page.wait_for_function(
                "(none) => (document.querySelector('#problem-count').innerText === 'none') === none", arg=none,
                timeout=5000)
        except Exception:
            pass
        self.settled()
        return self.page.inner_text("#problem-count"), self.page.inner_text("#problem-list")

    def save(self):
        self.settled()
        self.page.click("#btn-save")
        self.page.wait_for_selector("#banner:has-text('Saved')")

    def answer(self, value):
        self.page.click('#modal-buttons button[data-value="%s"]' % value)

    def test_slave_network_build_bind_export(self):
        pg = self.page
        shutil.copy(os.path.join(PINGPONG, "cpp-slave.eds"), self.folder)
        self.write(load(os.path.join(PINGPONG, "canopen_config.json")))
        self.open()
        pg.click('#net-bar button[data-net-action="add"]')
        pg.fill('#view input[data-path="adapter.interface"]', "vcan1")
        pg.select_option('#view select[data-path="role"]', "slave")
        pg.wait_for_selector("#view h2:has-text('Bus and slave device')")
        self.assertEqual(pg.locator("#view legend:has-text('Master')").count(), 0)
        self.assertTrue(pg.is_hidden("label.file-button:has(#eds-input)"))
        self.assertTrue(pg.is_visible("#nav-gateway"))
        # Build: two objects, generate, bind both.
        pg.click("[data-add-desc-object]")
        pg.click("[data-add-desc-object]")
        pg.select_option('tr[data-desc-object="1"] select[data-desc="direction"]', "to_master")
        pg.click("[data-generate]")
        pg.wait_for_selector("#modal-buttons button[data-value=bind]")
        self.assertIn("Generated openplc-slave.eds", pg.inner_text("#modal-text"))
        self.answer("bind")
        pg.wait_for_selector('[data-slave-objects] tr[data-object="0x2100:1"]')
        self.assertEqual(pg.locator("[data-slave-objects] tr[data-object]").count(), 2)
        count, text = self.problems(True)
        self.assertEqual(count, "none", text)
        # The area must match the direction.
        pg.fill('input[data-path="slave.objects[1].iec_location"]', "%IW500")
        self.settled()
        self.assertIn("needs a %Q location", pg.inner_text("#problem-list"))
        pg.click('tr[data-object="0x2100:1"] button[data-suggest="slave_object"]')
        count, text = self.problems(True)
        self.assertEqual(count, "none", text)
        self.save()
        saved = load(self.config_path)
        net = saved["networks"][1]
        self.assertEqual(net["role"], "slave")
        self.assertEqual(net["slave"]["eds"], "openplc-slave.eds")
        self.assertEqual([o["index"] for o in net["slave"]["objects"]], ["0x2000", "0x2100"])
        self.assertTrue(net["slave"]["objects"][1]["iec_location"].startswith("%QW"))
        self.assertTrue(os.path.isfile(os.path.join(self.folder, "openplc-slave.eds")))
        self.assertTrue(os.path.isfile(os.path.join(self.folder, "openplc-slave.eds.json")))
        with pg.expect_download() as d:
            pg.click("[data-export-eds]")
        self.assertEqual(d.value.suggested_filename, "openplc-slave.eds")
        with open(d.value.path(), "rb") as f, open(os.path.join(self.folder, "openplc-slave.eds"), "rb") as g:
            self.assertEqual(f.read(), g.read())
        # Back to master: asked first, then an empty master network.
        pg.select_option('#view select[data-path="role"]', "")
        self.answer("master")
        pg.wait_for_selector("#view legend:has-text('Master')")
        self.assertTrue(pg.is_visible("label.file-button:has(#eds-input)"))

    def test_gateway_page(self):
        pg = self.page
        for name in ("cpp-slave.eds", "openplc-gateway.eds"):
            shutil.copy(os.path.join(GATEWAY, name), self.folder)
        self.write(load(os.path.join(GATEWAY, "canopen_config.json")))
        self.open()
        count, text = self.problems(True)
        self.assertEqual(count, "none", text)
        pg.click("#nav-gateway")
        pg.wait_for_selector("#view h2:has-text('Gateway')")
        self.assertEqual(pg.locator("tr[data-route]").count(), 2)
        self.assertEqual(pg.input_value('select[data-path="gateway.upper"]'), "upper")
        self.assertIn("0x4001:0", pg.inner_text('tr[data-route="0"] select[data-path="gateway.routes[0].field"] option:checked'))
        pg.click("[data-add-route]")
        self.assertEqual(pg.locator("tr[data-route]").count(), 3)
        count, text = self.problems(False)
        self.assertNotEqual(count, "none", text)
        pg.click('tr[data-route="2"] button:has-text("Remove")')
        pg.select_option('select[data-path="gateway.on_upper_loss"]', "stop_nodes")
        self.save()
        saved = load(self.config_path)
        self.assertEqual(saved["gateway"]["on_upper_loss"], "stop_nodes")
        self.assertEqual(len(saved["gateway"]["routes"]), 2)
