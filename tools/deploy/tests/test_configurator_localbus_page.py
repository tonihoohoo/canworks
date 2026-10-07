"""The configurator's USB adapter target and "Commission a device" in a real
browser, on python-can's virtual bus (add-local-bus-commissioning). Needs
Playwright, like test_configurator_page.py."""

import itertools
import os
import time
import unittest
from unittest import mock

from openplc_canopen_deploy.localbus import core as core_mod

from .fake_canopen import FakeDevice, Peer
from .test_configurator_online_page import OnlineBase

_n = itertools.count(1)


class AdapterPage(OnlineBase):
    def setUp(self):
        super().setUp()
        self.ch = "page-localbus-%d-%d" % (os.getpid(), next(_n))
        p = mock.patch.object(core_mod, "LISTEN_S", 0.05)
        p.start()
        self.addCleanup(p.stop)
        self.devices = []

    def tearDown(self):
        self.server.connection.close()
        for d in self.devices:
            d.close()
        super().tearDown()

    def device(self, node, **kw):
        d = FakeDevice(self.ch, node, **kw)
        self.devices.append(d)
        return d

    def connect_adapter(self, allow=False):
        pg = self.page
        pg.check('input[data-online="target-adapter"]')
        pg.wait_for_selector('input[data-online="adapter"]')
        pg.fill('input[data-online="adapter"]', "virtual:" + self.ch)
        pg.select_option('select[data-online="adapter-bitrate"]', "250")
        if allow:
            pg.check('input[data-online="adapter-allow"]')
        pg.click('button[data-online="connect"]')
        pg.wait_for_selector("text=Connected to USB adapter")

    def test_online_view_on_an_adapter(self):
        pg = self.page
        d = self.device(2, heartbeat_s=0.05)
        self.open()  # the config has no online access: no token needed for an adapter
        pg.click('button[data-view="online"]')
        self.connect_adapter()
        pg.wait_for_selector('[data-online="local-nodes"] tr[data-online-node="2"]:has-text("PRE-OPERATIONAL")')
        self.assertIn("read-only", pg.inner_text("#online-conn"))
        self.assertTrue(pg.is_disabled('button[data-online="lss-find"]'))
        pg.click('button[data-online="adapter-allow-toggle"]')
        pg.click('#modal button[data-value="allow"]')
        pg.wait_for_selector('#online-conn:has-text("changes allowed")')
        pg.wait_for_selector('button[data-online="lss-find"]:not([disabled])')
        with open(os.path.join(self.cfg_dir, "online.json"), encoding="utf-8") as f:
            self.assertNotIn("allow", f.read())
        del d

    def test_other_master_asks_before_lss(self):
        pg = self.page
        self.device(None, identity=(0x360, 0x1, 0x2, 0x99))
        peer = Peer(self.ch)
        try:
            self.open()
            pg.click('button[data-view="online"]')
            self.connect_adapter(allow=True)
            peer.send(0x080, b"")
            pg.wait_for_selector('[data-online="other-master"]')
            pg.click('button[data-online="lss-find"]')
            pg.wait_for_selector("#modal:has-text('another master is active')")
            pg.click('#modal button[data-value="force"]')
            pg.wait_for_selector('[data-online="lss-result"]:has-text("00000099")', timeout=20000)
        finally:
            peer.close()

    def test_commission_a_device(self):
        pg = self.page
        self.device(7, identity=(0x360, 0x1, 0, 0x5))
        pg.goto(self.server.url)
        pg.click("#start-commission")
        pg.wait_for_selector('input[data-online="adapter"]')
        self.assertIn("commissioning a device", pg.inner_text("#mode"))
        pg.fill('input[data-online="adapter"]', "virtual:" + self.ch)
        pg.click('button[data-online="connect"]')
        pg.wait_for_selector("text=Connected to USB adapter")
        pg.click('button[data-view="scan"]')
        pg.click('button[data-online="scan"]')
        pg.wait_for_selector('tr[data-scan-node="7"]', timeout=20000)
        self.assertEqual(pg.query_selector_all('button[data-online="add-node"]'), [])
        time.sleep(0.1)


if __name__ == "__main__":
    unittest.main()
