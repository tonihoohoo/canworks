"""Write configuration, Restore defaults, the PDO test tab, the
commissioning log and "Add to a config…" in Commission a device in a real
browser, on python-can's virtual bus (add-device-commissioning task 4,
rework-commission-and-trim-configurator). Needs Playwright, like
test_configurator_page.py."""

import json
import os
import shutil
import struct
import time
import unittest

from .helpers import PINGPONG
from .test_commissioning import FIXED_IO, IDENTITY, RTD, fixed_io_od, rtd_od
from .test_configurator_layout import audit
from .test_configurator_localbus_page import AdapterPage as _Page
from .test_configurator_page import load


class Page(_Page):
    """The adapter page's fixtures without its tests, with the RTD module
    (node 5) and the fixed I/O module (node 23) in the project's config."""

    def setUp(self):
        super().setUp()
        canopen = os.path.join(self.project, "canworks")
        shutil.copy(FIXED_IO, canopen)
        shutil.copy(os.path.join(RTD, "rtd8.eds"), canopen)
        rtd = load(os.path.join(RTD, "canopen_config.json"))["nodes"][0]
        rtd.update(eds="rtd8.eds", status_location="%IX330.0")
        for p in rtd.get("tx_pdos", []):
            for k, e in enumerate(p["entries"]):
                e["iec_location"] = "%%IW%d" % (320 + k)
        self.cfg["nodes"].append(rtd)
        self.cfg["nodes"].append({"node_id": 23, "name": "io", "eds": "fixed-io.eds", "rx_pdos": [
            {"entries": [{"index": "0x6200", "subindex": 1, "type": "UNSIGNED8", "iec_location": "%QB310"}]}]})
        self.write_config()

    def open_node(self, node, tab, eds, allow=True):
        """Commission a device, connect, and open `node` added from `eds`
        (a file of the project's canworks folder) on its `tab`."""
        pg = self.page
        self.commission()
        self.connect_adapter(allow=allow)
        pg.click('button[data-view="nodes"]')
        pg.set_input_files('input[data-online="add-eds-file"]', os.path.join(self.project, "canworks", eds))
        pg.fill('input[data-online="add-node-id"]', str(node))
        pg.click('#modal button[data-value="add"]')
        pg.wait_for_selector('tr[data-online-node="%d"]' % node)
        pg.click('button[data-online-tab="%s"]' % tab)

for _name in [n for n in dir(_Page) if n.startswith("test_")]:
    setattr(Page, _name, None)


class WriteConfigurationPage(Page):
    def test_plan_write_verify_and_restore_defaults(self):
        pg = self.page
        od, ro = rtd_od(5)
        od[(0x1800, 2)] = b"\x01"
        dev = self.device(5, od=od, ro=ro, identity=IDENTITY, nvm=True, heartbeat_s=0.1)
        self.open_node(5, "params", "rtd8.eds")
        pg.wait_for_selector('[data-online="configure-box"]')
        # No config in Commission a device: node 5 of the project's config folder.
        pg.select_option('select[data-online="configure-source"]', "folder")
        pg.fill('input[data-online="configure-folder"]', self.project)
        pg.fill('input[data-online="configure-from"]', "5")
        pg.click('button[data-online="configure"]')
        pg.wait_for_selector('[data-online="configure-plan"]', timeout=20000)
        self.assertIn("TPDO1: written as one sequence", pg.inner_text('[data-online="configure-preview"]'))
        # Hold ticked, restore defaults and store unticked.
        self.assertTrue(pg.is_checked('input[data-online="configure-hold"]'))
        self.assertFalse(pg.is_checked('input[data-online="configure-restore"]'))
        self.assertFalse(pg.is_checked('input[data-online="configure-store"]'))
        audit(pg, "write configuration plan")
        self.assertEqual(dev.od[(0x1800, 2)], b"\x01")  # nothing written before confirming
        pg.click('#modal button[data-value="write"]')
        pg.wait_for_selector('[data-online="configure-done"]:has-text("Read-back verified")', timeout=20000)
        self.assertIn("Not stored on the device", pg.inner_text('[data-online="params-result"]'))
        self.assertEqual(dev.od[(0x6110, 1)], struct.pack("<H", 30))
        self.assertIsNone(dev.saved)
        pg.click('button[data-online="configure-verify"]')
        pg.wait_for_selector('[data-online="verify-done"]:has-text("no difference")', timeout=20000)
        self.assertIn("1 change in the log", pg.evaluate("() => logText()"))
        # Restore defaults asks, naming the node and 0x1011.
        pg.click('button[data-online="restore-defaults"]')
        pg.wait_for_selector("#modal[open]")
        text = pg.inner_text("#modal-text")
        self.assertIn("node 5", text)
        self.assertIn("0x1011", text)
        self.assertTrue(pg.is_checked('input[data-online="defaults-reset"]'))
        pg.click('#modal button[data-value="cancel"]')
        self.assertFalse(dev.loaded)


class PdoTestPage(Page):
    def test_set_an_output_with_sync(self):
        pg = self.page
        dev = self.device(23, od=fixed_io_od(23), pdo=True, nmt_state=127, heartbeat_s=0.1)
        self.open_node(23, "pdo", "fixed-io.eds")
        pg.check('input[data-online="pdo-nmt-start"]')
        pg.click('button[data-online="pdo-start"]')
        pg.wait_for_selector('[data-online="pdo-rpdos"]', timeout=20000)
        self.assertIn("read from the device", pg.inner_text('[data-online="pdo-msg"]'))
        pg.select_option('select[data-online="pdo-sync"]', "50")
        pg.fill('input[data-pdo-entry="1:0x6200:1"]', "15")
        pg.click('button[data-pdo-send="1"]')
        pg.wait_for_selector('[data-pdo-sent="1"]:not(:has-text("0 sent"))', timeout=10000)
        pg.wait_for_selector('[data-online="pdo-tpdos"] tr[data-pdo-tpdo="1"]:has-text("17 (0x11)")', timeout=10000)
        self.assertEqual(dev.od[(0x6200, 1)], b"\x0f")
        audit(pg, "PDO test")
        # Leaving the tab stops the test and the SYNC.
        pg.click('button[data-online-tab="status"]')
        time.sleep(1.0)
        n = dev.syncs
        time.sleep(0.4)
        self.assertEqual(dev.syncs, n)

    def test_read_only(self):
        pg = self.page
        self.device(23, od=fixed_io_od(23), pdo=True, heartbeat_s=0.1)
        self.open_node(23, "pdo", "fixed-io.eds", allow=False)
        pg.wait_for_selector('[data-online="pdo-no-changes"]')
        self.assertTrue(pg.is_disabled('button[data-online="pdo-start"]'))


class LogPage(Page):
    def test_log_and_add_to_a_config(self):
        pg = self.page
        self.device(None, identity=(0x360, 0x1, 0x2, 0x99))
        # A standalone config folder to carry the device into.
        folder = os.path.join(self.dir, "bench")
        os.makedirs(folder)
        shutil.copy(os.path.join(PINGPONG, "cpp-slave.eds"), folder)
        with open(os.path.join(folder, "canworks.json"), "w") as f:
            json.dump(load(os.path.join(PINGPONG, "canopen_config.json")), f)
        self.commission()
        audit(pg, "bus and master")
        self.connect_adapter(allow=True)
        pg.click('button[data-view="nodes"]')
        pg.click('button[data-online="lss-find"]')
        pg.wait_for_selector('[data-online="lss-result"]:has-text("00000099")', timeout=20000)
        pg.click('button[data-online="lss-set-id"]')
        pg.fill('input[data-online="lss-node-id"]', "12")
        pg.click('#modal button[data-value="set"]')
        pg.wait_for_selector('tr[data-online-node="12"]:has-text("LSS")')
        audit(pg, "nodes")
        # The log is in the bottom panel, with its count in the panel's title.
        self.assertEqual(pg.inner_text("#log-count"), "1")
        pg.click("#log-box > summary")
        pg.wait_for_selector('[data-online="log-count"]:has-text("1 change in the log, 1 not saved")')
        self.assertIn("LSS set node ID 12", pg.inner_text('[data-online="log-list"]'))
        with pg.expect_download() as dl:
            pg.click('button[data-online="save-log"]')
        d = dl.value
        self.assertRegex(d.suggested_filename, r"^node12-commissioning-\d{8}-\d{6}Z\.txt$")
        with open(d.path(), encoding="utf-8") as f:
            text = f.read()
        self.assertIn("LSS set node ID 12 (serial number 0x00000099): set", text)
        self.assertIn("Serial number 0x00000099", text)
        self.assertNotIn(self.ch, text)
        pg.wait_for_selector('[data-online="log-count"]:has-text("saved")')
        # C18: no "Compare against the configuration" without one.
        self.assertEqual(pg.evaluate("() => { const was = S.onlineEds; S.onlineEds = { 12: 'fixed-io.eds' }; "
                                     "const r = [...paramsPanel(12, { node_id: 12 }, true).querySelectorAll("
                                     "'[data-online=compare-ref] option')].map((o) => o.value); S.onlineEds = was; return r; }"),
                         ["file", "eds"])
        # A config that already has node 12: refused before it opens, the page stays.
        taken = os.path.join(self.dir, "taken")
        os.makedirs(taken)
        cfg = load(os.path.join(PINGPONG, "canopen_config.json"))
        cfg["nodes"][0]["node_id"] = 12
        with open(os.path.join(taken, "canworks.json"), "w") as f:
            json.dump(cfg, f)
        pg.click('button[data-view="nodes"]')
        pg.click('button[data-open-node="12"]')
        pg.click('button[data-online="add-to-config"]')
        pg.fill('input[data-online="add-folder"]', taken)
        pg.set_input_files('input[data-online="add-eds"]', FIXED_IO)
        pg.click('#modal button[data-value="add"]')
        pg.wait_for_selector("#banner:has-text('already has node 12')")
        self.assertTrue(pg.evaluate("() => S.state.commission"))
        # A change after saving: "Add to a config…" asks to save the log first.
        pg.evaluate("() => commLog(12, 'test entry', 'done')")
        pg.click('button[data-online="add-to-config"]')
        pg.fill('input[data-online="add-folder"]', folder)
        pg.set_input_files('input[data-online="add-eds"]', FIXED_IO)
        pg.click('#modal button[data-value="add"]')
        pg.wait_for_selector("#modal[open]:has-text('not saved')")
        pg.click('#modal button[data-value="discard"]')
        pg.wait_for_function("() => (S.config.nodes || []).some((n) => Number(n.node_id) === 12)")
        node = pg.evaluate("() => S.config.nodes.find((n) => Number(n.node_id) === 12)")
        self.assertEqual(node["serial_number"], 0x99)
        # fixed-io.eds has no LSS (LSS_Supported=0): no LSS assignment, and the page says why.
        self.assertNotIn("lss", node)
        self.assertIn("its EDS has no LSS", pg.inner_text("#banner [data-lss-note]"))
        self.assertEqual(node["eds"], "fixed-io.eds")
        self.assertTrue(pg.evaluate("() => S.dirty"))
        self.assertFalse(self.server.connection.connected)
        self.assertEqual(pg.evaluate("() => S.commLog.length"), 0)

    def test_close_asks_to_save_the_log(self):
        pg = self.page
        self.commission()
        pg.keyboard.press("Escape")  # the connect panel that opened with the page
        pg.wait_for_selector("#conn-dialog", state="hidden")
        pg.evaluate("() => commLog(5, 'test entry', 'done')")
        pg.click("#btn-close")
        pg.wait_for_selector("#modal[open]:has-text('not saved')")
        pg.click('#modal button[data-value="cancel"]')
        self.assertTrue(pg.evaluate("() => S.state.commission"))
        pg.click("#btn-close")
        with pg.expect_download():
            pg.click('#modal button[data-value="save"]')
        pg.wait_for_selector("#start-commission")


del _Page

if __name__ == "__main__":
    unittest.main()
