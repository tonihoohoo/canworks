"""J1939 networks in the configurator, in a real browser (j1939-pc-tools "J1939
network in the configurator", "J1939 online view"): a network built from the
example DBC and saved, and the online view against the fake plugin's
recorded status answer. Needs Playwright, like test_configurator_page.py."""

import json
import os
import shutil

from canworks import diag

from .fake_diag import J1939_NETWORK, TOKEN, FakePlugin
from .helpers import REPO
from .test_configurator_online_page import OnlineBase
from .test_configurator_page import load

EXAMPLE = os.path.join(REPO, "examples", "j1939")


class J1939Page(OnlineBase):
    def write_config(self, diagnostics=None):
        # Version 2: the diagnostics are a top-level object.
        cfg = json.loads(json.dumps(self.cfg))
        if diagnostics:
            cfg["diagnostics"] = diagnostics
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)

    def test_build_a_network_from_the_dbc(self):
        pg = self.page
        os.remove(self.config_path)
        self.open()
        # A J1939 network next to the empty CANopen one, then the CANopen one goes.
        pg.click('button[data-net-action="add"]')
        pg.click('#modal button[data-value="j1939"]')
        pg.wait_for_selector("h2:has-text('Bus and ECU')")
        self.assertTrue(pg.is_hidden("#nodes-caption"))
        self.assertTrue(pg.is_hidden("#eds-input >> xpath=.."))
        self.assertTrue(pg.is_hidden("#nav-scan"))
        self.assertEqual(pg.locator('[data-path="master.node_id"]').count(), 0)
        pg.click('#net-bar button[data-net="0"]')
        pg.click('button[data-net-action="remove"]')
        pg.click('#modal button[data-value="remove"]')
        pg.wait_for_selector("h2:has-text('Bus and ECU')")
        pg.fill('input[data-path="adapter.interface"]', "can1")
        pg.fill('input[data-path="j1939.ecu.name.identity_number"]', "77")
        pg.fill('input[data-path="j1939.ecu.name.function"]', "130")
        self.assertEqual(pg.inner_text("output[data-j1939=name]"), "0x000082000000004D")
        # Import: Setpoints comes from address 128 (this ECU), so Send is preselected.
        pg.set_input_files("input[data-j1939=dbc-input]", os.path.join(EXAMPLE, "machine.dbc"))
        pg.wait_for_selector("#modal .j1939-picker")
        picks = pg.eval_on_selector_all("#modal select[data-pick]", "ss => ss.map(s => [s.dataset.pick, s.value])")
        self.assertEqual(picks, [["Pressures", "rx"], ["Setpoints", "tx"], ["ComponentInfo", "rx"], ["Command", "tx"]])
        pg.select_option('#modal select[data-pick="Command"]', "")
        pg.click('#modal button[data-value="add"]')
        pg.wait_for_selector("#banner:has-text('Added 2 received and 1 sent PGNs from machine.dbc')")
        # Free locations: a device of the editor project uses %ID100.
        self.assertEqual(pg.input_value('input[data-path="j1939.rx[1].signals[0].iec_location"]'), "%ID101")
        pg.wait_for_function("() => document.body.dataset.checking === '0'")
        self.assertEqual(pg.inner_text("#problem-list"), "No problems.")
        # A problem shows at its field and goes away again.
        pg.fill('input[data-path="j1939.ecu.address"]', "254")
        pg.wait_for_selector('input[data-path="j1939.ecu.address"].invalid')
        self.assertIn("ECU identity", pg.inner_text("#problem-list"))
        pg.fill('input[data-path="j1939.ecu.address"]', "128")
        pg.wait_for_function("() => document.body.dataset.checking === '0'")
        pg.click("#btn-save")
        pg.wait_for_selector("#banner:has-text('Saved')")
        saved = load(self.config_path)
        self.assertEqual(saved["schema_version"], 2)
        net = saved["networks"][0]
        self.assertEqual(len(saved["networks"]), 1)
        self.assertEqual(net["protocol"], "j1939")
        self.assertEqual([m["name"] for m in net["j1939"]["rx"]], ["Pressures", "ComponentInfo"])
        self.assertEqual([m["name"] for m in net["j1939"]["tx"]], ["Setpoints"])
        self.assertEqual(net["j1939"]["dbc"], "machine.dbc")
        self.assertEqual(net["j1939"]["ecu"]["name"], {"identity_number": 77, "function": 130})
        self.assertTrue(os.path.isfile(os.path.join(self.project, "canworks", "machine.dbc")))

    def test_multiplexed_send_pgn(self):
        pg = self.page
        self.cfg = load(os.path.join(EXAMPLE, "canworks.json"))
        self.cfg["networks"][0]["j1939"]["tx"].append({"pgn": 0xFF20, "name": "Lamps", "period_ms": 100, "signals": [
            {"name": "Page", "start_bit": 0, "length": 8, "iec_location": "%QB220"},
            {"name": "Left", "start_bit": 8, "length": 8, "iec_location": "%QB221"},
            {"name": "Right", "start_bit": 8, "length": 8, "iec_location": "%QB222"}]})
        shutil.copy(os.path.join(EXAMPLE, "machine.dbc"), os.path.join(self.project, "canworks"))
        self.write_config()
        self.open()
        base = "j1939.tx[2]"
        pg.wait_for_selector(f'[data-j1939-msg="tx:2"]')
        # Without a switch there is no Pages choice, and Left and Right overlap.
        self.assertEqual(pg.locator(f'select[data-path="{base}.pages"]').count(), 0)
        pg.wait_for_function("() => document.body.dataset.checking === '0'")
        self.assertIn("overlap", pg.inner_text("#problem-list"))
        pg.check(f'input[data-path="{base}.signals[0].multiplexer"]')
        pg.fill(f'input[data-path="{base}.signals[1].mux"]', "1")
        pg.press(f'input[data-path="{base}.signals[1].mux"]', "Tab")
        pg.fill(f'input[data-path="{base}.signals[2].mux"]', "2-3")
        pg.press(f'input[data-path="{base}.signals[2].mux"]', "Tab")
        pg.wait_for_selector("#problem-list li.ok")
        # All pages: the plugin sets the switch, so its location goes.
        pg.select_option(f'select[data-path="{base}.pages"]', "all")
        self.assertEqual(pg.input_value(f'input[data-path="{base}.signals[0].iec_location"]'), "")
        pg.wait_for_selector("#problem-list li.ok")
        pg.click("#btn-save")
        pg.wait_for_selector("#banner:has-text('Saved')")
        lamps = load(self.config_path)["networks"][0]["j1939"]["tx"][2]
        self.assertEqual(lamps["pages"], "all")
        self.assertIs(lamps["signals"][0]["multiplexer"], True)
        self.assertNotIn("iec_location", lamps["signals"][0])
        self.assertEqual(lamps["signals"][2]["mux"], {"values": [[2, 3]]})

    def test_online_view(self):
        pg = self.page
        self.cfg = load(os.path.join(EXAMPLE, "canworks.json"))
        shutil.copy(os.path.join(EXAMPLE, "machine.dbc"), os.path.join(self.project, "canworks"))
        with FakePlugin(networks=[J1939_NETWORK]) as fp:
            fp.status["j1939"]["rx"][0]["unknown_pages"] = 3
            self.write_config({"token_verifier": diag.token_verifier(TOKEN)})
            self.remember(fp.runtime)
            self.open()
            pg.click('button[data-view="online"]')
            pg.wait_for_selector("[data-j1939=claim]")
            self.assertIn("J1939 session up", pg.inner_text("#online-conn"))
            self.assertEqual(pg.inner_text("[data-j1939=claim]"), "claimed, address 128")
            self.assertIn("0x80008200000004D2", pg.inner_text("td[data-j1939=name]"))
            ecu = pg.inner_text('tr[data-j1939-ecu="0"]')
            self.assertIn("0x0000000000000001", ecu)
            rx = pg.inner_text('tr[data-j1939-rx="65280"]')
            self.assertIn("Pressures", rx)
            self.assertIn("0, 3", rx)
            self.assertIn("timed out", rx)
            self.assertEqual(pg.inner_text('[data-j1939-unknown="65280"]'), "3 unknown pages")
            self.assertIn("Pressure = 123.4 bar (raw 1234)", rx)
            self.assertIn("Temp = -10 degC", rx)
            self.assertIn("not available", pg.inner_text('tr[data-j1939-rx="65280"] [data-j1939-signal="Level"]'))
            self.assertIn("never", pg.inner_text('tr[data-j1939-rx="65282"]'))
            self.assertIn("NAME 0x0000000000000001", pg.inner_text('tr[data-j1939-rx="65283"]'))
            tx = pg.inner_text('tr[data-j1939-tx="65281"]')
            self.assertIn("Setpoints", tx)
            self.assertIn("812", tx)
            self.assertIn("81", pg.inner_text('tr[data-j1939-request="65282"]'))
            # No CANopen tools on a J1939 network.
            self.assertEqual(pg.locator('[data-online="lss"]').count(), 0)
            self.assertEqual(pg.locator("tr[data-online-node]").count(), 0)
