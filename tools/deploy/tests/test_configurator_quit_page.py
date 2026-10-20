"""Quit, the leave-page question and closing the last tab, in a real browser
(configurator-quit-and-background). Needs Playwright, like
test_configurator_page.py."""

import json
import os
import threading
import time

from canworks.configurator import server as srv

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



class Gone(Base):
    """The page of a configurator that has stopped (configurator-survive-sleep)."""

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()  # its port refuses connections now

    def comes_back(self):
        self.page.evaluate("() => document.dispatchEvent(new Event('visibilitychange'))")

    def gone_notice(self):
        start = time.monotonic()
        self.page.wait_for_selector('#stopped[data-gone="1"]', timeout=5000)
        self.assertLess(time.monotonic() - start, 5)
        text = self.page.inner_text("#stopped")
        self.assertIn("canworks-config is not running any more.", text)
        self.assertIn("canworks configurator shortcut", text)
        self.assertIn("run canworks-config in a terminal", text)
        self.assertFalse(self.page.is_visible("#top"))
        return text

    def test_notice_after_the_configurator_stopped(self):
        pg = self.page
        self.open()
        self.stop_server()
        self.comes_back()
        text = self.gone_notice()
        self.assertNotIn("could not be saved", text)
        self.assertEqual(pg.locator("#stopped-download").count(), 0)
        # Nothing asks any more, and leaving asks nothing.
        self.assertEqual(pg.evaluate("LIFE.stopped"), True)
        asked = []
        pg.on("dialog", lambda d: (asked.append(d.type), d.accept()))
        pg.close(run_before_unload=True)
        self.assertEqual(asked, [])

    def test_one_missed_beat_says_nothing(self):
        pg = self.page
        self.open()
        refused = []

        def first_refused(route):
            if not refused:
                refused.append(1)
                route.abort("connectionrefused")
            else:
                route.continue_()

        pg.route("**/api/heartbeat", first_refused)
        self.comes_back()
        pg.wait_for_function("() => LIFE.misses === 1")
        pg.wait_for_function("() => LIFE.misses === 0 && !LIFE.beating", timeout=5000)  # the beat 2 s later answered
        self.assertEqual(refused, [1])
        self.assertEqual(pg.locator("#stopped").count(), 0)
        self.assertFalse(pg.evaluate("LIFE.stopped"))

    def test_http_error_is_an_answer(self):
        pg = self.page
        self.open()
        pg.route("**/api/heartbeat", lambda route: route.fulfill(status=500, body="{}"))
        for _ in range(3):
            pg.evaluate("heartbeat()")
            pg.wait_for_function("() => !LIFE.beating")
        self.assertEqual(pg.evaluate("LIFE.misses"), 0)
        self.assertEqual(pg.locator("#stopped").count(), 0)

    def test_unsaved_change_downloaded(self):
        pg = self.page
        self.dirty()
        self.stop_server()
        pg.evaluate("() => window.dispatchEvent(new Event('focus'))")
        text = self.gone_notice()
        self.assertIn("This page's unsaved changes could not be saved.", text)
        self.assertIn("EDS and notes files imported since the last save", text)
        with pg.expect_download() as info:
            pg.click("#stopped-download")
        download = info.value
        self.assertEqual(download.suggested_filename, "canworks.json")
        saved = os.path.join(self.dir, "downloaded.json")
        download.save_as(saved)
        with open(saved, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["nodes"][0]["name"], "renamed")
        # A new configurator opens it as edited.
        os.replace(saved, self.config_path)
        self.server = srv.Server()
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.page = self.context.new_page()
        self.page.on("pageerror", lambda e: self.errors.append(str(e)))
        self.open()
        self.assertEqual(self.page.evaluate("S.config.nodes[0].name"), "renamed")

    def test_fits(self):
        pg = self.page
        self.dirty()
        self.stop_server()
        self.comes_back()
        self.gone_notice()
        for width in (1000, 1280, 1440):
            pg.set_viewport_size({"width": width, "height": 800})
            pg.wait_for_timeout(100)
            self.assertEqual(pg.evaluate(FIT_CHECK), [], "gone notice at %d" % width)
            box = pg.locator("#stopped-download").bounding_box()
            self.assertLessEqual(box["x"] + box["width"], width)


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
