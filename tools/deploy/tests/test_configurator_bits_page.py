"""Bit channels in a real browser (spec canopen-configurator "Bit channels
in the PDOs tab"): Map all bits of a drive's statusword with names from the
built-in note, a rename, Unmap all, and an
RPDO entry that keeps its location, at 1280 px with no
clipped text. Needs Playwright, like test_configurator_page.py."""

import json
import os
import shutil

from .helpers import REPO, tree_net, tree_node
from .test_configurator_layout import FIT_CHECK
from .test_configurator_online_page import OnlineBase
from .test_configurator_page import load

EXAMPLE = os.path.join(REPO, "examples", "virtual-plant", "canworks")


class BitsPage(OnlineBase):
    def setUp(self):
        super().setUp()
        self.cfg = load(os.path.join(EXAMPLE, "canworks.json"))
        for name in ("dio16.eds", "rtd8.eds", "cell.eds", "cell_eds.json"):
            shutil.copy(os.path.join(EXAMPLE, name), os.path.join(self.project, "canworks"))
        # A drive in the motion network instead of the conveyor: its statusword has built-in bit names.
        shutil.copy(os.path.join(REPO, "test", "fixtures", "eds", "drives", "servo402.eds"), os.path.join(self.project, "canworks"))
        motion = [n for n in self.cfg["networks"] if n.get("name") == "motion"][0]
        motion["nodes"] = [{"node_id": 4, "name": "drive", "eds": "servo402.eds", "heartbeat_ms": 100, "tx_pdos": [
            {"entries": [{"index": "0x6041", "subindex": 0, "type": "UNSIGNED16", "iec_location": "%IW32"}]}]}]
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(self.cfg, f, indent=2)
        self.page.set_viewport_size({"width": 1280, "height": 900})

    def checked(self):
        self.page.wait_for_function("() => document.body.dataset.checking === '0'")

    def entry(self, i, obj):
        """The page path of node i's PDO entry of object `obj` ("0x6041:0")."""
        return self.page.get_attribute('[data-node-tab-panel="pdos"] tr:has(td:text-is("%s")) [data-bits-for]' % obj,
                                       "data-bits-for")

    def bits(self, path):
        return self.page.evaluate("(p) => getPath(p).bits || null", path)

    def test_statusword_map_all_rename_and_unmap(self):
        pg = self.page
        self.open()
        tree_net(pg, 1)  # motion: the drive
        tree_node(pg, 0, "pdos")
        ep = self.entry(0, "0x6041:0")
        pg.click('[data-bits-for="%s"]' % ep)
        table = '[data-bits-table="%s"]' % ep
        pg.wait_for_selector(table)
        self.assertEqual(pg.inner_text('%s tr[data-bit-row="0"] td:nth-child(2)' % table), "ready to switch on")
        pg.click('[data-map-all-bits="%s"]' % ep)
        pg.wait_for_function("(s) => document.querySelectorAll(s + ' tr.mapped').length === 16", arg=table)
        bits = self.bits(ep)
        self.assertEqual(bits[0]["name"], "ready_to_switch_on")
        self.assertEqual(bits[3]["name"], "fault")
        # The bridge serves the bits in the entry's own location: no location per bit.
        self.assertTrue(all("iec_location" not in b for b in bits))
        self.assertEqual(pg.inner_text('[data-bits-for="%s"]' % ep), "Bits… (16)")
        # A rename reaches the config.
        name = '%s input[data-bit-of][data-bit="3"]' % table
        pg.fill(name, "drive_fault")
        self.checked()
        self.assertEqual(self.bits(ep)[3]["name"], "drive_fault")
        self.assertNotIn("bit", pg.inner_text("#problem-list"))
        self.assertEqual(pg.evaluate(FIT_CHECK), [])
        # Unmap all is one undo step.
        pg.click('[data-unmap-all-bits="%s"]' % ep)
        self.assertIsNone(self.bits(ep))
        pg.keyboard.press("Control+z")
        pg.wait_for_function("(p) => (getPath(p).bits || []).length === 16", arg=ep)

    def test_output_entry_keeps_its_location(self):
        pg = self.page
        self.open()
        tree_net(pg, 0)  # io: the DIO-16
        tree_node(pg, 1, "pdos")
        ep = self.entry(1, "0x6200:1")
        loc = pg.evaluate("(p) => getPath(p).iec_location", ep)
        pg.click('[data-bits-for="%s"]' % ep)
        table = '[data-bits-table="%s"]' % ep
        # The bridge serves bits in the entry's location: a tick maps the bit and asks nothing.
        pg.click('%s tr[data-bit-row="0"] input[type=checkbox]' % table)
        pg.wait_for_function("(p) => (getPath(p).bits || []).length === 1", arg=ep)
        self.assertFalse(pg.is_visible("#modal[open]"))
        self.assertEqual(pg.evaluate("(p) => getPath(p).iec_location", ep), loc)
        # An unmapped bit keeps what the PLC writes in the entry's location.
        self.assertEqual(pg.inner_text('%s tr[data-bit-row="1"] td:nth-child(4)' % table), "")
        self.checked()
        self.assertNotIn("bit", pg.inner_text("#problem-list"))
