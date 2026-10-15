"""Commission a CANopen device in a real browser, on python-can's virtual bus
(add-local-bus-commissioning, rework-commission-and-trim-configurator,
ui-shell-and-connection): the connect panel with the bit rate check, the
connection bar with Disconnect and the live Allow changes switch, the Nodes
page, Trace on the adapter, and a config's online view without a USB adapter. Needs Playwright, like test_configurator_page.py."""

import itertools
import os
import threading
import time
import unittest
from unittest import mock

import can

from canworks.localbus import core as core_mod

from .fake_canopen import FakeDevice, Peer
from .helpers import REPO
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

    def listen_long(self):
        # Long enough to hear a 50 ms heartbeat for sure, so the check confirms by traffic.
        p = mock.patch.object(core_mod, "LISTEN_S", 0.3)
        p.start()
        self.addCleanup(p.stop)

    def commission(self):
        # Commission a device opens with the connect panel.
        pg = self.page
        pg.goto(self.server.url)
        pg.click("#start-commission")
        pg.wait_for_selector('#conn-dialog[open] input[data-online="adapter"]')

    def open_panel(self):
        pg = self.page
        if not pg.is_visible("#conn-dialog"):
            pg.click('#conn-bar [data-conn="connect"]')
        pg.wait_for_selector('#conn-dialog[open] input[data-online="adapter"]')

    def connect_adapter(self, allow=False):
        pg = self.page
        self.open_panel()
        pg.fill('#conn-dialog input[data-online="adapter"]', "virtual:" + self.ch)
        pg.select_option('#conn-dialog select[data-online="adapter-bitrate"]', "250")
        if allow:
            pg.check('#conn-dialog input[data-online="adapter-allow"]')
        pg.click('#conn-dialog button[data-online="connect"]')
        pg.wait_for_selector('#conn-bar [data-conn="target"]:has-text("virtual:%s")' % self.ch)
        pg.wait_for_selector("#conn-dialog", state="hidden")


class ConfigModePage(AdapterPage):
    def test_online_is_runtime_only(self):
        pg = self.page
        self.open()
        pg.click('#ws [data-ws="commission"]')
        pg.wait_for_selector("#view h2:has-text('Nodes')")
        self.assertEqual(pg.query_selector_all('input[name="online-target"]'), [])
        self.assertEqual(pg.query_selector_all('input[data-online="adapter"]'), [])
        self.assertEqual(pg.query_selector_all('button[data-view="nodes"]'), [])
        self.assertEqual(pg.query_selector_all('button[data-view="scan"]'), [])
        self.assertFalse(pg.is_visible("#log-panel"))
        self.assertEqual(pg.query_selector_all('[data-online="log-bar"], [data-online="log"]'), [])


class CommissionPage(AdapterPage):
    def test_layout_connect_and_disconnect(self):
        pg = self.page
        self.device(7, heartbeat_s=0.05)
        self.listen_long()
        self.commission()
        self.assertIn("commissioning a device", pg.inner_text("#mode"))
        self.assertFalse(pg.is_visible("#ws"))
        tabs = [b.inner_text() for b in pg.query_selector_all("#tool-tabs [role=tab]")]
        self.assertEqual(tabs, ["Nodes", "Trace", "Frame lab"])
        self.assertFalse(pg.is_visible("#side"))
        self.assertEqual(pg.query_selector_all('[data-online="steps"], [data-online="adapter-detect"], [data-online="detect-lone"]'), [])
        # No bit rate is picked for the user.
        pg.fill('#conn-dialog input[data-online="adapter"]', "virtual:" + self.ch)
        self.assertEqual(pg.input_value('#conn-dialog select[data-online="adapter-bitrate"]'), "")
        pg.click('#conn-dialog button[data-online="connect"]')
        self.assertIn("Pick the bus's bit rate", pg.inner_text('#conn-dialog [data-online="connect-msg"]'))
        pg.select_option('#conn-dialog select[data-online="adapter-bitrate"]', "250")
        pg.click('#conn-dialog button[data-online="connect"]')
        pg.wait_for_selector('#conn-bar [data-conn="rate"]:has-text("250 kbit/s, confirmed by frames on the bus")')
        self.assertFalse(pg.is_visible("#conn-dialog"))
        pg.wait_for_selector('#conn-bar [data-conn="frames"]:not(:has-text("0 frames"))')
        self.assertIn("Read-only", pg.inner_text('#conn-bar'))
        # The connection stays open on the other pages.
        pg.wait_for_selector('tr[data-online-node="7"]:has-text("PRE-OPERATIONAL")')
        pg.click('button[data-view="framelab"]')
        pg.wait_for_selector('#conn-bar [data-conn="target"]')
        self.assertTrue(self.server.connection.connected)
        pg.click('#conn-bar [data-conn="disconnect"]')
        pg.wait_for_selector('#conn-bar [data-conn="state"]:has-text("Not connected")')
        self.assertFalse(self.server.connection.connected)
        self.assertTrue(pg.is_visible('#conn-bar [data-conn="connect"]'))

    def test_wrong_bit_rate_refused(self):
        peer = Peer(self.ch)
        stop = threading.Event()

        def errors():
            while not stop.is_set():
                peer.bus.send(can.Message(arbitration_id=0x008, data=b"\0\0\x02\0\0\0\0\0", is_error_frame=True,
                                          is_extended_id=False))
                time.sleep(0.01)

        t = threading.Thread(target=errors, daemon=True)
        t.start()
        try:
            self.commission()
            self.connect_adapter_refused()
        finally:
            stop.set()
            t.join(1)
            peer.close()
        self.assertFalse(self.server.connection.connected)

    def connect_adapter_refused(self):
        # The panel stays open with the reason and the form filled in.
        pg = self.page
        pg.fill('#conn-dialog input[data-online="adapter"]', "virtual:" + self.ch)
        pg.select_option('#conn-dialog select[data-online="adapter-bitrate"]', "250")
        pg.click('#conn-dialog button[data-online="connect"]')
        pg.wait_for_selector('#conn-dialog [data-online="connect-msg"]:has-text("does not run at 250 kbit/s")')
        self.assertTrue(pg.is_visible('#conn-dialog button[data-online="connect"]'))
        self.assertEqual(pg.input_value('#conn-dialog select[data-online="adapter-bitrate"]'), "250")
        pg.wait_for_selector('#conn-bar.fault [data-conn="ended"]:has-text("does not run at 250 kbit/s")', state="attached")

    def test_allow_changes_keeps_the_connection(self):
        pg = self.page
        self.device(2, heartbeat_s=0.05)
        self.commission()
        self.connect_adapter()
        self.assertIn("Read-only", pg.inner_text("#conn-bar"))
        client = self.server.connection.client
        pg.check('#conn-bar input[data-conn="allow"]')
        pg.click('#modal button[data-value="allow"]')
        pg.wait_for_selector('#conn-bar:has-text("Changes allowed")')
        self.assertIs(self.server.connection.client, client)
        pg.wait_for_selector('button[data-online="lss-find"]:not([disabled])')
        self.assertNotIn("another master", pg.inner_text("#view"))
        with open(os.path.join(self.cfg_dir, "online.json"), encoding="utf-8") as f:
            self.assertNotIn("allow", f.read())

    def test_other_master_asks_before_lss(self):
        pg = self.page
        self.device(None, identity=(0x360, 0x1, 0x2, 0x99))
        peer = Peer(self.ch)
        try:
            self.commission()
            self.connect_adapter(allow=True)
            peer.send(0x080, b"")
            pg.wait_for_selector('#conn-bar.fault [data-conn="other"]')
            pg.click('button[data-online="lss-find"]')
            pg.wait_for_selector("#modal:has-text('another master is active')")
            pg.click('#modal button[data-value="force"]')
            pg.wait_for_selector('[data-online="lss-result"]:has-text("00000099")', timeout=20000)
        finally:
            peer.close()

    def test_nodes_scan_and_add_from_eds(self):
        pg = self.page
        self.device(7, identity=(0x360, 0x1, 0, 0x5))
        self.commission()
        pg.click('#conn-dialog [data-conn="close-panel"]')
        pg.wait_for_selector('[data-online="not-connected"]')
        self.assertTrue(pg.is_disabled('button[data-online="scan"]'))
        pg.click('[data-online="not-connected"] [data-online="open-connect"]')
        self.connect_adapter()
        pg.click('button[data-online="scan"]')
        pg.wait_for_selector('tr[data-online-node="7"]:has-text("scanned")', timeout=20000)
        # No EDS in the library matches: the device's own EDS file opens its object dictionary.
        pg.set_input_files('tr[data-online-node="7"] input[data-online="pick-eds"]',
                           os.path.join(REPO, "config", "gateway", "cpp-slave.eds"))
        pg.wait_for_selector('tr[data-od-key="%d:1"]' % 0x1018, state="attached", timeout=20000)
        self.assertTrue(pg.is_visible('button[data-online="add-to-config"]'))
        # Add node from EDS: a node of this page only.
        pg.set_input_files('input[data-online="add-eds-file"]', os.path.join(REPO, "config", "gateway", "cpp-slave.eds"))
        pg.fill('input[data-online="add-node-id"]', "9")
        pg.click('#modal button[data-value="add"]')
        pg.wait_for_selector('tr[data-online-node="9"]:has-text("added")')
        time.sleep(0.1)

    def test_scan_cancel(self):
        pg = self.page
        self.commission()
        self.connect_adapter()
        pg.click('button[data-online="scan"]')
        pg.wait_for_selector('button[data-online="scan-cancel"]:visible')
        pg.click('button[data-online="scan-cancel"]')
        pg.wait_for_selector('[data-online="scan-progress"]:has-text("Cancelled after")', timeout=10000)
        self.assertFalse(pg.is_visible('button[data-online="scan-cancel"]'))

    def test_commission_after_close_starts_empty(self):
        pg = self.page
        self.device(7, identity=(0x360, 0x1, 0, 0x5))
        self.commission()
        self.connect_adapter()
        pg.click('button[data-online="scan"]')
        pg.wait_for_selector('tr[data-online-node="7"]', timeout=20000)
        pg.click("#btn-close")
        pg.click("#start-commission")
        pg.wait_for_selector('#conn-dialog button[data-online="connect"]')
        self.assertFalse(self.server.connection.connected)
        pg.click('#conn-dialog [data-conn="close-panel"]')
        pg.wait_for_selector('[data-online="not-connected"]')
        self.assertEqual(pg.query_selector_all('tr[data-online-node="7"]'), [])

    def test_trace_records_on_the_adapter(self):
        pg = self.page
        self.device(7, heartbeat_s=0.05)
        self.commission()
        pg.click('#conn-dialog [data-conn="close-panel"]')
        pg.click('button[data-view="trace"]')
        pg.wait_for_selector('[data-trace="online-hint"]:has-text("needs the USB adapter connection")')
        pg.click('[data-trace="open-connect"]')
        self.connect_adapter()
        pg.click("[data-trace=start-stop]")
        pg.wait_for_selector("#ids-body [data-ids-key]", timeout=20000)
        self.assertEqual(pg.query_selector_all('[data-trace="online-hint"]'), [])
        self.assertIn("adapter", pg.inner_text("#trace-source"))
        pg.click("[data-trace=start-stop]")


if __name__ == "__main__":
    unittest.main()
