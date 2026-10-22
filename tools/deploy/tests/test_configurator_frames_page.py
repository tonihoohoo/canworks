"""The Trace view's transmit list in a real browser, against a fake plugin
(trace-workspace tasks 5 and 6; it replaced the Send panel of
add-raw-frames-bitrate-detect). Needs Playwright, like
test_configurator_page.py."""

import json
import os
import time

from canworks import diag
from canworks.bustrace.model import Frame

from .helpers import tool_tab, network_tab
from .fake_diag import TOKEN, FakePlugin
from .test_configurator_trace_page import TraceBase


class Base(TraceBase):
    def setUp(self):
        super().setUp()
        self.fake = FakePlugin(allow_changes=True)
        self.fake.__enter__()
        self.addCleanup(self.fake.__exit__)

    def trace(self, allow=True):
        self.write_config({"token_verifier": diag.token_verifier(TOKEN), "allow_changes": allow})
        self.remember(self.fake.runtime)
        self.open()
        self.trace_view()
        self.page.wait_for_selector("#tx-pane[open] [data-tx=add]")

    def add(self, ident="", data="", period="", count=""):
        """Adds a row and fills it in; returns the row's selector."""
        pg = self.page
        pg.click("[data-tx=add]")
        row = "[data-tx-key]:last-child"
        pg.wait_for_selector(row + " [data-tx=id]:focus")
        for field, value in (("id", ident), ("data", data), ("period_ms", period), ("count", count)):
            if value:
                pg.fill("%s [data-tx=%s]" % (row, field), value)
                pg.press("%s [data-tx=%s]" % (row, field), "Tab")
        return '[data-tx-key="%s"]' % pg.get_attribute(row, "data-tx-key")

    def stored(self):
        return self.page.evaluate("async () => (await api('POST', '/api/trace/transmit', {})).frames")

    def wait_stored(self, n):
        deadline = time.monotonic() + 5
        while len(self.stored()) != n and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertEqual(len(self.stored()), n)


class TransmitList(Base):
    def test_single_frame(self):
        pg = self.page
        self.trace()
        self.assertEqual(pg.locator("[data-tx=blocked]").count(), 0)
        row = self.add("60A", "40 18 10 01 00 00 00 00")
        pg.click(row + " [data-tx=send]")
        pg.wait_for_selector(row + " [data-tx=state]:has-text('sent ')")
        self.assertEqual([(f["id"], f["data"], f["forced"]) for f in self.fake.sent],
                         [(0x60A, "40 18 10 01 00 00 00 00", False)])
        # A remote frame: the data box becomes a DLC box.
        pg.check(row + " [data-tx=rtr]")
        pg.fill(row + " [data-tx=dlc]", "4")
        pg.press(row + " [data-tx=dlc]", "Tab")
        pg.click(row + " [data-tx=send]")
        deadline = time.monotonic() + 5
        while len(self.fake.sent) < 2 and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertEqual((self.fake.sent[1]["rtr"], self.fake.sent[1]["dlc"]), (True, 4))

    def test_force_needs_confirmation(self):
        pg = self.page
        self.trace()
        row = self.add("205", "01 02")
        pg.click(row + " [data-tx=send]")
        pg.wait_for_selector("#modal[open]")
        self.assertIn('"0x205 is RPDO1 of node 5; force needed"', pg.inner_text("#modal-text"))
        pg.click('#modal button[data-value="cancel"]')
        pg.wait_for_selector(row + " [data-tx=state]:has-text('not sent')")
        self.assertEqual(self.fake.sent, [])
        pg.click(row + " [data-tx=send]")
        pg.click('#modal button[data-value="force"]')
        pg.wait_for_selector(row + " [data-tx=state]:has-text('(forced)')")
        self.assertTrue(self.fake.sent[0]["forced"])

    def test_disabled_without_allow_changes(self):
        pg = self.page
        self.trace(allow=False)
        self.assertIn("Sending needs Allow changes in Online access", pg.inner_text("[data-tx=blocked]"))
        row = self.add("60A", "01")
        self.assertTrue(pg.is_disabled(row + " [data-tx=send]"))
        # The list can still be edited and is kept.
        self.wait_stored(1)

    def test_cyclic_job_kept_when_leaving_the_tab(self):
        pg = self.page
        self.trace()
        row = self.add("60A", "", period="50")
        self.assertEqual(pg.inner_text(row + " [data-tx=send]"), "Start")
        pg.click(row + " [data-tx=send]")
        pg.wait_for_selector(row + " [data-tx=stop]")
        pg.wait_for_function("(r) => /running, [1-9]\\d* sent/.test(document.querySelector(r + ' [data-tx=state]').innerText)", arg=row)
        self.assertIsNone(self.fake.jobs[1]["reason"])
        self.assertIn("1 cyclic job running", pg.inner_text("#tx-summary"))
        network_tab(pg)
        time.sleep(2.5)  # past the plugin's poll timeout: the page still polls
        self.assertIsNone(self.fake.jobs[1]["reason"])
        self.trace_view()
        pg.click(row + " [data-tx=stop]")
        pg.wait_for_selector(row + " [data-tx=state]:has-text('stopped')")
        self.assertEqual(self.fake.jobs[1]["reason"], "stopped")

    def test_count_and_stop_all(self):
        pg = self.page
        self.trace()
        row = self.add("60A", "", period="10", count="3")
        pg.click(row + " [data-tx=send]")
        pg.wait_for_selector(row + " [data-tx=state]:has-text('done, 3 sent')", timeout=5000)
        other = self.add("60B", "", period="100")
        pg.click(other + " [data-tx=send]")
        pg.wait_for_selector(other + " [data-tx=stop]")
        pg.click("[data-tx=stop-all]")
        pg.wait_for_selector(other + " [data-tx=state]:has-text('stopped')")
        self.assertTrue(pg.is_disabled("[data-tx=stop-all]"))

    def test_messages_in_the_page_words(self):
        pg = self.page
        self.trace()
        row = self.add()
        for ident, data, msg in (("6G0", "", "the identifier must be hex, e.g. 205"),
                                 ("60A", "4", "the data needs whole bytes (two hex digits each)"),
                                 ("60A", "zz", "the data must be hex bytes, e.g. 0F 01"),
                                 ("800", "", "out of range for a 11-bit identifier")):
            pg.fill(row + " [data-tx=id]", ident)
            pg.fill(row + " [data-tx=data]", data)
            pg.wait_for_selector(row + " [data-tx=msg]")
            self.assertEqual(pg.inner_text(row + " [data-tx=msg]"), msg)
            self.assertTrue(pg.is_disabled(row + " [data-tx=send]"))
        pg.fill(row + " [data-tx=id]", "60A")
        pg.fill(row + " [data-tx=data]", "")
        pg.wait_for_selector(row + " [data-tx=msg]", state="detached")
        self.assertFalse(pg.is_disabled(row + " [data-tx=send]"))
        # The server makes the same checks.
        pg.evaluate("banner('')")
        err = pg.evaluate("""async () => { try { await api('POST', '/api/trace/transmit/check', {frame: {id: '800'}}); }
                                            catch (e) { return e.message; } }""")
        self.assertIn("out of range", err)

    def test_kept_after_reload_and_files(self):
        pg = self.page
        self.trace()
        self.add("60A", "01 02")
        row = self.add("181", "", period="100")
        pg.fill(row + " [data-tx=name]", "heartbeat-ish")
        pg.press(row + " [data-tx=name]", "Tab")
        self.wait_stored(2)
        pg.reload()
        self.trace_view()
        pg.wait_for_selector("[data-tx-key] >> nth=1")
        self.assertEqual([pg.input_value("[data-tx-key] >> nth=%d >> [data-tx=id]" % i) for i in (0, 1)], ["60A", "181"])
        self.assertEqual(pg.input_value("[data-tx-key] >> nth=1 >> [data-tx=period_ms]"), "100")
        # Save list… downloads a file; Open list… adds it or replaces the list.
        with pg.expect_download() as dl:
            pg.click("[data-tx=save]")
        path = os.path.join(self.dir, "list.transmit.json")
        dl.value.save_as(path)
        with open(path) as f:
            saved = json.load(f)
        self.assertEqual(saved["format"], "canworks-transmit")
        self.assertEqual([r["id"] for r in saved["frames"]], ["60A", "181"])
        pg.set_input_files("[data-tx=open-input]", path)
        pg.wait_for_selector("#modal[open]")
        pg.click('#modal button[data-value="add"]')
        pg.wait_for_selector("[data-tx-key] >> nth=3")
        self.wait_stored(4)
        pg.set_input_files("[data-tx=open-input]", path)
        pg.click('#modal button[data-value="replace"]')
        pg.wait_for_function("() => document.querySelectorAll('[data-tx-key]').length === 2")
        # Clear list asks first.
        pg.click("[data-tx=clear]")
        pg.click('#modal button[data-value="clear"]')
        pg.wait_for_selector("[data-tx=empty]")
        self.wait_stored(0)

    def test_send_this_frame_from_the_trace(self):
        pg = self.page
        self.trace()
        pg.click("#tx-pane > summary")  # closed: Send… opens it again
        pg.click("[data-trace=start-stop]")
        pg.wait_for_selector("#trace-source:has-text('recording')")
        now = int(time.time() * 1e6)
        self.fake.push([Frame(now, 0x60A, bytes.fromhex("4018100100000000"))])
        self.chronological()
        pg.wait_for_selector("#trace-rows .trace-row")
        pg.click("#trace-rows .trace-row")
        pg.click("#trace-inspector [data-trace=send-this]")
        self.assertTrue(pg.eval_on_selector("#tx-pane", "d => d.open"))
        row = "[data-tx-key]:last-child"
        pg.wait_for_selector(row + " [data-tx=send]:focus")
        self.assertEqual(pg.input_value(row + " [data-tx=id]"), "60A")
        self.assertEqual(pg.input_value(row + " [data-tx=data]"), "40 18 10 01 00 00 00 00")
        self.assertEqual(self.fake.sent, [])  # Send… itself sends nothing
        pg.keyboard.press("Enter")
        pg.wait_for_selector(row + " [data-tx=state]:has-text('sent ')")
        self.assertEqual(self.fake.sent[0]["data"], "40 18 10 01 00 00 00 00")

    def test_send_from_the_frame_lab(self):
        pg = self.page
        self.trace()
        tool_tab(pg, "framelab")
        pg.fill("[data-fx=lab-frame]", "60A#4018100100000000")
        pg.click("[data-fx=lab-explain]")
        pg.click("#view [data-trace=send-this]")
        pg.wait_for_selector("#tx-pane[open] [data-tx-key]:last-child [data-tx=send]:focus")
        self.assertEqual(pg.input_value("[data-tx-key]:last-child [data-tx=id]"), "60A")
        self.wait_stored(1)
        self.assertEqual(self.fake.sent, [])


if __name__ == "__main__":
    import unittest
    unittest.main()
