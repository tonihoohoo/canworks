"""The configurator page in a real browser (add-canopen-configurator tasks
4.1 and 4.2). Needs the Python Playwright package and a Chromium it can
launch; skipped without them, unless CANWORKS_REQUIRE_BROWSER=1 (CI)."""

import json
import os
import re
import shutil
import threading
import time
import unittest

from canworks.configurator import server as srv

from .helpers import PINGPONG, REPO, fake_editor_cli, new_config, node_tab, show_path, tmpdir, tree_node, tree_view

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None

RTD = os.path.join(REPO, "config", "rtd-sensor")
FIXTURE = os.path.join(REPO, "test", "fixtures", "editor-project")
LINT = os.path.join(REPO, "test", "fixtures", "eds", "lint")
DRIVES = os.path.join(REPO, "test", "fixtures", "eds", "drives")
CIA402 = os.path.join(REPO, "config", "cia402-drive")


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


REQUIRED = os.environ.get("CANWORKS_REQUIRE_BROWSER") == "1"


@unittest.skipIf(sync_playwright is None and not REQUIRED, "Playwright for Python is not installed")
class Page(unittest.TestCase):
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
        self.server = srv.Server()
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.project = os.path.join(self.dir, "rtd-monitor")
        shutil.copytree(FIXTURE, self.project)
        self.context = self.browser.new_context()
        self.addCleanup(self.context.close)
        self.page = self.context.new_page()
        self.page.set_default_timeout(10000)
        self.errors = []
        self.page.on("pageerror", lambda e: self.errors.append(str(e)))
        self.page.goto(self.server.url)

    def tearDown(self):
        self.assertEqual(self.errors, [])

    # -- helpers ------------------------------------------------------------
    def open_from_start(self, choice, path):
        pg = self.page
        if choice == "#start-new":
            new_config(pg, path)
        else:
            pg.click(choice)
            pg.fill("[data-folder=path]", path)
            pg.click("[data-folder=dialog] [data-value=use]")
        pg.wait_for_selector("#editor:not([hidden])")

    def add_node(self, eds, heartbeat="100"):
        """Adds a node from `eds` and gives it a heartbeat: the test EDS files
        default to none, which the checks refuse (no supervision). Leaves the
        node's Supervision tab open."""
        n = self.page.evaluate("() => S.config.nodes.length")
        self.page.set_input_files("#eds-input", eds)
        self.page.wait_for_selector('[data-node-heading="%d"]' % n)
        node_tab(self.page, "supervision")
        self.page.wait_for_selector('select[data-supervision="%d"]' % n)
        if heartbeat is not None:
            self.page.select_option('select[data-supervision="%d"]' % n, "heartbeat")
            self.page.fill('input[data-path="nodes[%d].heartbeat_ms"]' % n, heartbeat)

    def settled(self):
        """Waits for the debounced check to finish."""
        self.page.wait_for_function("() => document.body.dataset.checking === '0'")

    def open_sections(self):
        """Opens the open node tab's collapsed sections, object pickers and
        PDO settings (they are collapsed while empty), as a user does with a
        click."""
        self.page.evaluate("() => document.querySelectorAll('details.section, details[data-picker], "
                           "details[data-pdo-settings]').forEach((d) => { d.open = true; })")
        self.page.wait_for_timeout(50)

    def pdo_settings(self, pb):
        """Opens the settings of PDO `pb` (nodes[i].tx_pdos[j]) from its summary line."""
        show_path(self.page, pb)
        d = self.page.locator('details[data-pdo-settings="%s"]' % pb)
        if not d.evaluate("d => d.open"):
            self.page.click('[data-pdo-summary="%s"]' % pb)
            self.page.wait_for_function("(s) => document.querySelector(s).open",
                                        arg='details[data-pdo-settings="%s"]' % pb)

    def show(self, path):
        """Opens the node tab (and the PDO settings) holding the field at
        `path`; other paths are left to the page that is open."""
        if not path.startswith("nodes["):
            return
        m = re.match(r"(nodes\[\d+\]\.(?:tx|rx)_pdos\[\d+\])\.(number|cob_id|transmission|inhibit_time_us|"
                     r"event_timer_ms|sync_start|timeout_ms|on_timeout|timeout_location)", path)
        if m:
            self.pdo_settings(m.group(1))
        else:
            show_path(self.page, path)

    def pick(self, obj):
        """Adds an object (index:subindex) to a PDO through the object picker
        of the PDOs tab."""
        node_tab(self.page, "pdos")
        self.open_sections()
        self.page.click('button[data-add="%s"]' % obj)

    def fill(self, path, value):
        self.show(path)
        self.page.fill('input[data-path="%s"]' % path, value)

    def filled(self, path):
        """Waits until the input at `path` has a value and returns it."""
        sel = 'input[data-path="%s"]' % path
        self.page.wait_for_function("(s) => { const e = document.querySelector(s); return e && e.value; }", arg=sel)
        return self.page.input_value(sel)

    def save(self):
        self.settled()
        self.page.click("#btn-save")
        self.page.wait_for_selector("#banner:has-text('Saved')")

    # -- tests --------------------------------------------------------------
    def test_start_page(self):
        """simplify-start-page: Open…, New config…, the Commission link and
        Recent; three starting points while Recent is empty."""
        pg = self.page
        pg.set_viewport_size({"width": 1280, "height": 900})
        pg.wait_for_selector("#start-open")
        self.assertIn("PLC", pg.inner_text("#start-intro"))
        self.assertEqual([pg.inner_text(i) for i in ("#start-open", "#start-new", "#start-commission")],
                         ["Open…", "New config…", "Commission a device without a config"])
        self.assertTrue(pg.is_visible("#start-first"))
        self.assertFalse(pg.is_visible("#start-recent"))
        tops = pg.eval_on_selector_all("#start-first .choice", "cs => cs.map(c => Math.round(c.getBoundingClientRect().top))")
        self.assertEqual(len(tops), 3)
        self.assertEqual(len(set(tops)), 1, tops)
        text = pg.inner_text("#start")
        for word in ("standalone", "canworks.json", "LSS", "object dictionary"):
            self.assertNotIn(word, text)
        self.open_from_start("#start-open", self.project)
        pg.click("#btn-close")
        pg.wait_for_selector("#start-recent:not([hidden])")
        self.assertFalse(pg.is_visible("#start-first"))
        row = pg.inner_text("#recent li")
        for part in ("rtd-monitor", "OpenPLC", "editor project", "today", self.project):
            self.assertIn(part, row)

    def test_open_folder_with_nothing(self):
        """Open… of a folder with neither project.json nor canworks.json offers New config there."""
        pg = self.page
        empty = os.path.join(self.dir, "empty")
        os.makedirs(empty)
        pg.wait_for_selector("#start-open")
        pg.click("#start-open")
        pg.fill("[data-folder=path]", empty)
        pg.click("[data-folder=dialog] [data-value=use]")
        pg.wait_for_selector("#modal[open]")
        self.assertIn("has no config yet. Start a new config there?", pg.inner_text("#modal-text"))
        pg.click("#modal-buttons button[data-value=new]")
        pg.wait_for_selector("[data-new-config=form]")
        self.assertEqual(pg.input_value("[data-new-config=name]"), "empty")
        self.assertEqual(pg.input_value("[data-new-config=location]"), self.dir)
        pg.click("#modal-buttons button[data-value=create]")
        pg.wait_for_selector("#editor:not([hidden])")
        self.assertIn("standalone " + empty, pg.inner_text("#mode"))

    def test_new_config_with_editor_project(self):
        pg = self.page
        os.environ["OPENPLC_CLI"] = fake_editor_cli(self.dir)
        self.addCleanup(os.environ.pop, "OPENPLC_CLI", None)
        pg.reload()
        pg.wait_for_selector("#start-new")
        pg.click("#start-new")
        pg.wait_for_selector("[data-new-config=form]")
        self.assertTrue(pg.is_checked("[data-new-config=project]"))
        pg.click('label:has([data-new-target="bridge"])')
        self.assertFalse(pg.is_visible("[data-new-config=project]"))
        pg.click('label:has([data-new-target="openplc"])')
        pg.fill("[data-new-config=location]", self.dir)
        pg.fill("[data-new-config=name]", "new-machine")
        pg.click("#modal-buttons button[data-value=create]")
        pg.wait_for_selector("#mode:has-text('project new-machine')")
        machine = os.path.join(self.dir, "new-machine")
        self.assertTrue(os.path.isfile(os.path.join(machine, "project.json")))
        self.assertIn("Created the OpenPLC Editor project", pg.inner_text("#banner"))

    def test_new_config_without_editor_cli(self):
        pg = self.page
        os.environ["OPENPLC_CLI"] = os.path.join(self.dir, "no-such-cli")
        self.addCleanup(os.environ.pop, "OPENPLC_CLI", None)
        pg.reload()
        pg.wait_for_selector("#start-new")
        pg.click("#start-new")
        pg.wait_for_selector("[data-new-config=form]")
        self.assertTrue(pg.is_disabled("[data-new-config=project]"))
        self.assertFalse(pg.is_checked("[data-new-config=project]"))
        self.assertIn("was not found", pg.inner_text("[data-new-config=project-hint]"))

    def test_rtd_node_in_a_project(self):
        pg = self.page
        pg.wait_for_selector("#start-open")  # the start page renders after its first fetch
        self.assertTrue(pg.is_visible("#start-open"))
        self.open_from_start("#start-open", self.project)
        self.assertIn("project rtd-monitor", pg.inner_text("#mode"))
        # Bus: SocketCAN and SYNC.
        self.fill("adapter.interface", "can0")
        pg.select_option('select[data-path="adapter.bitrate"]', "250000")
        self.fill("adapter.restart_ms", "100")
        self.fill("master.sync_period_us", "10")
        self.add_node(os.path.join(RTD, "rtd8.eds"), heartbeat=None)
        self.fill("nodes[0].node_id", "5")
        self.fill("nodes[0].name", "rtd")
        # Supervision is a dropdown; only the chosen method's fields show. The
        # EDS heartbeat is 0, so the new node starts with a 1000 ms heartbeat.
        node_tab(pg, "supervision")
        self.assertEqual(pg.input_value('input[data-path="nodes[0].heartbeat_ms"]'), "1000")
        pg.select_option('select[data-supervision="0"]', "heartbeat")
        self.assertEqual(pg.locator('input[data-path="nodes[0].guard_time_ms"]').count(), 0)
        self.fill("nodes[0].heartbeat_ms", "100")
        self.assertEqual(pg.get_attribute('input[data-path="nodes[0].heartbeat_timeout_ms"]', "placeholder"), "300")
        self.fill("nodes[0].heartbeat_timeout_ms", "300")
        self.fill("nodes[0].status_location", "%IX10.0")
        pg.click('button[data-suggest="state"]')
        pg.wait_for_function("() => document.querySelector('input[data-path=\"nodes[0].state_location\"]').value === '%IB100'")
        for sub in range(1, 5):
            self.pick("0x7130:%d" % sub)
            pg.wait_for_selector('input[data-path="nodes[0].tx_pdos[0].entries[%d].iec_location"]' % (sub - 1))
        # EMCY inputs: the next free word after the four temperatures, the
        # next free byte after the state byte.
        node_tab(pg, "supervision")
        pg.click('button[data-suggest="emcy"]')
        pg.wait_for_function("() => document.querySelector('input[data-path=\"nodes[0].emcy_code_location\"]').value === '%IW104'")
        pg.click('button[data-suggest="errreg"]')
        pg.wait_for_function("() => document.querySelector('input[data-path=\"nodes[0].error_register_location\"]').value === '%IB101'")
        # Defaults show where a value is left out: the CiA 301 COB-ID and the
        # EDS's own transmission type (255 for this module), in the PDO's
        # settings under its summary line.
        self.pdo_settings("nodes[0].tx_pdos[0]")
        self.assertIn("COB-ID 0x185", pg.inner_text('[data-pdo-summary="nodes[0].tx_pdos[0]"]'))
        self.assertEqual(pg.get_attribute('input[data-path="nodes[0].tx_pdos[0].cob_id"]', "placeholder"), "0x185")
        self.assertIn("EDS default (255", pg.inner_text('select[data-path="nodes[0].tx_pdos[0].transmission"] option:checked'))
        pg.select_option('select[data-path="nodes[0].tx_pdos[0].transmission"]', "n")
        pg.fill('input[aria-label="SYNC count"]', "5")
        self.settled()
        pg.select_option('select[data-path="nodes[0].tx_pdos[0].transmission"]', "")
        # Startup SDO: sensor type of channel 0, moved to the top of the list.
        # 0x1017 is a communication object the plugin sets, so the picker
        # lists it only with "Show all writable objects".
        node_tab(pg, "sdos")
        self.open_sections()
        self.assertEqual(pg.locator('button[data-sdo="0x1017:0"]').count(), 0)
        pg.check('input[aria-label="Show all writable objects"]')
        pg.click('button[data-sdo="0x1017:0"]')
        pg.click('button[data-sdo="0x6110:1"]')
        pg.wait_for_selector('input[data-path="nodes[0].sdo[1].value"]')
        pg.fill('input[data-path="nodes[0].sdo[1].value"]', "0x1E")
        pg.click('tr[data-path="nodes[0].sdo[1]"] button[title="Up"]')
        self.fill("nodes[0].sdo[1].value", "100")
        self.save()

        saved = load(os.path.join(self.project, "canworks", "canworks.json"))
        self.assertEqual(saved["adapter"], {"type": "socketcan", "interface": "can0", "bitrate": 250000,
                                            "restart_ms": 100})
        self.assertEqual(saved["master"]["sync_period_us"], 10000)
        node = saved["nodes"][0]
        want = [e for e in load(os.path.join(RTD, "canopen_config.json"))["nodes"][0]["tx_pdos"][0]["entries"]
                if e["index"] == "0x7130"]
        self.assertEqual(node["tx_pdos"][0]["entries"], want)
        self.assertEqual((node["node_id"], node["name"], node["eds"], node["status_location"], node["state_location"]),
                         (5, "rtd", "rtd8.eds", "%IX10.0", "%IB100"))
        self.assertEqual((node["emcy_code_location"], node["error_register_location"]), ("%IW104", "%IB101"))
        self.assertEqual(node["sdo"], [
            {"index": "0x6110", "subindex": 1, "type": "UNSIGNED16", "value": "0x1E"},
            {"index": "0x1017", "subindex": 0, "type": "UNSIGNED16", "value": 100}])
        self.assertTrue(os.path.isfile(os.path.join(self.project, "canworks", "rtd8.eds")))

        # Declarations for the editor.
        pg.click('button[data-view="declarations"]')
        block = pg.input_value("textarea.block")
        self.assertIn("rtd_ok           AT %IX10.0 : BOOL;", block)
        self.assertIn("rtd_state        AT %IB100 : USINT;", block)
        self.assertIn("rtd_emcy         AT %IW104 : WORD;", block)
        self.assertIn("rtd_errreg       AT %IB101 : BYTE;", block)
        for n in range(4):
            self.assertIn("rtd_AI%d_Input_PV AT %%IW%d : INT;" % (n, 100 + n), block)

    def test_export_dcf(self):
        pg = self.page
        self.open_from_start("#start-open", self.project)
        self.add_node(os.path.join(RTD, "rtd8.eds"), heartbeat="200")
        self.fill("nodes[0].node_id", "5")
        self.fill("nodes[0].name", "rtd")
        self.settled()
        # One node, unsaved: the download is the draft's DCF.
        with pg.expect_download() as dl:
            pg.click('button[data-export-dcf="0"]')
        self.assertEqual(dl.value.suggested_filename, "node_5.dcf")
        with open(dl.value.path(), encoding="utf-8") as f:
            text = f.read()
        self.assertIn("NodeName=rtd", text)
        self.assertRegex(text, r"\[1017\][^\[]*ParameterValue=0xC8")
        self.assertFalse(os.path.exists(os.path.join(self.project, "canworks", "canworks.json")))
        pg.wait_for_selector("#banner:has-text('Exported node_5.dcf')")
        # All nodes: one zip.
        with pg.expect_download() as dl:
            pg.evaluate("() => { document.querySelector('#menu-export').open = true; }")
            pg.click("#btn-export-all")
        self.assertEqual(dl.value.suggested_filename, "rtd-monitor_dcf.zip")
        # A problem: nothing downloads, the Problems pane says why.
        self.fill("nodes[0].node_id", "1")
        self.settled()
        downloads = []
        pg.on("download", lambda d: downloads.append(d))
        pg.click('button[data-export-dcf="0"]')
        pg.wait_for_selector("#problems-bars .notice-error:has-text('DCF export stopped')")
        self.assertTrue(pg.is_hidden("#banner"))
        self.assertIn("master's node ID", pg.inner_text("#problem-list"))
        self.assertEqual(downloads, [])

    def test_export_dbc(self):
        pg = self.page
        self.open_from_start("#start-open", self.project)
        self.add_node(os.path.join(RTD, "rtd8.eds"))
        self.fill("nodes[0].node_id", "5")
        self.fill("nodes[0].name", "rtd")
        self.settled()
        # Unsaved draft, no SDO frames by default.
        self.assertEqual(pg.input_value("#dbc-sdo"), "none")
        with pg.expect_download() as dl:
            pg.evaluate("() => { document.querySelector('#menu-export').open = true; }")
            pg.click("#btn-export-dbc")
        self.assertEqual(dl.value.suggested_filename, "rtd-monitor.dbc")
        with open(dl.value.path(), encoding="ascii") as f:
            text = f.read()
        self.assertIn("BU_: Master rtd", text)
        self.assertNotIn("SDO_Rx", text)
        self.assertFalse(os.path.exists(os.path.join(self.project, "canworks", "canworks.json")))
        pg.wait_for_selector("#banner:has-text('Exported rtd-monitor.dbc')")
        # The SDO choice applies and is stored with the page settings.
        with pg.expect_response(lambda r: r.url.endswith("/api/ui") and r.request.method == "POST") as resp:
            pg.evaluate("() => { document.querySelector('#menu-export').open = true; }")
            pg.select_option("#dbc-sdo", "all")
        self.assertEqual(resp.value.json()["dbc_sdo"], "all")
        with pg.expect_download() as dl:
            pg.evaluate("() => { document.querySelector('#menu-export').open = true; }")
            pg.click("#btn-export-dbc")
        with open(dl.value.path(), encoding="ascii") as f:
            self.assertIn("BO_ 1541 rtd_SDO_Rx: 8 Master", f.read())
        # A problem: nothing downloads, the Problems pane says why.
        self.fill("nodes[0].node_id", "1")
        self.settled()
        downloads = []
        pg.on("download", lambda d: downloads.append(d))
        pg.evaluate("() => { document.querySelector('#menu-export').open = true; }")
        pg.click("#btn-export-dbc")
        pg.wait_for_selector("#problems-bars .notice-error:has-text('DBC export stopped')")
        self.assertTrue(pg.is_hidden("#banner"))
        self.assertIn("master's node ID", pg.inner_text("#problem-list"))
        self.assertEqual(downloads, [])

    def test_bus_diagnostics(self):
        pg = self.page
        self.open_from_start("#start-open", self.project)
        self.fill("adapter.interface", "can0")
        self.fill("master.sync_period_us", "10")
        self.add_node(os.path.join(RTD, "rtd8.eds"))
        tree_view(pg, "bus")
        for key, want in (("bus_state_location", "%IB100"), ("tx_error_count_location", "%IB101"),
                          ("rx_error_count_location", "%IB102"), ("bus_off_count_location", "%IW100")):
            pg.click('button[data-suggest="%s"]' % key)
            pg.wait_for_function("() => document.querySelector('input[data-path=\"master.%s\"]').value === '%s'"
                                 % (key, want))
        self.save()
        master = load(os.path.join(self.project, "canworks", "canworks.json"))["master"]
        self.assertEqual((master["bus_state_location"], master["tx_error_count_location"],
                          master["rx_error_count_location"], master["bus_off_count_location"]),
                         ("%IB100", "%IB101", "%IB102", "%IW100"))
        pg.click('button[data-view="declarations"]')
        block = pg.input_value("textarea.block")
        for line in ("can_bus_state AT %IB100 : USINT;", "can_bus_offs  AT %IW100 : UINT;"):
            self.assertRegex(block, line.replace(" ", " +"))

    def test_eds_lint_import_report(self):
        pg = self.page
        self.open_from_start("#start-open", self.project)
        self.fill("adapter.interface", "can0")
        self.fill("master.sync_period_us", "10")

        def upload(eds):
            # Not add_node: opening another node tab clears the banner with the report.
            n = pg.evaluate("() => S.config.nodes.length")
            pg.set_input_files("#eds-input", eds)
            pg.wait_for_selector('[data-node-heading="%d"]' % n)
        # Accepted findings: one line, the list collapsed and grouped by object.
        upload(os.path.join(DRIVES, "servo-drive.eds"))
        report = pg.locator('#banner details[data-report="accepted"]')
        self.assertIn("2 lint findings accepted", report.locator("summary").inner_text())
        self.assertFalse(report.evaluate("d => d.open"))
        self.assertEqual(report.locator("li").all_text_contents(),
                         ["0x60C0: LowLimit overflow in [60C0]", "0x60C2 sub 2: LowLimit overflow in [60C2sub2]"])
        # Corrections in the copy the plugin reads: the file, that it is
        # kept, the reader, and one line per kind with its count.
        upload(os.path.join(LINT, "octet-string.eds"))
        self.assertIn('1 OCTET_STRING/DOMAIN value is cleared: [2051] DefaultValue was "----"',
                      pg.locator('#banner [data-report="corrections"]').inner_text())
        upload(os.path.join(LINT, "nodeid-suffix.eds"))
        report = pg.locator('#banner [data-report="corrections"]')
        self.assertIn("nodeid-suffix.eds is kept as imported. The OpenPLC plugin reads a corrected copy, because its "
                      "CANopen stack cannot read these values:", report.inner_text())
        self.assertEqual(report.locator("li").all_text_contents(),
                         ['3 values written "<number>+$NODEID" are read as "$NODEID+<number>"'])
        with open(os.path.join(PINGPONG, "cpp-slave.eds"), encoding="utf-8") as f:
            one = f.read().replace("$NODEID+0x200", "0x200+$NODEID", 1)
        path = os.path.join(tmpdir(self), "one-suffix.eds")
        with open(path, "w", encoding="utf-8") as f:
            f.write(one)
        upload(path)
        self.assertEqual(pg.locator('#banner [data-report="corrections"] li').all_text_contents(),
                         ['1 value written "<number>+$NODEID" is read as "$NODEID+<number>"'])
        # A clean file is just readable.
        upload(os.path.join(PINGPONG, "cpp-slave.eds"))
        pg.wait_for_selector('#banner [data-report="readable"]')
        # A finding in a communication object: refused, no node added.
        nodes = pg.locator("#tree [data-node]").count()
        pg.set_input_files("#eds-input", os.path.join(LINT, "comm-broken.eds"))
        pg.wait_for_selector("#banner.error:has-text(\"fails dcfgen's lint\")")
        self.assertIn("0x1A00 sub 0", pg.inner_text("#banner"))
        self.assertEqual(pg.locator("#tree [data-node]").count(), nodes)

    def test_eds_lint_setting(self):
        pg = self.page
        os.makedirs(os.path.join(self.project, "canworks"))
        shutil.copy(os.path.join(PINGPONG, "cpp-slave.eds"), os.path.join(self.project, "canworks"))
        cfg = srv.empty_config()
        cfg["master"]["strict_eds"] = False
        cfg["nodes"] = [{"node_id": 2, "name": "pingpong", "eds": "cpp-slave.eds", "heartbeat_ms": 100, "tx_pdos": [{"entries": [
            {"index": "0x4001", "subindex": 0, "type": "UNSIGNED32", "iec_location": "%ID110"}]}]}]
        path = os.path.join(self.project, "canworks", "canworks.json")
        with open(path, "w") as f:
            json.dump(cfg, f)
        self.open_from_start("#start-open", self.project)
        pg.wait_for_selector("#banner:has-text(\"old 'strict_eds'\")")
        tree_view(pg, "bus")
        sel = 'select[data-path="master.eds_lint"]'
        self.assertEqual(pg.input_value(sel), "off")
        self.save()
        self.assertEqual(load(path)["master"], {"node_id": 1, "sync_period_us": 10000, "eds_lint": "off"})
        for value, saved in (("all", "all"), ("", None)):
            pg.select_option(sel, value)
            self.save()
            deadline = time.time() + 10  # the banner still reads "Saved" from the last save
            while load(path)["master"].get("eds_lint") != saved and time.time() < deadline:
                time.sleep(0.1)
            self.assertEqual(load(path)["master"].get("eds_lint"), saved)
            self.assertNotIn("strict_eds", load(path)["master"])

    def test_sync_period_left_empty(self):
        pg = self.page
        os.makedirs(os.path.join(self.project, "canworks"))
        shutil.copy(os.path.join(PINGPONG, "cpp-slave.eds"), os.path.join(self.project, "canworks"))
        cfg = srv.empty_config()
        cfg["nodes"] = [{"node_id": 2, "name": "pingpong", "eds": "cpp-slave.eds", "heartbeat_ms": 100, "tx_pdos": [{"transmission": 255,
            "entries": [{"index": "0x4001", "subindex": 0, "type": "UNSIGNED32", "iec_location": "%ID110"}]}]}]
        path = os.path.join(self.project, "canworks", "canworks.json")
        with open(path, "w") as f:
            json.dump(cfg, f)
        self.open_from_start("#start-open", self.project)
        tree_view(pg, "bus")
        sel = 'input[data-path="master.sync_period_us"]'
        self.assertEqual(pg.input_value(sel), "10")
        self.assertEqual(pg.get_attribute(sel, "placeholder"), "off")
        self.fill("master.sync_period_us", "")
        self.save()
        self.assertEqual(load(path)["master"], {"node_id": 1})

    def test_sync_source_plc_cycle(self):
        pg = self.page
        os.makedirs(os.path.join(self.project, "canworks"))
        shutil.copy(os.path.join(PINGPONG, "cpp-slave.eds"), os.path.join(self.project, "canworks"))
        cfg = srv.empty_config()  # SYNC period 10 ms; the EDS's TPDO 1 is type 1
        cfg["nodes"] = [{"node_id": 2, "name": "pingpong", "eds": "cpp-slave.eds", "heartbeat_ms": 100, "tx_pdos": [{
            "entries": [{"index": "0x4001", "subindex": 0, "type": "UNSIGNED32", "iec_location": "%ID110"}]}]}]
        path = os.path.join(self.project, "canworks", "canworks.json")
        with open(path, "w") as f:
            json.dump(cfg, f)
        self.open_from_start("#start-open", self.project)
        tree_view(pg, "bus")
        sel = 'select[data-path="master.sync_source"]'
        self.assertEqual(pg.input_value(sel), "")
        pg.select_option(sel, "plc_cycle")
        pg.wait_for_selector('input[data-path="master.sync_cycles"]')
        self.assertEqual(pg.locator('input[data-path="master.sync_period_us"]').count(), 0)
        self.assertEqual(pg.get_attribute('input[data-path="master.sync_cycles"]', "placeholder"), "1")
        self.fill("master.sync_cycles", "2")
        self.save()
        self.assertEqual(load(path)["master"], {"node_id": 1, "sync_source": "plc_cycle", "sync_cycles": 2})
        # Back to the timer.
        pg.select_option(sel, "")
        pg.wait_for_selector('input[data-path="master.sync_period_us"]')
        self.fill("master.sync_period_us", "10")
        self.save()
        deadline = time.time() + 10
        while "sync_source" in load(path)["master"] and time.time() < deadline:
            time.sleep(0.1)
        self.assertEqual(load(path)["master"], {"node_id": 1, "sync_period_us": 10000})

    def test_slcan_adapter(self):
        pg = self.page
        self.open_from_start("#start-open", self.project)
        self.fill("adapter.interface", "can0")
        pg.select_option('select[data-path="adapter.bitrate"]', "500000")
        pg.uncheck('input[data-path="adapter.configure_link"]')
        self.fill("master.sync_period_us", "10")
        self.add_node(os.path.join(PINGPONG, "cpp-slave.eds"))
        self.pick("0x4001:0")
        pg.wait_for_selector('input[data-path="nodes[0].tx_pdos[0].entries[0].iec_location"]')
        self.fill("nodes[0].tx_pdos[0].entries[0].iec_location", "%ID300")
        tree_view(pg, "bus")
        pg.select_option('select[data-path="adapter.type"]', "slcan")
        pg.wait_for_selector('input[data-path="adapter.device"]')
        # SocketCAN-only settings are gone; the interface and bit rate stay.
        self.assertEqual(pg.locator('input[data-path="adapter.configure_link"]').count(), 0)
        self.assertEqual(pg.locator('input[data-path="adapter.restart_ms"]').count(), 0)
        self.assertEqual(pg.input_value('input[data-path="adapter.interface"]'), "can0")
        self.assertIn("does not report the CAN error state", pg.inner_text("#editor"))
        self.fill("adapter.device", "ttyACM0")
        self.settled()
        self.assertIn("absolute path", pg.inner_text('.field-msg[data-for="adapter.device"]'))
        self.assertGreater(pg.locator("#problem-list li.error").count(), 0)
        device = "/dev/serial/by-id/usb-Openlight_Labs_CANable2_b158aa7-if00"
        self.fill("adapter.device", device)
        self.save()
        saved = load(os.path.join(self.project, "canworks", "canworks.json"))["adapter"]
        self.assertEqual(saved, {"type": "slcan", "device": device, "interface": "can0", "bitrate": 500000})
        # Back to SocketCAN: the serial device is dropped.
        pg.select_option('select[data-path="adapter.type"]', "socketcan")
        pg.wait_for_selector('input[data-path="adapter.configure_link"]')
        self.settled()
        pg.click("#btn-save")  # the banner still says Saved from the first save
        pg.wait_for_function("() => document.querySelector('#btn-save').textContent === 'Saved'")
        saved = load(os.path.join(self.project, "canworks", "canworks.json"))["adapter"]
        self.assertEqual(saved, {"type": "socketcan", "interface": "can0", "bitrate": 500000})

    def test_network_start_copy_as_st_call(self):
        # add-plc-network-control 5.2: the corrected hint and a CO_NETWORK_START call.
        pg = self.page
        self.open_from_start("#start-open", self.project)
        tree_view(pg, "bus")
        pg.click('details[data-advanced="master"] > summary')
        box = pg.locator('input[data-path="master.start"]').locator("xpath=ancestor::div[1]")
        self.assertIn("until the PLC program starts it with CO_NETWORK_START", box.inner_text())
        self.assertNotIn("something starts it", pg.inner_text("body"))
        pg.uncheck('input[data-path="master.start"]')
        pg.evaluate("() => { window.__copied = []; navigator.clipboard.writeText = async (t) => { "
                    "window.__copied.push(t); }; }")
        pg.click('button[data-action="network-start-st"]')
        pg.wait_for_function("() => window.__copied.length === 1")
        text = pg.evaluate("() => window.__copied[0]")
        self.assertIn("net_start : CO_NETWORK_START;", text)
        self.assertIn("net_start(EXECUTE := net_start_go, TIMEOUT := T#0s", text)
        self.assertNotIn("NETWORK :=", text)
        pg.wait_for_selector("#banner:has-text('Copied the CO_NETWORK_START call')")

    def test_advanced_settings(self):
        pg = self.page
        self.open_from_start("#start-open", self.project)
        self.fill("adapter.interface", "can0")
        self.fill("master.sync_period_us", "10")
        self.add_node(os.path.join(REPO, "test", "fixtures", "eds", "node-options.eds"))
        self.fill("nodes[0].node_id", "2")
        node_tab(pg, "supervision")
        pg.click('button[data-suggest="boot_error"]')
        pg.wait_for_function("() => document.querySelector('input[data-path=\"nodes[0].boot_error_location\"]').value === '%IB100'")
        # On the Advanced tab, open there; node-side fields show the EDS value.
        self.assertFalse(pg.is_visible('input[data-path="nodes[0].time_cob_id"]'))
        node_tab(pg, "advanced")
        self.assertTrue(pg.is_visible('input[data-path="nodes[0].time_cob_id"]'))
        self.assertEqual(pg.get_attribute('input[data-path="nodes[0].time_cob_id"]', "placeholder"),
                         "EDS default (0x80000100)")
        pg.check('input[data-path="nodes[0].mandatory"]')
        self.fill("nodes[0].revision_number", "0x00010002")
        self.fill("nodes[0].error_behavior", "1=0, 3=2")
        pg.select_option('select[data-path="nodes[0].heartbeat_consumer"]', "false")
        # The section stays open across a re-render and a visit to another tab.
        self.settled()
        self.assertTrue(pg.is_visible('input[data-path="nodes[0].time_cob_id"]'))
        node_tab(pg, "supervision")
        pg.click('button[data-suggest="state"]')
        pg.wait_for_function("() => document.querySelector('input[data-path=\"nodes[0].state_location\"]').value === '%IB101'")
        node_tab(pg, "advanced")
        self.assertTrue(pg.is_visible('input[data-path="nodes[0].time_cob_id"]'))
        tree_view(pg, "bus")
        pg.click('button[data-suggest="state_location"]')
        pg.wait_for_function("() => document.querySelector('input[data-path=\"master.state_location\"]').value === '%IB102'")
        pg.click('details[data-advanced="master"] > summary')
        pg.uncheck('input[data-path="master.start_nodes"]')
        self.fill("master.nmt_inhibit_time_us", "200")
        self.fill("master.heartbeat_multiplier", "2.5")
        self.assertEqual(pg.get_attribute('input[data-path="master.sdo_timeout_ms"]', "placeholder"), "1000")
        self.fill("master.sdo_timeout_ms", "3000")
        self.save()
        cfg = load(os.path.join(self.project, "canworks", "canworks.json"))
        node, master = cfg["nodes"][0], cfg["master"]
        self.assertEqual((node["boot_error_location"], node["mandatory"], node["revision_number"],
                          node["error_behavior"], node["heartbeat_consumer"]),
                         ("%IB100", True, "0x00010002", {"1": 0, "3": 2}, False))
        self.assertNotIn("time_cob_id", node)
        self.assertEqual((master["state_location"], master["start_nodes"], master["nmt_inhibit_time_us"],
                          master["heartbeat_multiplier"], master["sdo_timeout_ms"]), ("%IB102", False, 200, 2.5, 3000))
        # Emptied again: nothing saved, the plugin's default applies.
        tree_view(pg, "bus")
        if not pg.is_visible('input[data-path="master.sdo_timeout_ms"]'):
            pg.click('details[data-advanced="master"] > summary')
        self.fill("master.sdo_timeout_ms", "")
        self.save()  # the banner still says Saved from before, so wait for the file
        path = os.path.join(self.project, "canworks", "canworks.json")
        deadline = time.time() + 5
        while "sdo_timeout_ms" in load(path)["master"] and time.time() < deadline:
            time.sleep(0.05)
        self.assertNotIn("sdo_timeout_ms", load(path)["master"])
        pg.click('button[data-view="declarations"]')
        block = pg.input_value("textarea.block")
        self.assertRegex(block, "n?\\w+_boot_err +AT %IB100 : USINT;")
        self.assertRegex(block, "can_master_state +AT %IB102 : USINT;")

    def test_config_check_settings(self):
        pg = self.page
        self.open_from_start("#start-open", self.project)
        self.fill("adapter.interface", "can0")
        self.fill("master.sync_period_us", "10")
        self.add_node(os.path.join(REPO, "test", "fixtures", "eds", "config-check.eds"))
        self.fill("nodes[0].node_id", "2")
        node_tab(pg, "advanced")
        check = 'input[data-path="nodes[0].config_check"]'
        store = 'select[data-path="nodes[0].store_configuration"]'
        # The save needs the check first.
        self.assertTrue(pg.is_enabled(check))
        self.assertTrue(pg.is_disabled(store))
        pg.check(check)
        self.assertTrue(pg.is_enabled(store))
        labels = pg.eval_on_selector_all(store + " option", "os => os.map(o => o.textContent)")
        self.assertEqual(labels[0], "No")
        self.assertEqual(len(labels), 4)  # 0x1010 sub 1-3 in config-check.eds
        pg.select_option(store, "1")
        self.save()
        path = os.path.join(self.project, "canworks", "canworks.json")
        node = load(path)["nodes"][0]
        self.assertEqual((node["config_check"], node["store_configuration"]), (True, 1))
        # Turning the check off drops both keys.
        pg.uncheck(check)
        self.assertTrue(pg.is_disabled(store))
        self.save()
        deadline = time.time() + 5
        while "config_check" in load(path)["nodes"][0] and time.time() < deadline:
            time.sleep(0.05)
        node = load(path)["nodes"][0]
        self.assertNotIn("config_check", node)
        self.assertNotIn("store_configuration", node)
        # A device without 0x1020: the checkbox is off and says why.
        self.add_node(os.path.join(RTD, "rtd8.eds"))
        node_tab(pg, "advanced")
        self.assertTrue(pg.is_disabled('input[data-path="nodes[1].config_check"]'))
        field = pg.locator('input[data-path="nodes[1].config_check"]').locator("xpath=ancestor::div[1]")
        self.assertIn("no 0x1020", field.inner_text())
        self.assertTrue(pg.is_disabled('select[data-path="nodes[1].store_configuration"]'))

    def test_lss_settings(self):
        pg = self.page
        self.open_from_start("#start-open", self.project)
        self.fill("adapter.interface", "can0")
        self.fill("master.sync_period_us", "10")
        self.add_node(os.path.join(REPO, "test", "fixtures", "eds", "lss-slave.eds"))
        self.fill("nodes[0].node_id", "12")
        node_tab(pg, "advanced")
        assign = 'input[data-path="nodes[0].lss.assign"]'
        store = 'input[data-path="nodes[0].lss.store"]'
        reset = 'input[data-path="nodes[0].reset_communication"]'
        self.assertTrue(pg.is_disabled(store))
        self.assertEqual(pg.locator("[data-lss-warning]").count(), 0)  # LSS_Supported=1
        pg.check(assign)
        self.assertTrue(pg.is_enabled(store))
        self.assertFalse(pg.is_checked(store))
        self.assertTrue(pg.is_disabled(reset))
        self.assertIn("node ID 12 at every start", pg.locator(assign).locator("xpath=ancestor::div[1]").inner_text())
        # Without a serial number it is an error, and the field says why.
        self.settled()
        self.assertGreater(pg.locator("#problem-list li.error").count(), 0)
        pg.wait_for_selector('[data-for="nodes[0].serial_number"]:has-text("serial_number")')
        path = os.path.join(self.project, "canworks", "canworks.json")
        self.assertFalse(os.path.exists(path))
        self.fill("nodes[0].serial_number", "0x1234")
        self.save()
        node = load(path)["nodes"][0]
        self.assertEqual(node["lss"], {"assign": True})
        self.assertEqual(node["serial_number"], "0x1234")  # as typed, like the other identity fields
        self.assertNotIn("reset_communication", node)
        # Unticking drops the whole object.
        pg.uncheck(assign)
        self.assertTrue(pg.is_enabled(reset))
        self.save()
        deadline = time.time() + 5
        while "lss" in load(path)["nodes"][0] and time.time() < deadline:
            time.sleep(0.05)
        self.assertNotIn("lss", load(path)["nodes"][0])
        # An EDS without LSS_Supported: no LSS for the node, the boxes are off with the reason.
        self.add_node(os.path.join(REPO, "test", "fixtures", "eds", "cpp-slave.eds"))
        node_tab(pg, "advanced")
        self.assertEqual(pg.locator("[data-lss-warning]").count(), 1)
        self.assertIn("has no LSS", pg.inner_text("[data-lss-warning]"))
        self.assertTrue(pg.is_disabled('input[data-path="nodes[1].lss.assign"]'))
        self.assertTrue(pg.is_disabled('input[data-path="nodes[1].lss.store"]'))
        self.assertEqual(pg.locator("[data-lss-remove]").count(), 0)
        # An lss object left in the file: a problem, removed with one click.
        pg.evaluate("() => { S.config.nodes[1].lss = {}; render(); }")
        pg.wait_for_selector("[data-lss-remove]")
        pg.click("[data-lss-remove]")
        self.assertFalse(pg.evaluate("() => 'lss' in S.config.nodes[1]"))

    def test_cia402_axis(self):
        pg = self.page
        self.open_from_start("#start-open", self.project)
        self.fill("adapter.interface", "can0")
        self.add_node(os.path.join(CIA402, "servo402.eds"))
        self.fill("nodes[0].node_id", "4")
        self.fill("nodes[0].name", "drive")
        node_tab(pg, "cia402")
        box = 'input[data-path="nodes[0].axis"]'
        self.assertEqual(pg.locator("button[data-map-cia402]").count(), 0)
        pg.check(box)
        self.assertEqual(pg.locator("[data-axis-status]").count(), 1)
        self.assertEqual(pg.locator("[data-axis-profile]").count(), 0)  # device type 0x00020192
        pg.click('button[data-map-cia402="nodes[0]"]')
        pg.wait_for_selector("[data-axis-result]")
        self.assertIn("0x6081 profile velocity (RPDO2", pg.inner_text("[data-axis-result]"))
        self.assertEqual(pg.locator("[data-axis-status]").count(), 0)
        node_tab(pg, "pdos")
        pg.wait_for_selector('input[data-path="nodes[0].rx_pdos[3].entries[0].iec_location"]')
        node_tab(pg, "cia402")
        self.fill("nodes[0].axis.scale_numerator", "10")
        self.fill("nodes[0].axis.scale_factor", "2.5")
        self.save()
        node = load(os.path.join(self.project, "canworks", "canworks.json"))["nodes"][0]
        self.assertEqual(node["axis"], {"scale_numerator": 10, "scale_factor": 2.5})
        self.assertEqual(node["status_location"], "%IX100.0")
        example = load(os.path.join(CIA402, "canopen_config.json"))["nodes"][0]

        def layout_of(n):
            return {k: [(p["number"], [e["index"] for e in p["entries"]]) for p in n[k]] for k in ("tx_pdos", "rx_pdos")}
        got, want = layout_of(node), layout_of(example)
        # The example maps everything but the torques.
        self.assertEqual(got["tx_pdos"][:3], want["tx_pdos"])
        self.assertEqual(got["rx_pdos"][:3], want["rx_pdos"])
        self.assertEqual((got["tx_pdos"][3], got["rx_pdos"][3]), ((4, ["0x6077"]), (4, ["0x6071"])))
        # Mapping again adds nothing.
        node_tab(pg, "cia402")
        pg.click('button[data-map-cia402="nodes[0]"]')
        pg.wait_for_selector("[data-axis-result]:has-text('Nothing new to map')")
        # The declarations have the axis and its bridge call.
        pg.click('button[data-view="declarations"]')
        block = pg.input_value("textarea.block")
        self.assertIn("drive        : AXIS_REF_SM3;", block)
        self.assertIn("drive_bridge : SM_Drive_GenericDS402;", block)
        self.assertIn("drive.iRatioTechUnitsNum := DINT#10;", block)
        self.assertIn("drive.fScalefactor := LREAL#2.5;", block)
        self.assertIn("bOnline := drive_ok", block)
        # A device that is not a CiA 402 drive (no 0x6040 and 0x6041): no CiA 402 tab.
        pg.click('#tool-tabs button[data-view="network"]')
        tree_node(pg, 0)
        self.add_node(os.path.join(REPO, "test", "fixtures", "eds", "cpp-slave.eds"))
        self.assertEqual(pg.locator('.node-tabs [data-node-tab="cia402"]').count(), 0)
        self.assertEqual(pg.locator('.node-tabs [data-node-tab="general"]').count(), 1)
        # An axis set already (an older file): the tab shows, the axis can still be switched off; the profile warning shows.
        pg.evaluate("() => { setPath('nodes[1].axis', {}); changed(); render(); }")
        node_tab(pg, "cia402")
        self.assertFalse(pg.is_disabled('input[data-path="nodes[1].axis"]'))
        self.assertEqual(pg.locator("[data-axis-profile]").count(), 1)
        pg.click('button[data-map-cia402="nodes[1]"]')
        pg.wait_for_selector("[data-axis-result] li:has-text('0x6040 controlword: not in the EDS')")

    def test_cia402_cyclic_axis(self):
        # add-cia402-cyclic-modes: the switch, the SYNC fix button, the cyclic
        # layout and the cycle time line with its task interval.
        pg = self.page
        self.open_from_start("#start-open", self.project)
        self.fill("adapter.interface", "can0")
        self.add_node(os.path.join(CIA402, "servo402.eds"))
        self.fill("nodes[0].node_id", "4")
        self.fill("nodes[0].name", "drive")
        node_tab(pg, "cia402")
        pg.check('input[data-path="nodes[0].axis"]')
        cyc = 'input[data-path="nodes[0].axis.cyclic"]'
        self.assertEqual(pg.locator('input[data-path="nodes[0].axis.interpolation_period_us"]').count(), 0)
        pg.check(cyc)
        self.assertEqual(pg.locator('input[data-path="nodes[0].axis.interpolation_period_us"]').count(), 1)
        pg.click('button[data-map-cia402="nodes[0]"]')
        pg.wait_for_selector("[data-axis-changes]")
        self.assertIn("RPDO1 (was 255)", pg.inner_text("[data-axis-changes]"))
        # The SYNC check: an error on the node, fixed by the button.
        pg.wait_for_selector('[data-for="nodes[0].axis.cyclic"]:has-text("needs SYNC from the PLC cycle")')
        self.assertEqual(pg.locator("button[data-cyclic-fix]").count(), 1)
        def until(pred):
            deadline = time.time() + 5
            while not pred() and time.time() < deadline:
                time.sleep(0.05)
            return pred()
        pg.click("button[data-cyclic-fix]")
        self.assertTrue(until(lambda: not pg.inner_text('[data-for="nodes[0].axis.cyclic"]')))
        self.assertEqual(pg.locator("button[data-cyclic-fix]").count(), 0)
        self.save()
        cfg = load(os.path.join(self.project, "canworks", "canworks.json"))
        self.assertEqual(cfg["master"].get("sync_source"), "plc_cycle")
        self.assertNotIn("sync_period_us", cfg["master"])
        node = cfg["nodes"][0]
        self.assertEqual(node["axis"], {"cyclic": True})
        self.assertEqual([e["index"] for e in node["rx_pdos"][0]["entries"]], ["0x6040", "0x6060", "0x607A"])
        self.assertTrue(all(p["transmission"] == 1 for p in node["rx_pdos"] + node["tx_pdos"]))
        # The declarations: fCycleTime from the task interval.
        pg.click('button[data-view="declarations"]')
        self.assertTrue(until(lambda: "fCycleTime" in pg.input_value("textarea.block")))
        self.assertIn("drive.fCycleTime := LREAL#0.02;", pg.input_value("textarea.block"))
        pg.fill("#task-interval", "T#5ms")
        # A check that lands before Enter renders the view again: the typed
        # text and the focus stay.
        pg.evaluate("runCheck()")
        self.assertEqual(pg.input_value("#task-interval"), "T#5ms")
        self.assertTrue(pg.evaluate("document.activeElement.id === 'task-interval'"))
        pg.press("#task-interval", "Enter")
        self.assertTrue(until(lambda: "drive.fCycleTime := LREAL#0.005;" in pg.input_value("textarea.block")))

    def test_startup_sdo_notes(self):
        # Device notes on the startup SDO list (canopen-device-notes): the
        # built-in note, a note written on the Notes tab, a value picked by
        # name; Save writes the notes file next to the EDS.
        pg = self.page
        self.open_from_start("#start-open", self.project)
        self.fill("adapter.interface", "can0")
        self.add_node(os.path.join(RTD, "rtd8.eds"))
        self.fill("nodes[0].node_id", "5")
        node_tab(pg, "sdos")
        self.open_sections()
        pg.check('input[aria-label="Show all writable objects"]')
        pg.click('button[data-sdo="0x1017:0"]')
        row = 'tr[data-path="nodes[0].sdo[0]"]'
        pg.wait_for_selector(row)
        pg.wait_for_selector(row + ' [data-note="text"]:has-text("sends its heartbeat")')
        pg.click('button[data-sdo="0x6110:1"]')
        row = 'tr[data-path="nodes[0].sdo[1]"]'
        pg.wait_for_selector(row)
        self.assertEqual(pg.locator(row + " select[data-value-pick]").count(), 0)
        # Notes are written on the Notes tab only (notes-tab-own-notes).
        self.assertEqual(pg.locator('[data-node-tab-panel="sdos"] button[data-note-edit]').count(), 0)
        node_tab(pg, "notes")
        pg.click("button[data-add-note]")
        pg.fill("#modal [data-note-picker-filter]", "6110:1")
        pg.keyboard.press("Enter")
        pg.wait_for_selector("#modal .note-editor")
        # The dialog fits without a horizontal scroll bar.
        self.assertFalse(pg.evaluate("""() => { for (let x = document.querySelector('#modal .note-editor');
            x && x.id !== 'modal'; x = x.parentElement) if (x.scrollWidth > x.clientWidth + 1) return x.id || x.className || x.tagName;
            const m = document.querySelector('#modal'); return m.scrollWidth > m.clientWidth + 1 ? 'modal' : false; }"""))
        pg.fill('#modal [data-note-field="text"]', "Sensor type of the channel")
        pg.fill('#modal [data-note-field="values"]', "1 = two-wire\n30 = four-wire")
        pg.click('#modal button[data-value="save"]')
        # My notes lists it, with the focus on its row, and the tab counts it.
        pg.wait_for_selector('[data-note-row="0x6110:1"][data-note-source="mine"]')
        self.assertEqual(pg.evaluate("() => document.activeElement.dataset.noteEdit"), "0x6110:1")
        self.assertEqual(pg.inner_text('.node-tabs [data-node-tab="notes"]').strip(), "Notes 1")
        node_tab(pg, "sdos")
        pg.wait_for_selector(row + ' [data-note="text"]:has-text("Sensor type of the channel")')
        pg.select_option(row + " select[data-value-pick]", "30")
        self.assertEqual(pg.input_value('input[data-path="nodes[0].sdo[1].value"]'), "30")
        self.assertIn("four-wire", pg.inner_text(row + " [data-sdo-meaning]"))
        self.save()
        saved = load(os.path.join(self.project, "canworks", "canworks.json"))
        self.assertEqual(saved["nodes"][0]["sdo"][1]["value"], 30)
        notes = load(os.path.join(self.project, "canworks", "rtd8.eds.notes.json"))
        self.assertEqual(notes["objects"]["0x6110:1"], {"name": "AI0_Sensor_Type", "text": "Sensor type of the channel",
                                                        "values": {"1": "two-wire", "30": "four-wire"}})
        self.assertEqual(notes["eds"]["file"], "rtd8.eds")

    def test_note_picker_rows(self):
        # The Add note picker (notes-row-pick-and-commission-notes): a click
        # on a row picks it, the arrow keys move between rows, and nothing
        # needs a sideways scroll at 1000 px.
        pg = self.page
        pg.set_viewport_size({"width": 1000, "height": 800})
        self.open_from_start("#start-open", self.project)
        self.fill("adapter.interface", "can0")
        self.add_node(os.path.join(RTD, "rtd8.eds"))
        self.fill("nodes[0].node_id", "5")
        node_tab(pg, "notes")
        pg.click("button[data-add-note]")
        pg.wait_for_selector("#modal [data-note-pick-row]")
        self.assertTrue(pg.evaluate("""() => { const l = document.querySelector('#modal .note-picker-list');
            return l.scrollWidth <= l.clientWidth + 1; }"""))
        self.assertRegex(pg.locator("#modal button[data-note-pick]").first.get_attribute("aria-label"),
                         r"^(Write a note for|Edit the note of) 0x1000:0 ")
        pg.fill("#modal [data-note-picker-filter]", "1018")
        pg.keyboard.press("ArrowDown")
        pg.keyboard.press("ArrowDown")
        self.assertEqual(pg.evaluate("() => document.activeElement.dataset.notePick"), "0x1018:1")
        pg.keyboard.press("ArrowUp")
        pg.keyboard.press("ArrowUp")
        self.assertEqual(pg.evaluate("() => document.activeElement.dataset.notePickerFilter"), "1")
        pg.keyboard.press("ArrowDown")
        pg.keyboard.press("ArrowDown")
        pg.keyboard.press("Enter")
        pg.wait_for_selector('#modal .note-editor[data-note-editor="0x1018:1"]')
        pg.click('#modal button[data-value="cancel"]')
        pg.click("button[data-add-note]")
        pg.fill("#modal [data-note-picker-filter]", "2000")
        pg.click('#modal tr[data-note-pick-row="0x2000:2"] td:nth-child(3)')
        pg.wait_for_selector('#modal .note-editor[data-note-editor="0x2000:2"]')
        pg.fill('#modal [data-note-field="text"]', "Delay")
        pg.click('#modal button[data-value="save"]')
        pg.wait_for_selector('[data-note-row="0x2000:2"][data-note-source="mine"]')
        # The Notes tab's row opens its note on a click, too.
        pg.click('[data-note-row="0x2000:2"] td:nth-child(2)')
        pg.wait_for_selector('#modal .note-editor[data-note-editor="0x2000:2"]')
        pg.click('#modal button[data-value="cancel"]')
        # Notes written while commissioning a device go with it into a config
        # as unsaved edits, unless the config has notes of its own for the EDS.
        pg.evaluate("""() => carryNotes('rtd8.eds', { '0x2000:1': { text: 'Filter' } })""")
        pg.wait_for_selector("#banner [data-notes-carried]")
        self.assertEqual(pg.evaluate("() => S.model.notes['rtd8.eds']['0x2000:1']"), {"text": "Filter"})
        self.save()
        pg.evaluate("""() => carryNotes('rtd8.eds', { '0x2000:3': { text: 'Other' } })""")
        pg.wait_for_selector("#banner [data-notes-kept]")
        self.assertNotIn("0x2000:3", load(os.path.join(self.project, "canworks", "rtd8.eds.notes.json"))["objects"])
        self.assertIsNone(pg.evaluate("() => ((S.model.notes || {})['rtd8.eds'] || {})['0x2000:3'] || null"))

    def test_note_editor_hides_builtin_field(self):
        # Emptying a built-in field in the Note editor hides it (null in the
        # notes file); Use built-in brings it back (clear-builtin-note-fields).
        pg = self.page
        self.open_from_start("#start-open", self.project)
        self.fill("adapter.interface", "can0")
        self.add_node(os.path.join(RTD, "rtd8.eds"))
        self.fill("nodes[0].node_id", "5")
        node_tab(pg, "notes")

        def edit():
            pg.click("button[data-add-note]")
            pg.fill("#modal [data-note-picker-filter]", "1017")
            pg.keyboard.press("Enter")
            pg.wait_for_selector("#modal .note-editor")

        edit()
        unit = '#modal [data-note-field="unit"]'
        self.assertEqual(pg.input_value(unit), "ms")
        self.assertTrue(pg.is_hidden('#modal [data-note-restore="unit"]'))
        pg.fill(unit, "")
        self.assertIn("ms (built-in, hidden)", pg.get_attribute(unit, "placeholder"))
        self.assertTrue(pg.is_visible('#modal [data-note-restore="unit"]'))
        pg.click('#modal button[data-value="save"]')
        pg.wait_for_selector('[data-note-row="0x1017:0"][data-note-source="changed"]')
        self.save()
        notes = load(os.path.join(self.project, "canworks", "rtd8.eds.notes.json"))
        self.assertEqual(notes["objects"]["0x1017"], {"name": "Producer heartbeat time", "unit": None})
        # Reopened: the hidden value is named; Use built-in puts it back.
        edit()
        self.assertEqual(pg.input_value(unit), "")
        self.assertIn("ms (built-in, hidden)", pg.get_attribute(unit, "placeholder"))
        pg.click('#modal [data-note-restore="unit"]')
        self.assertEqual(pg.input_value(unit), "ms")
        pg.click('#modal button[data-value="save"]')
        pg.wait_for_selector('[data-notes-empty="mine"]')
        # Ctrl+Z brings the hidden unit back.
        pg.click("[data-node-heading]")
        pg.keyboard.press("Control+z")
        pg.wait_for_selector('[data-note-row="0x1017:0"][data-note-source="changed"]')

    def test_notes_tab_import_export_undo(self):
        # The Notes tab (notes-tab-own-notes): own notes first, export,
        # import with a preview, undo, and Save.
        from .test_configurator_layout import audit
        pg = self.page
        pg.on("filechooser", lambda _: None)
        self.open_from_start("#start-open", self.project)
        self.fill("adapter.interface", "can0")
        self.add_node(os.path.join(RTD, "rtd8.eds"))
        self.fill("nodes[0].node_id", "5")
        node_tab(pg, "notes")
        pg.wait_for_selector('[data-notes-empty="mine"]:has-text("You have not written any notes")')
        pg.click("[data-notes-show-all]")
        pg.wait_for_selector('[data-note-row="0x1017:0"][data-note-source="builtin"]')
        audit(pg, "Notes tab, all notes")
        # Without notes of one's own only the merged file is offered.
        pg.click("button[data-export-notes]")
        self.assertEqual(pg.locator('#modal button[data-value="own"]').count(), 0)
        with pg.expect_download() as dl:
            pg.click('#modal button[data-value="merged"]')
        self.assertEqual(dl.value.suggested_filename, "rtd8.eds.merged.notes.json")
        with open(dl.value.path(), encoding="utf-8") as f:
            doc = json.load(f)
        doc["objects"]["0x2000:2"] = {"text": "Delay before the first reading", "unit": "ms"}
        doc["objects"]["0x2999"] = {"text": "not in this EDS"}
        path = os.path.join(self.dir, "colleague.notes.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(doc, f)
        # Import: a preview first, then one draft edit.
        pg.click("button[data-import-notes]")
        pg.set_input_files("#modal [data-import-notes-file]", path)
        pg.click('#modal button[data-value="next"]')
        pg.wait_for_selector("#modal [data-import-preview]")
        preview = pg.inner_text("#modal [data-import-preview]")
        self.assertIn("New notes: 1.", preview)
        self.assertIn("Skipped (not in rtd8.eds): 1.", preview)
        audit(pg, "Notes import preview")
        pg.click('#modal button[data-value="import"]')
        pg.wait_for_selector('[data-note-row="0x2000:2"][data-note-source="mine"]')
        self.assertEqual(pg.locator("[data-note-row]").count(), 1)
        self.assertEqual(pg.inner_text('.node-tabs [data-node-tab="notes"]').strip(), "Notes 1")
        # Ctrl+Z takes the whole import back, Ctrl+Shift+Z brings it again.
        pg.click("[data-node-heading]")
        pg.keyboard.press("Control+z")
        pg.wait_for_selector('[data-notes-empty="mine"]')
        pg.keyboard.press("Control+Shift+z")
        pg.wait_for_selector('[data-note-row="0x2000:2"]')
        self.save()
        notes = load(os.path.join(self.project, "canworks", "rtd8.eds.notes.json"))
        self.assertEqual(notes["objects"]["0x2000:2"], {"name": "Start delay ms", "text": "Delay before the first reading", "unit": "ms"})
        self.assertNotIn("0x1017", notes["objects"])
        # Export of one's own notes: only the filled entries.
        pg.click("button[data-export-notes]")
        with pg.expect_download() as dl:
            pg.click('#modal button[data-value="own"]')
        self.assertEqual(dl.value.suggested_filename, "rtd8.eds.notes.json")
        with open(dl.value.path(), encoding="utf-8") as f:
            self.assertEqual(list(json.load(f)["objects"]), ["0x2000:2"])

    def test_pdo_timing_and_sdo_picker(self):
        pg = self.page
        self.open_from_start("#start-open", self.project)
        self.fill("adapter.interface", "can0")
        self.fill("master.sync_period_us", "10")
        self.add_node(os.path.join(REPO, "test", "fixtures", "eds", "pdo-comm.eds"))
        self.fill("nodes[0].node_id", "2")
        self.pick("0x4001:0")
        self.pick("0x4000:0")
        pg.wait_for_selector('input[data-path="nodes[0].rx_pdos[0].entries[0].iec_location"]')
        self.fill("nodes[0].tx_pdos[0].entries[0].iec_location", "%ID300")
        self.fill("nodes[0].rx_pdos[0].entries[0].iec_location", "%QD300")
        # pdo-comm.eds fixes TPDO 1's inhibit time (ro) and RPDO 1's
        # transmission type (ro, 255); RPDO 1 has a deadline (sub 5).
        self.pdo_settings("nodes[0].tx_pdos[0]")
        self.pdo_settings("nodes[0].rx_pdos[0]")
        self.assertTrue(pg.is_disabled('input[data-path="nodes[0].tx_pdos[0].inhibit_time_us"]'))
        self.assertIn("255: event-driven, fixed by the EDS",
                      pg.inner_text('output[data-path="nodes[0].rx_pdos[0].transmission"]'))
        self.assertEqual(pg.get_attribute('input[data-path="nodes[0].tx_pdos[0].event_timer_ms"]', "placeholder"),
                         "EDS default (0 ms)")
        # SYNC start shows for TPDO 1 (EDS transmission type 1).
        self.assertEqual(pg.locator('input[data-path="nodes[0].tx_pdos[0].sync_start"]').count(), 1)
        self.fill("nodes[0].tx_pdos[0].event_timer_ms", "50")
        self.fill("nodes[0].rx_pdos[0].event_timer_ms", "500")
        self.fill("nodes[0].tx_pdos[0].cob_id", "auto")
        pg.wait_for_selector("text=auto = 0x182")
        # The SDO picker hides process signals and plugin objects.
        node_tab(pg, "sdos")
        self.open_sections()
        self.assertEqual(pg.locator('button[data-sdo="0x4000:0"]').count(), 0)
        self.assertEqual(pg.locator('button[data-sdo="0x1400:5"]').count(), 0)
        self.assertIn("Hidden:", pg.inner_text('fieldset[data-path="nodes[0].sdo"]'))
        pg.check('input[aria-label="Show all writable objects"]')
        self.assertEqual(pg.locator('button[data-sdo="0x1400:5"]').count(), 1)
        self.save()
        node = load(os.path.join(self.project, "canworks", "canworks.json"))["nodes"][0]
        self.assertEqual(node["tx_pdos"][0].get("event_timer_ms"), 50)
        self.assertEqual(node["tx_pdos"][0].get("cob_id"), "auto")
        self.assertNotIn("inhibit_time_us", node["tx_pdos"][0])
        self.assertEqual(node["rx_pdos"][0].get("event_timer_ms"), 500)
        self.assertNotIn("transmission", node["rx_pdos"][0])

    def test_input_pdo_receive_timeout(self):
        pg = self.page
        self.open_from_start("#start-open", self.project)
        self.fill("adapter.interface", "can0")
        self.fill("master.sync_period_us", "10")
        self.add_node(os.path.join(REPO, "test", "fixtures", "eds", "pdo-comm.eds"))
        self.fill("nodes[0].node_id", "2")
        self.pick("0x4001:0")
        pg.wait_for_selector('input[data-path="nodes[0].tx_pdos[0].entries[0].iec_location"]')
        self.fill("nodes[0].tx_pdos[0].entries[0].iec_location", "%ID300")
        self.pdo_settings("nodes[0].tx_pdos[0]")
        # Off by default. The EDS event timer is 0, so auto has nothing to use.
        self.assertEqual(pg.get_attribute('input[data-path="nodes[0].tx_pdos[0].timeout_ms"]', "placeholder"), "off")
        self.assertEqual(pg.locator('select[data-path="nodes[0].tx_pdos[0].on_timeout"]').count(), 0)
        pg.click('button[data-timeout-auto="nodes[0].tx_pdos[0]"]')
        pg.wait_for_selector('[data-timeout-for="nodes[0].tx_pdos[0]"]:has-text("auto needs an event timer")')
        self.fill("nodes[0].tx_pdos[0].event_timer_ms", "50")
        pg.press('input[data-path="nodes[0].tx_pdos[0].event_timer_ms"]', "Tab")
        pg.click('button[data-timeout-auto="nodes[0].tx_pdos[0]"]')
        pg.wait_for_selector('[data-timeout-for="nodes[0].tx_pdos[0]"]:has-text("auto (100 ms)")')
        pg.select_option('select[data-path="nodes[0].tx_pdos[0].on_timeout"]', "zero")
        self.fill("nodes[0].tx_pdos[0].timeout_location", "%IX10.1")
        self.save()
        pdo = load(os.path.join(self.project, "canworks", "canworks.json"))["nodes"][0]["tx_pdos"][0]
        self.assertEqual(pdo.get("timeout_ms"), "auto")
        self.assertEqual(pdo.get("on_timeout"), "zero")
        self.assertEqual(pdo.get("timeout_location"), "%IX10.1")
        # Emptying the timeout drops the fields that need it.
        self.fill("nodes[0].tx_pdos[0].timeout_ms", "")
        pg.press('input[data-path="nodes[0].tx_pdos[0].timeout_ms"]', "Tab")
        pg.wait_for_selector('select[data-path="nodes[0].tx_pdos[0].on_timeout"]', state="detached")
        self.save()  # the banner still says Saved from before, so wait for the file
        path = os.path.join(self.project, "canworks", "canworks.json")
        deadline = time.time() + 5
        while "timeout_ms" in load(path)["nodes"][0]["tx_pdos"][0] and time.time() < deadline:
            time.sleep(0.05)
        pdo = load(path)["nodes"][0]["tx_pdos"][0]
        for key in ("timeout_ms", "on_timeout", "timeout_location"):
            self.assertNotIn(key, pdo)

    def test_device_pdo_mapping(self):
        pg = self.page
        self.open_from_start("#start-open", self.project)
        self.fill("adapter.interface", "can0")
        self.fill("master.sync_period_us", "10")
        self.add_node(os.path.join(REPO, "test", "fixtures", "eds", "fixed-io.eds"))
        self.fill("nodes[0].node_id", "2")
        # Every TPDO of fixed-io.eds is fixed: 0x6000:3 is in none of them.
        node_tab(pg, "pdos")
        self.open_sections()
        self.assertEqual(pg.locator('button[data-add="0x6000:2"]').count(), 1)
        self.assertEqual(pg.locator('button[data-add="0x6000:3"]').count(), 0)
        self.pick("0x6000:2")
        pg.wait_for_selector('[data-mapping="nodes[0].tx_pdos[0]"]:has-text("Set by the device")')
        pg.click('button[data-map-all="nodes[0].tx_pdos[0]"]')
        pg.wait_for_selector('input[data-path="nodes[0].tx_pdos[0].entries[1].iec_location"]')
        self.pick("0x6200:1")
        pg.wait_for_selector('input[data-path="nodes[0].rx_pdos[0].entries[0].iec_location"]')
        self.save()
        node = load(os.path.join(self.project, "canworks", "canworks.json"))["nodes"][0]
        tx, rx = node["tx_pdos"][0], node["rx_pdos"][0]
        self.assertNotIn("mapping", tx)
        self.assertEqual(tx["number"], 1)
        self.assertEqual(sorted((e["index"], e["subindex"]) for e in tx["entries"]), [("0x6000", 1), ("0x6000", 2)])
        self.assertEqual([(e["index"], e["subindex"], e["type"]) for e in rx["entries"]], [("0x6200", 1, "UNSIGNED8")])

    def test_device_mapping_on_a_writable_pdo(self):
        pg = self.page
        self.open_from_start("#start-open", self.project)
        self.fill("adapter.interface", "can0")
        self.fill("master.sync_period_us", "10")
        self.add_node(os.path.join(REPO, "test", "fixtures", "eds", "cpp-slave.eds"))
        self.fill("nodes[0].node_id", "2")
        self.pick("0x4001:0")
        pg.wait_for_selector('input[data-path="nodes[0].tx_pdos[0].entries[0].iec_location"]')
        self.fill("nodes[0].tx_pdos[0].entries[0].iec_location", "%ID300")
        pg.select_option('select[data-path="nodes[0].tx_pdos[0].mapping"]', "device")
        pg.wait_for_selector('.pdo-map:has-text("0x4001:0")')
        self.save()
        pdo = load(os.path.join(self.project, "canworks", "canworks.json"))["nodes"][0]["tx_pdos"][0]
        self.assertEqual(pdo["mapping"], "device")

    def test_inhibit_time_in_ms(self):
        pg = self.page
        self.open_from_start("#start-open", self.project)
        self.fill("adapter.interface", "can0")
        self.fill("master.sync_period_us", "10")
        self.add_node(os.path.join(REPO, "test", "fixtures", "eds", "cpp-slave.eds"))
        self.fill("nodes[0].node_id", "2")
        self.pick("0x4001:0")
        pg.wait_for_selector('input[data-path="nodes[0].tx_pdos[0].entries[0].iec_location"]')
        self.fill("nodes[0].tx_pdos[0].entries[0].iec_location", "%ID300")
        self.fill("nodes[0].tx_pdos[0].inhibit_time_us", "2.5")
        # cpp-slave.eds has no RPDO sub 5, so no deadline field.
        self.save()
        pdo = load(os.path.join(self.project, "canworks", "canworks.json"))["nodes"][0]["tx_pdos"][0]
        self.assertEqual(pdo["inhibit_time_us"], 2500)

    def test_read_only_sdo_refused(self):
        pg = self.page
        self.open_from_start("#start-open", self.project)
        self.add_node(os.path.join(RTD, "rtd8.eds"))
        node_tab(pg, "sdos")
        self.open_sections()
        self.assertEqual(pg.locator('button[data-sdo="0x1018:1"]').count(), 0)
        pg.fill('input[aria-label="SDO index"]', "0x1018")
        pg.fill('input[aria-label="SDO subindex"]', "1")
        pg.click("text=Add write")
        self.assertIn("cannot be written", pg.inner_text("#banner"))

    def test_sdo_variables_and_nmt_command(self):
        pg = self.page
        self.open_from_start("#start-open", self.project)
        self.fill("adapter.interface", "can0")
        self.add_node(os.path.join(RTD, "rtd8.eds"))
        self.fill("nodes[0].node_id", "5")
        # NMT command byte next to the state byte.
        node_tab(pg, "supervision")
        pg.click('button[data-suggest="nmt"]')
        nmt = self.filled("nodes[0].nmt_command_location")
        self.assertTrue(nmt.startswith("%QB"), nmt)
        # Read the serial number (0x1018:4, const).
        node_tab(pg, "sdos")
        self.open_sections()
        pg.fill('input[aria-label="Filter SDO variable objects"]', "0x1018")
        pg.click('button[data-sdo-var="0x1018:4"]')
        pg.wait_for_selector('input[data-path="nodes[0].sdo_variables[0].iec_location"]')
        pg.click('.sdo-var[data-path="nodes[0].sdo_variables[0]"] button[data-suggest="sdo_status"]')
        self.filled("nodes[0].sdo_variables[0].status_location")
        self.fill("nodes[0].sdo_variables[0].period_ms", "1000")
        # The write picker hides read-only objects; writing 0x1017 warns.
        pg.select_option('select[aria-label="SDO variable direction"]', "write")
        self.assertEqual(pg.locator('button[data-sdo-var="0x1018:4"]').count(), 0)
        pg.fill('input[aria-label="Filter SDO variable objects"]', "")
        pg.click('button[data-sdo-var="0x1017:0"]')
        pg.wait_for_selector('input[data-path="nodes[0].sdo_variables[1].iec_location"]')
        self.settled()
        self.assertIn("plugin configures itself",
                      pg.inner_text('.field-msg[data-for="nodes[0].sdo_variables[1]"]'))
        pg.fill('input[aria-label="SDO variable index"]', "0x7FFF")
        pg.click("text=Add variable")
        self.assertIn("not in", pg.inner_text("#banner"))
        self.save()
        node = load(os.path.join(self.project, "canworks", "canworks.json"))["nodes"][0]
        self.assertEqual(node["nmt_command_location"], nmt)
        read, write = node["sdo_variables"]
        self.assertEqual((read["index"], read["subindex"], read["type"], read["direction"], read["period_ms"]),
                         ("0x1018", 4, "UNSIGNED32", "read", 1000))
        self.assertTrue(read["iec_location"].startswith("%ID"), read)
        self.assertTrue(read["status_location"].startswith("%IB"), read)
        self.assertEqual((write["index"], write["type"], write["direction"]), ("0x1017", "UNSIGNED16", "write"))
        self.assertTrue(write["iec_location"].startswith("%QW"), write)
        pg.click('button[data-view="declarations"]')
        block = pg.input_value("textarea.block")
        self.assertIn("AT %s : USINT;" % nmt, block)
        self.assertIn("AT %s : UDINT;" % read["iec_location"], block)
        self.assertIn("AT %s : USINT;" % read["status_location"], block)

    def test_selected_rows_resize_and_picker_notes(self):
        # row-highlight-and-list-resize: one selected row per list, kept
        # through a re-render, cleared by Escape; the pickers' resize bars keep
        # their height per kind of box; whole notes on the pickers.
        pg = self.page
        self.open_from_start("#start-open", self.project)
        self.fill("adapter.interface", "can0")
        self.add_node(os.path.join(RTD, "rtd8.eds"))
        self.fill("nodes[0].node_id", "5")
        # A note with named values and no text shows on the pickers.
        node_tab(pg, "notes")
        pg.click("button[data-add-note]")
        pg.fill("#modal [data-note-picker-filter]", "2000:1")
        pg.keyboard.press("Enter")
        pg.wait_for_selector("#modal .note-editor")
        pg.fill('#modal [data-note-field="values"]', "0 = wait\n1 = start")
        pg.click('#modal button[data-value="save"]')
        pg.wait_for_selector('[data-note-row="0x2000:1"][data-note-source="mine"]')
        node_tab(pg, "sdos")
        self.open_sections()
        sdo = 'tr:has(button[data-sdo="0x2000:1"])'
        self.assertIn("0 = wait, 1 = start", pg.inner_text(sdo + ' [data-note="meaning"]'))
        var = 'tr:has(button[data-sdo-var="0x2000:1"])'
        self.assertIn("0 = wait, 1 = start", pg.inner_text(var + ' [data-note="meaning"]'))
        # The SDO variables picker shows built-in note text, and filters by it.
        pg.fill('input[aria-label="Filter SDO variable objects"]', "heartbeat")
        pg.wait_for_selector('button[data-sdo-var="0x1017:0"]')
        self.assertIn("heartbeat", pg.inner_text('tr:has(button[data-sdo-var="0x1017:0"]) [data-note="text"]').lower())
        pg.fill('input[aria-label="Filter SDO variable objects"]', "")
        # Selecting rows: a click on the name, then on another row's name.
        selected = """(box) => [...document.querySelectorAll(`[data-box="${box}"] tr.row-selected`)]
            .map((r) => r.cells[0].textContent + ' ' + r.getAttribute('aria-current'))"""
        pg.click(sdo + " td:nth-child(2)")
        self.assertEqual(pg.evaluate(selected, "sdo_picker"), ["0x2000:1 true"])
        pg.click('tr:has(button[data-sdo="0x2000:2"]) td:nth-child(1)')
        self.assertEqual(pg.evaluate(selected, "sdo_picker"), ["0x2000:2 true"])
        # Add selects its row too, and the selection survives the re-render.
        pg.click('button[data-sdo-var="0x2000:1"]')
        pg.wait_for_selector('.sdo-var[data-path="nodes[0].sdo_variables[0]"]')
        self.assertIn("0 = wait, 1 = start", pg.inner_text('.sdo-var[data-path="nodes[0].sdo_variables[0]"] [data-note="meaning"]'))
        pg.wait_for_function("() => document.querySelector('[data-box=\"sdo_var_picker\"] tr.row-selected')")
        self.assertEqual(pg.evaluate(selected, "sdo_var_picker"), ["0x2000:1 true"])
        self.assertEqual(pg.evaluate(selected, "sdo_picker"), ["0x2000:2 true"])
        # Tab into a row's button selects it; Escape clears.
        third = '[data-box="sdo_picker"] tbody tr:nth-child(3)'
        pg.focus(third + " button")
        self.assertEqual(pg.evaluate(selected, "sdo_picker"), [pg.inner_text(third + " td:nth-child(1)").strip() + " true"])
        pg.keyboard.press("Escape")
        self.assertEqual(pg.evaluate(selected, "sdo_picker"), [])
        # The look is the same as the object dictionary's.
        pg.click(sdo + " td:nth-child(2)")
        look = pg.evaluate("""() => { const tr = document.querySelector('[data-box="sdo_picker"] tr.row-selected');
            const c = getComputedStyle(tr.cells[0]); return [c.backgroundColor, c.boxShadow.includes('3px')]; }""")
        sel_bg = pg.evaluate("""() => { const d = document.createElement('div'); d.style.background = 'var(--sel-bg)';
            document.body.append(d); const c = getComputedStyle(d).backgroundColor; d.remove(); return c; }""")
        self.assertEqual(look, [sel_bg, True])
        pg.emulate_media(forced_colors="active")
        outline = pg.eval_on_selector('[data-box="sdo_picker"] tr.row-selected', "tr => getComputedStyle(tr).outlineStyle")
        pg.emulate_media(forced_colors="none")
        self.assertEqual(outline, "solid")
        # The resize bar: Down twice makes the picker 80 px taller, the height
        # is kept on this PC, and double-click restores the default.
        bar = '[data-box-bar="sdo_picker"]'
        pg.wait_for_selector(bar)
        h0 = pg.evaluate("() => document.querySelector('[data-box=\"sdo_picker\"]').getBoundingClientRect().height")
        pg.focus(bar)
        pg.keyboard.press("ArrowUp")
        pg.keyboard.press("ArrowUp")
        h1 = pg.evaluate("() => document.querySelector('[data-box=\"sdo_picker\"]').getBoundingClientRect().height")
        self.assertAlmostEqual(h1, h0 - 80, delta=2)
        self.assertEqual(pg.get_attribute(bar, "role"), "separator")
        self.assertEqual(pg.get_attribute(bar, "aria-valuenow"), str(round(h1)))
        # Polled here: a wait_for_function predicate that returns a promise
        # ends when the promise settles, true or not.
        ui_file = os.path.join(self.dir, "cfg", "ui.json")
        def box_heights(want):
            end = time.time() + 5
            while True:
                got = load(ui_file).get("box_heights") if os.path.exists(ui_file) else None
                if got == want or time.time() > end:
                    return got
                time.sleep(0.05)
        self.assertEqual(box_heights({"sdo_picker": round(h1)}), {"sdo_picker": round(h1)})
        self.save()
        pg.reload()
        pg.wait_for_selector("#editor:not([hidden])")
        tree_node(pg, 0, "sdos")
        self.open_sections()
        pg.wait_for_function("(h) => document.querySelector('[data-box=\"sdo_picker\"]').style.maxHeight === h + 'px'",
                             arg=round(h1))
        pg.dblclick(bar)
        self.assertEqual(pg.evaluate("() => document.querySelector('[data-box=\"sdo_picker\"]').style.maxHeight"), "")
        self.assertEqual(box_heights({}), {})

    def test_supervision_method_switch(self):
        pg = self.page
        self.open_from_start("#start-open", self.project)
        self.add_node(os.path.join(RTD, "rtd8.eds"), heartbeat=None)
        # save-anytime: the EDS heartbeat is 0, so the new node starts with 1000 ms.
        self.assertEqual(pg.input_value('input[data-path="nodes[0].heartbeat_ms"]'), "1000")
        pg.wait_for_selector("[data-supervision-added]")
        # With "EDS default" the node would never be seen lost, which is an error under Method.
        pg.select_option('select[data-supervision="0"]', "none")
        msg = '.field-msg[data-for="nodes[0].heartbeat_ms"]'
        pg.wait_for_selector(msg + ':has-text("has no heartbeat or guarding")')
        self.assertIn("has no heartbeat or guarding", pg.inner_text("#problem-list"))
        pg.select_option('select[data-supervision="0"]', "heartbeat")
        self.fill("nodes[0].heartbeat_ms", "100")
        pg.select_option('select[data-supervision="0"]', "guarding")
        self.assertEqual(pg.locator('input[data-path="nodes[0].heartbeat_ms"]').count(), 0)
        self.fill("nodes[0].guard_time_ms", "100")
        self.fill("nodes[0].life_time_factor", "3")
        self.pick("0x7130:1")
        pg.wait_for_selector('input[data-path="nodes[0].tx_pdos[0].entries[0].iec_location"]')
        self.save()
        node = load(os.path.join(self.project, "canworks", "canworks.json"))["nodes"][0]
        self.assertNotIn("heartbeat_ms", node)
        self.assertEqual((node["guard_time_ms"], node["life_time_factor"]), (100, 3))

    def test_clash_with_ethercat(self):
        pg = self.page
        self.open_from_start("#start-open", self.project)
        self.add_node(os.path.join(PINGPONG, "cpp-slave.eds"))
        self.pick("0x4001:0")
        loc = 'input[data-path="nodes[0].tx_pdos[0].entries[0].iec_location"]'
        pg.wait_for_selector(loc)
        pg.fill(loc, "%ID100")
        pg.wait_for_selector("#problem-list li.error:has-text('ecat-bus.json')")
        pg.wait_for_selector(loc + ".invalid")
        pg.check("#allow-overlap")
        pg.wait_for_selector("#problem-list li.warning:has-text('ecat-bus.json')")
        self.save()
        saved = load(os.path.join(self.project, "canworks", "canworks.json"))
        self.assertEqual(saved["nodes"][0]["tx_pdos"][0]["entries"][0]["iec_location"], "%ID100")

    def test_standalone_then_move_into_project(self):
        pg = self.page
        folder = os.path.join(self.dir, "canopen-rtd")
        self.open_from_start("#start-new", folder)
        self.assertIn("standalone", pg.inner_text("#mode"))
        self.assertIn("skipped", pg.inner_text("#scan-info"))
        self.add_node(os.path.join(RTD, "rtd8.eds"))
        self.pick("0x7130:1")
        pg.wait_for_selector('input[data-path="nodes[0].tx_pdos[0].entries[0].iec_location"]')
        self.save()
        self.assertTrue(os.path.isfile(os.path.join(folder, "canworks.json")))
        pg.evaluate("() => { document.querySelector('#menu-project').open = true; }")
        pg.click("#btn-move")
        pg.fill("#modal-extra input", self.project)
        pg.click("#modal-buttons button[data-value=move]")
        pg.wait_for_selector("#mode:has-text('project rtd-monitor')")
        self.assertIn("Moved into", pg.inner_text("#banner"))
        moved = load(os.path.join(self.project, "canworks", "canworks.json"))
        self.assertEqual(moved["nodes"][0]["tx_pdos"][0]["entries"][0]["index"], "0x7130")
        self.assertIn("in use", pg.inner_text("#scan-info"))

    def test_standalone_then_new_editor_project(self):
        pg = self.page
        os.environ["OPENPLC_CLI"] = fake_editor_cli(self.dir)
        self.addCleanup(os.environ.pop, "OPENPLC_CLI", None)
        folder = os.path.join(self.dir, "canopen-rtd")
        work = os.path.join(self.dir, "work")
        os.makedirs(os.path.join(work, "taken"))
        self.open_from_start("#start-new", folder)
        self.assertTrue(pg.is_visible("#menu-project"))
        self.add_node(os.path.join(RTD, "rtd8.eds"))
        self.pick("0x7130:1")
        pg.wait_for_selector('input[data-path="nodes[0].tx_pdos[0].entries[0].iec_location"]')
        pg.evaluate("() => { document.querySelector('#menu-project').open = true; }")
        pg.click("#btn-new-project")
        self.assertIn("Save the config", pg.inner_text("#banner"))
        self.save()
        pg.evaluate("() => { document.querySelector('#menu-project').open = true; }")
        pg.click("#btn-new-project")
        pg.fill('#modal-extra input[aria-label="Parent folder"]', work)
        pg.fill('#modal-extra input[aria-label="Project name"]', "taken")
        self.assertEqual(pg.input_value('#modal-extra input[aria-label="Task interval"]'), "T#20ms")
        pg.click("#modal-buttons button[data-value=create]")
        pg.wait_for_selector("#modal-text:has-text('Not created')")
        self.assertIn("already exists", pg.inner_text("#modal-text"))
        self.assertEqual(os.listdir(os.path.join(work, "taken")), [])
        user_data = os.path.join(self.dir, "open-plc-editor")
        os.makedirs(user_data)
        os.environ["OPENPLC_EDITOR_USER_DATA"] = user_data
        self.addCleanup(os.environ.pop, "OPENPLC_EDITOR_USER_DATA", None)
        self.assertFalse(pg.is_checked('#modal-extra input[aria-label="Enable the canworks function blocks"]'))
        pg.check('#modal-extra input[aria-label="Enable the canworks function blocks"]')
        pg.fill('#modal-extra input[aria-label="Project name"]', "rtd-monitor")
        pg.click("#modal-buttons button[data-value=create]")
        pg.wait_for_selector("#mode:has-text('project rtd-monitor')")
        self.assertIn("1 CANopen variable declared in main", pg.inner_text("#banner"))
        self.assertIn("Installed canworks", pg.inner_text("#banner"))
        self.assertEqual(load(os.path.join(work, "rtd-monitor", "project.json"))["data"]["libraries"][0]["name"],
                         "canworks")
        self.assertTrue(os.path.isfile(os.path.join(user_data, "libraries", "registry.json")))
        self.assertTrue(pg.is_hidden("#menu-project"))
        main = os.path.join(work, "rtd-monitor", "pous", "programs", "main.st")
        with open(main, encoding="utf-8") as f:
            self.assertIn(" : INT AT %IW", f.read())
        self.assertIn("in use", pg.inner_text("#scan-info"))

    def test_changed_on_disk(self):
        pg = self.page
        self.open_from_start("#start-open", self.project)
        self.add_node(os.path.join(PINGPONG, "cpp-slave.eds"))
        self.pick("0x4001:0")
        pg.wait_for_selector('input[data-path="nodes[0].tx_pdos[0].entries[0].iec_location"]')
        self.save()
        path = os.path.join(self.project, "canworks", "canworks.json")
        doc = load(path)
        doc["master"]["sync_period_us"] = 20000
        with open(path, "w") as f:
            json.dump(doc, f)
        tree_view(pg, "bus")
        self.fill("adapter.interface", "can1")
        self.settled()
        pg.click("#btn-save")
        pg.wait_for_selector("#modal[open]")
        self.assertIn("changed on disk", pg.inner_text("#modal-text"))
        pg.click("#modal-buttons button[data-value=reload]")
        pg.wait_for_function("() => document.querySelector('input[data-path=\"master.sync_period_us\"]')?.value === '20'")
        self.assertEqual(pg.input_value('input[data-path="master.sync_period_us"]'), "20")
        self.assertEqual(load(path)["adapter"]["interface"], "can0")


if __name__ == "__main__":
    unittest.main()
