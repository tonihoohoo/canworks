"""The configurator page refuses what the plugin refuses, in plain words
(fix-gui-test-findings tasks 2.2-2.6): a missing CAN interface, numbers out
of range in hex and decimal, duplicate COB-IDs, a short heartbeat timeout,
schema errors without schema text, and the Simulation view's check of the
simulation file against the config. Needs Playwright, like
test_configurator_page.py."""

import copy
import json
import os
import re
import shutil
import threading
import unittest

from canworks.configurator import server as srv

from .helpers import REPO, tmpdir
from .test_configurator_page import REQUIRED, load, sync_playwright
from .test_configurator_sim_page import Base as SimBase, View as SimView, rtd_config

TWO = os.path.join(REPO, "config", "two-networks")

# Schema and regex text that must not reach the user.
SCHEMA_TEXT = re.compile(r"\^|\$|\[0-9\]|is not valid under|was expected|does not match|is a required property|"
                         r"greater than the maximum|less than the minimum|is not of type|should not be valid")


@unittest.skipIf(sync_playwright is None and not REQUIRED, "Playwright for Python is not installed")
class ChecksPage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        exe = os.environ.get("CANWORKS_CHROMIUM")
        try:
            cls.browser = cls.pw.chromium.launch(**({"executable_path": exe} if exe else {}))
        except Exception as e:  # pragma: no cover
            cls.pw.stop()
            if REQUIRED:
                raise
            raise unittest.SkipTest("no Chromium for Playwright: %s" % e)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def setUp(self):
        self.dir = tmpdir(self)
        os.environ["CANWORKS_CONFIG_DIR"] = os.path.join(self.dir, "cfg")
        self.addCleanup(os.environ.pop, "CANWORKS_CONFIG_DIR", None)
        self.folder = os.path.join(self.dir, "plant")
        os.makedirs(self.folder)
        shutil.copy(os.path.join(TWO, "cpp-slave.eds"), self.folder)
        self.server = srv.Server()
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.context = self.browser.new_context()
        self.addCleanup(self.context.close)
        self.page = self.context.new_page()
        self.page.set_default_timeout(10000)
        self.errors = []
        self.page.on("pageerror", lambda e: self.errors.append(str(e)))

    def tearDown(self):
        self.assertEqual(self.errors, [])

    def config(self):
        """One network with nodes 2 and 3 (the ping-pong slave twice)."""
        cfg = load(os.path.join(TWO, "canopen_config.json"))
        net = cfg["networks"][0]
        second = copy.deepcopy(net["nodes"][0])
        second.update(node_id=3, name="second", status_location="%IX10.1")
        second["tx_pdos"][0]["entries"][0]["iec_location"] = "%ID104"
        second["rx_pdos"][0]["entries"][0]["iec_location"] = "%QD104"
        net["nodes"].append(second)
        return {"schema_version": 1, "adapter": net["adapter"], "master": net["master"], "nodes": net["nodes"]}

    def open(self, cfg):
        with open(os.path.join(self.folder, "canworks.json"), "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
        pg = self.page
        pg.goto(self.server.url)
        pg.click("#start-standalone")
        pg.fill("#browser-path", self.folder)
        pg.click("#browser-open")
        pg.wait_for_selector("#editor:not([hidden])")
        self.settled()

    def settled(self):
        self.page.wait_for_function("() => document.body.dataset.checking === '0'")

    def problems(self):
        self.settled()
        return self.page.locator("#problem-list li").all_inner_texts()

    def field_msg(self, path):
        return self.page.inner_text('.field-msg[data-for="%s"]' % path)

    def node(self, i):
        self.page.click('#node-list [data-node="%d"]' % i)
        # Every folded section open, so each field can be typed into.
        self.page.evaluate("() => document.querySelectorAll('#view details').forEach((d) => d.open = true)")

    def type(self, path, text):
        self.page.fill('input[data-path="%s"]' % path, text)
        self.settled()

    def test_missing_interface_disables_save(self):
        pg = self.page
        self.open(self.config())
        pg.click('#net-bar button[data-net-action="add"]')
        pg.click('#modal button[data-value="canopen"]')
        self.assertEqual(pg.input_value('input[data-path="adapter.interface"]'), "")
        self.assertIn("CAN adapter: the CAN interface is missing", "\n".join(self.problems()))
        self.assertEqual(self.field_msg("adapter.interface"), "the CAN interface is missing")
        self.assertTrue(pg.is_disabled("#btn-save"))
        self.type("adapter.interface", "vcan1")
        self.assertNotIn("CAN interface is missing", "\n".join(self.problems()))

    def test_hex_and_decimal_meet_the_same_range(self):
        pg = self.page
        self.open(self.config())
        self.node(0)
        for text in ("0x80", "128"):
            self.type("nodes[0].node_id", text)
            self.assertEqual(self.field_msg("nodes[0].node_id"), "node ID must be 1 to 127", text)
            self.assertTrue(pg.is_disabled("#btn-save"))
        self.type("nodes[0].node_id", "0x2")
        self.assertEqual(self.field_msg("nodes[0].node_id"), "")
        for text in ("0x10000", "65536"):
            self.type("nodes[0].heartbeat_ms", text)
            self.assertEqual(self.field_msg("nodes[0].heartbeat_ms"), "heartbeat period must be 0 to 65535", text)
        self.type("nodes[0].heartbeat_ms", "100")
        self.type("nodes[0].heartbeat_timeout_ms", "50")
        self.assertIn("the heartbeat timeout (50 ms) must not be shorter than the heartbeat period (100 ms)",
                      self.field_msg("nodes[0].heartbeat_timeout_ms"))
        self.assertTrue(pg.is_disabled("#btn-save"))

    def test_duplicate_cob_id_marks_both_pdos(self):
        pg = self.page
        self.open(self.config())
        self.node(1)
        self.type("nodes[1].tx_pdos[0].cob_id", "0x182")
        text = "node 3 (second) TPDO 1 and node 2 (pingpong) TPDO 1 both use COB-ID 0x182"
        self.assertTrue(any(text in p for p in self.problems()), self.problems())
        self.assertIn(text, self.field_msg("nodes[1].tx_pdos[0].cob_id"))
        self.assertIn("invalid", pg.get_attribute('input[data-path="nodes[1].tx_pdos[0].cob_id"]', "class"))
        self.node(0)
        self.assertIn("invalid", pg.get_attribute('input[data-path="nodes[0].tx_pdos[0].cob_id"]', "class"))
        # Above 11 bits, in hex or decimal: what the field takes, not "'auto' was expected".
        self.node(1)
        for text in ("0x800", "2048"):
            self.type("nodes[1].tx_pdos[0].cob_id", text)
            self.assertEqual(self.field_msg("nodes[1].tx_pdos[0].cob_id"), 'COB-ID must be 0x80 to 0x7FF or "auto"')

    def test_messages_are_plain(self):
        pg = self.page
        cfg = self.config()
        cfg["master"]["sync_source"] = "plc_cycle"
        del cfg["master"]["sync_period_us"]
        self.open(cfg)
        self.node(0)
        self.type("nodes[0].node_id", "abc")
        self.type("nodes[0].status_location", "%IB13")
        self.type("nodes[0].tx_pdos[0].number", "600")
        self.assertEqual(self.field_msg("nodes[0].node_id"), "node ID must be a number (decimal or 0x hex), 1 to 127")
        self.assertEqual(self.field_msg("nodes[0].status_location"), "status bit must be an input bit such as %IX0.0")
        pg.click('button[data-view="bus"]')
        self.type("master.sync_cycles", "0")
        self.assertEqual(self.field_msg("master.sync_cycles"), "SYNC every N PLC cycles must be 1 to 1000")
        problems = self.problems()
        self.assertIn("Master: SYNC every N PLC cycles must be 1 to 1000", problems)
        self.assertIn("Node abc pingpong, TPDO 600: PDO number must be 1 to 512", problems)
        for p in problems:
            self.assertIsNone(SCHEMA_TEXT.search(p), p)
            # The place is said once.
            self.assertNotRegex(p, r"Node \S+ pingpong.*node \S+ \(pingpong\)")


    def test_pdo_place_said_once(self):
        cfg = self.config()
        del cfg["master"]["sync_period_us"]
        cfg["nodes"][0]["tx_pdos"][0]["transmission"] = 1
        self.open(cfg)
        sync = [p for p in self.problems() if "needs SYNC" in p or "SYNC" in p]
        self.assertTrue(sync, self.problems())
        self.assertTrue(sync[0].startswith("Node 2 pingpong, TPDO 1: transmission type 1"), sync[0])
        self.assertNotIn("node 2 (pingpong) TPDO 1", sync[0])


class SimulationFile(SimBase):
    """The Simulation view checks the file against the config, as the plugin
    loads it (D3): a value source on an object the master writes."""

    def test_source_on_a_master_written_object(self):
        pg = self.page
        cfg = rtd_config()
        cfg["adapter"]["simulate"] = True
        cfg["nodes"][0]["sdo"] = [{"index": "0x6110", "subindex": 1, "type": "UNSIGNED16", "value": 30}]
        self.write_config(cfg)
        with open(self.sim_path, "w", encoding="utf-8") as f:
            json.dump({"schema_version": 1, "nodes": {"5": {"sources": {"0x6110:1": {"constant": 1},
                                                                         "0x7130:1": {"constant": 2}}}}}, f)
        self.open()
        pg.click('button[data-view="simulation"]')
        pg.click('button[data-sim-tab="file"]')
        pg.fill('input[data-sim-field="file-tick"]', "20")
        box = pg.wait_for_selector('[data-sim-problems=""] li')
        self.assertIn("node 5 (rtd): 0x6110:1 is written by the master (startup SDO); a value source cannot drive it",
                      box.inner_text())
        self.assertTrue(pg.is_disabled('button[data-sim="save"]'))
        self.assertIn("1 problem", pg.inner_text('[data-sim="file-state"]'))
        pg.click('tr[data-sim-file-source="0x6110:1"] button[data-sim="remove-file-source"]')
        pg.wait_for_function("() => !document.querySelector('[data-sim-problems=\"\"] li')")
        self.assertFalse(pg.is_disabled('button[data-sim="save"]'))
        pg.click('button[data-sim="save"]')
        pg.wait_for_selector("#banner:has-text('Saved')")
        self.assertEqual(list(load(self.sim_path)["nodes"]["5"]["sources"]), ["0x7130:1"])


class SimulationLive(SimView):
    """Live: a pin or a TPDO stop the device's EDS does not have is refused
    on the page, before anything is sent (D19)."""

    def test_unknown_pin_and_tpdo(self):
        pg = self.page
        self.sim_view()
        pg.fill('input[data-sim="pin-typed"]', "0x9999:1")
        pg.click('button[data-sim="pin"]')
        pg.wait_for_selector("#banner:has-text('Node 5 has no object 0x9999:1 in its EDS.')")
        self.assertEqual(pg.locator('tr[data-sim-object="0x9999:1"]').count(), 0)
        pg.click('button[data-sim-fault="tpdo_stop"]')
        form = '[data-sim-form="tpdo_stop"] '
        pg.fill(form + 'input[data-sim-field="tpdo"]', "9")
        pg.click(form + 'button[data-sim="inject"]')
        pg.wait_for_selector(form + ".field-msg:has-text('Node 5 has no TPDO 9 (its EDS has no object 0x1808).')")
        self.assertEqual(self.fake.sent("sim_fault"), [])
        pg.fill(form + 'input[data-sim-field="tpdo"]', "1")
        pg.click(form + 'button[data-sim="inject"]')
        self.assertEqual(self.wait_sent("sim_fault")[-1]["fault"], {"tpdo_stop": 1})


if __name__ == "__main__":
    unittest.main()
