"""The configurator's simulation parts in a real browser (add-device-simulator
tasks 8.5-8.7): the network choice and the per-node Simulated switch, the
banner, and the Simulation view against a fake simulator. Needs Playwright,
like test_configurator_page.py."""

import json
import os
import shutil
import threading
import unittest

from canworks import diag
from canworks.configurator import server as srv

from .fake_sim_page import TOKEN, FakeSim
from .helpers import tmpdir
from .test_configurator_page import FIXTURE, REQUIRED, RTD, load, sync_playwright

BANNER_END = "must not be uploaded to a machine as it is"


def rtd_config():
    """The rtd-sensor example on can0, moved off the fixture project's addresses."""
    cfg = load(os.path.join(RTD, "canopen_config.json"))
    cfg["adapter"]["interface"] = "can0"
    node = cfg["nodes"][0]
    node["status_location"] = "%IX300.0"
    for p in node["tx_pdos"]:
        for e in p["entries"]:
            e["iec_location"] = e["iec_location"].replace("%IW10", "%IW30").replace("%IB10", "%IB30")
    return cfg


def three_nodes():
    """Nodes 5, 6 and 7 with the rtd EDS and nothing mapped."""
    cfg = rtd_config()
    cfg["nodes"] = [{"node_id": i, "name": "n%d" % i, "eds": "rtd8.eds"} for i in (5, 6, 7)]
    return cfg


@unittest.skipIf(sync_playwright is None and not REQUIRED, "Playwright for Python is not installed")
class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        exe = os.environ.get("CANOPEN_CHROMIUM")
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
        self.cfg_dir = os.path.join(self.dir, "cfg")
        os.environ["CANWORKS_CONFIG_DIR"] = self.cfg_dir
        self.addCleanup(os.environ.pop, "CANWORKS_CONFIG_DIR", None)
        self.project = os.path.join(self.dir, "rtd-monitor")
        shutil.copytree(FIXTURE, self.project)
        self.canopen = os.path.join(self.project, "canworks")
        os.makedirs(self.canopen)
        shutil.copy(os.path.join(RTD, "rtd8.eds"), self.canopen)
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

    @property
    def config_path(self):
        return os.path.join(self.canopen, "canworks.json")

    @property
    def sim_path(self):
        return os.path.join(self.canopen, "simulation.json")

    def write_config(self, cfg):
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)

    def open(self):
        self.page.goto(self.server.url)
        self.page.click("#start-project")
        self.page.fill("#browser-path", self.project)
        self.page.click("#browser-open")
        self.page.wait_for_selector("#editor:not([hidden])")

    def settled(self):
        self.page.wait_for_function("() => document.body.dataset.checking === '0'")

    def save(self):
        self.settled()
        self.page.evaluate("banner('')")
        self.page.click("#btn-save")
        self.page.wait_for_selector("#banner:has-text('Saved')")
        return load(self.config_path)

    def badges(self):
        return self.page.eval_on_selector_all("#node-list [data-node]",
                                              "els => els.map(e => { const b = e.querySelector('[data-sim-badge]');"
                                              " return b ? b.dataset.simBadge : ''; })")

    def banner_text(self):
        return self.page.inner_text("#sim-banner") if self.page.is_visible("#sim-banner") else ""


class Network(Base):
    """The four combinations of docs/simulator.md, "Two switches"."""

    def setUp(self):
        super().setUp()
        self.write_config(three_nodes())
        self.open()

    def node_switch(self, i, on):
        self.page.click('#node-list [data-node="%d"]' % i)
        box = self.page.locator('input[data-sim="node"]')
        if on:
            box.check()
        else:
            box.uncheck()
        self.page.wait_for_function("(on) => document.querySelector('input[data-sim=\"node\"]').checked === on", arg=on)

    def test_simulated_network_all_nodes(self):
        pg = self.page
        self.assertEqual(self.banner_text(), "")
        self.assertEqual(self.badges(), ["", "", ""])
        pg.select_option('select[data-path="adapter.simulate"]', "true")
        pg.wait_for_selector("#banner:has-text('Online access is now on with Allow changes')")
        self.assertEqual(self.badges(), ["simulated"] * 3)
        text = self.banner_text()
        self.assertIn("The network is simulated", text)
        self.assertIn("nodes 5, 6, 7 simulated", text)
        self.assertIn(BANNER_END, text)
        # The banner is on every page.
        for view in ('#node-list [data-node="1"]', 'button[data-view="declarations"]', 'button[data-view="trace"]'):
            pg.click(view)
            self.assertIn("The network is simulated", self.banner_text())
        pg.click('button[data-view="bus"]')
        self.assertTrue(pg.is_checked('input[data-path="master.diagnostics.allow_changes"]'))
        saved = self.save()
        self.assertEqual(saved["adapter"],
                         {"type": "socketcan", "simulate": True, "interface": "can0", "bitrate": 125000})
        self.assertTrue(all("simulate" not in n for n in saved["nodes"]))
        settings = load(os.path.join(self.cfg_dir, "online.json"))["projects"][self.project]
        self.assertTrue(diag.token_matches(settings["token"], saved["master"]["diagnostics"].pop("token_verifier")))
        self.assertEqual(saved["master"]["diagnostics"], {"allow_changes": True})
        # Back to the real network: the adapter settings were kept.
        pg.select_option('select[data-path="adapter.simulate"]', "")
        self.assertEqual(self.banner_text(), "")
        saved = self.save()
        self.assertEqual(saved["adapter"], {"type": "socketcan", "interface": "can0", "bitrate": 125000})

    def test_simulated_network_some_nodes(self):
        pg = self.page
        pg.select_option('select[data-path="adapter.simulate"]', "true")
        pg.wait_for_selector("#banner:has-text('Online access is now on')")
        self.node_switch(2, False)
        self.assertIn("Absent", pg.inner_text('[data-section] ~ fieldset, #view'))
        self.assertEqual(self.badges(), ["simulated", "simulated", "absent"])
        self.assertIn("nodes 5, 6 simulated and node 7 absent", self.banner_text())
        saved = self.save()
        self.assertIs(saved["adapter"]["simulate"], True)
        self.assertEqual([n.get("simulate") for n in saved["nodes"]], [None, None, False])

    def test_real_network_one_node(self):
        pg = self.page
        self.node_switch(0, True)
        pg.wait_for_selector("#banner:has-text('Online access is now on')")
        self.assertEqual(self.badges(), ["simulated", "", ""])
        self.assertIn("Node 5 is simulated on the real network can0.", self.banner_text())
        self.assertIn(BANNER_END, self.banner_text())
        saved = self.save()
        self.assertNotIn("simulate", saved["adapter"])
        self.assertEqual([n.get("simulate") for n in saved["nodes"]], [True, None, None])
        self.assertTrue(saved["master"]["diagnostics"]["allow_changes"])

    def test_real_network_all_nodes(self):
        pg = self.page
        pg.click('button[data-sim="all"]')
        pg.wait_for_selector("#banner:has-text('Online access is now on')")
        self.assertEqual(self.badges(), ["simulated"] * 3)
        self.assertIn("Nodes 5, 6, 7 are simulated on the real network can0.", self.banner_text())
        self.assertIn("Simulated: nodes 5, 6, 7.", pg.inner_text('[data-sim="nodes"]'))
        saved = self.save()
        self.assertEqual([n.get("simulate") for n in saved["nodes"]], [True, True, True])
        pg.click('button[data-sim="none"]')
        self.assertEqual(self.banner_text(), "")
        self.assertEqual(self.badges(), ["", "", ""])
        saved = self.save()
        self.assertTrue(all("simulate" not in n for n in saved["nodes"]))

    def test_online_access_already_on_is_left_alone(self):
        pg = self.page
        cfg = three_nodes()
        cfg["master"]["diagnostics"] = {"token_verifier": diag.token_verifier(TOKEN)}
        self.write_config(cfg)
        pg.click("#btn-reload")
        pg.wait_for_selector('input[data-online="enable"]:checked')
        pg.click('button[data-sim="all"]')
        self.assertIn("Nodes 5, 6, 7 are simulated", self.banner_text())
        self.assertFalse(pg.is_checked('input[data-path="master.diagnostics.allow_changes"]'))


class View(Base):
    """The Simulation view against the fake runtime with node 5 simulated."""

    allow = True

    def setUp(self):
        super().setUp()
        cfg = rtd_config()
        cfg["nodes"][0]["simulate"] = True
        cfg["master"]["diagnostics"] = {"token_verifier": diag.token_verifier(TOKEN), "allow_changes": self.allow}
        self.write_config(cfg)
        self.fake = FakeSim(allow_changes=self.allow).__enter__()
        self.addCleanup(self.fake.__exit__)
        os.makedirs(self.cfg_dir, exist_ok=True)
        with open(os.path.join(self.cfg_dir, "online.json"), "w") as f:
            json.dump({"projects": {self.project: {"host": self.fake.address, "token": TOKEN}}}, f)

    def sim_view(self):
        self.open()
        self.page.click('button[data-view="simulation"]')
        self.page.wait_for_selector('tr[data-sim-object="0x7130:1"] [data-sim="value"]:has-text("215")')

    def row(self, obj):
        return 'tr[data-sim-object="%s"]' % obj

    def wait_sent(self, op, n=1):
        self.page.wait_for_function("() => true")
        for _ in range(100):
            if len(self.fake.sent(op)) >= n:
                return self.fake.sent(op)
            self.page.wait_for_timeout(50)
        self.fail("no %s request" % op)


class Live(View):
    def test_values_slider_override_and_release(self):
        pg = self.page
        self.sim_view()
        self.assertIn("Connected to %s: real network can0, 1 simulated device, changes allowed." % self.fake.address,
                      pg.inner_text("#sim-conn"))
        self.assertTrue(pg.is_hidden('[data-sim="readonly"]'))
        # No machine file in this network's section: no Machine tab.
        self.assertEqual(pg.eval_on_selector_all("button[data-sim-tab]", "els => els.map(e => e.dataset.simTab)"),
                         ["live", "file", "scenarios"])
        self.assertIn("AI0_Input_PV", pg.inner_text(self.row("0x7130:1")))
        # Live values come in by themselves.
        self.fake.set_value(5, "0x7130:2", 233)
        pg.wait_for_selector(self.row("0x7130:2") + ' [data-sim="value"]:has-text("233")')
        # Dragging the slider holds the value as an override.
        pg.eval_on_selector(self.row("0x7130:1") + ' input[data-sim="slider"]',
                            "e => { e.value = '900'; e.dispatchEvent(new Event('input'));"
                            " e.dispatchEvent(new Event('change')); }")
        sent = self.wait_sent("sim_override")
        self.assertEqual(sent[-1], dict(sent[-1], node=5, values={"0x7130:1": 900}))
        pg.wait_for_selector(self.row("0x7130:1") + ' [data-sim="overridden"]')
        pg.wait_for_selector(self.row("0x7130:1") + ' [data-sim="value"]:has-text("900")')
        pg.click(self.row("0x7130:1") + ' button[data-sim="release"]')
        sent = self.wait_sent("sim_release")
        self.assertEqual(sent[-1], dict(sent[-1], node=5, objects=["0x7130:1"]))
        pg.wait_for_selector(self.row("0x7130:1") + ' [data-sim="overridden"]', state="detached")
        pg.wait_for_selector(self.row("0x7130:1") + ' [data-sim="value"]:has-text("215")')
        # Set once, from the field.
        pg.fill(self.row("0x7130:2") + ' input[data-sim="input"]', "250")
        pg.click(self.row("0x7130:2") + ' button[data-sim="set"]')
        self.assertEqual(self.wait_sent("sim_set")[-1]["values"], {"0x7130:2": 250})
        # Bits of an UNSIGNED8 and the switch of a pinned BOOLEAN.
        pg.check(self.row("0x6150:1") + ' input[data-sim-bit="2"]')
        self.assertEqual(self.wait_sent("sim_override", 2)[-1]["values"], {"0x6150:1": 4})
        pg.fill('[data-sim="pin-typed"]', "0x2000")
        pg.click('button[data-sim="pin"]')
        pg.check(self.row("0x2000:0") + ' input[data-sim="switch"]')
        self.assertEqual(self.wait_sent("sim_override", 3)[-1]["values"], {"0x2000:0": 1})
        pins = load(os.path.join(self.cfg_dir, "online.json"))["projects"][self.project]["sim_pins"]
        self.assertEqual(pins, {"5": ["0x2000:0"]})

    def test_source_with_expression_check_and_save(self):
        pg = self.page
        self.sim_view()
        pg.click(self.row("0x7130:2") + ' button[data-sim="source"]')
        pg.select_option('[data-sim-source-for="0x7130:2"] select[data-sim="source-type"]', "expr")
        pg.fill('[data-sim-source-for="0x7130:2"] input[data-sim-field="expr"]', "[0x7130:1] + foo")
        err = pg.wait_for_selector('[data-sim="expr-error"]')
        self.assertEqual(err.get_attribute("data-position"), "13")
        self.assertIn("At position 13: unknown name 'foo'", err.inner_text())
        self.assertIn("[0x7130:1] + foo\n             ^", pg.inner_text("pre.sim-caret"))
        self.assertEqual(self.fake.sent("sim_check_expr")[-1]["node"], 5)
        pg.fill('[data-sim-source-for="0x7130:2"] input[data-sim-field="expr"]', "[0x7130:1] * 2")
        pg.wait_for_selector('[data-sim="expr-ok"]')
        pg.click('button[data-sim="apply-source"]')
        sent = self.wait_sent("sim_source")
        self.assertEqual(sent[-1], dict(sent[-1], node=5, object="0x7130:2", source={"expr": "[0x7130:1] * 2"}))
        pg.wait_for_selector(self.row("0x7130:2") + ' [data-sim="sourced"]')
        # A sine on another object, then the file.
        pg.click(self.row("0x7130:1") + ' button[data-sim="source"]')
        pg.select_option('[data-sim-source-for="0x7130:1"] select[data-sim="source-type"]', "sine")
        for k, v in (("min", "200"), ("max", "260"), ("period_s", "10")):
            pg.fill('[data-sim-source-for="0x7130:1"] input[data-sim-field="%s"]' % k, v)
        pg.click('button[data-sim="apply-source"]')
        self.wait_sent("sim_source", 2)
        self.assertIn("Unsaved changes", pg.inner_text('[data-sim="file-state"]'))
        self.assertFalse(os.path.exists(self.sim_path))
        pg.click('button[data-sim="save"]')
        pg.wait_for_selector("#banner:has-text('Saved')")
        self.assertEqual(load(self.sim_path), {"schema_version": 1, "nodes": {"5": {"sources": {
            "0x7130:2": {"expr": "[0x7130:1] * 2"}, "0x7130:1": {"sine": {"min": 200, "max": 260, "period_s": 10}}}}}})
        self.assertIn("Saved", pg.inner_text('[data-sim="file-state"]'))
        # Reloading the project reads it back.
        pg.click("#btn-reload")
        pg.click('button[data-view="simulation"]')
        pg.click('button[data-sim-tab="file"]')
        self.assertIn("sine 200 to 260, 10 s", pg.inner_text('[data-sim-file="5"]'))

    def test_fault_buttons(self):
        pg = self.page
        self.sim_view()
        pg.click('button[data-sim-fault="emcy"]')
        form = '[data-sim-form="emcy"] '
        pg.fill(form + 'input[data-sim-field="code"]', "0x5000")
        pg.fill(form + 'input[data-sim-field="register"]', "1")
        pg.fill(form + 'input[data-sim-field="msef"]', "0100000000")
        pg.click(form + 'button[data-sim="inject"]')
        sent = self.wait_sent("sim_fault")
        emcy = {"emcy": {"code": "0x5000", "register": 1, "msef": "0100000000"}}
        self.assertEqual(sent[-1], dict(sent[-1], node=5, fault=emcy))
        pg.click('button[data-sim-fault="heartbeat"]')
        self.assertEqual(self.wait_sent("sim_fault", 2)[-1]["fault"], {"heartbeat": "stop"})
        pg.click('button[data-sim-fault="power_cycle"]')
        pg.fill('[data-sim-form="power_cycle"] input[data-sim-field="off_ms"]', "2000")
        pg.click('[data-sim-form="power_cycle"] button[data-sim="inject"]')
        self.assertEqual(self.wait_sent("sim_fault", 3)[-1]["fault"], {"power": "cycle", "off_ms": 2000})
        pg.click('button[data-sim-fault="sdo_abort"]')
        form = '[data-sim-form="sdo_abort"] '
        pg.fill(form + 'input[data-sim-field="object"]', "0x2000:1")
        pg.fill(form + 'input[data-sim-field="code"]', "0x08000020")
        pg.select_option(form + 'select[data-sim-field="on"]', "write")
        pg.fill(form + 'input[data-sim-field="count"]', "1")
        pg.click(form + 'button[data-sim="inject"]')
        self.assertEqual(self.wait_sent("sim_fault", 4)[-1]["fault"],
                         {"sdo_abort": {"object": "0x2000:1", "code": "0x08000020", "on": "write", "count": 1}})
        pg.click(form + 'button[data-sim="at-start"]')
        # A drive only gets drive inputs; this device is CiA 404.
        self.assertEqual(pg.locator('button[data-sim-fault="drive_input"]').count(), 0)
        self.assertEqual(pg.locator('button[data-sim-fault]').count(), 15)
        pg.wait_for_selector('#sim-active-faults button[data-sim-clear="emcy"]')
        pg.click('#sim-active-faults button[data-sim-clear="emcy"]')
        self.assertEqual(self.wait_sent("sim_clear")[-1], dict(self.fake.sent("sim_clear")[-1], node=5, fault="emcy"))
        pg.click('#sim-active-faults button[data-sim-clear="sdo_abort"]')
        self.assertEqual(self.wait_sent("sim_clear", 2)[-1]["object"], "0x2000:1")
        pg.click('#sim-active-faults button[data-sim-clear="all"]')
        self.assertEqual(self.wait_sent("sim_clear", 3)[-1]["fault"], "all")
        pg.click('button[data-sim="save"]')
        pg.wait_for_selector("#banner:has-text('Saved')")
        self.assertEqual(load(self.sim_path)["nodes"]["5"]["faults"],
                         [{"sdo_abort": {"object": "0x2000:1", "code": "0x08000020", "on": "write", "count": 1}}])

    def test_extra_device_and_file_settings(self):
        pg = self.page
        self.open()
        pg.click('button[data-view="simulation"]')
        pg.click('button[data-sim-tab="file"]')
        pg.uncheck('[data-sim-file="5"] input[data-sim-field="default_behaviour"]')
        pg.select_option('select[data-sim="extra-eds"]', "rtd8.eds")
        pg.click('button[data-sim="add-extra"]')
        self.assertIn("needs a name", pg.inner_text('[data-sim="extra-devices"]'))
        pg.fill('input[data-sim-field="extra-name"]', "spare")
        pg.click('button[data-sim="add-extra"]')
        pg.wait_for_selector("#banner:has-text('takes effect at the next start')")
        pg.wait_for_selector('tr[data-sim-extra="0"]')
        pg.select_option('[data-sim-file="5"] select[data-sim="file-fault-kind"]', "heartbeat")
        pg.click('[data-sim-file="5"] button[data-sim="add-file-fault"]')
        pg.click('button[data-sim="save"]')
        pg.wait_for_selector("#banner:has-text('Saved')")
        self.assertEqual(load(self.sim_path), {
            "schema_version": 1,
            "nodes": {"5": {"default_behaviour": False, "faults": [{"heartbeat": "stop"}]}},
            "extra_devices": [{"node": 0, "name": "spare", "eds": "rtd8.eds"}]})

    def test_standalone_simulator(self):
        pg = self.page
        with FakeSim(token="", standalone=True, simulated_network=True) as other:
            self.open()
            pg.click('button[data-view="simulation"]')
            pg.click('button[data-sim-target="simulator"]')
            pg.fill('input[data-sim="address"]', other.address)
            pg.click('button[data-sim="connect"]')
            pg.wait_for_selector("#sim-conn:has-text('Connected to the simulator at %s: simulated network')"
                                 % other.address)
            pg.wait_for_selector(self.row("0x7130:1"))
            self.assertTrue(other.sent("sim_status"))
        projects = load(os.path.join(self.cfg_dir, "online.json"))["projects"][self.project]
        self.assertEqual((projects["sim_target"], projects["sim_address"]), ("simulator", other.address))
        self.assertNotIn("sim", json.dumps(load(self.config_path)["master"]))


class ReadOnly(View):
    allow = False

    def test_without_allow_changes(self):
        pg = self.page
        self.sim_view()
        note = pg.wait_for_selector('[data-sim="readonly"]:visible')
        self.assertIn("Read-only", note.inner_text())
        self.assertIn("Allow changes", note.inner_text())
        self.assertIn("read-only", pg.inner_text("#sim-conn"))
        for sel in ('input[data-sim="slider"]', 'button[data-sim="set"]', 'button[data-sim="override"]',
                    'button[data-sim="source"]', 'button[data-sim-fault="emcy"]', 'button[data-sim-clear="all"]'):
            self.assertTrue(pg.locator(self.row("0x7130:1") + " " + sel if "fault" not in sel and "clear" not in sel
                                       else sel).first.is_disabled(), sel)
        # Values still refresh.
        self.fake.set_value(5, "0x7130:1", 300)
        pg.wait_for_selector(self.row("0x7130:1") + ' [data-sim="value"]:has-text("300")')
        self.assertEqual(self.fake.sent("sim_override"), [])


class Scenarios(View):
    def test_create_start_and_result(self):
        pg = self.page
        self.sim_view()
        pg.click('button[data-sim-tab="scenarios"]')
        pg.fill('[data-sim="new-scenario"]', "sensor-break")
        pg.click('[data-sim="create-scenario"]')
        editor = '[data-sim-editor="sensor-break"] '
        pg.select_option(editor + 'select[data-sim="step-action"]', "set")
        pg.click(editor + 'button[data-sim="add-step"]')
        step = editor + '[data-sim-step="0"] '
        pg.fill(step + 'input[data-sim-field="new-object"]', "0x7130:1")
        pg.fill(step + 'input[data-sim-field="new-value"]', "900")
        pg.click(step + 'button[data-sim="add-pair"]')
        pg.select_option(editor + 'select[data-sim="step-action"] >> nth=-1', "expect")
        pg.click(editor + 'button[data-sim="add-step"] >> nth=-1')
        step = editor + '[data-sim-step="1"] '
        pg.fill(step + 'input[data-sim-field="cond-object"]', "0x6150:1")
        pg.fill(step + 'input[data-sim-field="cond-bit"]', "2")
        pg.fill(step + 'input[data-sim-field="cond-value"]', "1")
        pg.select_option(step + 'select[data-sim-field="expect-mode"]', "within_ms")
        pg.fill(step + 'input[data-sim-field="expect_ms"]', "500")
        pg.select_option(step + 'select[data-sim-field="timing"]', "after_ms")
        pg.fill(step + 'input[data-sim-field="time_ms"]', "100")
        # A third step, with an expression condition checked as typed.
        pg.select_option(editor + 'select[data-sim="step-action"] >> nth=-1', "wait")
        pg.click(editor + 'button[data-sim="add-step"] >> nth=-1')
        step = editor + '[data-sim-step="2"] '
        pg.select_option(step + 'select[data-sim-field="cond-mode"]', "expr")
        pg.fill(step + 'input[data-sim-field="expr"]', "foo > 1")
        pg.wait_for_selector(step + '[data-sim="expr-error"][data-position="0"]')
        pg.fill(step + 'input[data-sim-field="expr"]', "[5/0x6150:1] > 1")
        pg.fill(step + 'input[data-sim-field="timeout_ms"]', "2000")
        pg.wait_for_timeout(500)
        self.assertEqual(pg.inner_text(editor + '[data-sim-problems]').strip(), "")
        pg.click('tr[data-sim-scenario="sensor-break"] button[data-sim="start-scenario"]')
        sent = self.wait_sent("sim_scenario_start")
        steps = [{"node": 5, "set": {"0x7130:1": 900}},
                 {"expect": {"node": 5, "object": "0x6150:1", "bit": 2, "eq": 1}, "within_ms": 500, "after_ms": 100},
                 {"wait": {"expr": "[5/0x6150:1] > 1"}, "timeout_ms": 2000}]
        self.assertEqual(sent[-1]["name"], "sensor-break")
        self.assertEqual(sent[-1]["scenario"], {"steps": steps})
        row = 'tr[data-sim-scenario="sensor-break"] '
        pg.wait_for_selector(row + '[data-sim="scenario-state"]:has-text("running")')
        self.assertIn("1 of 3: set Node 5 0x7130:1 = 900", pg.inner_text(row + '[data-sim="scenario-step"]'))
        self.assertTrue(pg.locator(row + 'button[data-sim="stop-scenario"]').is_enabled())
        self.fake.finish("sensor-break", "failed", "step 2: expect 5/0x6150:1 bit 2 eq 1 within 500 ms: value seen 0",
                         step=2)
        pg.wait_for_selector(row + '[data-sim="scenario-state"]:has-text("failed")')
        self.assertIn("value seen 0", pg.inner_text(row + '[data-sim="scenario-result"]'))
        self.assertIn("2 of 3: expect 5/0x6150:1 bit 2 = 1", pg.inner_text(row + '[data-sim="scenario-step"]'))
        self.assertRegex(pg.inner_text(row + '[data-sim="scenario-time"]'), r"^\d+\.\d s$")
        # Saved, the scenario is started by name only.
        pg.click('button[data-sim="save"]')
        pg.wait_for_selector("#banner:has-text('Saved')")
        self.assertEqual(load(self.sim_path)["scenarios"], {"sensor-break": {"steps": steps}})
        pg.wait_for_selector(row + 'td:has-text("yes")')
        pg.click(row + 'button[data-sim="start-scenario"]')
        sent = self.wait_sent("sim_scenario_start", 2)
        self.assertNotIn("scenario", sent[-1])
        pg.wait_for_selector(row + '[data-sim="scenario-state"]:has-text("running")')
        pg.click(row + 'button[data-sim="stop-scenario"]')
        self.assertEqual(self.wait_sent("sim_scenario_stop")[-1]["name"], "sensor-break")
        pg.wait_for_selector(row + '[data-sim="scenario-state"]:has-text("stopped")')

    def test_check_shows_problems_and_delete(self):
        pg = self.page
        self.open()
        pg.click('button[data-view="simulation"]')
        pg.click('button[data-sim-tab="scenarios"]')
        pg.fill('[data-sim="new-scenario"]', "bad name!")
        pg.click('[data-sim="create-scenario"]')
        pg.wait_for_selector("#banner:has-text('A scenario name')")
        pg.fill('[data-sim="new-scenario"]', "s1")
        pg.click('[data-sim="create-scenario"]')
        pg.select_option('select[data-sim="step-action"]', "set")
        pg.click('button[data-sim="add-step"]')
        pg.wait_for_selector('[data-sim-editor="s1"] [data-sim-problems] li:has-text("give at least one entry")')
        pg.click('button[data-sim="save"]')
        pg.wait_for_selector("#banner.error:has-text('nothing was saved')")
        self.assertFalse(os.path.exists(self.sim_path))
        pg.click('tr[data-sim-scenario="s1"] button[data-sim="delete-scenario"]')
        pg.click('#modal button[data-value="delete"]')
        pg.wait_for_selector('tr[data-sim-scenario="s1"]', state="detached")
        pg.click('button[data-sim="save"]')
        pg.wait_for_selector("#banner:has-text('Saved')")
        self.assertEqual(load(self.sim_path), {"schema_version": 1})


if __name__ == "__main__":
    unittest.main()


class FileSections(Base):
    """A config with several networks: the Simulation file tab edits the shown
    network's section of a version 2 file (add-virtual-example)."""

    def setUp(self):
        super().setUp()
        io = rtd_config()
        io["name"] = "io"
        line = {"name": "line", "adapter": {"type": "socketcan", "interface": "can1", "bitrate": 125000},
                "master": {"node_id": 1}, "nodes": [{"node_id": 6, "name": "n6", "eds": "rtd8.eds"}]}
        io.pop("schema_version", None)
        self.write_config({"schema_version": 2, "networks": [io, line]})

    def file_tab(self):
        self.page.click('button[data-view="simulation"]')
        self.page.click('button[data-sim-tab="file"]')

    def test_each_network_its_section(self):
        pg = self.page
        self.open()
        self.file_tab()
        self.assertIn("Network io", pg.inner_text('[data-sim="file-section"]'))
        pg.uncheck('[data-sim-file="5"] input[data-sim-field="default_behaviour"]')
        pg.click('.net-tab[data-net="1"]')
        self.file_tab()
        self.assertIn("Network line", pg.inner_text('[data-sim="file-section"]'))
        pg.uncheck('[data-sim-file="6"] input[data-sim-field="default_behaviour"]')
        pg.click('button[data-sim="save"]')
        pg.wait_for_selector("#banner:has-text('Saved')")
        self.assertEqual(load(self.sim_path), {
            "schema_version": 2,
            "networks": {"io": {"nodes": {"5": {"default_behaviour": False}}},
                         "line": {"nodes": {"6": {"default_behaviour": False}}}}})
        # Saving one network's section keeps the other's.
        pg.check('[data-sim-file="6"] input[data-sim-field="default_behaviour"]')
        pg.evaluate("banner('')")
        pg.click('button[data-sim="save"]')
        pg.wait_for_selector("#banner:has-text('Saved')")
        self.assertEqual(load(self.sim_path), {
            "schema_version": 2, "networks": {"io": {"nodes": {"5": {"default_behaviour": False}}}}})

    def test_version_1_file_is_converted_on_save(self):
        pg = self.page
        with open(self.sim_path, "w", encoding="utf-8") as f:
            json.dump({"tick_ms": 20, "nodes": {"5": {"default_behaviour": False}}}, f)
        self.open()
        self.file_tab()
        pg.click('button[data-sim="save"]')
        pg.wait_for_selector("#modal[open]")
        self.assertIn("section of network io", pg.inner_text("#modal-text"))
        pg.click('#modal button[data-value="convert"]')
        pg.wait_for_selector("#banner:has-text('Saved')")
        self.assertEqual(load(self.sim_path), {
            "schema_version": 2, "tick_ms": 20, "networks": {"io": {"nodes": {"5": {"default_behaviour": False}}}}})
