"""Write configuration, Restore defaults, the PDO test tab, the lone-device
Detect and the Commission a device steps and log in a real browser, on
python-can's virtual bus (add-device-commissioning task 4). Needs
Playwright, like test_configurator_page.py."""

import json
import os
import shutil
import struct
import time
import unittest
from unittest import mock

from openplc_canopen_deploy.localbus import adapter as adapter_mod
from openplc_canopen_deploy.localbus import parse
from openplc_canopen_deploy.localbus import sweep as sweep_mod

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
        canopen = os.path.join(self.project, "canopen")
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

    def open_node(self, node, tab):
        pg = self.page
        self.open()
        pg.click('button[data-view="online"]')
        self.connect_adapter(allow=True)
        pg.click('tr[data-online-node="%d"]' % node)
        pg.click('button[data-online-tab="%s"]' % tab)


for _name in [n for n in dir(_Page) if n.startswith("test_")]:
    setattr(Page, _name, None)


class WriteConfigurationPage(Page):
    def test_plan_write_verify_and_restore_defaults(self):
        pg = self.page
        od, ro = rtd_od(5)
        od[(0x1800, 2)] = b"\x01"
        dev = self.device(5, od=od, ro=ro, identity=IDENTITY, nvm=True, heartbeat_s=0.1)
        self.open_node(5, "params")
        pg.wait_for_selector('[data-online="configure-box"]')
        self.assertEqual(pg.input_value('select[data-online="configure-source"]'), "node:5")
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
        self.open_node(23, "pdo")
        pg.check('input[data-online="pdo-nmt-start"]')
        pg.click('button[data-online="pdo-start"]')
        pg.wait_for_selector('[data-online="pdo-rpdos"]', timeout=20000)
        self.assertIn("from the configuration", pg.inner_text('[data-online="pdo-msg"]'))
        pg.select_option('select[data-online="pdo-sync"]', "50")
        pg.fill('input[data-pdo-entry="1:0x6200:1"]', "15")
        pg.click('button[data-pdo-send="1"]')
        pg.wait_for_selector('[data-pdo-sent="1"]:not(:has-text("0 sent"))', timeout=10000)
        pg.wait_for_selector('[data-online="pdo-tpdos"] tr[data-pdo-tpdo="1"]:has-text("17 (0x11)")', timeout=10000)
        self.assertEqual(dev.od[(0x6200, 1)], b"\x0f")
        audit(pg, "PDO test")
        # Leaving the tab stops the test and the SYNC.
        pg.click('button[data-online-tab="overview"]')
        time.sleep(1.0)
        n = dev.syncs
        time.sleep(0.4)
        self.assertEqual(dev.syncs, n)

    def test_read_only_and_runtime(self):
        pg = self.page
        self.device(23, od=fixed_io_od(23), pdo=True, heartbeat_s=0.1)
        self.open()
        pg.click('button[data-view="online"]')
        self.connect_adapter()
        pg.click('tr[data-online-node="23"]')
        pg.click('button[data-online-tab="pdo"]')
        pg.wait_for_selector('[data-online="pdo-no-changes"]')
        self.assertTrue(pg.is_disabled('button[data-online="pdo-start"]'))


class FastSweep(sweep_mod.Sweep):
    def __init__(self, spec, rates=None, per_rate_ms=1000, *args, **kw):
        super().__init__(spec, rates, 200, *args, **kw)


class LoneDetectPage(Page):
    def setUp(self):
        super().setUp()
        self.opened = []
        real = adapter_mod.open

        def opener(spec, bitrate, listen_only=False, options=None, disturb_bus=False):
            self.opened.append((bitrate, listen_only))
            if bitrate != 250000:
                spec = parse("virtual:%s-other-%d" % (self.ch, bitrate))
            return real(spec, bitrate, listen_only, options)

        for p in (mock.patch.object(adapter_mod, "open", opener), mock.patch.object(sweep_mod, "Sweep", FastSweep)):
            p.start()
            self.addCleanup(p.stop)

    def test_lone_device_in_the_connection_form(self):
        pg = self.page
        self.device(None)  # quiet: answers only the LSS query
        self.open()
        pg.click('button[data-view="online"]')
        pg.check('input[data-online="target-adapter"]')
        pg.fill('input[data-online="adapter"]', "virtual:" + self.ch)
        pg.select_option('select[data-online="adapter-bitrate"]', "500")
        pg.check('input[data-online="detect-lone"]')
        pg.click('button[data-online="adapter-detect"]')
        pg.wait_for_selector("#modal[open]")
        self.assertIn("Use it only on a bench", pg.inner_text("#modal-text"))
        pg.click('#modal button[data-value="go"]')
        pg.wait_for_selector('[data-online="adapter-detect-msg"]:has-text("250 kbit/s detected")', timeout=20000)
        self.assertFalse(any(lo for _, lo in self.opened))

    def test_silent_hint_and_scan_page_needs_allow(self):
        pg = self.page
        self.device(None)
        self.open()
        pg.click('button[data-view="online"]')
        self.connect_adapter()
        pg.click('button[data-view="scan"]')
        pg.wait_for_selector('[data-online="detect-box"]')
        self.assertTrue(pg.is_disabled('input[data-online="detect-lone"]'))
        pg.click('[data-online="detect"]')
        pg.wait_for_selector('[data-online="detect-verdict"]', timeout=20000)
        self.assertIn("Only this device is on the bus", pg.inner_text('[data-online="detect-verdict"]'))


class StepsPage(Page):
    def test_guided_commissioning_log_and_add_to_a_config(self):
        pg = self.page
        self.device(None, identity=(0x360, 0x1, 0x2, 0x99))
        # A standalone config folder to carry the device into.
        folder = os.path.join(self.dir, "bench")
        os.makedirs(folder)
        shutil.copy(os.path.join(PINGPONG, "cpp-slave.eds"), folder)
        with open(os.path.join(folder, "canopen.json"), "w") as f:
            json.dump(load(os.path.join(PINGPONG, "canopen_config.json")), f)
        pg.goto(self.server.url)
        pg.click("#start-commission")
        pg.wait_for_selector('[data-online="steps"]')
        self.assertEqual(len(pg.query_selector_all("#comm-steps tr")), 9)
        audit(pg, "commissioning steps")
        pg.fill('input[data-online="adapter"]', "virtual:" + self.ch)
        pg.select_option('select[data-online="adapter-bitrate"]', "250")  # commissioning picks none
        pg.check('input[data-online="adapter-allow"]')
        pg.click('button[data-online="connect"]')
        pg.wait_for_selector("text=Connected to USB adapter")
        pg.click('button[data-online="lss-find"]')
        pg.wait_for_selector('[data-online="lss-result"]:has-text("00000099")', timeout=20000)
        pg.wait_for_selector('tr[data-step="find"][data-step-state="done"]')
        pg.click('button[data-online="lss-set-id"]')
        pg.fill('input[data-online="lss-node-id"]', "12")
        pg.click('#modal button[data-value="set"]')
        pg.wait_for_selector('tr[data-step="nodeid"]:has-text("node ID 12")')
        pg.click('button[data-step-skip="pdo"]')
        pg.wait_for_selector('tr[data-step="pdo"][data-step-state="skipped"]')
        self.assertIn("not done", pg.inner_text('tr[data-step="store"]'))
        with pg.expect_download() as dl:
            pg.click('[data-online="steps"] button[data-online="save-log"]')
        d = dl.value
        self.assertRegex(d.suggested_filename, r"^node12-commissioning-\d{8}-\d{6}Z\.txt$")
        with open(d.path(), encoding="utf-8") as f:
            text = f.read()
        self.assertIn("LSS set node ID 12 (serial number 0x00000099): set", text)
        self.assertIn("Serial number 0x00000099", text)
        self.assertNotIn(self.ch, text)
        # Add to a config: the folder opens with node 12 added, unsaved.
        pg.click('button[data-online="add-to-config"]')
        pg.fill('input[data-online="add-folder"]', folder)
        pg.set_input_files('input[data-online="add-eds"]', FIXED_IO)
        pg.click('#modal button[data-value="add"]')
        pg.wait_for_function("() => (S.config.nodes || []).some((n) => Number(n.node_id) === 12)")
        node = pg.evaluate("() => S.config.nodes.find((n) => Number(n.node_id) === 12)")
        self.assertEqual(node["serial_number"], 0x99)
        self.assertTrue(node["lss"]["assign"])
        self.assertEqual(node["eds"], "fixed-io.eds")
        self.assertTrue(pg.evaluate("() => S.dirty"))


del _Page

if __name__ == "__main__":
    unittest.main()
