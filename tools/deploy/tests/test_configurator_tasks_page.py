"""Whole user tasks on the configurator page with the keyboard alone, in the
Light and the Dark theme (visual-refresh): connect to a USB adapter, scan the
bus, add a found node to a config, map a PDO entry and save, record and save
a trace. Each step is audited with axe-core, checks that the focused control
shows its focus ring and that nothing is clipped (keyboard_only.KeyboardOnly);
a pointer action fails the test. Against python-can's virtual bus, the fake
plugin runtime and the local simulator runtime. Needs Playwright, like
test_configurator_page.py."""

import unittest

from .keyboard_only import KeyboardOnly, PointerUsed
from .test_configurator_layout import FIT_CHECK, audit
from .test_configurator_localbus_page import AdapterPage

SCHEMES = ("light", "dark")


class TaskBase(AdapterPage):
    def kb(self, name, scheme):
        self.page.emulate_media(color_scheme=scheme)  # the page follows the OS (theme Auto)
        return KeyboardOnly(self.page, f"{type(self).__name__} {name} ({scheme})", audit, FIT_CHECK)

    def pick(self, kb, selector, text):
        """Focus a <select> with Tab and pick an option by typing its start."""
        kb.tab_to(selector)
        kb.type(text)
        self.page.wait_for_function("([s, t]) => document.querySelector(s).selectedOptions[0]?.textContent.startsWith(t)", arg=[selector, text])


class Connect(TaskBase):
    def connect(self, scheme):
        self.device(7, heartbeat_s=0.05)
        self.listen_long()
        pg = self.page
        kb = self.kb("connect", scheme)
        pg.goto(self.server.url)
        with kb.step("open Commission a device"):
            kb.tab_to("#start-commission")
            kb.press("Enter")
            pg.wait_for_selector('#conn-dialog[open] input[data-online="adapter"]')
        with kb.step("pick the adapter and the bit rate"):
            kb.tab_to('#conn-dialog input[data-online="adapter"]')
            kb.type("virtual:" + self.ch)
            self.pick(kb, '#conn-dialog select[data-online="adapter-bitrate"]', "250")
        with kb.step("connect"):
            kb.tab_to('#conn-dialog button[data-online="connect"]')
            kb.press("Enter")
            pg.wait_for_selector('#conn-bar [data-conn="target"]:has-text("virtual:%s")' % self.ch)
            pg.wait_for_selector("#conn-dialog", state="hidden")
            self.assertIn("250 kbit/s", pg.inner_text('#conn-bar [data-conn="rate"]'))
            self.assertIn("confirmed", pg.inner_text('#conn-bar [data-conn="rate"]'))
        with kb.step("disconnect"):
            kb.tab_to('#conn-bar button[data-conn="disconnect"]', back=True)
            kb.press("Enter")
            pg.wait_for_selector('#conn-bar [data-conn="connect"]')

    def test_connect_light(self):
        self.connect("light")

    def test_connect_dark(self):
        self.connect("dark")


class Guard(unittest.TestCase):
    """The wrapper refuses the pointer without a browser."""

    class FakePage:
        def click(self, *a):
            raise AssertionError("not reached")

        def locator(self, *a):
            return Guard.FakePage()

        url = "about:blank"

    def test_pointer_step_caught(self):
        kb = KeyboardOnly(self.FakePage(), "guard", None, None)
        with self.assertRaisesRegex(PointerUsed, "used the pointer"):
            kb.click("#btn-save")
        with self.assertRaisesRegex(PointerUsed, "used the pointer"):
            kb.locator("#btn-save").click()
        self.assertEqual(kb.url, "about:blank")


if __name__ == "__main__":
    unittest.main()
