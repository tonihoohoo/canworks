"""The Trace view's wheel zoom, resize bars and own window in a real browser
(trace-window-zoom-resize). Needs Playwright, like test_configurator_page.py."""

import os
import time

from canworks.bustrace import formats
from canworks.bustrace.model import Frame, Trace

from .test_bustrace import T0
from .test_configurator_trace_page import SIGNAL, TraceBase

RATE = "bus.rate"


def minute_trace():
    """60 s of node 2's TPDO 1 every 10 ms, from 0 s to 60 s."""
    t = Trace()
    for i in range(6001):
        t.append(Frame(T0 + i * 10000, 0x182, (i & 0xFFFFFFFF).to_bytes(4, "little")))
    t.meta.update({"interface": "can0", "bitrate": 125000})
    return t


class GraphBase(TraceBase):
    def opened(self):
        path = os.path.join(self.dir, "minute.log")
        formats.write_file(minute_trace(), path)
        self.open()
        self.trace_view()
        self.page.set_input_files('input[data-trace="open-input"]', path)
        self.page.wait_for_selector("#trace-source:has-text('File minute.log')")

    def graph(self, lanes=2):
        pg = self.page
        pg.click('[data-trace-tab="graph"]')
        pg.check('[data-trace-series="%s"]' % SIGNAL)
        if lanes > 1:
            pg.check('[data-trace-series="%s"]' % RATE)
            pg.select_option('[data-trace-lane="%s"]' % RATE, "2")
        pg.wait_for_function("n => T.plots.length === n && document.querySelectorAll('#trace-plots .uplot').length === n", arg=lanes)

    def view_s(self):
        """The graph's range in seconds from the trace start, or None for the whole trace."""
        return self.page.evaluate("T.zoom && [(T.zoom[0] - traceT0()) / 1e6, (T.zoom[1] - traceT0()) / 1e6]")

    def lane_ranges(self):
        return self.page.evaluate("T.plots.map(p => [p.scales.x.min, p.scales.x.max])")

    def point_at(self, seconds, lane=-1):
        """The page position of `seconds` in the middle of a lane's plot."""
        return self.page.evaluate("""([s, lane]) => {
            const p = T.plots.at(lane), b = p.over.getBoundingClientRect();
            return [b.left + p.valToPos(s, 'x'), b.top + b.height / 2];
        }""", [seconds, lane])


class WheelZoom(GraphBase):
    def test_wheel_zooms_at_the_pointer_on_every_lane(self):
        pg = self.page
        pg.set_viewport_size({"width": 1280, "height": 600})
        self.opened()
        self.graph()
        asked = []
        pg.on("request", lambda r: asked.append(r.url) if r.url.endswith("/api/trace/series") else None)
        pg.evaluate("T.plots[1].over.scrollIntoView({ block: 'center' })")
        before = pg.evaluate("window.scrollY")
        self.assertGreater(before, 0)
        x, y = self.point_at(12.0)
        pg.mouse.move(x, y)
        for _ in range(3):
            pg.mouse.wheel(0, -100)
        lo, hi = self.view_s()
        # 1.25 per notch, three notches, 12.0 s kept under the pointer.
        self.assertAlmostEqual(lo, 12 - 12 / 1.25 ** 3, delta=0.05)
        self.assertAlmostEqual(hi, 12 + 48 / 1.25 ** 3, delta=0.05)
        ranges = self.lane_ranges()
        self.assertAlmostEqual(ranges[0][0], ranges[1][0], places=6)
        self.assertAlmostEqual(ranges[0][1], ranges[1][1], places=6)
        self.assertAlmostEqual(ranges[1][0], lo, places=3)
        self.assertEqual(pg.evaluate("window.scrollY"), before)
        # One request for the points of the final range, once the wheel stopped.
        pg.wait_for_timeout(500)
        self.assertEqual(len(asked), 1, asked)
        pg.wait_for_function("() => !document.querySelector('#trace-plots p')")
        # "Graph zoom" downloads use the wheel's range.
        pg.evaluate("T.range = 'view'")
        got = pg.evaluate("traceRange()")
        z = pg.evaluate("T.zoom")
        self.assertEqual((got["start_us"], got["end_us"]), (int(z[0]), -int(-z[1] // 1)))
        # Outside the plots the wheel scrolls the page and leaves the graph alone.
        box = pg.locator("#trace-stats").bounding_box()
        pg.mouse.move(box["x"] + 20, box["y"] + 5)
        pg.mouse.wheel(0, -40)
        pg.wait_for_function("y => window.scrollY < y", arg=before)
        self.assertEqual(self.view_s(), [lo, hi])
        # Wheel down past the whole trace: the whole trace again.
        x, y = self.point_at(20.0)
        pg.mouse.move(x, y)
        for _ in range(8):
            pg.mouse.wheel(0, 200)
        self.assertIsNone(self.view_s())

    def test_shift_wheel_pans_and_the_window_has_a_floor(self):
        pg = self.page
        self.opened()
        self.graph(lanes=1)
        pg.evaluate("setZoom(traceT0() + 10e6, traceT0() + 20e6)")
        x, y = self.point_at(15.0)
        pg.mouse.move(x, y)
        pg.keyboard.down("Shift")
        pg.mouse.wheel(0, -200)
        lo, hi = self.view_s()
        self.assertLess(lo, 10)
        self.assertAlmostEqual(hi - lo, 10, places=3)
        for _ in range(10):
            pg.mouse.wheel(0, -2000)
        pg.keyboard.up("Shift")
        lo, hi = self.view_s()
        self.assertAlmostEqual(lo, 0, places=6)
        self.assertAlmostEqual(hi, 10, places=3)
        # A sideways swipe pans too.
        pg.mouse.wheel(300, 0)
        self.assertGreater(self.view_s()[0], 0)
        # Zooming in stops at a 100 µs window.
        x, y = self.point_at(sum(self.view_s()) / 2)
        pg.mouse.move(x, y)
        for _ in range(80):
            pg.mouse.wheel(0, -200)
        lo, hi = self.view_s()
        self.assertAlmostEqual((hi - lo) * 1e6, 100, delta=0.5)
        # Zoom out (the button) uses the same limits.
        for _ in range(30):
            pg.click("[data-trace=zoom-out]")
        self.assertIsNone(self.view_s())


class Resize(GraphBase):
    def drag(self, selector, dy):
        pg = self.page
        pg.locator(selector).scroll_into_view_if_needed()
        box = pg.locator(selector).bounding_box()
        x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        pg.mouse.move(x, y)
        pg.mouse.down()
        pg.mouse.move(x, y + dy / 2)
        pg.mouse.move(x, y + dy)
        pg.mouse.up()

    def height(self, selector):
        return self.page.evaluate("s => document.querySelector(s).getBoundingClientRect().height", selector)

    def test_list_height_is_dragged_kept_and_reset(self):
        pg = self.page
        self.opened()
        self.chronological()
        pg.wait_for_selector("#trace-rows .trace-row")
        h0 = self.height("#trace-list")
        rows0 = pg.locator("#trace-rows .trace-row").count()
        self.drag("[data-trace=list-size]", 300)
        self.assertAlmostEqual(self.height("#trace-list"), h0 + 300, delta=1)
        pg.wait_for_function("n => document.querySelectorAll('#trace-rows .trace-row').length > n", arg=rows0)
        pg.wait_for_function("async () => (await api('GET', '/api/trace/prefs')).list_h === %d" % round(h0 + 300))
        # By identifier has the same height; it is kept over a reload.
        pg.click('[data-trace-tab="ids"]')
        pg.wait_for_selector("#ids-grid")
        self.assertAlmostEqual(self.height("#ids-grid"), h0 + 300, delta=1)
        pg.reload()
        pg.wait_for_selector("#editor:not([hidden])")
        self.trace_view()
        self.chronological()
        self.assertAlmostEqual(self.height("#trace-list"), h0 + 300, delta=1)
        # The arrow keys change 40 px; double-click goes back to the default.
        pg.focus("[data-trace=list-size]")
        pg.keyboard.press("ArrowDown")
        self.assertAlmostEqual(self.height("#trace-list"), h0 + 340, delta=1)
        self.assertEqual(pg.get_attribute("[data-trace=list-size]", "aria-valuenow"), str(round(h0 + 340)))
        pg.dblclick("[data-trace=list-size]")
        self.assertAlmostEqual(self.height("#trace-list"), h0, delta=1)
        pg.wait_for_function("async () => (await api('GET', '/api/trace/prefs')).list_h === null")
        # Where the list and the inspector share the window height, the bar is not offered.
        pg.set_viewport_size({"width": 1000, "height": 800})
        pg.wait_for_selector("[data-trace=split-box].shared-height")
        self.assertFalse(pg.is_visible("[data-trace=list-size]"))

    def test_graph_lanes_are_dragged_taller(self):
        pg = self.page
        self.opened()
        self.graph()
        self.assertEqual(pg.evaluate("T.plots.map(p => p.height)"), [200, 200])
        box = pg.locator("#trace-plots .u-over").first.bounding_box()
        pg.mouse.click(box["x"] + box["width"] * 0.3, box["y"] + box["height"] / 2)
        a = pg.evaluate("T.a")
        self.assertIsNotNone(a)
        self.drag("[data-trace=graph-size]", 200)
        self.assertEqual(pg.evaluate("T.plots.map(p => p.height)"), [300, 300])
        self.assertEqual(pg.evaluate("T.a"), a)
        pg.wait_for_function("async () => (await api('GET', '/api/trace/prefs')).lane_h === 300")
        pg.reload()
        pg.wait_for_selector("#editor:not([hidden])")
        self.trace_view()
        self.graph()
        self.assertEqual(pg.evaluate("T.plots.map(p => p.height)"), [300, 300])
        pg.dblclick("[data-trace=graph-size]")
        self.assertEqual(pg.evaluate("T.plots.map(p => p.height)"), [200, 200])


class OwnWindow(TraceBase):
    """The trace in its own window, recording from the fake plugin while the
    main window shows other views."""

    def setUp(self):
        super().setUp()
        from .fake_diag import FakePlugin
        self.fake = FakePlugin()
        self.fake.__enter__()
        self.addCleanup(self.fake.__exit__)

    def push(self, n, start=0):
        now = int(time.time() * 1e6)
        self.fake.push([Frame(now + i * 1000, 0x182, bytes([(start + i) & 0xFF, 0, 0, 0])) for i in range(n)])

    def wait_closed(self, page, other):
        """Waits for `page` to close, letting Playwright take events through `other`."""
        end = time.monotonic() + 10
        while not page.is_closed():
            self.assertLess(time.monotonic(), end, "the window did not close")
            other.wait_for_timeout(50)

    def open_window(self):
        with self.context.expect_page() as info:
            self.page.click("[data-trace=open-window]")
        tw = info.value
        tw.set_default_timeout(10000)
        tw.on("pageerror", lambda e: self.errors.append("trace window: %s" % e))
        tw.wait_for_selector("#trace-source:not(:has-text('Loading'))")
        self.page.wait_for_selector("[data-trace=elsewhere]")
        return tw

    def test_watch_the_trace_while_the_main_window_works(self):
        pg = self.page
        self.live(self.fake)
        tw = self.open_window()
        self.assertIn("window=trace", tw.url)
        self.assertTrue(tw.title().startswith("Trace – "), tw.title())
        # Only the Trace view: no workspace tabs, connection bar or Problems panel.
        for sel in ("#ws", "#conn-bar", "#bottom", "#side", "[data-trace=open-window]"):
            self.assertFalse(tw.is_visible(sel), sel)
        self.assertTrue(tw.is_visible("[data-trace=window-bar]"))
        self.assertTrue(tw.is_visible("[data-tx=pane]") or tw.locator(".tx-body, [data-tx]").count() > 0)
        # The main window's Trace tab only points at the window, and draws nothing.
        self.assertEqual(pg.locator("#trace-source").count(), 0)
        # Start in the trace window opens the main window's runtime connection.
        tw.click("[data-trace=start-stop]")
        tw.wait_for_selector("#trace-source:has-text('recording')")
        self.push(30)
        tw.wait_for_selector("[data-trace=stats]:has-text('30 frames')")
        # The main window goes on with other work; the trace window keeps showing the bus.
        pg.click('button[data-view="online"]')
        pg.wait_for_selector("#online-live, [data-online]")
        self.push(5, 30)
        tw.wait_for_selector("[data-trace=stats]:has-text('35 frames')")
        tw.wait_for_selector("[data-trace=window-conn]:has-text('runtime')")
        # Explain in Frame lab from the trace window happens in the main window.
        tw.click('[data-trace-tab="frames"]')
        tw.wait_for_selector("#trace-rows .trace-row")
        tw.locator("#trace-rows .trace-row").first.click()
        tw.click("#trace-inspector [data-fx=to-lab]")
        pg.wait_for_selector("#fx-lab-inspector [data-fx=inspector]")
        self.assertFalse(tw.is_closed())
        # Back to trace in the main window selects the frame in the trace window.
        pg.click("[data-fx=back-to-trace]")
        tw.wait_for_selector("#trace-rows .trace-row.selected")
        # Bring the trace back: the window closes and the main window shows the same recording.
        pg.click('button[data-view="trace"]')
        pg.wait_for_selector("[data-trace=elsewhere]")
        pg.click("[data-trace=bring-back]")
        self.wait_closed(tw, pg)
        pg.wait_for_selector("#trace-source:has-text('recording')")
        pg.wait_for_selector("[data-trace=stats]:has-text('35 frames')")

    def test_main_window_closed_and_trace_window_closed(self):
        pg = self.page
        self.live(self.fake)
        pg.click("[data-trace=start-stop]")
        pg.wait_for_selector("#trace-source:has-text('recording')")
        self.push(10)
        pg.wait_for_selector("[data-trace=stats]:has-text('10 frames')")
        tw = self.open_window()
        # Closing the trace window shows the trace in the main window again.
        tw.close()
        pg.wait_for_selector("#trace-source:has-text('recording')")
        self.assertEqual(pg.locator("[data-trace=elsewhere]").count(), 0)
        tw = self.open_window()
        # The main window closes without asking about the recording; the trace window goes on.
        asked = []
        pg.on("dialog", lambda d: (asked.append(d.type), d.dismiss()))
        pg.close(run_before_unload=True)
        self.wait_closed(pg, tw)
        self.assertEqual(asked, [])
        self.push(5, 10)
        tw.wait_for_selector("[data-trace=stats]:has-text('15 frames')")
        self.assertIn("recording", tw.inner_text("#trace-source"))
        # Now the trace window is the last one showing the recording: closing it asks.
        tw.evaluate("TW.mainSeen = 0")
        self.assertTrue(tw.evaluate("unsavedWork()"))
