"""The Trace view's Send panel and Detect bit rate on the scan page in a real
browser, against a fake plugin (add-raw-frames-bitrate-detect task 3.2).
Needs Playwright, like test_configurator_page.py."""

import time

from openplc_canopen_deploy import diag
from openplc_canopen_deploy.bustrace.model import Frame

from .fake_diag import TOKEN, FakePlugin
from .test_configurator_trace_page import TraceBase


class Base(TraceBase):
    def setUp(self):
        super().setUp()
        self.fake = FakePlugin(allow_changes=True)
        self.fake.__enter__()
        self.addCleanup(self.fake.__exit__)

    def trace(self, allow=True):
        self.write_config({"token_sha256": diag.hash_token(TOKEN), "allow_changes": allow})
        self.remember(self.fake.runtime)
        self.open()
        self.trace_view()
        self.page.click("[data-trace=send-panel] > summary")

    def scan(self, allow=True):
        self.online(self.fake, allow=allow)
        self.page.click('button[data-view="scan"]')
        self.page.wait_for_selector('[data-online="detect-box"]')


class SendPanel(Base):
    def test_single_frame(self):
        pg = self.page
        self.trace()
        self.assertTrue(pg.is_visible('[data-send="id"]'))
        self.assertEqual(pg.locator('[data-send="blocked"]').count(), 0)
        pg.fill('[data-send="id"]', "60A")
        pg.fill('[data-send="data"]', "40 18 10 01 00 00 00 00")
        pg.click('[data-send="send"]')
        pg.wait_for_selector('[data-send="sent"] li:has-text("60A [8] 40 18 10 01 00 00 00 00")')
        self.assertEqual([(f["id"], f["data"], f["forced"]) for f in self.fake.sent],
                         [(0x60A, "40 18 10 01 00 00 00 00", False)])
        # A remote frame.
        pg.check('[data-send="rtr"]')
        pg.fill('[data-send="dlc"]', "4")
        pg.click('[data-send="send"]')
        pg.wait_for_selector('[data-send="sent"] li:has-text("60A remote [4]")')
        self.assertEqual((self.fake.sent[1]["rtr"], self.fake.sent[1]["dlc"]), (True, 4))

    def test_force_needs_confirmation(self):
        pg = self.page
        self.trace()
        pg.fill('[data-send="id"]', "205")
        pg.fill('[data-send="data"]', "01 02")
        pg.click('[data-send="send"]')
        pg.wait_for_selector("#modal[open]")
        self.assertIn('"0x205 is RPDO1 of node 5; force needed"', pg.inner_text("#modal-text"))
        pg.click('#modal button[data-value="cancel"]')
        pg.wait_for_selector("#banner:has-text('Nothing was sent')")
        self.assertEqual(self.fake.sent, [])
        pg.click('[data-send="send"]')
        pg.click('#modal button[data-value="force"]')
        pg.wait_for_selector('[data-send="sent"] li:has-text("205 [2] 01 02 (forced)")')
        self.assertTrue(self.fake.sent[0]["forced"])

    def test_disabled_without_allow_changes(self):
        pg = self.page
        self.trace(allow=False)
        self.assertEqual(pg.inner_text('[data-send="blocked"]'), "Sending needs Allow changes in Online access")
        self.assertTrue(pg.is_disabled('[data-send="send"]'))
        self.assertTrue(pg.is_disabled('[data-send="id"]'))

    def test_cyclic_job_stopped_when_leaving(self):
        pg = self.page
        self.trace()
        pg.fill('[data-send="id"]', "60A")
        pg.select_option('[data-send="mode"]', "cyclic")
        pg.fill('[data-send="period"]', "50")
        pg.click('[data-send="send"]')
        pg.wait_for_selector('[data-send-job="1"]')
        pg.wait_for_function("() => /, ([1-9]\\d*) sent/.test(document.querySelector('[data-send-job=\"1\"]').innerText)")
        self.assertIsNone(self.fake.jobs[1]["reason"])
        pg.click('button[data-view="bus"]')
        deadline = time.monotonic() + 5
        while self.fake.jobs[1]["reason"] is None and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertEqual(self.fake.jobs[1]["reason"], "stopped")

    def test_stop_buttons_and_count(self):
        pg = self.page
        self.trace()
        pg.fill('[data-send="id"]', "60A")
        pg.select_option('[data-send="mode"]', "cyclic")
        pg.fill('[data-send="period"]', "100")
        pg.click('[data-send="send"]')
        pg.wait_for_selector('[data-send-job="1"]')
        pg.click('[data-send-job="1"] [data-send="stop-job"]')
        pg.wait_for_selector("#banner:has-text('Job 1 stopped')")
        self.assertEqual(pg.locator("[data-send-job]").count(), 0)
        self.assertTrue(pg.is_disabled('[data-send="stop"]'))
        # A job with a count ends by itself.
        pg.fill('[data-send="period"]', "10")
        pg.fill('[data-send="count"]', "3")
        pg.click('[data-send="send"]')
        pg.wait_for_selector("#banner:has-text('ended: count reached, 3 sent')")
        self.assertEqual(pg.locator("[data-send-job]").count(), 0)

    def test_send_this_frame_from_the_trace(self):
        pg = self.page
        self.trace()
        pg.click("[data-trace=start]")
        pg.wait_for_selector("#trace-source:has-text('recording')")
        now = int(time.time() * 1e6)
        self.fake.push([Frame(now, 0x60A, bytes.fromhex("4018100100000000"))])
        pg.wait_for_selector("#trace-rows .trace-row")
        pg.click("#trace-rows .trace-row")
        pg.click("[data-trace=send-this]")
        self.assertEqual(pg.input_value('[data-send="id"]'), "60A")
        self.assertEqual(pg.input_value('[data-send="data"]'), "40 18 10 01 00 00 00 00")
        pg.click('[data-send="send"]')
        pg.wait_for_selector('[data-send="sent"] li')
        self.assertEqual(self.fake.sent[0]["data"], "40 18 10 01 00 00 00 00")


class DetectPage(Base):
    def test_detect_and_use_the_rate(self):
        pg = self.page
        self.scan()
        pg.click('[data-online="detect"]')
        pg.wait_for_selector("#modal[open]")
        self.assertIn("CANopen on that network stops during the sweep", pg.inner_text("#modal-text"))
        self.assertIn("nodes boot again afterwards", pg.inner_text("#modal-text"))
        pg.click('#modal button[data-value="detect"]')
        pg.wait_for_selector('[data-online="detect-verdict"]')
        self.assertIn("250 kbit/s detected", pg.inner_text('[data-online="detect-verdict"]'))
        self.assertEqual(pg.locator('[data-online="detect-table"] tbody tr').count(), 8)
        self.assertIn("0x705 0x185 0x285", pg.inner_text('tr[data-detect-rate="250"]'))
        self.assertIn("12", pg.inner_text('tr[data-detect-rate="500"]'))
        self.assertEqual(pg.evaluate("S.dirty"), False)
        pg.click('[data-online="use-bitrate"]:has-text("Use 250 kbit/s")')
        self.assertEqual(pg.evaluate("S.config.adapter.bitrate"), 250000)
        self.assertEqual(pg.evaluate("S.dirty"), True)
        pg.wait_for_function("() => document.querySelector('#btn-save').textContent === 'Save'")
        self.assertEqual(pg.locator('[data-online="use-bitrate"]').count(), 0)
        with open(self.config_path, encoding="utf-8") as f:
            self.assertIn('"bitrate": 125000', f.read())  # not saved

    def test_silent_bus(self):
        pg = self.page
        self.fake.sweep_hears = {}
        self.scan()
        pg.click('[data-online="detect"]')
        pg.click('#modal button[data-value="detect"]')
        pg.wait_for_selector('[data-online="detect-verdict"]')
        self.assertEqual(pg.inner_text('[data-online="detect-verdict"]'),
                         "The bus was silent. A device sends a boot-up message when it is powered on or reset: "
                         "power-cycle one during the sweep, or run more rounds.")
        self.assertEqual(pg.locator('[data-online="use-bitrate"]').count(), 0)

    def test_force_and_refusals(self):
        pg = self.page
        self.fake.operational = 5
        self.scan()
        pg.click('[data-online="detect"]')
        pg.click('#modal button[data-value="detect"]')
        pg.wait_for_selector("#modal[open]:has-text('node 5 is OPERATIONAL')")
        pg.click('#modal button[data-value="force"]')
        pg.wait_for_selector('[data-online="detect-verdict"]')
        self.assertTrue(self.fake.sweeps[0]["force"])
        self.fake.operational, self.fake.sweep = None, None
        self.fake.detect_refusal = "no bit rate on a virtual bus"
        pg.click('[data-online="detect"]')
        pg.click('#modal button[data-value="detect"]')
        pg.wait_for_selector('[data-online="detect-error"]:has-text("no bit rate on a virtual bus")')

    def test_disabled_without_allow_changes(self):
        self.scan(allow=False)
        self.assertTrue(self.page.is_disabled('[data-online="detect"]'))
        self.assertIn("needs Allow changes", self.page.inner_text('[data-online="detect-blocked"]'))
