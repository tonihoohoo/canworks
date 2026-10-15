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
        # Commission a device opens on the Nodes table, which only points to
        # Connect… in the connection bar, the one place to connect.
        pg = self.page
        pg.goto(self.server.url)
        pg.click("#start-commission")
        pg.wait_for_selector('#view [data-nodes="not-connected"]:has-text("Connect… in the connection bar")')
        self.assertEqual(pg.query_selector_all('#view input[data-online="adapter"], #view button[data-online="connect"]'), [])
        self.assertFalse(pg.is_visible("#conn-dialog"))

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
        # The session log is in Commission only; Configure has none.
        self.assertTrue(pg.is_visible("#log-panel"))
        pg.click('#ws [data-ws="configure"]')
        pg.wait_for_selector("#log-panel", state="hidden")
        self.assertEqual(pg.query_selector_all('[data-online="log-bar"]:visible, [data-online="log"]:visible'), [])


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
        self.open_panel()
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
        # The form stays with the reason and the form filled in.
        pg = self.page
        self.open_panel()
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
        # No dead-end Scan before a connection: the form is the first step.
        self.assertFalse(pg.is_visible('button[data-online="scan"]'))
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
        pg.wait_for_selector('#view [data-nodes="not-connected"]')
        self.assertFalse(self.server.connection.connected)
        self.assertEqual(pg.query_selector_all('tr[data-online-node="7"]'), [])

    def test_recent_connection_and_status_tab(self):
        # commission-workspace 6.2: a recent connection connects in one click,
        # with the bit rate check and Allow changes off; the node opens on Status.
        pg = self.page
        self.device(7, heartbeat_s=0.05)
        self.commission()
        self.connect_adapter(allow=True)
        pg.click('#conn-bar [data-conn="disconnect"]')
        # The recent connections are listed first in the connect panel, the newest focused.
        pg.click('#conn-bar [data-conn="connect"]')
        recent = '#conn-dialog [data-conn="recent"] button[data-conn-recent="0"]'
        pg.wait_for_selector(recent + ':has-text("virtual:%s at 250 kbit/s")' % self.ch)
        self.assertEqual(pg.evaluate("document.activeElement.dataset.connRecent"), "0")
        pg.click(recent)
        pg.wait_for_selector('#conn-bar [data-conn="target"]:has-text("virtual:%s")' % self.ch)
        self.assertIn("Read-only", pg.inner_text("#conn-bar"))
        pg.wait_for_selector('tr[data-online-node="7"]')
        pg.click('button[data-open-node="7"]')
        pg.wait_for_selector('button[data-online-tab="status"][aria-selected="true"]')
        tabs = [b.inner_text() for b in pg.query_selector_all("[data-online-tab]")]
        self.assertEqual([t.split()[0] for t in tabs], ["Status", "Object", "Parameters", "PDO", "Notes", "Log"])
        pg.wait_for_selector('[data-online="node-status"]:has-text("PRE-OPERATIONAL")')
        # The selected tab stays when the node page is drawn again.
        pg.click('button[data-online-tab="log"]')
        pg.click('button[data-open-node="7"]')
        pg.wait_for_selector('button[data-online-tab="log"][aria-selected="true"]')

    def test_unlock_in_place(self):
        # A locked control offers Unlock…: the bar's question, then the control
        # is enabled where it is and keeps the focus.
        pg = self.page
        self.device(2, heartbeat_s=0.05)
        self.commission()
        self.connect_adapter()
        note = '[data-online="lss-no-changes"]'
        pg.wait_for_selector(note + ':has-text("Locked.")')
        self.assertTrue(pg.is_disabled('button[data-online="lss-find"]'))
        pg.click(note + " button[data-unlock]")
        pg.wait_for_selector("#modal:has-text('Allow changes on this adapter connection?')")
        pg.click('#modal button[data-value="allow"]')
        pg.wait_for_selector('#conn-bar:has-text("Changes allowed")')
        pg.wait_for_selector('button[data-online="lss-find"]:not([disabled])')
        pg.wait_for_function("() => document.activeElement.dataset.online === 'lss-find'")
        self.assertEqual(pg.locator(note).count(), 0)
        self.assertNotIn("another master", pg.inner_text("#view"))

    def test_save_log_with_and_without_bus_events(self):
        pg = self.page
        self.device(7, heartbeat_s=0.05)
        self.commission()
        self.connect_adapter()
        pg.wait_for_selector('tr[data-online-node="7"]')
        pg.evaluate("() => { commLog(7, 'test entry', 'done'); commEvent(7, null, 'State test event', 'ok'); }")
        if not pg.evaluate("document.querySelector('#log-box').open"):
            pg.click("#log-box > summary")
        pg.wait_for_selector('#log-panel [data-online="log"] li.event')
        for events, expect in ((False, False), (True, True)):
            box = '#log-panel input[data-online="log-events"]'
            if pg.is_checked(box) != events:
                pg.click(box)
            with pg.expect_download() as dl:
                pg.click('#log-panel button:has-text("Save log")')
            with open(dl.value.path(), encoding="utf-8") as f:
                text = f.read()
            self.assertIn("test entry", text)
            self.assertEqual("(bus)" in text, expect, text)

    def test_trace_records_on_the_adapter(self):
        pg = self.page
        self.device(7, heartbeat_s=0.05)
        self.commission()
        pg.click('button[data-view="trace"]')
        pg.wait_for_selector('[data-trace="online-hint"]:has-text("needs the USB adapter connection")')
        # No Connect button of its own: the bar's Connect… is the one place.
        self.assertEqual(pg.query_selector_all('#view button:has-text("Connect")'), [])
        self.connect_adapter()
        pg.click("[data-trace=start-stop]")
        pg.wait_for_selector("#ids-body [data-ids-key]", timeout=20000)
        self.assertEqual(pg.query_selector_all('[data-trace="online-hint"]'), [])
        self.assertIn("adapter", pg.inner_text("#trace-source"))
        pg.click("[data-trace=start-stop]")


if __name__ == "__main__":
    unittest.main()
