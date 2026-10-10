"""The configurator's remote link parts in a real browser (add-remote-access):
runtimes in the connect box, Reachable from other networks in Online access,
the path and round trip in the online view, and the question before an LSS
fast scan on a slow path. Discovery and the link are mocked. Needs
Playwright, like test_configurator_page.py."""

import os
from unittest import mock

from canworks import diag
from canworks.configurator import online
from canworks.link import discovery, pc as linkpc

from . import test_configurator_online_page as base
from .fake_diag import TOKEN, FakePlugin
from .test_configurator_page import load


def link_info(path, rtt, note=None):
    """A stand-in for Connection.link_info: `note` on the first call only."""
    notes = [note]

    def info(self):
        return {"path": path, "rtt_ms": rtt, "pairing_note": notes.pop() if notes else None}
    return info


class LinkPage(base.OnlineBase):
    def test_connect_box_lists_discovered_and_remembered(self):
        pg = self.page
        linkpc.remember("line3", hosts=["192.168.1.50"], id="a" * 64, paired=True, internet=True)
        found = [{"name": "bench", "addresses": ["10.0.0.7"], "diag": 7600, "runtime": None, "id": None, "link": None}]
        with mock.patch.object(discovery, "available", return_value=True), \
                mock.patch.object(discovery, "browse", return_value=found):
            self.write_config({"token_verifier": diag.token_verifier(TOKEN)})
            self.open()
            pg.click('button[data-view="online"]')
            sel = 'select[data-online="runtime-list"]'
            pg.wait_for_selector(sel + ' option[data-kind="discovered"]', state="attached")
            self.assertIn("bench 10.0.0.7:7600", pg.inner_text(sel))
            self.assertIn("line3 192.168.1.50, paired, from other networks", pg.inner_text(sel))
            # A discovered runtime fills its address, a remembered one its name.
            pg.select_option(sel, "10.0.0.7:7600")
            self.assertEqual(pg.input_value('input[data-online="host"]'), "10.0.0.7:7600")
            pg.select_option(sel, "line3")
            self.assertEqual(pg.input_value('input[data-online="host"]'), "line3")
            pg.wait_for_timeout(300)
            self.assertEqual(load(os.path.join(self.cfg_dir, "online.json"))["projects"][self.project]["host"], "line3")
            # Typing an address keeps working.
            pg.fill('input[data-online="host"]', "plc.local")
            pg.press('input[data-online="host"]', "Tab")
            pg.wait_for_timeout(300)
            self.assertEqual(load(os.path.join(self.cfg_dir, "online.json"))["projects"][self.project]["host"], "plc.local")

    def test_reachable_from_other_networks(self):
        pg = self.page
        self.write_config({"token_verifier": diag.token_verifier(TOKEN), "allow_changes": True})
        self.remember("plc.local")
        self.open()
        box = 'input[data-online="internet"]'
        pg.wait_for_selector(box)
        self.assertEqual(pg.locator('textarea[data-online="relays"]').count(), 0)
        pg.check(box)
        pg.wait_for_selector('textarea[data-online="relays"]')
        pg.fill('textarea[data-online="relays"]', "http://relay.example.com")
        pg.wait_for_selector('[data-online="relays-msg"]:has-text("must use https")')
        pg.fill('textarea[data-online="relays"]', "https://relay.example.com\n\n")
        pg.wait_for_selector('[data-online="relays-msg"]:text-is("")', state="attached")
        pg.wait_for_function("() => document.body.dataset.checking === '0'")
        pg.click("#btn-save")
        pg.wait_for_selector("#banner:has-text('Saved')")
        saved = load(self.config_path)["master"]["diagnostics"]
        self.assertEqual(saved["remote_link"], {"internet": True, "relays": ["https://relay.example.com"]})
        self.assertTrue(saved["allow_changes"])  # the other fields stay
        self.assertTrue(diag.token_matches(TOKEN, saved["token_verifier"]))
        # All defaults again: no remote_link at all.
        pg.fill('textarea[data-online="relays"]', "")
        pg.uncheck(box)
        pg.wait_for_selector('textarea[data-online="relays"]', state="detached")
        pg.evaluate("banner('')")  # the first Saved goes, so the wait below sees the second
        pg.wait_for_function("() => document.body.dataset.checking === '0'")
        pg.click("#btn-save")
        pg.wait_for_selector("#banner:has-text('Saved')")
        saved = load(self.config_path)["master"]["diagnostics"]
        self.assertNotIn("remote_link", saved)
        self.assertTrue(saved["allow_changes"])

    def test_path_badge_and_pairing_note(self):
        pg = self.page
        with FakePlugin() as fp:
            with mock.patch.object(online.Connection, "link_info",
                                   link_info("internet relayed", 350, "This PC is now paired with line3 and can reach "
                                                                     "it from other networks.")):
                self.online(fp)
                badge = '#online-conn [data-online="path"]'
                pg.wait_for_selector(badge)
                self.assertEqual(pg.inner_text(badge), "internet relayed, 350 ms")
                self.assertIn("bad", pg.get_attribute(badge, "class"))
                pg.wait_for_selector("#banner:has-text('can reach it from other networks')")
            with mock.patch.object(online.Connection, "link_info", link_info("internet direct", 150)):
                pg.wait_for_selector(badge + ':has-text("internet direct, 150 ms")')
                self.assertIn("warn", pg.get_attribute(badge, "class"))
            with mock.patch.object(online.Connection, "link_info", link_info("LAN", 2)):
                pg.wait_for_selector(badge + ':has-text("LAN, 2 ms")')
                cls = pg.get_attribute(badge, "class")
                self.assertNotIn("warn", cls)
                self.assertNotIn("bad", cls)

    def test_lss_asks_on_a_slow_path(self):
        pg = self.page
        with FakePlugin(allow_changes=True, scan_polls=1) as fp, \
                mock.patch.object(online.Connection, "link_info", link_info("internet relayed", 120)):
            fp.lss_devices[(0x360, 0, 0, 0x43)] = 255
            self.online(fp, allow=True)
            pg.wait_for_selector('#online-conn [data-online="path"]')
            pg.wait_for_selector('button[data-online="lss-find"]:not([disabled])')
            pg.click('button[data-online="lss-find"]')
            pg.wait_for_selector('#modal button[data-value="go"]')
            text = pg.inner_text("#modal-text")
            self.assertIn("internet relayed", text)
            self.assertIn("results and stop commands arrive late", text)
            pg.click('#modal button[data-value="cancel"]')
            pg.wait_for_selector('[data-online="lss-status"]:has-text("Not started")')
            self.assertFalse([r for r in fp.requests if r["op"].startswith("lss")])  # nothing sent
            pg.click('button[data-online="lss-find"]')
            pg.click('#modal button[data-value="go"]')
            pg.wait_for_selector('tr[data-lss-device="66"]')
            self.assertTrue([r for r in fp.requests if r["op"].startswith("lss")])

    def test_lss_on_the_lan_asks_nothing(self):
        pg = self.page
        with FakePlugin(allow_changes=True, scan_polls=1) as fp:
            fp.lss_devices[(0x360, 0, 0, 0x43)] = 255
            self.online(fp, allow=True)
            pg.wait_for_selector('#online-conn [data-online="path"]:has-text("LAN")')
            pg.wait_for_selector('button[data-online="lss-find"]:not([disabled])')
            pg.click('button[data-online="lss-find"]')
            pg.wait_for_selector('tr[data-lss-device="66"]')
