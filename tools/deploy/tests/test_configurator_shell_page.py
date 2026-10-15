"""The configurator's shell in a real browser (ui-shell-and-connection): the
Configure and Commission workspaces, the tool tabs, the connection bar and
connect panel, the jobs in the status bar and the bottom panel. Against the
fake plugin for a runtime, and python-can's virtual bus for a USB adapter.
Needs Playwright, like test_configurator_page.py."""

import os
import time

from canworks import diag

from .fake_canopen import FakeDevice
from .fake_diag import TOKEN, FakePlugin
from .test_configurator_layout import audit
from .test_configurator_localbus_page import AdapterPage
from .test_configurator_online_page import OnlineBase


class Workspaces(OnlineBase):
    def runtime(self, fp):
        self.write_config({"token_verifier": diag.token_verifier(TOKEN), "allow_changes": False})
        self.remember(fp.runtime)
        self.open()

    def test_switch_keeps_draft_and_connection(self):
        pg = self.page
        with FakePlugin() as fp:
            self.runtime(fp)
            # Configure: the config pages and its tools, no connection bar until connected.
            tabs = [b.inner_text() for b in pg.query_selector_all("#tool-tabs [role=tab]")]
            self.assertEqual(tabs, ["Network", "Variable declarations", "Simulation", "Trace", "Frame lab"])
            self.assertFalse(pg.is_visible("#conn-bar"))
            self.assertTrue(pg.is_visible("#side"))
            self.assertTrue(pg.is_visible("#problems"))
            pg.fill('input[data-path="master.node_id"]', "3")
            pg.wait_for_selector("#btn-save:has-text('Save')")
            self.assertTrue(pg.is_visible("[data-unsaved]"))
            # Commission: the runtime connects at once (host and token are on this PC).
            pg.click('#ws [data-ws="commission"]')
            pg.wait_for_selector('tr[data-online-node="2"]')
            tabs = [b.inner_text() for b in pg.query_selector_all("#tool-tabs [role=tab]")]
            self.assertEqual(tabs, ["Nodes", "Simulation", "Trace", "Frame lab"])
            self.assertFalse(pg.is_visible("#side"))
            self.assertIn(fp.runtime, pg.inner_text('#conn-bar [data-conn="target"]'))
            self.assertIn("Read-only (runtime setting)", pg.inner_text('#conn-bar [data-conn="allow"]'))
            self.assertEqual(pg.query_selector_all('#conn-bar input[data-conn="allow"]'), [])
            self.assertFalse(pg.evaluate("() => document.querySelector('#problems-box').open"))
            # Back to Configure: the draft and the connection are as they were.
            pg.click('#ws [data-ws="configure"]')
            self.assertEqual(pg.input_value('input[data-path="master.node_id"]'), "3")
            self.assertEqual(pg.inner_text("#btn-save"), "Save")
            self.assertTrue(pg.is_visible('#conn-bar [data-conn="disconnect"]'))
            self.assertTrue(self.server.connection.connected)

    def test_reload_keeps_the_workspace(self):
        pg = self.page
        with FakePlugin() as fp:
            self.runtime(fp)
            pg.click('#ws [data-ws="commission"]')
            pg.wait_for_selector('tr[data-online-node="2"]')
            pg.reload()
            pg.wait_for_selector('#ws [data-ws="commission"][aria-pressed="true"]')
            pg.wait_for_selector('tr[data-online-node="2"]')

    def test_tools_take_the_whole_width(self):
        pg = self.page
        self.open()
        pg.click('#tool-tabs button[data-view="framelab"]')
        pg.wait_for_selector("#view h2:has-text('Frame lab')")
        self.assertFalse(pg.is_visible("#side"))
        self.assertFalse(pg.is_visible("#problems"))
        view = pg.locator("#view").bounding_box()
        self.assertGreater(view["width"], 1200)
        # Network goes back to the page the user was on.
        pg.click('#tool-tabs button[data-view="network"]')
        pg.wait_for_selector("#side")
        self.assertTrue(pg.is_visible("#problems"))

    def test_one_time_note(self):
        pg = self.page
        self.open()
        pg.wait_for_selector("[data-ws-note]")
        pg.click('#ws [data-ws="commission"]')
        self.assertEqual(pg.query_selector_all("[data-ws-note]"), [])
        pg.click("#btn-close")
        self.open()
        self.assertEqual(pg.query_selector_all("[data-ws-note]"), [])

    def test_trace_without_a_connection_offers_connect(self):
        pg = self.page
        self.write_config({"token_verifier": diag.token_verifier(TOKEN)})
        self.open()
        pg.click('#tool-tabs button[data-view="trace"]')
        pg.wait_for_selector('[data-trace="online-hint"]:has-text("needs the connection to the runtime")')
        pg.click('[data-trace="open-connect"]')
        pg.wait_for_selector('#conn-dialog[open] input[data-online="host"]')
        self.assertEqual(pg.query_selector_all('#view input[data-online="host"]'), [])

    def test_trace_and_simulation_use_the_bar_connection(self):
        pg = self.page
        with FakePlugin() as fp:
            self.runtime(fp)
            pg.click('#tool-tabs button[data-view="simulation"]')
            pg.wait_for_selector('#conn-bar [data-conn="target"]')
            self.assertEqual(pg.query_selector_all('#view input[data-online="host"]'), [])
            pg.click('#tool-tabs button[data-view="trace"]')
            self.assertEqual(pg.query_selector_all('[data-trace="online-hint"]'), [])
            # Disconnect: the tools offer Connect… instead of a form of their own.
            pg.click('#conn-bar [data-conn="disconnect"]')
            pg.wait_for_selector('[data-trace="open-connect"]')
            pg.click('#tool-tabs button[data-view="simulation"]')
            pg.wait_for_selector('[data-sim="open-connect"]')

    def test_runtime_bar_and_panel_audit(self):
        pg = self.page
        with FakePlugin() as fp:
            self.runtime(fp)
            pg.click('#ws [data-ws="commission"]')
            pg.wait_for_selector('#conn-bar [data-conn="target"]')
            for theme in ("light", "dark"):
                pg.evaluate("(t) => { document.documentElement.dataset.theme = t; }", theme)
                audit(pg, "commission, connected, %s" % theme)
            pg.click('#conn-bar [data-conn="disconnect"]')
            pg.click('#conn-bar [data-conn="connect"]')
            pg.wait_for_selector('#conn-dialog[open] input[data-online="host"]')
            audit(pg, "connect panel")

    def test_lost_runtime_is_shown_in_the_bar(self):
        pg = self.page
        with FakePlugin() as fp:
            self.runtime(fp)
            pg.click('#ws [data-ws="commission"]')
            pg.wait_for_selector('#conn-bar [data-conn="target"]')
            fp.outage()
            pg.wait_for_selector('#conn-bar.fault[role="alert"] [data-conn="state"]:has-text("not answering")', timeout=8000)
            pg.wait_for_selector('#conn-bar [data-conn="state"]:has-text("last data")', timeout=8000)
            fp.restart()
            pg.wait_for_selector('#conn-bar:not(.fault) [data-conn="target"]', timeout=8000)

    def test_cancel_asks_for_a_restore(self):
        # The status bar's Cancel of a job that writes to a device asks first.
        pg = self.page
        self.open()
        pg.evaluate("""() => { JOBS.list = [{ id: "params-1", kind: "restore", label: "Restore node 5", done: 3, total: 10,
            stop: { path: "/api/online/job", body: { job: 1, cancel: true } }, confirm: "Cancel restore of node 5? What was written stays written." }];
            renderJobs(); }""")
        self.assertIn("Restore node 5 – 3/10", pg.inner_text("#jobs"))
        pg.click('#jobs [data-job-cancel="params-1"]')
        pg.wait_for_selector("#modal[open]:has-text('What was written stays written')")
        self.assertEqual(pg.evaluate("() => document.activeElement.dataset.value"), "cancel")
        pg.click('#modal button[data-value="cancel"]')

    def test_narrow_window_keeps_problems_in_the_bottom_panel(self):
        pg = self.page
        pg.set_viewport_size({"width": 900, "height": 800})
        self.open()
        pg.fill('input[data-path="master.node_id"]', "200")
        pg.wait_for_selector("#problem-count:not(:empty)")
        box = pg.locator("#problems-box > summary").bounding_box()
        self.assertLess(box["y"] + box["height"], 800)
        self.assertGreater(box["y"], 400)


class AdapterJobs(AdapterPage):
    def test_scan_cancelled_from_the_status_bar(self):
        pg = self.page
        self.commission()
        self.connect_adapter()
        pg.click('button[data-online="scan"]')
        pg.click('#tool-tabs button[data-view="framelab"]')
        pg.wait_for_selector('#jobs [data-job="scan"]:has-text("Scan the bus")')
        pg.click('#jobs [data-job-cancel="scan"]')
        pg.wait_for_selector('#jobs [data-job="scan"]', state="detached", timeout=10000)
        pg.click('#tool-tabs button[data-view="nodes"]')
        pg.wait_for_selector('[data-online="scan-progress"]:has-text("Cancelled after")', timeout=10000)

    def test_job_without_a_stop_has_no_cancel(self):
        # LSS find ends by itself (at most about 15 s): listed, without Cancel.
        pg = self.page
        self.commission()
        pg.evaluate("""() => { JOBS.list = [{ id: "lss_find", kind: "lss_find", label: "LSS: finding a device without node ID",
            done: 2, total: null, unit: "s", stop: null, confirm: null }]; renderJobs(); }""")
        self.assertIn("LSS: finding a device without node ID – 2 s", pg.inner_text("#jobs"))
        self.assertEqual(pg.query_selector_all('#jobs [data-job-cancel="lss_find"]'), [])

    def test_frame_rate_and_keyboard(self):
        pg = self.page
        self.device(7, heartbeat_s=0.02)
        self.commission()
        self.connect_adapter()
        pg.wait_for_selector("#bus-info:has-text('frames/s')", timeout=10000)
        self.assertIn("bus load about", pg.inner_text("#bus-info"))
        # Keyboard only: the tool tabs move with the arrow keys, Disconnect is reachable.
        pg.focus('#tool-tabs [role=tab][aria-selected="true"]')
        pg.keyboard.press("ArrowRight")
        pg.wait_for_selector('#tool-tabs button[data-view="trace"][aria-selected="true"]')
        pg.focus('#conn-bar [data-conn="disconnect"]')
        pg.keyboard.press("Enter")
        pg.wait_for_selector('#conn-bar [data-conn="state"]:has-text("Not connected")')
        audit(pg, "commission a device, not connected")
        time.sleep(0.1)

    def device(self, node, **kw):
        d = FakeDevice(self.ch, node, **kw)
        self.devices.append(d)
        return d


del AdapterPage
del OnlineBase
