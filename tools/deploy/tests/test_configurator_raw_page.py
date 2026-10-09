"""Plain CAN networks and the CAN messages page in a real browser (spec
canopen-configurator, "CAN messages page"): a plain network built from the
example DBC and saved, and the online view against the fake plugin's plain
network status. Needs Playwright, like test_configurator_page.py."""

import json
import os
import shutil

from canworks import diag

from .fake_diag import PLAIN_NETWORK, TOKEN, FakePlugin
from .helpers import REPO
from .test_configurator_online_page import OnlineBase
from .test_configurator_page import load

EXAMPLE = os.path.join(REPO, "examples", "raw-can")


class RawPage(OnlineBase):
    def write_config(self, diagnostics=None):
        cfg = json.loads(json.dumps(self.cfg))
        if diagnostics:
            cfg["diagnostics"] = diagnostics
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)

    def test_build_a_plain_network_from_the_dbc(self):
        pg = self.page
        os.remove(self.config_path)
        self.open()
        pg.click('button[data-net-action="add"]')
        pg.click('#modal button[data-value="none"]')
        pg.wait_for_selector("h2:has-text('Bus')")
        self.assertTrue(pg.is_hidden("#nodes-caption"))
        self.assertTrue(pg.is_hidden("#nav-scan"))
        self.assertEqual(pg.locator('[data-path="master.node_id"]').count(), 0)
        pg.click('#net-bar button[data-net="0"]')
        pg.click('button[data-net-action="remove"]')
        pg.click('#modal button[data-value="remove"]')
        pg.wait_for_selector("h2:has-text('Bus')")
        pg.fill('input[data-path="adapter.interface"]', "can1")
        pg.click("#nav-raw")
        pg.wait_for_selector("h2:has-text('CAN messages')")
        pg.click("#raw-import")
        pg.set_input_files('#modal input[type="file"]', os.path.join(EXAMPLE, "cab.dbc"))
        pg.click('#modal button[data-value="next"]')
        pg.wait_for_selector('#modal select[aria-label="Use Joystick"]')
        # The PLC sends Display in the DBC, so Send is preselected.
        self.assertEqual(pg.input_value('#modal select[aria-label="Use Display"]'), "send")
        pg.select_option('#modal select[aria-label="Use Joystick"]', "receive")
        pg.select_option('#modal select[aria-label="Use Pedal"]', "receive")
        pg.click('#modal button[data-value="import"]')
        pg.wait_for_selector("#banner:has-text('Imported 3 messages')")
        self.assertIn("0x18FF1020 ext", pg.inner_text('[data-raw-table="rx"]'))
        pg.wait_for_function("() => document.body.dataset.checking === '0'")
        self.assertEqual(pg.inner_text("#problem-list"), "No problems.")
        pg.click("#btn-save")
        pg.wait_for_selector("#banner:has-text('Saved')")
        saved = load(self.config_path)
        net = saved["networks"][0]
        self.assertEqual(len(saved["networks"]), 1)
        self.assertEqual(net["protocol"], "none")
        self.assertEqual(net["adapter"]["interface"], "can1")
        self.assertEqual([m["name"] for m in net["raw"]["rx"]], ["Joystick", "Pedal"])
        self.assertEqual([m["name"] for m in net["raw"]["tx"]], ["Display"])
        self.assertEqual(net["raw"]["dbc"], "cab.dbc")
        self.assertTrue(all(s.get("iec_location") for m in net["raw"]["rx"] + net["raw"]["tx"] for s in m["signals"]))

    def test_online_view(self):
        pg = self.page
        self.cfg = load(os.path.join(EXAMPLE, "canworks.json"))
        self.cfg["networks"][0]["adapter"].pop("simulate")
        shutil.copy(os.path.join(EXAMPLE, "cab.dbc"), os.path.join(self.project, "canworks"))
        with FakePlugin(networks=[PLAIN_NETWORK]) as fp:
            self.write_config({"token_verifier": diag.token_verifier(TOKEN)})
            self.remember(fp.runtime)
            self.open()
            pg.click('button[data-view="online"]')
            pg.wait_for_selector('[data-online="raw"]')
            self.assertIn("plain CAN network up", pg.inner_text("#online-conn"))
            self.assertNotIn("No plain CAN session", pg.inner_text("#online-conn"))
            self.assertEqual(pg.inner_text('[data-online="bus"]'), "can0: error-active")
            self.assertIn("81 received, bus load 3 %", pg.inner_text('[data-online="raw"]'))
            self.assertIn("1 receivers", pg.inner_text('[data-online="raw-program"]'))
            self.assertIn("joystick", pg.inner_text('[data-online="raw-devices"]'))
            self.assertIn("0x181 [5] E8 03 0C FE 01", pg.inner_text('tr[data-raw-rx="Joystick"]'))
            pedal = pg.inner_text('tr[data-raw-rx="Pedal"]')
            self.assertIn("timed out, 1 short", pedal)
            self.assertIn("0x18FF1020", pedal)
            self.assertIn("38", pg.inner_text('tr[data-raw-tx="Display"]'))
            self.assertEqual(pg.locator('[data-online="lss"]').count(), 0)
            self.assertEqual(pg.locator("tr[data-online-node]").count(), 0)

    def test_simulation_view(self):
        pg = self.page
        self.cfg = load(os.path.join(EXAMPLE, "canworks.json"))
        shutil.copy(os.path.join(EXAMPLE, "cab.sim.json"), os.path.join(self.project, "canworks", "simulation.json"))
        self.write_config()
        self.open()
        pg.click("#nav-simulation")
        pg.click('button[data-sim-tab="file"]')
        devices = pg.inner_text('[data-sim="raw-devices"]')
        self.assertIn("0x181 every 20 ms (X, Y)", devices)
        self.assertIn("0x18FF1020 every 50 ms", devices)
        pg.click('button[data-sim-tab="scenarios"]')
        pg.wait_for_selector("text=joystick_lost")
