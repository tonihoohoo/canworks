"""The Trace view's By identifier view and its round trips in a real browser,
against a fake plugin (trace-workspace tasks 4, 7 and 8). Needs Playwright,
like test_configurator_page.py."""

import os
import time

from canworks.bustrace.model import Frame

from .fake_diag import FakePlugin
from .test_configurator_layout import FIT_CHECK
from .test_configurator_trace_page import TraceBase

ROW = '#ids-body [data-ids-key][data-trace-id="%s"]'


class Base(TraceBase):
    def setUp(self):
        super().setUp()
        self.fake = FakePlugin()
        self.fake.__enter__()
        self.addCleanup(self.fake.__exit__)
        self.t = int(time.time() * 1e6)

    def send(self, can_id, data, n=1, cycle_ms=10, tx=False):
        frames = []
        for _ in range(n):
            self.t += cycle_ms * 1000
            frames.append(Frame(self.t, can_id, bytes.fromhex(data), tx=tx))
        self.fake.push(frames)

    def record(self):
        self.live(self.fake)
        self.page.click("[data-trace=start-stop]")
        self.page.wait_for_selector("#trace-source:has-text('recording')")

    def count(self, ident):
        return self.page.inner_text(ROW % ident + " .ids-c-count")

    def wait_count(self, ident, n):
        self.page.wait_for_selector(ROW % ident + " .ids-c-count:text-is('%s')" % n)

    def data_classes(self, ident):
        return self.page.eval_on_selector_all(ROW % ident + " .ids-c-data span", "ss => ss.map(s => s.className)")


class ByIdentifier(Base):
    def test_rows_update_in_place_with_change_marks(self):
        pg = self.page
        self.record()
        self.send(0x182, "01000000", n=5)
        self.wait_count("182", "5")
        handle = pg.query_selector(ROW % "182")
        self.assertIn("pingpong_TPDO1", handle.inner_text())
        self.assertEqual(pg.inner_text(ROW % "182" + " .ids-c-cycle_last"), "10.0")
        self.send(0x182, "02000000")
        self.wait_count("182", "6")
        self.assertTrue(handle.evaluate("e => e.isConnected"))  # patched, not redrawn
        classes = self.data_classes("182")
        self.assertIn("chg", classes[0])
        self.assertIn("static", classes[1])
        self.assertNotIn("chg", classes[1])
        # Tx and Rx of one identifier are two rows.
        self.send(0x182, "02000000", tx=True)
        pg.wait_for_function("() => document.querySelectorAll('#ids-body [data-trace-id=\"182\"]').length === 2")
        self.assertEqual(pg.locator("#ids-body .ids-row.tx").count(), 1)
        # The change mark goes after a second.
        pg.wait_for_function("() => !document.querySelector('#ids-body [data-trace-id=\"182\"]:not(.tx) .chg')", timeout=4000)
        self.assertEqual(pg.evaluate(FIT_CHECK), [])

    def test_reference_and_new_identifiers(self):
        pg = self.page
        self.record()
        self.send(0x182, "01000000", n=3)
        self.wait_count("182", "3")
        pg.click("[data-ids=set-ref]")
        pg.wait_for_selector("[data-ids=status]:has-text('reference at')")
        self.assertFalse(pg.is_disabled("[data-ids=clear-ref]"))
        self.send(0x182, "01050000")
        self.send(0x183, "AA")
        self.wait_count("182", "4")
        pg.wait_for_selector(ROW % "183" + ".ref-new")
        self.assertIn("new since the reference", pg.inner_text(ROW % "183"))
        self.assertIn("ref", self.data_classes("182")[1])
        self.assertNotIn("ref", self.data_classes("182")[0])
        self.assertFalse(pg.eval_on_selector(ROW % "182", "e => e.classList.contains('ref-new')"))
        pg.click("[data-ids=clear-ref]")
        pg.wait_for_selector(ROW % "183" + ":not(.ref-new)")
        self.assertEqual([c for c in self.data_classes("182") if "ref" in c.split()], [])

    def test_silent_rows(self):
        pg = self.page
        self.record()
        self.t = int(time.time() * 1e6) - 100000
        self.send(0x182, "01000000", n=5)
        self.send(0x701, "05", n=1)  # too few frames to have a cycle
        self.wait_count("182", "5")
        pg.wait_for_selector(ROW % "182" + ".silent", timeout=5000)
        self.assertIn("silent", pg.inner_text(ROW % "182" + " .ids-c-last_seen"))
        self.assertFalse(pg.eval_on_selector(ROW % "701", "e => e.classList.contains('silent')"))
        # It comes back.
        self.t = int(time.time() * 1e6)
        self.send(0x182, "01000000")
        pg.wait_for_selector(ROW % "182" + ":not(.silent)")

    def test_sort_filter_and_pause(self):
        pg = self.page
        self.record()
        self.send(0x281, "00", n=2)
        self.send(0x182, "00", n=6)
        self.send(0x701, "05", n=4)
        self.wait_count("701", "4")
        order = lambda: pg.eval_on_selector_all("#ids-body [data-ids-key]", "rs => rs.map(r => r.dataset.traceId)")
        self.assertEqual(order(), ["182", "281", "701"])
        pg.click("[data-ids-sort=count]")
        self.assertEqual(pg.get_attribute(".ids-c-count[role=columnheader]", "aria-sort"), "ascending")
        self.assertEqual(order(), ["281", "701", "182"])
        pg.click("[data-ids-sort=count]")
        self.assertEqual(pg.get_attribute(".ids-c-count[role=columnheader]", "aria-sort"), "descending")
        self.assertEqual(order(), ["182", "701", "281"])
        # The sort is kept for the next visit.
        pg.click('#tool-tabs button[data-view="network"]')
        self.trace_view()
        pg.wait_for_selector(ROW % "701")
        self.assertEqual(pg.get_attribute(".ids-c-count[role=columnheader]", "aria-sort"), "descending")
        # The display filters apply to both lists.
        self.filters()
        pg.fill('[data-trace-filter="id_from"]', "200")
        pg.press('[data-trace-filter="id_from"]', "Tab")
        pg.wait_for_function("() => document.querySelectorAll('#ids-body [data-ids-key]').length === 2")
        pg.keyboard.press("Escape")
        # Pause: the table stands still while the recording goes on.
        pg.click("[data-ids=pause]")
        self.assertEqual(pg.get_attribute("[data-ids=pause]", "aria-pressed"), "true")
        self.send(0x701, "05", n=3)
        pg.wait_for_selector("[data-ids=status]:has-text('1 update waiting')")
        self.assertEqual(self.count("701"), "4")
        pg.click("[data-ids=pause]")
        self.wait_count("701", "7")

    def test_keyboard_selection_hold_and_show_frames(self):
        pg = self.page
        self.record()
        self.send(0x182, "01000000", n=3)
        self.send(0x701, "05", n=2)
        self.wait_count("701", "2")
        pg.focus("#ids-grid")
        pg.keyboard.press("ArrowDown")
        pg.wait_for_selector(ROW % "182" + "[aria-selected=true]")
        self.assertEqual(pg.get_attribute("#ids-grid", "aria-activedescendant"),
                         pg.get_attribute(ROW % "182", "id"))
        pg.wait_for_selector("#trace-inspector [data-fx=inspector][data-kind=pdo]")
        self.assertEqual(pg.inner_text("[data-ids=change]"), "No change since the previous frame.")
        pg.keyboard.press("End")
        pg.wait_for_selector(ROW % "701" + "[aria-selected=true]")
        pg.wait_for_selector("#trace-inspector [data-fx=inspector][data-kind=heartbeat]")
        pg.keyboard.press("Home")
        pg.wait_for_selector("#trace-inspector [data-fx=inspector][data-kind=pdo]")
        # Hold frame keeps the inspector on its frame while the row updates.
        before = pg.inner_text("#trace-inspector [data-fx=meaning]")
        pg.click("[data-ids=hold]")
        self.send(0x182, "07000000")
        self.wait_count("182", "4")
        pg.wait_for_timeout(400)
        self.assertEqual(pg.inner_text("#trace-inspector [data-fx=meaning]"), before)
        pg.click("[data-ids=hold]")
        pg.wait_for_function("t => document.querySelector('#trace-inspector [data-fx=meaning]').innerText !== t", arg=before)
        # Show frames: the Chronological list of this identifier.
        pg.click("[data-ids=show-frames]")
        pg.wait_for_selector("#trace-rows .trace-row")
        self.assertEqual(pg.get_attribute('[data-trace-tab="frames"]', "aria-selected"), "true")
        self.assertTrue(all("pingpong_TPDO1" in r for r in self.rows()))
        self.assertEqual(len(self.rows()), 4)

    def test_explain_in_frame_lab_and_back(self):
        pg = self.page
        self.record()
        self.send(0x182, "01000000", n=2)
        self.wait_count("182", "2")
        pg.click(ROW % "182")
        pg.click("[data-ids=explain]")
        pg.wait_for_selector("[data-fx=source]:has-text('From trace, frame 2')")
        self.assertEqual(pg.input_value("[data-fx=lab-frame]"), "182#01000000")
        # The trace's own decoding: the PDO mapping of the config.
        pg.wait_for_selector("#fx-lab-inspector [data-fx=inspector][data-kind=pdo]")
        pg.fill("[data-fx=lab-frame]", "182#02000000")
        pg.click("[data-fx=lab-explain]")
        pg.wait_for_selector("[data-fx=source]:has-text('Edited from trace frame 2')")
        pg.click("[data-fx=back-to-trace]")
        pg.wait_for_selector(ROW % "182" + "[aria-selected=true]")
        self.assertEqual(pg.get_attribute('[data-trace-tab="ids"]', "aria-selected"), "true")

    def test_continue_after_stop(self):
        pg = self.page
        self.record()
        self.send(0x182, "01000000", n=3)
        pg.wait_for_selector("[data-trace=stats]:has-text('3 frames')")
        pg.click("[data-trace=start-stop]")
        pg.wait_for_selector("#trace-source:has-text('stopped')")
        pg.click("[data-trace=start-stop]")
        pg.wait_for_selector("#modal[open]")
        self.assertIn("Continue this trace", pg.inner_text("#modal"))
        pg.click('#modal button[data-value="continue"]')
        pg.wait_for_selector("#trace-source:has-text('recording')")
        self.t = int(time.time() * 1e6)
        self.send(0x182, "01000000", n=2)
        self.wait_count("182", "5")
        self.chronological()
        pg.wait_for_selector("#trace-rows .trace-row:has-text('capture restarted')")
        self.assertEqual(len(self.rows()), 6)  # three frames, the gap, two frames


class Layout(Base):
    def test_split_and_pane_fit(self):
        pg = self.page
        self.record()
        self.send(0x182, "01000000", n=3)
        self.send(0x60A, "4018100100000000", tx=True)
        self.wait_count("182", "3")
        pg.click(ROW % "182")
        for width, side in ((1000, False), (1280, True), (1440, True)):
            pg.set_viewport_size({"width": width, "height": 800})
            pg.wait_for_timeout(200)
            for tab in ("ids", "frames"):
                pg.click('[data-trace-tab="%s"]' % tab)
                pg.wait_for_timeout(200)
                self.assertEqual(pg.evaluate(FIT_CHECK), [], "%s at %d" % (tab, width))
            boxes = pg.evaluate("""() => ['#trace-tab .trace-split-view', '#trace-inspector'].map(s => {
                const b = document.querySelector(s).getBoundingClientRect(); return [b.left, b.top]; })""")
            # Wide: the inspector docks at the side; narrow: under the list.
            self.assertEqual(boxes[1][0] > boxes[0][0], side, width)


class BigFile(TraceBase):
    def test_two_thousand_identifiers(self):
        """An opened file with 2,000 identifiers: the table is virtualised and
        one update of every row takes under 20 ms of script time."""
        pg = self.page
        path = os.path.join(self.dir, "busy.log")
        with open(path, "w") as f:
            for k in range(2000):
                f.write("(%d.%06d) can0 %08X#%02X00\n" % (1700000000, k, 0x10000 + k, k & 0xFF))
        self.open()
        self.trace_view()
        pg.set_input_files('input[data-trace="open-input"]', path)
        pg.wait_for_selector("[data-ids=status]:has-text('2000 identifiers')")
        self.assertLess(pg.locator("#ids-body [data-ids-key]").count(), 100)
        took = pg.evaluate("""() => {
            const rows = [...TI.rows.values()].map((r) => Object.assign({}, r, { count: r.count + 1 }));
            const t = performance.now();
            idsApply({ generation: TI.since.generation, rev: TI.since.rev, filter: TI.since.filter, now_us: TI.now_us,
                       reference: false, reference_us: null, reset: false, ids: rows }, false);
            return performance.now() - t;
        }""")
        self.assertLess(took, 20)
        pg.focus("#ids-grid")
        pg.keyboard.press("End")
        pg.wait_for_selector('#ids-body [aria-selected=true]')
        self.assertEqual(pg.get_attribute('#ids-body [aria-selected=true]', 'data-trace-id'), '000107CF')
