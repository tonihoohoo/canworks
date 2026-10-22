"""An adapter on another machine in a real browser (add-remote-adapter): the
connect panel's Adapter on another machine in Commission a device and with a
config, the token prompt and the token kept per server, the connection bar
with the server and the round trip, the bit rate warning against the
network's, and the panel at 1000, 1280 and 1440 px. The adapter server runs
in this process on python-can's virtual bus. Needs Playwright, like
test_configurator_page.py."""

import threading
import time
from unittest import mock

from canworks import diag
from canworks.configurator import online
from canworks.localbus import client as client_mod
from canworks.localbus import core as core_mod
from canworks.localbus import parse, serve

from . import fake_tls
from .helpers import tool_tab
from .test_configurator_localbus_page import AdapterPage

TOKEN = "page-adapter-token"


class RemotePage(AdapterPage):
    def setUp(self):
        super().setUp()
        self.log = []
        self.srv = serve.AdapterServer(parse("virtual:" + self.ch), 250000, diag.token_verifier(TOKEN),
                                       bind="127.0.0.1", port=0, listen_s=0.05, name="benchbox",
                                       context=fake_tls.server_context(), cert_hash=fake_tls.CERT_HASH,
                                       log=self.log.append, allow_changes=True)
        threading.Thread(target=self.srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)
        self.address = "127.0.0.1:%d" % self.srv.port
        # The panel's found servers: this one, as discovery would list it.
        found = {"servers": [{"name": "benchbox", "address": self.address, "adapter": "virtual:" + self.ch,
                              "bitrate_kbit": 250}], "discovery": True}
        p = mock.patch.object(online, "adapter_servers_list", lambda wait=2.0: found)
        p.start()
        self.addCleanup(p.stop)

    def wait(self, cond, timeout=3.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if cond():
                return True
            time.sleep(0.05)
        return False

    def pick_server(self):
        pg = self.page
        # One combobox: the found servers are its list, picking one fills the host.
        pg.wait_for_selector('#conn-dialog datalist[data-online="server-list"] option[value="%s"]' % self.address,
                             state="attached")
        pg.wait_for_selector('#conn-dialog [data-online="server-status"]:has-text("1 found")')
        pg.fill('#conn-dialog input[data-online="remote-host"]', self.address)

    def pick_remote(self):
        pg = self.page
        if not pg.is_visible("#conn-dialog"):
            pg.click('#conn-bar [data-conn="connect"]')
        pg.click('#conn-dialog [data-conn-target="remote"]')
        pg.wait_for_selector('#conn-dialog input[data-online="remote-host"]')
        self.assertEqual(pg.inner_text("#conn-dialog-title"), "Connect to an adapter on another machine")

    def connect_remote(self, token=TOKEN):
        pg = self.page
        self.pick_remote()
        self.pick_server()
        pg.wait_for_selector('#conn-dialog [data-online="served"]:has-text("Serves virtual:%s at 250 kbit/s")' % self.ch)
        if token:
            pg.fill('#conn-dialog input[data-online="remote-token"]', token)
        pg.click('#conn-dialog button[data-online="connect"]')


class CommissionRemote(RemotePage):
    def test_connect_token_kept_and_disconnect(self):
        pg = self.page
        self.device(7, heartbeat_s=0.05)
        self.commission()
        # Without a token the panel asks for it and connects nothing.
        self.connect_remote(token=None)
        pg.wait_for_selector('#conn-dialog [data-online="connect-msg"]:has-text("Enter the adapter server\'s token")')
        self.assertFalse(self.srv.status()["pcs"])
        pg.fill('#conn-dialog input[data-online="remote-token"]', TOKEN)
        pg.click('#conn-dialog button[data-online="connect"]')
        target = '#conn-bar [data-conn="target"]:has-text("virtual:%s on %s")' % (self.ch, self.address)
        pg.wait_for_selector(target)
        pg.wait_for_selector('#conn-bar [data-conn="rtt"]:has-text("round trip")')
        self.assertFalse(pg.is_visible("#conn-dialog"))
        self.assertIn("Read-only", pg.inner_text("#conn-bar"))
        pg.wait_for_selector('tr[data-online-node="7"]')
        self.assertEqual(self.srv.status()["pcs"][0]["address"], "127.0.0.1")
        # Disconnect frees the adapter on the server.
        pg.click('#conn-bar [data-conn="disconnect"]')
        pg.wait_for_selector('#conn-bar [data-conn="state"]:has-text("Not connected")')
        self.assertTrue(self.wait(lambda: not self.srv.status()["pcs"]))
        self.assertTrue(self.wait(lambda: "virtual:" + self.ch not in core_mod._cores))
        # The next time the token is not asked again, and the server is a recent connection.
        pg.click('#conn-bar [data-conn="connect"]')
        recent = '#conn-dialog [data-conn="recent"] button[data-conn-recent="0"]'
        pg.wait_for_selector(recent + ':has-text("adapter server %s")' % self.address)
        self.assertEqual(pg.input_value('#conn-dialog input[data-online="remote-token"]'), "")
        pg.click(recent)
        pg.wait_for_selector(target)
        self.assertIn("Read-only", pg.inner_text("#conn-bar"))

    def test_wrong_token_asks_again(self):
        pg = self.page
        self.device(7, heartbeat_s=0.05)
        self.commission()
        with mock.patch.object(serve, "LOGIN_BACKOFF_S", 0.0):
            self.connect_remote(token="not-the-token")
            pg.wait_for_selector('#conn-dialog [data-online="connect-msg"]:has-text("wrong token")')
        self.assertTrue(any("wrong token" in line for line in self.log))
        self.assertEqual(pg.get_attribute('#conn-dialog input[data-online="remote-token"]', "placeholder"),
                         "printed when the server started")

    def test_allow_changes_needs_both(self):
        pg = self.page
        self.device(7, heartbeat_s=0.05)
        self.commission()
        self.pick_remote()
        pg.check('#conn-dialog input[data-online="adapter-allow"]')
        self.connect_remote()
        pg.wait_for_selector('#conn-bar [data-conn="lock-state"]:has-text("Changes allowed")')

    def test_panel_widths(self):
        pg = self.page
        self.commission()
        for width in (1000, 1280, 1440):
            pg.set_viewport_size({"width": width, "height": 800})
            self.pick_remote()
            box = pg.eval_on_selector("#conn-dialog", "d => [d.scrollWidth, d.clientWidth]")
            self.assertLessEqual(box[0], box[1], width)
            targets = pg.eval_on_selector('#conn-dialog [data-conn="targets"]', "e => e.getBoundingClientRect().right")
            dialog = pg.eval_on_selector("#conn-dialog", "e => e.getBoundingClientRect().right")
            self.assertLessEqual(targets, dialog, width)
            pg.click('#conn-dialog [data-conn="close-panel"]')


class RemoteWords(RemotePage):
    """configurator-survive-sleep: an adapter on another machine is never
    called a USB adapter, and its machine's kernel drops are its own."""

    def test_lock_names_the_host(self):
        pg = self.page
        self.device(7, heartbeat_s=0.05)
        self.commission()
        self.connect_remote()
        pg.wait_for_selector('#conn-bar [data-conn="target"]:has-text("on %s")' % self.address)
        note = '[data-online="lss-no-changes"]'
        pg.wait_for_selector(note + ':has-text("Locked.")')
        text = pg.inner_text(note)
        self.assertIn("Changes are off for this connection to the adapter on %s" % self.address, text)
        self.assertNotIn("USB adapter", text)
        self.assertNotIn("USB adapter", pg.evaluate("NO_CHANGES"))

    def test_trace_drops_are_the_adapter_machines(self):
        pg = self.page
        self.device(7, heartbeat_s=0.05)
        real = client_mod.OPS["trace_fetch"]

        def with_drops(c, f):
            return dict(real(c, f), kernel_drops=3)

        p = mock.patch.dict(client_mod.OPS, {"trace_fetch": with_drops})
        p.start()
        self.addCleanup(p.stop)
        self.commission()
        self.connect_remote()
        pg.wait_for_selector('#conn-bar [data-conn="target"]:has-text("on %s")' % self.address)
        tool_tab(pg, "trace")
        pg.click("[data-trace=start-stop]")
        pg.wait_for_selector('#trace-stats:has-text("dropped by")', timeout=20000)
        stats = pg.inner_text("#trace-stats")
        self.assertIn("3 dropped by the adapter machine's kernel (%s)" % self.address, stats)
        self.assertNotIn("PLC", stats)
        self.assertIn("the adapter on %s" % self.address, pg.inner_text("#trace-source"))
        self.assertNotIn("USB adapter", pg.inner_text("#trace-source"))
        pg.click("[data-trace=start-stop]")


class ConfigRemote(RemotePage):
    def test_config_without_online_access_uses_the_server(self):
        # The ping-pong config runs its network at 125 kbit/s; the server serves 250.
        pg = self.page
        self.device(2, heartbeat_s=0.05)
        self.open()
        pg.click('#ws [data-ws="commission"]')
        pg.wait_for_selector("#view h2:has-text('Nodes')")
        pg.click('#conn-bar [data-conn="connect"]')
        pg.wait_for_selector('#conn-dialog [data-conn="targets"] button[data-conn-target="remote"]')
        targets = [b.inner_text() for b in pg.query_selector_all('#conn-dialog [data-conn="targets"] button')]
        self.assertEqual(targets, ["Runtime", "Standalone simulator", "Adapter on another machine"])
        self.assertIn("Online access is off", pg.inner_text("#conn-dialog"))
        self.connect_remote()
        # The warning is in the panel before Connect, and on the page after.
        pg.wait_for_selector('#conn-bar [data-conn="target"]:has-text("on %s")' % self.address)
        pg.wait_for_selector('[data-online="rate-mismatch"]:has-text("runs the bus at 250 kbit/s and the network is set to 125 kbit/s")')
        pg.wait_for_selector('#view [data-online="local-bus"]')
        pg.click('#conn-bar [data-conn="disconnect"]')
        pg.wait_for_selector('#conn-bar [data-conn="connect"]')

    def test_mismatch_warned_before_connect(self):
        pg = self.page
        self.open()
        pg.click('#ws [data-ws="commission"]')
        pg.wait_for_selector("#view h2:has-text('Nodes')")
        self.pick_remote()
        self.pick_server()
        pg.wait_for_selector('#conn-dialog [data-online="rate-mismatch"]:has-text("The server runs the bus at 250 kbit/s and the network is set to 125 kbit/s")')
        self.assertFalse(self.srv.status()["pcs"])
