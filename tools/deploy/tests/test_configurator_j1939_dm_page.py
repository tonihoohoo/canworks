"""J1939 diagnostics in the configurator, in a real browser (j1939-pc-tools
"Diagnostics in the configurator", "Faults in the J1939 online view"): an own
trouble code added and saved, a watched ECU, the PGN 65226 hint, and the
Faults panel against the fake plugin with DM2 read and a confirmed clear.
Needs Playwright, like test_configurator_page.py."""

import json
import os
import shutil
import time
from unittest import mock

from canworks import diag
from canworks.j1939 import dbc as j1939_dbc

from .fake_diag import J1939_NETWORK, TOKEN, FakePlugin
from .test_configurator_j1939_page import EXAMPLE
from .test_configurator_layout import FIT_CHECK
from .test_configurator_online_page import OnlineBase
from .test_configurator_page import load

FORCE_TEXT = "clearing trouble codes acts on another ECU: repeat with force"


class DmPlugin(FakePlugin):
    """The fake plugin with the DM operations of a J1939 network (the
    diagnostics channel's j1939_dm_read and j1939_dm_clear)."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.dm2 = {0: [{"spn": 520193, "fmi": 1, "oc": 2, "cm": False}]}

    def answer(self, req, conn=None):
        op = req.get("op")
        if op == "j1939_dm_read":
            a = req.get("address")
            if a not in self.dm2:
                return {"ok": False, "error": "no answer from %s within 1000 ms" % a}
            return {"ok": True, "result": {"address": a, "lamps": 0, "flash": 255, "count": len(self.dm2[a]),
                                           "dtcs": self.dm2[a]}}
        if op == "j1939_dm_clear":
            if not req.get("force"):
                return {"ok": False, "error": FORCE_TEXT}
            a = req.get("address")
            return {"ok": True, "result": {"address": a, "result": "sent" if a == 255 else "ack"}}
        return super().answer(req, conn)


def dm_status(sources=()):
    return {"sources": list(sources),
            "watched": [{"index": 0, "source": 0, "source_name": None, "timed_out": False, "timeouts": 0}],
            "own": {"active": [{"spn": 520192, "fmi": 3, "oc": 1, "lamps": ["amber"], "flash": None}],
                    "previous": [{"spn": 520193, "fmi": 1, "oc": 2}],
                    "lamps": 4, "flash": 255, "clears": 1, "suspended": False, "dm1_sent": 12}}


class J1939DmPage(OnlineBase):
    def write_config(self, diagnostics=None):
        cfg = json.loads(json.dumps(self.cfg))
        if diagnostics:
            cfg["diagnostics"] = diagnostics
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)

    def use_example(self, keep_diagnostics=True):
        self.cfg = load(os.path.join(EXAMPLE, "canworks.json"))
        if not keep_diagnostics:
            self.cfg["networks"][0]["j1939"].pop("diagnostics", None)
        shutil.copy(os.path.join(EXAMPLE, "machine.dbc"), os.path.join(self.project, "canworks"))

    def checked(self):
        self.page.wait_for_function("() => document.body.dataset.checking === '0'")

    def test_add_an_own_code(self):
        pg = self.page
        self.use_example(keep_diagnostics=False)
        # A hand-mapped DM1 gets the hint to use the Diagnostics section.
        self.cfg["networks"][0]["j1939"]["rx"].append({"pgn": 65226, "source": 0, "signals": [
            {"name": "Lamps", "start_bit": 0, "length": 8, "iec_location": "%IB240"}]})
        self.write_config()
        self.open()
        pg.wait_for_selector('fieldset[data-section="j1939-diagnostics"]')
        self.assertIn("watch the ECU in the Diagnostics section", pg.inner_text('[data-j1939-dm-pgn="rx:65226"]'))
        self.assertEqual(pg.locator('[data-j1939-dm-pgn^="rx:65280"]').count(), 0)
        pg.click('button[data-j1939-remove="rx:2"]')
        self.assertEqual(pg.locator("[data-j1939-dm-pgn]").count(), 0)
        # Add an own code: SPN 520192 at a free %QX, then FMI 3 and the amber lamp.
        pg.click('button[data-j1939-add="dm-dtc"]')
        base = "j1939.diagnostics.dtcs[0]"
        pg.wait_for_selector(f'input[data-path="{base}.spn"]')
        self.assertEqual(pg.input_value(f'input[data-path="{base}.spn"]'), "520192")
        location = pg.input_value(f'input[data-path="{base}.active_location"]')
        self.assertRegex(location, r"^%QX\d+\.[0-7]$")
        fmi_texts = pg.eval_on_selector(f'select[data-path="{base}.fmi"]', "s => [...s.options].map(o => o.text)")
        self.assertEqual(len(fmi_texts), 32)
        self.assertEqual(fmi_texts[3], "3: voltage above normal or shorted high")
        pg.select_option(f'select[data-path="{base}.fmi"]', "3")
        pg.check('input[data-j1939-lamp="0:amber"]')
        # A second code gets the next SPN and another location.
        pg.click('button[data-j1939-add="dm-dtc"]')
        pg.wait_for_selector('input[data-path="j1939.diagnostics.dtcs[1].spn"]')
        self.assertEqual(pg.input_value('input[data-path="j1939.diagnostics.dtcs[1].spn"]'), "520193")
        self.assertNotEqual(pg.input_value('input[data-path="j1939.diagnostics.dtcs[1].active_location"]'), location)
        pg.click('button[data-j1939-remove="dm-dtc:1"]')
        self.checked()
        self.assertEqual(pg.inner_text("#problem-list"), "No problems.")
        # An SPN out of range shows at its field and goes away again.
        pg.fill(f'input[data-path="{base}.spn"]', "600000")
        pg.wait_for_selector(f'input[data-path="{base}.spn"].invalid')
        self.assertIn("own code SPN 600000", pg.inner_text("#problem-list"))
        pg.fill(f'input[data-path="{base}.spn"]', "520192")
        self.checked()
        self.assertEqual(pg.inner_text("#problem-list"), "No problems.")
        pg.set_viewport_size({"width": 1280, "height": 800})
        self.assertEqual(pg.evaluate(FIT_CHECK), [])
        pg.click("#btn-save")
        pg.wait_for_selector("#banner:has-text('Saved')")
        saved = load(self.config_path)["networks"][0]["j1939"]
        self.assertEqual(saved["diagnostics"], {"dtcs": [{"spn": 520192, "fmi": 3, "active_location": location,
                                                          "lamps": ["amber"]}]})

    def test_watch_an_ecu_and_settings(self):
        pg = self.page
        self.use_example(keep_diagnostics=False)
        self.write_config()
        self.open()
        pg.click('button[data-j1939-add="dm-rx"]')
        base = "j1939.diagnostics.rx[0]"
        pg.wait_for_selector(f'input[data-path="{base}.source"]')
        self.assertEqual(pg.input_value(f'input[data-path="{base}.source"]'), "0")
        locs = {k: pg.input_value(f'input[data-path="{base}.{k}"]')
                for k in ("status_location", "lamps_location", "count_location", "dtcs_location")}
        self.assertRegex(locs["status_location"], r"^%IX\d+\.[0-7]$")
        self.assertRegex(locs["lamps_location"], r"^%IB\d+$")
        self.assertRegex(locs["count_location"], r"^%IB\d+$")
        self.assertNotEqual(locs["lamps_location"], locs["count_location"])
        self.assertRegex(locs["dtcs_location"], r"^%ID\d+$")
        self.assertEqual(pg.input_value(f'input[data-path="{base}.dtcs"]'), "4")
        # More codes: the suggestion finds 8 free double words in a row.
        pg.fill(f'input[data-path="{base}.dtcs"]', "8")
        pg.click(f'button[data-suggest="{base}.dtcs_location"]')
        pg.wait_for_function(f"""() => /^%ID\\d+$/.test(document.querySelector('input[data-path="{base}.dtcs_location"]').value)""")
        pg.click('button[data-suggest="j1939.diagnostics.lamps_location"]')
        pg.wait_for_function("""() => /^%QB\\d+$/.test(document.querySelector('input[data-path="j1939.diagnostics.lamps_location"]').value)""")
        pg.uncheck('input[data-path="j1939.diagnostics.accept_clear"]')
        self.checked()
        self.assertEqual(pg.inner_text("#problem-list"), "No problems.")
        pg.click("#btn-save")
        pg.wait_for_selector("#banner:has-text('Saved')")
        d = load(self.config_path)["networks"][0]["j1939"]["diagnostics"]
        self.assertEqual(d["rx"][0]["source"], 0)
        self.assertEqual(d["rx"][0]["dtcs"], 8)
        self.assertIs(d["accept_clear"], False)
        self.assertRegex(d["lamps_location"], r"^%QB\d+$")
        # Removing the only watched ECU leaves the settings.
        pg.click('button[data-j1939-remove="dm-rx:0"]')
        self.assertEqual(pg.locator('[data-j1939-dm-rx]').count(), 0)

    def test_faults_panel(self):
        pg = self.page
        self.use_example()
        names = mock.patch.object(j1939_dbc, "spn_names", lambda path: {520192: "OilPressureLow"}, create=True)
        names.start()
        self.addCleanup(names.stop)
        with DmPlugin(networks=[J1939_NETWORK]) as fp:
            fp.status["j1939"]["dm"] = dm_status()
            self.write_config({"token_verifier": diag.token_verifier(TOKEN)})
            self.remember(fp.runtime)
            self.open()
            pg.click('button[data-view="online"]')
            pg.wait_for_selector('[data-j1939="faults"]')
            self.assertIn("no DM1 yet", pg.inner_text('[data-j1939="dm-sources"]'))
            own = pg.inner_text('[data-j1939="dm-own"]')
            self.assertIn("amber warning", own)
            self.assertIn("SPN 520192 OilPressureLow, FMI 3 (voltage above normal or shorted high), OC 1",
                          pg.inner_text('[data-j1939="own-active"]'))
            self.assertIn("SPN 520193, FMI 1", pg.inner_text('[data-j1939="own-previous"]'))
            # ECU 0 raises a fault while the panel is open: its row within 2 s.
            fp.status["j1939"]["dm"] = dm_status([{
                "address": 0, "lamps": 0x04, "flash": 0xFF, "count": 1, "truncated": 0,
                "dtcs": [{"spn": 520192, "fmi": 3, "oc": 2, "cm": False}], "age_ms": 120, "dm1_count": 3,
                "old_spn_format": False}])
            started = time.monotonic()
            pg.wait_for_selector('tr[data-j1939-dm-source="0"] [data-lamp="amber"]', timeout=2000)
            self.assertLess(time.monotonic() - started, 2.0)
            row = pg.inner_text('tr[data-j1939-dm-source="0"]')
            self.assertIn("SPN 520192 OilPressureLow, FMI 3 (voltage above normal or shorted high), OC 2", row)
            self.assertIn("watched", row)
            self.assertEqual(pg.input_value('[data-j1939="dm-address"]'), "0")
            pg.set_viewport_size({"width": 1280, "height": 800})
            self.assertEqual(pg.evaluate(FIT_CHECK), [])
            # DM2 of ECU 0.
            pg.click('[data-j1939="dm-read"]')
            pg.wait_for_selector('[data-j1939="dm2"]')
            dm2 = pg.inner_text('[data-j1939="dm2"]')
            self.assertIn("ECU 0 (NAME 0x0000000000000001), previously active codes (DM2)", dm2)
            self.assertIn("SPN 520193, FMI 1 (below normal, most severe), OC 2", dm2)
            # The answer stays while the status keeps coming.
            pg.wait_for_timeout(1200)
            self.assertEqual(pg.locator('[data-j1939="dm2"]').count(), 1)
            reads = [r for r in fp.requests if r.get("op") == "j1939_dm_read"]
            self.assertEqual([r["address"] for r in reads], [0])
            # A read of a silent ECU says so.
            pg.fill('[data-j1939="dm-address"]', "7")
            pg.click('[data-j1939="dm-read"]')
            pg.wait_for_selector('[data-j1939="dm2"].bad')
            self.assertIn("no answer from 7 within 1000 ms", pg.inner_text('[data-j1939="dm2"]'))
            # A clear asks first, naming the ECU and what goes; Cancel sends nothing.
            pg.fill('[data-j1939="dm-address"]', "0")
            pg.click('[data-j1939="dm-clear"]')
            pg.wait_for_selector("#modal[open]")
            text = pg.inner_text("#modal-text")
            self.assertIn("active and previously active trouble codes", text)
            self.assertIn("ECU 0", text)
            self.assertIn("DM11", text)
            pg.click('#modal button[data-value="cancel"]')
            self.assertEqual([r for r in fp.requests if r.get("op") == "j1939_dm_clear"], [])
            pg.click('[data-j1939="dm-clear"]')
            pg.click('#modal button[data-value="clear"]')
            pg.wait_for_selector('[data-j1939="dm-cleared"]')
            self.assertEqual(pg.inner_text('[data-j1939="dm-cleared"]'),
                             "ECU 0 (NAME 0x0000000000000001) acknowledged the clear (DM11).")
            clears = [r for r in fp.requests if r.get("op") == "j1939_dm_clear"]
            self.assertEqual([(r["address"], r["previous"], r["force"]) for r in clears], [(0, False, True)])
            # DM3 to every ECU.
            pg.fill('[data-j1939="dm-address"]', "255")
            pg.click('[data-j1939="dm-clear-previous"]')
            self.assertIn("previously active trouble codes of every ECU on the bus (DM3)", pg.inner_text("#modal-text"))
            pg.click('#modal button[data-value="clear"]')
            pg.wait_for_selector('[data-j1939="dm-cleared"]:has-text("DM3 sent to every ECU")')
            clears = [r for r in fp.requests if r.get("op") == "j1939_dm_clear"]
            self.assertEqual((clears[-1]["address"], clears[-1]["previous"]), (255, True))
            # An address out of range is not sent.
            pg.fill('[data-j1939="dm-address"]', "254")
            pg.click('[data-j1939="dm-read"]')
            pg.wait_for_selector('[data-j1939="dm-address"].invalid')
            self.assertEqual(len([r for r in fp.requests if r.get("op") == "j1939_dm_read"]), 2)
