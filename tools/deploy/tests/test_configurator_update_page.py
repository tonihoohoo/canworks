"""The update chip, its dialog, the Settings switch, the updating page and
the result bar, in a real browser (pc-tools-self-update). The check answers
from a stub and nothing is installed: the hand-off is stubbed. Needs
Playwright, like test_configurator_page.py."""

import os
import time
import unittest
from unittest import mock

from canworks.configurator import update

from .helpers import header_action
from .test_configurator_online_page import OnlineBase
from .test_configurator_page import REQUIRED, sync_playwright

UV_TOOL = {"kind": "uv-tool", "why": None, "uv": "uv", "python": "3.14", "base": "python", "env": "/t/canworks",
           "bin": "/bin"}


@unittest.skipIf(sync_playwright is None and not REQUIRED, "Playwright for Python is not installed")
class UpdatePage(OnlineBase):
    def updates(self, info=UV_TOOL, latest="99.0.0", installed=None):
        p = mock.patch.dict(os.environ)
        p.start()
        self.addCleanup(p.stop)
        os.environ.pop(update.OFF_ENV, None)  # tests/__init__.py turns the check off
        u = update.Updates(fetch=lambda: latest, info=lambda: dict(info), installed=lambda: installed)
        u.check()
        self.server.updates = u
        return u

    def start(self):
        self.page.goto(self.server.url)
        self.page.wait_for_selector("#start:not([hidden])")

    def chip(self):
        self.page.wait_for_selector("#update-chip:not([hidden])")
        return self.page.inner_text("#update-chip")

    def dialog(self):
        self.page.click("#update-chip")
        self.page.wait_for_selector("#modal[open]")
        return self.page.inner_text("#modal-text"), self.page.eval_on_selector_all(
            "#modal-buttons button", "bs => bs.map((b) => b.dataset.value)")

    def test_no_chip_without_a_newer_release(self):
        self.updates(latest="0.0.1")
        self.start()
        time.sleep(0.5)
        self.assertTrue(self.page.is_hidden("#update-chip"))

    def test_chip_and_dialog(self):
        self.updates()
        self.start()
        self.assertEqual(self.chip(), "Update: 99.0.0")
        text, buttons = self.dialog()
        self.assertIn("canworks 99.0.0 is available", text)
        self.assertEqual(buttons, ["cancel", "skip", "quit", "now"])
        link = self.page.get_attribute("#modal-extra a", "href")
        self.assertTrue(link.endswith("/releases/tag/deploy-v99.0.0"), link)
        self.page.click('#modal button[data-value="skip"]')
        self.page.wait_for_selector("#update-chip", state="hidden")
        self.assertEqual(self.server.updates.state()["dismissed"], "99.0.0")

    def test_update_when_i_quit(self):
        self.updates()
        self.start()
        self.chip()
        self.dialog()
        self.page.click('#modal button[data-value="quit"]')
        self.page.wait_for_selector("text=Updates to 99.0.0 when you quit")
        self.assertEqual(self.server.updates.on_quit, "99.0.0")
        header_action(self.page, "#btn-quit")
        self.page.wait_for_selector("#modal[open]")
        self.assertIn("canworks 99.0.0 is installed after it stops.", self.page.inner_text("#modal-text"))
        with mock.patch.object(update.Updates, "start_updater") as start:
            self.page.click('#modal button[data-value="quit"]')
            self.page.wait_for_selector("#stopped")
            for _ in range(100):
                if start.called:
                    break
                time.sleep(0.02)
        self.assertEqual(start.call_args[0][0]["restart"], False)
        self.assertIn("installed now", self.page.inner_text("#stopped"))

    def test_unsaved_changes_offer_quit(self):
        self.updates()
        self.open()
        self.page.evaluate("() => { S.config.nodes[0].name = 'renamed'; changed(true); }")
        self.page.wait_for_selector('[data-unsaved="1"]:not([hidden])')
        # At once, before the page's heartbeat tells the server.
        with mock.patch.object(update.Updates, "start_updater") as start:
            self.dialog()
            self.page.click('#modal button[data-value="now"]')
            self.page.wait_for_selector("#modal[open] >> text=Not now: there are unsaved changes")
        start.assert_not_called()
        self.page.click('#modal button[data-value="quit"]')
        self.page.wait_for_selector("text=Updates to 99.0.0 when you quit")

    def test_restart_into_the_installed_version(self):
        """Reinstalled as 99.1.0 while this configurator runs, and the kept
        answer is the older 99.0.0: the chip offers a restart, not 99.0.0."""
        self.updates(latest="99.0.0", installed="99.1.0")
        self.start()
        self.assertEqual(self.chip(), "Restart for 99.1.0")
        text, buttons = self.dialog()
        self.assertIn("canworks 99.1.0 is installed", text)
        self.assertEqual(buttons, ["cancel", "now"])
        with mock.patch.object(update.Updates, "start_updater") as start:
            self.page.click('#modal button[data-value="now"]')
            self.page.wait_for_selector("#stopped[data-updating]")
        self.assertIn("Restarting canworks configurator in 99.1.0", self.page.inner_text("#stopped"))
        self.assertEqual(start.call_args[0][0]["to"], "99.1.0")

    def test_update_goes_to_the_newest_release_now(self):
        u = self.updates()
        self.start()
        self.chip()
        u.fetch = lambda: "99.2.0"  # 99.0.0 was replaced since the page was loaded
        self.dialog()
        with mock.patch.object(update.Updates, "start_updater") as start:
            self.page.click('#modal button[data-value="now"]')
            self.page.wait_for_selector("#stopped[data-updating]")
        stopped = self.page.inner_text("#stopped")
        self.assertIn("Updating canworks configurator to 99.2.0", stopped)
        self.assertIn("99.2.0 is the newest release now", stopped)
        self.assertEqual(start.call_args[0][0]["to"], "99.2.0")

    def test_cannot_update_itself(self):
        self.updates(info={"kind": "other", "why": "these tools were not installed with the one-line installer (uv tool)"})
        self.start()
        self.chip()
        text, buttons = self.dialog()
        self.assertEqual(buttons, ["cancel", "skip"])
        extra = self.page.inner_text("#modal-extra")
        self.assertIn("This copy cannot update itself", extra)
        self.assertIn("install-pc.s", self.page.input_value("#modal-extra textarea"))

    def test_settings(self):
        self.updates()
        self.start()
        header_action(self.page, "#menu-settings > summary")
        self.page.wait_for_selector("#update-status:visible")
        self.assertIn("99.0.0 is available", self.page.inner_text("#update-status"))
        self.assertTrue(self.page.is_checked("#update-check"))
        self.page.uncheck("#update-check")
        for _ in range(50):
            if srv_ui()["update_check"] == "off":
                break
            time.sleep(0.05)
        self.assertEqual(srv_ui()["update_check"], "off")

    def test_check_now_keeps_the_menu_open(self):
        # UI-6: the menu stays open with the result there and in the banner, at 1280 px (in ⋯) and 1800 px.
        for width in (1280, 1800):
            with self.subTest(width=width):
                self.updates()
                self.page.set_viewport_size({"width": width, "height": 860})
                self.start()
                header_action(self.page, "#menu-settings > summary")
                self.page.wait_for_selector("#update-check-now:visible")
                self.page.click("#update-check-now")
                self.page.wait_for_selector("#banner:has-text('canworks 99.0.0 is available')")
                self.assertTrue(self.page.evaluate("document.querySelector('#menu-settings').open"))
                self.assertTrue(self.page.is_visible("#update-status"))
                self.assertIn("99.0.0 is available", self.page.inner_text("#update-status"))

    def test_check_now_off_with_the_check(self):
        # UI-7: CANWORKS_NO_UPDATE_CHECK turns Check now off too, with the reason.
        self.start()
        header_action(self.page, "#menu-settings > summary")
        self.page.wait_for_selector("#update-status:has-text('Turned off by CANWORKS_NO_UPDATE_CHECK')")
        self.assertTrue(self.page.is_disabled("#update-check-now"))
        self.assertIn("CANWORKS_NO_UPDATE_CHECK", self.page.get_attribute("#update-check-now", "title"))

    def test_updating_page_reloads_and_shows_the_result(self):
        u = self.updates()
        self.start()
        self.chip()
        # The page after Update now; the configurator "comes back" with a new start id and a result.
        old = u.boot
        self.page.evaluate("(b) => updatingPage('99.0.0', b)", old)
        self.page.wait_for_selector("#stopped[data-updating]")
        self.assertIn("Updating canworks configurator to 99.0.0", self.page.inner_text("#stopped"))
        u.boot = "new-start"
        u.result = {"state": "ok", "message": "Updated to 99.0.0.", "version": "99.0.0", "at": time.time()}
        self.page.wait_for_selector("#banner:not([hidden]) >> text=Updated to 99.0.0.", timeout=15000)
        self.assertFalse(self.page.query_selector("#stopped"))


def srv_ui():
    from canworks.configurator import server
    return server.load_ui()


if __name__ == "__main__":
    unittest.main()
