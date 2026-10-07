"""The configurator's USB adapter target and "Commission a device" in a real
browser, on python-can's virtual bus (add-local-bus-commissioning). Needs
Playwright, like test_configurator_page.py."""

import itertools
import os
import threading
import time
import unittest
from unittest import mock

from openplc_canopen_deploy.localbus import adapter as adapter_mod
from openplc_canopen_deploy.localbus import core as core_mod
from openplc_canopen_deploy.localbus import parse
from openplc_canopen_deploy.localbus import sweep as sweep_mod

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


class FastSweep(sweep_mod.Sweep):
    def __init__(self, spec, rates=None, per_rate_ms=1000, *args, **kw):
        super().__init__(spec, rates, 100, *args, **kw)


class DetectPage(AdapterPage):
    """Bit rate detection on a USB adapter: a virtual bus that carries a
    device's heartbeats only when the adapter listens at 250 kbit/s."""

    def setUp(self):
        super().setUp()
        self.opened = []
        real = adapter_mod.open

        def opener(spec, bitrate, listen_only=False, options=None):
            self.opened.append((bitrate, listen_only))
            if listen_only and bitrate != 250000:
                spec = parse("virtual:%s-other-%d" % (self.ch, bitrate))
            return real(spec, bitrate, listen_only, options)

        for p in (mock.patch.object(adapter_mod, "open", opener), mock.patch.object(sweep_mod, "Sweep", FastSweep)):
            p.start()
            self.addCleanup(p.stop)
        self.peer = Peer(self.ch)
        self.running = True
        t = threading.Thread(target=self._traffic, daemon=True)
        t.start()

        def end():
            self.running = False
            t.join()
            self.peer.close()
        self.addCleanup(end)

    def _traffic(self):
        while self.running:
            self.peer.send(0x705, b"\x7f")
            time.sleep(0.02)

    def test_detect_in_the_connection_form(self):
        pg = self.page
        self.open()
        pg.click('button[data-view="online"]')
        pg.check('input[data-online="target-adapter"]')
        pg.wait_for_selector('input[data-online="adapter"]')
        pg.click('button[data-online="adapter-detect"]')
        self.assertIn("Pick or type the adapter", pg.inner_text('[data-online="adapter-detect-msg"]'))
        pg.fill('input[data-online="adapter"]', "virtual:" + self.ch)
        pg.select_option('select[data-online="adapter-bitrate"]', "500")
        pg.click('button[data-online="adapter-detect"]')
        pg.wait_for_selector('[data-online="adapter-detect-msg"]:has-text("250 kbit/s detected")', timeout=20000)
        self.assertEqual(pg.input_value('select[data-online="adapter-bitrate"]'), "250")
        self.assertTrue(all(lo for _, lo in self.opened))  # listen-only only: nothing was sent
        # The picked rate connects.
        pg.click('button[data-online="connect"]')
        pg.wait_for_selector("text=Connected to USB adapter")
        pg.wait_for_selector('#online-conn:has-text("250 kbit/s")')

    def test_detect_on_the_scan_page(self):
        pg = self.page
        self.open()
        pg.click('button[data-view="online"]')
        self.connect_adapter()  # read-only: listening needs no Allow changes
        pg.click('button[data-view="scan"]')
        pg.wait_for_selector('[data-online="detect-box"]')
        self.assertIsNone(pg.query_selector('[data-online="detect-blocked"]'))
        pg.click('[data-online="detect"]')
        pg.wait_for_selector('[data-online="detect-verdict"]', timeout=20000)
        self.assertIn("250 kbit/s detected, the bit rate the USB adapter is set to",
                      pg.inner_text('[data-online="detect-verdict"]'))
        self.assertIn("0x705", pg.inner_text('tr[data-detect-rate="250"]'))
        self.assertEqual(self.opened[-1], (250000, False))  # back at the connection's rate


if __name__ == "__main__":
    unittest.main()
