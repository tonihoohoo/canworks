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


    def connect_steps(self, kb):
        """Commission a device from the start page, connected to the virtual adapter at 250 kbit/s."""
        pg = self.page
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

    def open_tool(self, kb, view):
        """The tool tabs are one tab stop: reach the selected tab, then arrow to the tool."""
        kb.tab_to("#tool-tabs [role=tab][aria-selected=true]")
        for _ in range(8):
            if self.page.evaluate("(v) => document.activeElement?.dataset.view === v", view):
                break
            kb.press("ArrowRight")
        kb.expect_focus(f'#tool-tabs [data-view="{view}"]')
        kb.press("Enter")


class Connect(TaskBase):
    def connect(self, scheme):
        self.device(7, heartbeat_s=0.05)
        self.listen_long()
        pg = self.page
        kb = self.kb("connect", scheme)
        self.connect_steps(kb)
        with kb.step("disconnect"):
            kb.tab_to('#conn-bar button[data-conn="disconnect"]', back=True)
            kb.press("Enter")
            pg.wait_for_selector('#conn-bar [data-conn="connect"]')

    def test_connect_light(self):
        self.connect("light")

    def test_connect_dark(self):
        self.connect("dark")


class RecordTrace(TaskBase):
    def record(self, scheme):
        self.device(7, heartbeat_s=0.05)
        self.listen_long()
        pg = self.page
        kb = self.kb("record a trace", scheme)
        self.connect_steps(kb)
        with kb.step("open the Trace tab"):
            self.open_tool(kb, "trace")
            pg.wait_for_selector("[data-trace=start-stop]")
        with kb.step("start recording"):
            kb.tab_to("[data-trace=start-stop]")
            kb.press("Enter")
            pg.wait_for_selector("#ids-body [data-ids-key]", timeout=20000)
            pg.wait_for_selector('[data-trace=start-stop]:has-text("Stop")')
        with kb.step("stop recording"):
            kb.expect_focus("[data-trace=start-stop]")
            kb.press("Enter")
            pg.wait_for_selector('[data-trace=start-stop]:has-text("Start")')
        with kb.step("open the Save menu"):
            kb.tab_to("[data-trace=save-menu] > summary")
            kb.press("Enter")
            pg.wait_for_selector("[data-trace=save-menu][open]")
        with kb.step("save to the traces folder"):
            kb.tab_to("[data-trace=save]")
            kb.press("Enter")
            pg.wait_for_selector('#banner-text:has-text("Saved")')

    def test_record_light(self):
        self.record("light")

    def test_record_dark(self):
        self.record("dark")


class MapPdo(TaskBase):
    def map_pdo(self, scheme):
        pg = self.page
        kb = self.kb("map a PDO entry", scheme)
        pg.goto(self.server.url)
        with kb.step("open the project folder"):
            kb.tab_to("#start-project")
            kb.press("Enter")
            pg.wait_for_selector("#browser-path")
            kb.tab_to("#browser-path")
            kb.press("Control+A")
            kb.type(self.project)
            kb.press("Enter")
            kb.tab_to("#browser-open")
            kb.press("Enter")
            pg.wait_for_selector("#editor:not([hidden])")
        with kb.step("open node 1 from the tree"):
            kb.tab_to('#tree [role=treeitem][tabindex="0"]')
            kb.press("Home")
            for _ in range(30):
                if pg.evaluate("() => document.activeElement.dataset.key") == "0:node:0":
                    break
                kb.press("ArrowDown")
            kb.press("Enter")
            pg.wait_for_selector('[data-node-heading="0"]')
        with kb.step("open the PDOs tab"):
            kb.tab_to('.node-tabs [role=tab][aria-selected="true"]')
            kb.press("Home")
            for _ in range(10):
                if pg.evaluate("() => document.activeElement.dataset.nodeTab") == "pdos":
                    break
                kb.press("ArrowRight")
            pg.wait_for_selector('[data-node-tab-panel="pdos"]')
        with kb.step("pick an object for TPDO 1"):
            kb.tab_to('button[data-add-entry="nodes[0].tx_pdos[0]"]')
            kb.press("Enter")
            pg.wait_for_selector('details[data-picker="input"][open]')
            kb.type("1001")
            kb.tab_to('details[data-picker="input"] button[data-add="0x1001:0"]')
            kb.press("Enter")
            pg.wait_for_selector('tr[data-path="nodes[0].tx_pdos[0].entries[1]"]')
            self.assertRegex(pg.input_value('input[data-path="nodes[0].tx_pdos[0].entries[1].iec_location"]'), r"^%I")
        with kb.step("save"):
            kb.tab_to("#btn-save", back=True)
            kb.press("Enter")
            pg.wait_for_selector('#btn-save:has-text("Saved")')

    def test_map_pdo_light(self):
        self.map_pdo("light")

    def test_map_pdo_dark(self):
        self.map_pdo("dark")


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
