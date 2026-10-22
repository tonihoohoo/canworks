"""The Frame lab and the Trace inspector made easier to use
(frame-lab-usability): close and reopen the inspector, the shared height in
narrow windows, folding layers, the compact data grid, the Frame lab's
columns, Clear and results in view, the one-line simulation banner, and the
two display fixes. Needs Playwright, like test_configurator_page.py."""

import os
import shutil

from .helpers import REPO
from .test_configurator_trace_page import TraceBase

IN_VIEW = """sel => { const e = document.querySelector(sel); if (!e) return false;
  const r = e.getBoundingClientRect(); return r.height > 0 && r.top >= 0 && r.bottom <= window.innerHeight; }"""


class Base(TraceBase):
    def open_sample(self, view="frames"):
        pg = self.page
        self.open()
        self.trace_view()
        pg.set_input_files('input[data-trace="open-input"]', self.sample_file())
        pg.wait_for_selector("#ids-body [data-ids-key]")
        if view == "frames":
            self.chronological()
            pg.wait_for_selector("#trace-rows .trace-row")

    def in_view(self, sel):
        return self.page.evaluate(IN_VIEW, sel)

    def lab(self):
        self.page.click('button[data-view="framelab"]')
        self.page.wait_for_selector("[data-fx=lab-frame]")

    def explain(self, frame):
        pg = self.page
        pg.fill("[data-fx=lab-frame]", frame)
        pg.click("[data-fx=lab-explain]")
        pg.wait_for_selector("#fx-lab-inspector [data-fx=inspector]")


class DisplayFixes(Base):
    def test_no_node_id_and_arbitration_bus(self):
        pg = self.page
        self.open()
        self.lab()
        for frame in ("080#", "000#0105"):
            self.explain(frame)
            text = pg.inner_text("#fx-lab-inspector [data-fx=identifier]")
            self.assertNotIn("null", text)
            self.assertIn("No node ID", text)
        pg.click("[data-fx-mode=arbitration]")
        pg.fill("[data-fx-arb=arbA]", "185#")
        pg.fill("[data-fx-arb=arbB]", "183#")
        pg.click("[data-fx-arb=go]")
        pg.wait_for_selector("[data-fx=arb-result]")
        # The bus row's texts (y 101), SOF and identifier bits 10 to 0: after
        # bit 2, where 0x183 wins, the bus carries 0x183's bits 1 and 0.
        bus = pg.eval_on_selector_all("[data-fx=arbitration] svg text[y='101']", "ts => ts.map(t => t.textContent)")
        self.assertEqual(bus[:12], ["0", "0", "0", "1", "1", "0", "0", "0", "0", "0", "1", "1"])
        a = pg.eval_on_selector_all("[data-fx=arbitration] svg text[y='37']", "ts => ts.map(t => t.textContent)")
        self.assertEqual(a[10:12], ["–", "–"])


class CloseAndReopen(Base):
    def test_close_with_esc_reopen_by_select(self):
        pg = self.page
        self.open_sample()
        pg.click("#trace-rows .trace-row:has-text('SYNC')")
        pg.wait_for_selector("#trace-inspector [data-fx=inspector][data-kind=sync]")
        self.assertFalse(pg.is_visible("[data-trace=inspector-rail]"))
        # Esc inside the inspector closes it and puts the focus on the list.
        pg.focus("#trace-inspector .fx-about > summary")
        pg.keyboard.press("Escape")
        pg.wait_for_selector("[data-trace=inspector-rail]", state="visible")
        self.assertFalse(pg.is_visible("#trace-inspector"))
        self.assertEqual(pg.evaluate("document.activeElement.id"), "trace-list")
        # The arrow keys move the selection and keep it closed.
        before = pg.inner_text("#trace-rows .trace-row.selected")
        pg.keyboard.press("ArrowDown")
        pg.wait_for_function("t => document.querySelector('#trace-rows .trace-row.selected').innerText !== t", arg=before)
        self.assertFalse(pg.is_visible("#trace-inspector"))
        # Enter opens it on the selected frame.
        pg.keyboard.press("Enter")
        pg.wait_for_selector("#trace-inspector [data-fx=inspector]", state="visible")
        # ✕ closes it; the state is kept on this PC.
        pg.click("[data-trace=inspector-toggle]")
        pg.wait_for_selector("[data-trace=inspector-rail]", state="visible")
        pg.wait_for_function("async () => (await api('GET', '/api/trace/prefs')).inspector === false")
        # A click on a row opens it on that row.
        pg.click("#trace-rows .trace-row:has-text('TPDO1')")
        pg.wait_for_selector("#trace-inspector [data-fx=inspector][data-kind=pdo]", state="visible")
        self.assertFalse(pg.is_visible("[data-trace=inspector-rail]"))
        # The rail opens it too.
        pg.click("[data-trace=inspector-toggle]")
        pg.click("[data-trace=inspector-rail]")
        pg.wait_for_selector("#trace-inspector [data-fx=inspector]", state="visible")

    def test_by_identifier_click_opens(self):
        pg = self.page
        self.open_sample(view="ids")
        pg.click("#ids-body [data-ids-key]:has-text('SYNC')")
        pg.wait_for_selector("#trace-inspector [data-fx=inspector][data-kind=sync]")
        pg.click("[data-trace=inspector-toggle]")
        self.assertEqual(pg.evaluate("document.activeElement.id"), "ids-grid")
        pg.click("#ids-body [data-ids-key]:has-text('EMCY')")
        pg.wait_for_selector("#trace-inspector [data-fx=inspector][data-kind=emcy]", state="visible")

    def test_narrow_window_shows_the_explanation(self):
        pg = self.page
        pg.set_viewport_size({"width": 1000, "height": 800})
        self.open_sample()
        pg.click("#trace-rows .trace-row:nth-child(5)")
        pg.wait_for_selector("#trace-inspector [data-fx=meaning]")
        pg.wait_for_timeout(200)
        self.assertTrue(self.in_view("#trace-rows .trace-row.selected"))
        self.assertTrue(self.in_view("#trace-inspector [data-fx=meaning]"))


class Layers(Base):
    def test_fold_carries_over_and_is_kept(self):
        pg = self.page
        self.open_sample()
        pg.click("#trace-rows .trace-row:has-text('TPDO1')")
        pg.wait_for_selector("#trace-inspector [data-fx=inspector][data-kind=pdo]")
        pg.click('#trace-inspector details[data-fx-layer="data"] > summary')
        self.assertFalse(pg.is_visible("#trace-inspector [data-fx=grid]"))
        self.assertIn("01 00 00 00", pg.inner_text('#trace-inspector details[data-fx-layer="data"] > summary'))
        pg.wait_for_function("async () => (await api('GET', '/api/trace/prefs')).fx_fold.includes('data')")
        # Another frame and the Frame lab: still folded.
        pg.click("#trace-rows .trace-row:has-text('RPDO1')")
        pg.wait_for_selector("#trace-inspector [data-fx=meaning]:has-text('RPDO1')")
        self.assertFalse(pg.is_visible("#trace-inspector [data-fx=grid]"))
        self.lab()
        self.explain("185#2500EA00")
        self.assertFalse(pg.is_visible("#fx-lab-inspector [data-fx=grid]"))
        # The keyboard folds the wire layer; its heading keeps the figures.
        # Settled first: a late redraw of the view would take the focus away.
        pg.wait_for_timeout(300)
        pg.locator('#fx-lab-inspector details[data-fx-layer="wire"] > summary').press("Enter")
        pg.wait_for_selector("#fx-lab-inspector [data-fx=wire]", state="hidden", timeout=3000)
        self.assertRegex(pg.inner_text('#fx-lab-inspector details[data-fx-layer="wire"] > summary'), r"\d+ bits, \d+ stuff bits")
        # After a reload (once the setting is saved).
        pg.wait_for_function("async () => (await api('GET', '/api/trace/prefs')).fx_fold.includes('wire')")
        pg.reload()
        pg.wait_for_selector("#editor:not([hidden])")
        self.lab()
        self.explain("705#7F")
        self.assertFalse(pg.is_visible("#fx-lab-inspector [data-fx=wire]"))
        self.assertFalse(pg.is_visible("#fx-lab-inspector [data-fx=grid]"))

    def test_compact_grid(self):
        pg = self.page
        pg.set_viewport_size({"width": 1440, "height": 900})
        self.open()
        self.lab()
        self.explain("602#4018100400000000")
        self.assertLessEqual(pg.evaluate("document.querySelector('#fx-lab-inspector [data-fx=grid]').getBoundingClientRect().height"), 260)
        # An EMCY's empty manufacturer data: one row that opens to its bits.
        self.explain("085#0010010000000000")
        run = "#fx-lab-inspector [data-fx-run]:has-text('Manufacturer data')"
        self.assertIn("Manufacturer data", pg.inner_text(run))
        self.assertIn("00 00 00 00 00", pg.inner_text(run))
        self.assertFalse(pg.is_visible('[data-ref="data.7.7"]'))
        pg.click(run)
        self.assertEqual(pg.get_attribute(run, "aria-expanded"), "true")
        pg.focus('#fx-lab-inspector [data-ref="data.0.7"]')
        for _ in range(7):
            pg.keyboard.press("ArrowDown")
        self.assertEqual(pg.evaluate("document.activeElement.dataset.ref"), "data.7.7")
        self.assertIn("Bit 63", pg.get_attribute('[data-ref="data.7.7"]', "title"))


class LabLayout(Base):
    def test_wide_result_beside_the_input(self):
        pg = self.page
        pg.set_viewport_size({"width": 1440, "height": 900})
        self.open()
        self.lab()
        pg.wait_for_selector("[data-fx=examples] .chip")
        pg.click('[data-fx=examples] .chip:has-text("Heartbeat OPERATIONAL")')
        pg.wait_for_selector("#fx-lab-inspector [data-fx=meaning]")
        self.assertTrue(self.in_view("#fx-lab-inspector [data-fx=meaning]"))
        beside = pg.evaluate("""() => document.querySelector('#fx-lab-result').getBoundingClientRect().left >=
          document.querySelector('[data-fx=examples]').getBoundingClientRect().right""")
        self.assertTrue(beside)
        # Arbitration goes in the same column.
        pg.click("[data-fx-mode=arbitration]")
        pg.click("[data-fx-arb=go]")
        pg.wait_for_selector("#fx-lab-result [data-fx=arb-result]")
        self.assertEqual(pg.locator("#fx-lab-inspector [data-fx=inspector]").count(), 0)

    def test_examples_after_switching_tabs(self):
        """The Examples tab shows its chips each time, not "[object HTMLDivElement]"
        (fix-frame-lab-examples-text)."""
        pg = self.page
        self.open()
        self.lab()
        pg.wait_for_selector("[data-fx=examples] .chip")
        for other in ("build", "arbitration"):
            pg.click("[data-fx-mode=%s]" % other)
            pg.click("[data-fx-mode=examples]")
            self.assertGreater(pg.locator("[data-fx=examples] .chip").count(), 0, other)
            self.assertNotIn("[object ", pg.inner_text("#fx-lab-panel"), other)

    def test_narrow_result_and_clear(self):
        pg = self.page
        pg.set_viewport_size({"width": 1000, "height": 800})
        self.open()
        self.lab()
        pg.click("[data-fx-mode=build]")
        pg.fill("[data-fx-build=index]", "1018")
        pg.click("[data-fx-build=go]")
        pg.wait_for_selector("#fx-lab-inspector [data-fx=meaning]")
        pg.wait_for_timeout(200)
        self.assertTrue(self.in_view("#fx-lab-inspector [data-fx=meaning]"))
        # Clear: result gone, frame box empty and focused, the builder keeps its values.
        pg.click("[data-fx=lab-clear]")
        self.assertEqual(pg.locator("#fx-lab-inspector [data-fx=inspector]").count(), 0)
        self.assertEqual(pg.input_value("[data-fx=lab-frame]"), "")
        self.assertEqual(pg.evaluate("document.activeElement.dataset.fx"), "lab-frame")
        self.assertEqual(pg.input_value("[data-fx-build=index]"), "1018")
        # Esc in the frame box does the same.
        self.explain("705#7F")
        pg.focus("[data-fx=lab-frame]")
        pg.keyboard.press("Escape")
        self.assertEqual(pg.locator("#fx-lab-inspector [data-fx=inspector]").count(), 0)
        self.assertEqual(pg.input_value("[data-fx=lab-frame]"), "")

    def test_explain_in_lab_from_the_trace_in_view(self):
        pg = self.page
        pg.set_viewport_size({"width": 1000, "height": 800})
        self.open_sample()
        pg.click("#trace-rows .trace-row:has-text('SYNC')")
        pg.click("[data-trace=explain-lab]")
        pg.wait_for_selector("#fx-lab-inspector [data-fx=meaning]")
        pg.wait_for_timeout(200)
        self.assertTrue(self.in_view("#fx-lab-inspector [data-fx=meaning]"))
        self.assertTrue(self.in_view("[data-fx=back-to-trace]"))
        self.assertEqual(pg.evaluate("document.activeElement.dataset.fx"), "result-title")


class SimBanner(Base):
    def setUp(self):
        super().setUp()
        self.project = os.path.join(self.dir, "virtual-plant")
        shutil.copytree(os.path.join(REPO, "examples", "virtual-plant"), self.project)

    def test_one_line_with_details(self):
        # compact-chrome: a chip in the header row, the full text under Details.
        pg = self.page
        pg.set_viewport_size({"width": 1440, "height": 900})
        self.open()
        pg.wait_for_selector("#sim-banner:not([hidden])")
        self.assertEqual(pg.locator("#top .top-row #sim-banner").count(), 1)
        self.assertEqual(pg.inner_text("#sim-banner [data-sim=line]"), "Simulated: 4 networks")
        self.assertIn("Do not upload", pg.get_attribute("#sim-banner", "aria-label"))
        self.assertLess(pg.evaluate("document.querySelector('#sim-banner').getBoundingClientRect().height"), 34)
        self.assertFalse(pg.is_visible("#sim-banner [data-sim=details]"))
        pg.click("[data-sim=details-toggle]")
        details = pg.inner_text("#sim-banner [data-sim=details]")
        for part in ("Network io:", "nodes 5, 6, 7 simulated", "Network motion:", "Network cell:", "Network host:",
                     "must not be uploaded to a machine", "Do not upload it as it is"):
            self.assertIn(part, details)
        pg.click("[data-sim=details-toggle]")
        # The chip takes no row of its own: the header is as tall as without it.
        top = pg.evaluate("document.querySelector('#top .top-row').getBoundingClientRect().height")
        self.assertLess(top, 60)
