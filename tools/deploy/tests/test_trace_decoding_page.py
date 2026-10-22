"""The Trace's Decoding panel in a real browser (add-trace-eds-dbc-decoding):
DBC files added, remembered and removed, a node's EDS picked from the panel
with the "assumed" tag, and PDO layouts read from a device on python-can's
virtual bus in Commission a device. Needs Playwright, like
test_configurator_page.py."""

import os
import struct
import time

from canworks.bustrace.model import Frame

from .helpers import browse_eds, tool_tab
from .fake_canopen import Peer
from .test_bustrace import T0, written
from .test_configurator_layout import FIT_CHECK, pick_theme
from .test_configurator_localbus_page import AdapterPage
from .test_configurator_trace_page import TraceBase
from .test_trace_decoding import PINGPONG_DBC, SERVO


class DbcInTheTrace(TraceBase):
    def decoding(self):
        pg = self.page
        if not pg.evaluate("document.querySelector('[data-trace=decoding]').open"):
            pg.click("[data-trace=decoding] > summary")
        pg.wait_for_selector("[data-trace=decoding-panel] h3")

    def test_add_remembered_and_remove(self):
        pg = self.page
        self.open()
        self.trace_view()
        pg.set_input_files('input[data-trace="open-input"]', self.sample_file())
        pg.wait_for_selector('[data-ids-key][data-trace-id="182"]')
        self.decoding()
        self.assertIn("No DBC file", pg.inner_text("[data-trace=decoding-panel]"))
        pg.set_input_files('input[data-trace="add-dbc"]', PINGPONG_DBC)
        pg.wait_for_selector('[data-dbc-row="0"]:has-text("pingpong.dbc")')
        # The configuration's PDOs decode 0x182 and 0x202; the DBC says so.
        self.assertIn("4 of 6 messages used", pg.inner_text('[data-dbc-row="0"]'))
        pg.wait_for_selector("#trace-decoding-summary:has-text('1 DBC')")
        self.assertEqual(pg.eval_on_selector('[data-trace="dbc-up"]', "b => b.dataset.disabledReason"),
                         "Already the first file")
        pg.keyboard.press("Escape")
        # Remembered over a reload.
        pg.reload()
        self.trace_view()
        pg.wait_for_selector("#trace-decoding-summary:has-text('1 DBC')")
        self.decoding()
        pg.click('[data-trace="dbc-remove"]')
        pg.wait_for_selector("[data-trace=decoding-panel]:has-text('No DBC file')")

    def test_layout_fits(self):
        pg = self.page
        self.open()
        self.trace_view()
        pg.set_input_files('input[data-trace="open-input"]', self.sample_file())
        pg.wait_for_selector('[data-ids-key][data-trace-id="182"]')
        self.decoding()
        pg.set_input_files('input[data-trace="add-dbc"]', PINGPONG_DBC)
        pg.wait_for_selector('[data-dbc-row="0"]')
        for theme in ("light", "dark"):
            pick_theme(pg, theme)
            if not pg.is_visible("[data-trace=decoding-panel]"):
                self.decoding()
            for width in (1000, 1280, 1440):
                pg.set_viewport_size({"width": width, "height": 800})
                self.assertEqual(pg.evaluate(FIT_CHECK), [], (theme, width))


class CommissionTrace(AdapterPage):
    def servo_trace(self):
        frames = [Frame(T0 + k * 10_000, 0x185, bytes([0x37, 0x02, 0x08])) for k in range(3)]
        path = os.path.join(self.dir, "servo.log")
        with open(path, "wb") as f:
            f.write(written(frames, "candump"))
        return path

    def test_pick_eds_from_the_inspector_gives_assumed_rows(self):
        pg = self.page
        self.commission()
        tool_tab(pg, "trace")
        pg.wait_for_selector("#trace-source:not(:has-text('Loading'))")
        pg.set_input_files('input[data-trace="open-input"]', self.servo_trace())
        pg.click('[data-trace-tab="frames"]')
        pg.wait_for_selector("#trace-rows .trace-row")
        pg.click("#trace-rows .trace-row")
        pg.wait_for_selector("[data-fx=layout]")
        self.assertIn("node 5", pg.inner_text("[data-fx=layout]"))
        pg.click('[data-fx=layout] button[data-trace="pick-eds"]')
        browse_eds(pg, SERVO)
        pg.wait_for_selector('#trace-rows .trace-row [data-trace="assumed"]')
        self.assertIn("=567", pg.inner_text("#trace-rows .trace-row"))
        pg.click("#trace-rows .trace-row")
        pg.wait_for_selector("[data-fx=layout]:has-text('EDS defaults')")

    def test_layout_read_from_the_device(self):
        pg = self.page
        od = {(0x1800, 1): struct.pack("<I", 0x187), (0x1800, 2): b"\xff", (0x1A00, 0): b"\x01",
              (0x1A00, 1): struct.pack("<I", 0x60000108), (0x6000, 1): b"\x2a"}
        self.device(7, heartbeat_s=0.05, nmt_state=5, pdo=True, od=od)
        self.commission()
        tool_tab(pg, "trace")
        pg.wait_for_selector("#trace-source:not(:has-text('Loading'))")
        self.connect_adapter()
        pg.click("[data-trace=start-stop]")
        pg.click('[data-trace-tab="frames"]')
        pg.wait_for_function("""() => [...document.querySelectorAll('#trace-rows .trace-row')]
            .some(r => r.innerText.includes('TPDO1') && r.innerText.includes('=42'))""", timeout=20000)
        pg.click("[data-trace=decoding] > summary")
        pg.wait_for_selector('[data-decoding-node="7"]:has-text("read from the device")')
        pg.click("[data-trace=start-stop]")

    def three_tpdos(self, mapped):
        """Node 49 with TPDO1-3; the mapping objects of the PDOs in `mapped` only."""
        od = {(0x1000, 0): struct.pack("<I", 0x191), (0x6000, 1): b"\x2a"}
        for n in range(3):
            od[(0x1800 + n, 1)] = struct.pack("<I", 0x180 + 0x100 * n + 49)
            od[(0x1800 + n, 2)] = b"\xff"
            if n in mapped:
                od[(0x1A00 + n, 0)] = b"\x01"
                od[(0x1A00 + n, 1)] = struct.pack("<I", 0x60000108)
        self.device(49, heartbeat_s=0.05, nmt_state=5, pdo=True, od=od)
        self.commission()
        pg = self.page
        tool_tab(pg, "trace")
        pg.wait_for_selector("#trace-source:not(:has-text('Loading'))")
        self.connect_adapter()
        pg.click("[data-trace=start-stop]")
        pg.click("[data-trace=decoding] > summary")
        pg.wait_for_selector('[data-decoding-node="49"] [data-trace="read-pdos"]')

    def test_read_without_mapping_says_why(self):
        # canopen-configurator: "Result of a PDO layout read" - the COB-IDs
        # answer, the mapping objects do not: an error naming the object, and
        # the column reads "not read" with the reasons instead of "unknown".
        pg = self.page
        self.three_tpdos(())
        pg.click('[data-decoding-node="49"] [data-trace="read-pdos"]')
        pg.wait_for_selector("#banner:has-text('no PDO decodes')")
        text = pg.inner_text("#banner")
        self.assertIn("TPDO1 not usable: 0x1A00:0 not read (abort 0x06020000", text)
        self.assertNotIn("read from the device", text)
        row = '[data-decoding-node="49"]'
        pg.wait_for_selector(row + ':has-text("not read")')
        self.assertNotIn("unknown", pg.inner_text(row))
        self.assertEqual(pg.locator(row + ' [data-trace="read-why"]').count(), 3)
        pg.click("[data-trace=start-stop]")

    def test_read_names_the_pdo_that_does_not_decode(self):
        pg = self.page
        self.three_tpdos((0, 1))
        pg.click('[data-decoding-node="49"] [data-trace="read-pdos"]')
        pg.wait_for_selector("#banner:has-text('Node 49: TPDO1, TPDO2 read from the device.')")
        self.assertIn("TPDO3 not usable: 0x1A02:0 not read", pg.inner_text("#banner"))
        row = '[data-decoding-node="49"]'
        pg.wait_for_selector(row + ':has-text("read from the device")')
        self.assertIn("TPDO1, TPDO2", pg.inner_text(row))
        self.assertIn("TPDO3: 0x1A02:0 not read", pg.inner_text(row + ' [data-trace="read-why"]'))
        pg.click("[data-trace=start-stop]")

    def test_no_automatic_read_beside_another_master(self):
        pg = self.page
        od = {(0x1800, 1): struct.pack("<I", 0x187), (0x1800, 2): b"\xff", (0x1A00, 0): b"\x01",
              (0x1A00, 1): struct.pack("<I", 0x60000108), (0x6000, 1): b"\x2a"}
        peer = Peer(self.ch)
        try:
            self.commission()
            tool_tab(pg, "trace")
            pg.wait_for_selector("#trace-source:not(:has-text('Loading'))")
            self.connect_adapter()
            peer.send(0x080, b"")
            pg.wait_for_selector('#conn-bar.fault [data-conn="other"]')
            # The node comes up only now, with another master already reported.
            self.device(7, heartbeat_s=0.05, nmt_state=5, pdo=True, od=od)
            pg.click("[data-trace=start-stop]")
            pg.click('[data-trace-tab="frames"]')
            pg.wait_for_function("""() => [...document.querySelectorAll('#trace-rows .trace-row')]
                .some(r => r.innerText.includes('TPDO1'))""", timeout=20000)
            time.sleep(3)
            pg.click("[data-trace=decoding] > summary")
            pg.wait_for_selector('[data-decoding-node="7"]')
            self.assertNotIn("read from the device", pg.inner_text('[data-decoding-node="7"]'))
            pg.click('[data-decoding-node="7"] [data-trace="read-pdos"]')
            pg.wait_for_selector("#modal:has-text('Another master is active')")
            pg.click('#modal button[data-value="cancel"]')
            pg.click("[data-trace=start-stop]")
        finally:
            peer.close()
