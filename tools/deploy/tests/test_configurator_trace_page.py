"""The configurator's Trace view in a real browser (add-bus-trace tasks
4.3-4.5): opened files without a runtime, recording from the fake plugin,
display filters, graphs with cursors, triggers and the layout. Needs
Playwright, like test_configurator_page.py."""

import os
import time

from openplc_canopen_deploy import diag
from openplc_canopen_deploy.bustrace import formats
from openplc_canopen_deploy.bustrace.model import Frame, Trace

from .fake_diag import TOKEN, FakePlugin
from .test_bustrace import sample_trace, written
from .test_configurator_layout import FIT_CHECK
from .test_configurator_online_page import OnlineBase

SIGNAL = "pingpong_TPDO1.UNSIGNED32_sent_from_slave"


class TraceBase(OnlineBase):
    def setUp(self):
        super().setUp()
        self.page.set_viewport_size({"width": 1280, "height": 800})

    def trace_view(self):
        self.page.click('button[data-view="trace"]')
        self.page.wait_for_selector("#trace-source:not(:has-text('Loading'))")

    def sample_file(self, trace=None, name="sample.log"):
        path = os.path.join(self.dir, name)
        with open(path, "wb") as f:
            f.write(written(trace or sample_trace(), formats.format_of(path)))
        return path

    def rows(self):
        return self.page.eval_on_selector_all("#trace-rows .trace-row", "rs => rs.map(r => r.innerText)")

    def wait_rows(self, n):
        self.page.wait_for_function("n => document.querySelectorAll('#trace-rows .trace-row').length === n", arg=n)

    def live(self, fake):
        self.write_config({"token_verifier": diag.token_verifier(TOKEN)})
        self.remember(fake.runtime)
        self.open()
        self.trace_view()


class Files(TraceBase):
    def test_open_filter_graph_and_export_without_a_runtime(self):
        pg = self.page
        self.open()
        self.trace_view()
        self.assertIn("Recording needs online access", pg.inner_text("#trace-source"))
        pg.set_input_files('input[data-trace="open-input"]', self.sample_file())
        pg.wait_for_selector("#trace-source:has-text('File sample.log')")
        pg.wait_for_selector("#trace-rows .trace-row")
        rows = self.rows()
        self.assertIn("start node 2 (pingpong)", rows[0])
        self.assertTrue(rows[0].startswith("0.000000"), rows[0])
        self.assertIn("25 frames", pg.inner_text("[data-trace=stats]"))
        # Display filters: node 2 and SDO.
        pg.fill('[data-trace-filter="nodes"]', "2")
        pg.press('[data-trace-filter="nodes"]', "Tab")
        pg.check('[data-trace-kind="sdo"]')
        self.wait_rows(4)
        self.assertTrue(all("SDO" in r for r in self.rows()))
        self.assertIn("= 305419896", self.rows()[1])
        pg.uncheck('[data-trace-kind="sdo"]')
        pg.fill('[data-trace-filter="nodes"]', "")
        pg.press('[data-trace-filter="nodes"]', "Tab")
        pg.fill('[data-trace-filter="text"]', "abort")
        pg.press('[data-trace-filter="text"]', "Tab")
        self.wait_rows(1)
        pg.fill('[data-trace-filter="text"]', "")
        pg.press('[data-trace-filter="text"]', "Tab")
        pg.click('[data-trace-time="utc"]')
        pg.wait_for_function("() => ((document.querySelector('#trace-rows .trace-row span') || {}).textContent || '').startsWith('06:20:00.000000')")
        pg.click('[data-trace-time="rel"]')
        # Identifier table.
        pg.click('[data-trace-tab="ids"]')
        pg.wait_for_selector('tr[data-trace-id="182"]')
        self.assertIn("pingpong_TPDO1", pg.inner_text('tr[data-trace-id="182"]'))
        self.assertIn("10.0", pg.inner_text('tr[data-trace-id="182"]'))  # 10 ms cycle
        # Graph: a series, cursors A and B with deltas, jump to the frame and back.
        pg.click('[data-trace-tab="graph"]')
        pg.check('[data-trace-series="%s"]' % SIGNAL)
        pg.wait_for_selector("#trace-plots .uplot")
        box = pg.locator("#trace-plots .u-over").first.bounding_box()
        pg.mouse.click(box["x"] + box["width"] * 0.05, box["y"] + box["height"] / 2)
        pg.keyboard.down("Shift")
        pg.mouse.click(box["x"] + box["width"] * 0.15, box["y"] + box["height"] / 2)
        pg.keyboard.up("Shift")
        text = pg.inner_text("[data-trace=delta-t]")
        self.assertIn("Δt", text)
        delta = pg.inner_text('tr[data-trace-delta="%s"]' % SIGNAL)
        self.assertRegex(delta, r"\d")
        pg.click("[data-trace=to-frames]")
        pg.wait_for_selector("#trace-rows .trace-row.selected")
        pg.click("[data-trace=back-to-graph]")
        pg.wait_for_selector("#trace-plots .uplot")
        # Export downloads a file; Start says online access is needed.
        pg.select_option("[data-trace=export-format]", "asc")
        with pg.expect_download() as dl:
            pg.click("[data-trace=export]")
        path = dl.value.path()
        self.assertEqual(dl.value.suggested_filename, "rtd-monitor-trace.asc")
        with open(path, "rb") as f:
            self.assertEqual(len([x for x in formats.read(f.read(), "x.asc") if not x.gap]), 25)
        pg.click("[data-trace=start]")
        pg.click('#modal button[data-value="start"]')
        pg.wait_for_selector("#banner.error:has-text('set up online access')")

    def test_large_trace_scrolls_and_graphs(self):
        """2 million frames: the list and the graph get windows from the server."""
        pg = self.page
        t = Trace(limit=2_100_000)
        base = 1_791_181_200_000_000
        recs = bytearray()
        for i in range(2_000_000):
            recs += Frame(base + i * 250, 0x182, (i & 0xFFFFFFFF).to_bytes(4, "little")).pack()
        t.append_packed(bytes(recs))
        path = os.path.join(self.dir, "big.pcapng")
        formats.write_file(t, path)
        self.open()
        self.trace_view()
        started = time.monotonic()
        pg.set_input_files('input[data-trace="open-input"]', path)
        pg.wait_for_selector("#trace-source:has-text('File big.pcapng')", timeout=120000)
        pg.wait_for_selector("#trace-rows .trace-row")
        opened = time.monotonic() - started
        pg.eval_on_selector("#trace-list", "l => { l.scrollTop = l.scrollHeight; }")
        pg.wait_for_function("() => [...document.querySelectorAll('#trace-rows .trace-row')].some(r => r.innerText.includes('sent_from_slave=1999999'))")
        pg.click('[data-trace-tab="graph"]')
        t0 = time.monotonic()
        pg.check('[data-trace-series="%s"]' % SIGNAL)
        pg.wait_for_selector("#trace-plots .uplot")
        graphed = time.monotonic() - t0
        points = int(pg.get_attribute("#trace-plots", "data-points"))
        self.assertLess(points, 20000)
        self.assertLess(graphed, 10, "graphing 2 million frames took %.1f s" % graphed)
        print("2M frames: opened in %.1f s, graphed in %.1f s (%d points)" % (opened, graphed, points))


class Live(TraceBase):
    def setUp(self):
        super().setUp()
        self.fake = FakePlugin()
        self.fake.__enter__()
        self.addCleanup(self.fake.__exit__)

    def push(self, n, start=0, can_id=0x182):
        now = int(time.time() * 1e6)
        self.fake.push([Frame(now + i * 1000, can_id, bytes([(start + i) & 0xFF, 0, 0, 0])) for i in range(n)])

    def test_record_reload_and_stop(self):
        pg = self.page
        self.live(self.fake)
        pg.click("[data-trace=start]")
        pg.wait_for_selector("#trace-source:has-text('recording')")
        self.push(30)
        pg.wait_for_selector("[data-trace=stats]:has-text('30 frames')")
        pg.wait_for_function("() => [...document.querySelectorAll('#trace-rows .trace-row')].some(r => r.innerText.includes('sent_from_slave=29'))")
        # A reload keeps the recording and its frames.
        pg.reload()
        pg.wait_for_selector("#editor:not([hidden])")
        self.trace_view()
        pg.wait_for_selector("#trace-source:has-text('recording')")
        self.push(5, 30)
        pg.wait_for_selector("[data-trace=stats]:has-text('35 frames')")
        pg.click("[data-trace=stop]")
        pg.wait_for_selector("#trace-source:has-text('stopped')")
        self.assertEqual(self.fake.requests[-1]["op"], "trace_stop")

    def test_old_plugin(self):
        self.fake.trace_supported = False
        self.live(self.fake)
        self.page.click("[data-trace=start]")
        self.page.wait_for_selector("#banner.error:has-text('too old for traces')")

    def test_triggers(self):
        pg = self.page
        self.live(self.fake)
        pg.click('[data-trace-tab="trigger"]')
        pg.select_option('[data-trace-cond="0.type"]', "emcy")
        pg.fill('[data-trace-cond="0.node"]', "2")
        pg.fill('[data-trace-trig="pre_s"]', "1")
        pg.fill('[data-trace-trig="post_s"]', "0")
        pg.click("[data-trace=apply-trigger]")
        pg.wait_for_selector("[data-trace=trigger-text]:has-text('EMCY from node 2')")
        pg.click("[data-trace=start]")
        pg.wait_for_selector("#trace-source:has-text('recording')")
        self.push(5)
        now = int(time.time() * 1e6)
        self.fake.push([Frame(now + 10000, 0x082, bytes.fromhex("1050010000000000"))])
        pg.wait_for_selector("#trace-source:has-text('stopped by the trigger')")
        pg.wait_for_selector("text=Hit 1 at")
        # Normal mode with auto-save: every hit is a marker and a file, recording goes on.
        folder = os.path.join(self.dir, "auto")
        pg.select_option('[data-trace-cond="0.type"]', "frame")
        pg.fill('[data-trace-cond="0.id"]', "0x702")
        pg.select_option('[data-trace-trig="mode"]', "normal")
        pg.check('[data-trace-trig="autosave"]')
        pg.select_option('[data-trace-trig="autosave-format"]', "candump")
        pg.fill('[data-trace-trig="autosave-folder"]', folder)
        pg.click("[data-trace=apply-trigger]")
        pg.wait_for_selector("[data-trace=trigger-text]:has-text('frame 0x702')")
        pg.click("[data-trace=start]")
        pg.click('#modal button[data-value="start"]')
        pg.wait_for_selector("#trace-source:has-text('recording')")
        self.push(3, can_id=0x702)
        pg.wait_for_function("() => document.querySelectorAll('[data-trace=saved] li').length === 3")
        self.assertEqual(len([f for f in os.listdir(folder) if f.startswith("rtd-monitor-trace-")]), 3)
        self.assertIn("recording", pg.inner_text("#trace-source"))
        # Markers show in the graph.
        pg.click('[data-trace-tab="graph"]')
        pg.check('[data-trace-series="bus.rate"]')
        pg.wait_for_selector("#trace-plots .uplot")

    def test_layout_fits(self):
        pg = self.page
        self.live(self.fake)
        pg.click("[data-trace=start]")
        pg.wait_for_selector("#trace-source:has-text('recording')")
        self.push(20)
        now = int(time.time() * 1e6)
        self.fake.push([Frame(now + 50000, 0x602, bytes.fromhex("4018100400000000"), tx=True),
                        Frame(now + 51000, 0x582, bytes.fromhex("4318100478563412"))])
        pg.wait_for_selector("[data-trace=stats]:has-text('22 frames')")
        for width in (1000, 1280, 1440):
            pg.set_viewport_size({"width": width, "height": 800})
            for tab in ("frames", "ids", "graph", "trigger"):
                pg.click('[data-trace-tab="%s"]' % tab)
                if tab == "graph" and not pg.is_checked('[data-trace-series="%s"]' % SIGNAL):
                    pg.check('[data-trace-series="%s"]' % SIGNAL)
                    pg.wait_for_selector("#trace-plots .uplot")
                pg.wait_for_timeout(300)
                self.assertEqual(pg.evaluate(FIT_CHECK), [], "%s at %d" % (tab, width))
