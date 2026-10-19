"""Quit, the leave-page question and closing the last tab, in a real browser
(configurator-quit-and-background). Needs Playwright, like
test_configurator_page.py."""

import json
import os
import time

from .test_configurator_layout import FIT_CHECK
from .test_configurator_localbus_page import AdapterPage
from .test_configurator_online_page import OnlineBase


class Base(OnlineBase):
    def quit_dialog(self):
        pg = self.page
        pg.click("#btn-quit")
        pg.wait_for_selector("#modal[open]")
        return pg.inner_text("#modal-text"), pg.eval_on_selector_all(
            "#modal-buttons button", "bs => bs.map((b) => b.dataset.value)")

    def stopped(self):
        """The page shows the stopped notice and the configurator no longer serves."""
        pg = self.page
        pg.wait_for_selector("#stopped")
        self.assertIn("canworks-config has stopped. You can close this tab.", pg.inner_text("#stopped"))
        self.assertIn("start it again", pg.inner_text("#stopped"))
        self.assertFalse(pg.is_visible("#top"))
        deadline = time.monotonic() + 5
        while self.server.socket.fileno() != -1 and time.monotonic() < deadline:
            try:
                self.server.socket.getsockname()
                if self.server.stopped_why == "Quit":
                    break
            except OSError:
                break
            time.sleep(0.05)
        self.assertEqual(self.server.stopped_why, "Quit")

    def dirty(self):
        pg = self.page
        self.open()
        pg.evaluate("() => { S.config.nodes[0].name = 'renamed'; changed(true); }")
        pg.wait_for_selector('[data-unsaved="1"]:not([hidden])')

    def saved_name(self):
        with open(self.config_path, encoding="utf-8") as f:
            return json.load(f)["nodes"][0]["name"]


class Quit(Base):
    def test_asks_and_cancel_keeps_it(self):
        pg = self.page
        pg.goto(self.server.url)
        pg.wait_for_selector("#start:not([hidden])")
        self.assertTrue(pg.is_visible("#btn-quit"))  # on the start page too
        text, buttons = self.quit_dialog()
        self.assertEqual((text, buttons), ("Quit canworks-config?", ["cancel", "quit"]))
        pg.click('#modal button[data-value="cancel"]')
        pg.wait_for_selector("#modal", state="hidden")
        self.assertIsNone(self.server.stopped_why)
        self.assertEqual(pg.evaluate("async () => (await api('GET', '/api/state')).mode"), None)
        self.quit_dialog()
        pg.click('#modal button[data-value="quit"]')
        self.stopped()
        # Leaving the stopped page asks nothing.
        asked = []
        pg.on("dialog", lambda d: (asked.append(d.type), d.accept()))
        pg.close(run_before_unload=True)
        self.assertEqual(asked, [])

    def test_unsaved_cancel(self):
        self.dirty()
        text, buttons = self.quit_dialog()
        self.assertIn("There are unsaved changes.", text)
        self.assertEqual(buttons, ["cancel", "save", "quit"])
        self.page.click('#modal button[data-value="cancel"]')
        self.page.wait_for_selector("#modal", state="hidden")
        self.assertTrue(self.page.evaluate("S.dirty"))
        self.assertIsNone(self.server.stopped_why)

    def test_unsaved_quit_without_saving(self):
        before = self.saved_name()
        self.dirty()
        self.quit_dialog()
        self.page.click('#modal button[data-value="quit"]')
        self.stopped()
        self.assertEqual(self.saved_name(), before)

    def test_unsaved_save_and_quit(self):
        self.dirty()
        self.quit_dialog()
        self.page.click('#modal button[data-value="save"]')
        self.stopped()
        self.assertEqual(self.saved_name(), "renamed")

    def test_fits(self):
        pg = self.page
        widths = (1000, 1280, 1440)
        pg.goto(self.server.url)
        pg.wait_for_selector("#start:not([hidden])")
        for where in ("start page", "editor"):
            if where == "editor":
                self.open()
            for width in widths:
                pg.set_viewport_size({"width": width, "height": 800})
                pg.wait_for_timeout(100)
                self.assertEqual(pg.evaluate(FIT_CHECK), [], "%s at %d" % (where, width))
                box = pg.locator("#btn-quit").bounding_box()
                self.assertLessEqual(box["x"] + box["width"], width, "%s at %d" % (where, width))
                self.quit_dialog()
                self.assertEqual(pg.evaluate(FIT_CHECK), [], "quit dialog at %d" % width)
                pg.click('#modal button[data-value="cancel"]')


class Leave(Base):
    def test_closing_asks_with_nothing_unsaved(self):
        pg = self.page
        pg.goto(self.server.url)
        pg.click("#start-intro")  # the browser asks only after the user did something on the page
        self.assertFalse(pg.evaluate("unsavedWork()"))
        asked = []
        pg.on("dialog", lambda d: (asked.append(d.type), d.dismiss()))
        pg.close(run_before_unload=True)
        other = self.context.new_page()  # takes Playwright's events while the question is open
        deadline = time.monotonic() + 5
        while not asked and time.monotonic() < deadline:
            other.wait_for_timeout(50)
        self.assertEqual(asked, ["beforeunload"])
        self.assertFalse(pg.is_closed())  # Cancel kept it

    def test_closing_the_last_tab_stops_it(self):
        pg = self.page
        self.server.stop_unused, self.server.closed_s, self.server.tick_s = True, 0.3, 0.05
        self.server.start_watch()
        pg.goto(self.server.url)
        pg.wait_for_selector("#start:not([hidden])")
        deadline = time.monotonic() + 5
        while not self.server.pages and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertTrue(self.server.pages, "the page sent no heartbeat")
        pg.reload()  # a reload keeps it
        pg.wait_for_selector("#start:not([hidden])")
        time.sleep(0.8)
        self.assertIsNone(self.server.stopped_why)
        pg.close()
        deadline = time.monotonic() + 5
        while self.server.stopped_why is None and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertEqual(self.server.stopped_why, "its last page was closed")


class SecondStart(Base):
    """canworks-config PATH while the page is open."""

    def wait_unsaved(self, want):
        deadline = time.monotonic() + 5
        while not any(p["unsaved"] == want for p in self.server.pages.values()) and time.monotonic() < deadline:
            time.sleep(0.05)

    def other(self):
        path = os.path.join(self.dir, "other")
        os.makedirs(path)
        return path

    def test_asks_with_unsaved_changes(self):
        pg = self.page
        self.dirty()
        self.wait_unsaved(True)
        other = self.other()
        self.server.second_start(other, browser=False)
        self.assertEqual(self.server.session.folder, self.project)  # not yet: the page asks
        pg.evaluate("heartbeat()")
        pg.wait_for_selector("#modal[open]")
        self.assertIn("canworks-config was started again to open %s" % other, pg.inner_text("#modal-text"))
        pg.click('#modal button[data-value="open"]')
        pg.wait_for_function("(p) => S.state.folder === p", arg=other)
        self.assertIsNone(self.server.open_request)

    def test_opens_at_once_without(self):
        pg = self.page
        self.open()
        self.wait_unsaved(False)
        other = self.other()
        self.server.second_start(other, browser=False)
        self.assertEqual(self.server.session.folder, other)
        pg.evaluate("heartbeat()")  # the page shows it
        pg.wait_for_function("(p) => S.state.folder === p", arg=other)


class QuitConnected(AdapterPage):
    def test_adapter_and_send_job_stop(self):
        pg = self.page
        self.commission()
        self.connect_adapter(allow=True)
        r = pg.evaluate("async () => api('POST', '/api/online/send_frame', "
                        "{ id: '123', data: '01', period_ms: 50, port: diagPort() })")
        self.assertTrue(r.get("job"), r)
        self.assertTrue(self.server.connection.connected)
        pg.click("#btn-quit")
        pg.wait_for_selector("#modal[open]")
        self.assertEqual(pg.inner_text("#modal-text"),
                         "Quit canworks-config? The adapter connection and cyclic send 0x123 every 50 ms will stop.")
        pg.click('#modal button[data-value="quit"]')
        pg.wait_for_selector("#stopped")
        deadline = time.monotonic() + 5
        while (self.server.connection.connected or self.server.sender.jobs) and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertFalse(self.server.connection.connected)  # the adapter is free for other tools
        self.assertEqual(self.server.sender.jobs, {})


del Base
del AdapterPage
del OnlineBase
