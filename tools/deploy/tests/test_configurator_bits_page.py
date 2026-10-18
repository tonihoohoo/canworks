"""Bit channels in a real browser (spec canopen-configurator "Bit channels
in the PDOs tab"): Map all bits of a CiA 402 statusword with names from the
built-in note, a rename that reaches the declarations, Unmap all, and the
question before an RPDO entry's own location goes, at 1280 px with no
clipped text. Needs Playwright, like test_configurator_page.py."""

import json
import os
import shutil

from .helpers import REPO, tree_node
from .test_configurator_layout import FIT_CHECK
from .test_configurator_online_page import OnlineBase
from .test_configurator_page import load

EXAMPLE = os.path.join(REPO, "examples", "gantry-cell", "canworks")


class BitsPage(OnlineBase):
    def setUp(self):
        super().setUp()
        self.cfg = load(os.path.join(EXAMPLE, "canworks.json"))
        for name in ("servo402.eds", "dio16.eds"):
            shutil.copy(os.path.join(EXAMPLE, name), os.path.join(self.project, "canworks"))
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
        # Bit n at bit n mod 8 of the block's (n div 8)-th byte.
        first = int(bits[0]["iec_location"][3:].split(".")[0])
        self.assertEqual([b["iec_location"] for b in bits],
                         ["%%IX%d.%d" % (first + b // 8, b % 8) for b in range(16)])
        self.assertEqual(pg.inner_text('[data-bits-for="%s"]' % ep), "Bits… (16)")
        # A rename reaches the declarations.
        name = '%s input[data-bit-of][data-bit="3"]' % table
        pg.fill(name, "drive_fault")
        self.checked()
        decls = pg.evaluate("() => S.check.declarations.filter((d) => d.bit === 3).map((d) => [d.name, d.type, d.location])")
        self.assertIn(["x_drive_fault", "BOOL", bits[3]["iec_location"]], decls)
        self.assertNotIn("bit", pg.inner_text("#problem-list"))  # the fixture project's EtherCAT overlaps stay
        self.assertEqual(pg.evaluate(FIT_CHECK), [])
        # Unmap all is one undo step.
        pg.click('[data-unmap-all-bits="%s"]' % ep)
        self.assertIsNone(self.bits(ep))
        pg.keyboard.press("Control+z")
        pg.wait_for_function("(p) => (getPath(p).bits || []).length === 16", arg=ep)

    def test_output_entry_asks_before_its_location_goes(self):
        pg = self.page
        self.open()
        tree_node(pg, 3, "pdos")
        ep = self.entry(3, "0x6200:1")
        self.assertEqual(pg.evaluate("(p) => getPath(p).iec_location", ep), "%QB130")
        pg.click('[data-bits-for="%s"]' % ep)
        table = '[data-bits-table="%s"]' % ep
        tick = '%s tr[data-bit-row="0"] input[type=checkbox]' % table
        # Keeping the location maps nothing.
        pg.click(tick)
        pg.wait_for_selector("#modal[open]")
        self.assertIn("%QB130 is removed", pg.inner_text("#modal-text"))
        pg.click('#modal-buttons button[data-value="cancel"]')
        self.assertIsNone(self.bits(ep))
        self.assertFalse(pg.is_checked(tick))
        pg.click(tick)
        pg.click('#modal-buttons button[data-value="bits"]')
        pg.wait_for_function("(p) => (getPath(p).bits || []).length === 1", arg=ep)
        self.assertIsNone(pg.evaluate("(p) => getPath(p).iec_location || null", ep))
        self.assertTrue(self.bits(ep)[0]["iec_location"].startswith("%QX"))
        self.assertEqual(pg.inner_text('%s tr[data-bit-row="1"] td:nth-child(4)' % table), "sent as 0")
        self.checked()
        self.assertNotIn("bit", pg.inner_text("#problem-list"))  # the fixture project's EtherCAT overlaps stay
