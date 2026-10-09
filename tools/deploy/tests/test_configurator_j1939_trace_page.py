"""J1939 frames in the configurator's frame inspector and Trace view, in a
real browser (j1939-trace: "J1939 identifier in the frame inspector",
"J1939 decoding"). The project holds the example J1939 network and its DBC.
Needs Playwright, like test_configurator_page.py."""

import os
import shutil

from .helpers import REPO
from .test_configurator_page import load
from .test_configurator_trace_page import TraceBase

EXAMPLE = os.path.join(REPO, "examples", "j1939")
TRACE = os.path.join(os.path.dirname(__file__), "data", "trace", "j1939.log")


class J1939Inspector(TraceBase):
    def setUp(self):
        super().setUp()
        self.cfg = load(os.path.join(EXAMPLE, "canworks.json"))
        shutil.copy(os.path.join(EXAMPLE, "machine.dbc"), os.path.join(self.project, "canworks"))
        self.write_config()

    def box(self):
        return self.page.inner_text("[data-fx=box]")

    def test_identifier_split_in_the_frame_lab(self):
        pg = self.page
        self.open()
        pg.click('button[data-view="framelab"]')
        pg.fill("[data-fx=lab-frame]", "18EF0380#01")
        pg.click("[data-fx=lab-explain]")
        pg.wait_for_selector("#fx-lab-inspector [data-fx=identifier]")
        caps = pg.eval_on_selector_all("#fx-lab-inspector [data-fx=identifier] .fx-cap",
                                       "es => es.map(e => e.textContent)")
        self.assertEqual(caps, ["Priority 6", "R 0", "DP 0", "PF 0xEF", "Destination 3", "Source 0x80"])
        self.assertIn("PGN 0xEF00 = 61184 (Command)", pg.inner_text("#fx-lab-inspector [data-fx=pgn]"))
        self.assertIn("Mode=1", pg.inner_text("#fx-lab-inspector [data-fx=meaning]"))
        pg.hover('#fx-lab-inspector [data-fx=identifier] [data-ref="id.9"]')
        self.assertIn("PDU specific: destination address (its bit 1)", self.box())
        # A PDU2 identifier: PS is the group extension, part of the PGN.
        pg.fill("[data-fx=lab-frame]", "18FF0000#D204F664FDFFFFFF")
        pg.click("[data-fx=lab-explain]")
        pg.wait_for_selector("#fx-lab-inspector .fx-cap:has-text('Group extension 0x00')")
        self.assertIn("PGN 0xFF00 = 65280 (Pressures)", pg.inner_text("#fx-lab-inspector [data-fx=pgn]"))
        self.assertIn("Pressure=123.4 bar", pg.inner_text("#fx-lab-inspector [data-fx=meaning]"))

    def test_trace_rows_and_inspector(self):
        pg = self.page
        self.open()
        self.trace_view()
        pg.set_input_files('input[data-trace="open-input"]', TRACE)
        pg.wait_for_selector("#trace-rows .trace-row")
        rows = self.rows()
        self.assertIn("Pressure=123.4 bar", next(r for r in rows if "Pressures" in r))
        self.assertTrue(any("Address Claimed" in r and "address 128 (PLC)" in r for r in rows))
        # The BAM session: one row with the whole message, its seven frames
        # still rows.
        pg.fill('[data-trace-filter="text"]', "PGN 65283")
        pg.press('[data-trace-filter="text"]', "Tab")
        self.wait_rows(7)
        bam = self.rows()
        self.assertIn("BAM for PGN 65283", bam[0])
        self.assertIn("40 bytes by BAM", bam[-1])
        self.assertIn("01 02 03 04 05 06 07 08 09 0A", bam[-1])
        pg.fill('[data-trace-filter="text"]', "")
        pg.press('[data-trace-filter="text"]', "Tab")
        # Filter on the transport frames: the parts without the message rows.
        pg.check('[data-trace-kind="tp"]')
        self.wait_rows(14)
        pg.uncheck('[data-trace-kind="tp"]')
        pg.click("#trace-rows .trace-row:has-text('Address Claimed')")
        pg.wait_for_selector("#trace-inspector [data-fx=inspector][data-kind=claim]")
        self.assertIn("Identity number", pg.inner_text("#trace-inspector [data-fx=fields]"))
        self.assertIn("Source 0x80", pg.inner_text("#trace-inspector [data-fx=identifier]"))
