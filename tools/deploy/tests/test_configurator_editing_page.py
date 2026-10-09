"""The start page, project files and editing fixes of the configurator bug
hunt in a real browser (fix-gui-test-findings groups 3 and 4): folders the
configurator cannot use, open vs new, the folder browser and Recent, moving
a config with its simulation file, the slave EDS description, the gateway
following renames, the rename dialog, PDO and startup SDO edits, a second
DBC import, the declarations wording and a typed-back value. Needs
Playwright, like test_configurator_page.py."""

import json
import os
import shutil
import threading
import unittest

from canworks.configurator import server as srv

from .helpers import REPO, tmpdir
from .test_configurator_page import REQUIRED, load, sync_playwright

PLANT = os.path.join(REPO, "examples", "virtual-plant")
J1939 = os.path.join(REPO, "examples", "j1939")
PUMP_DBC = os.path.join(os.path.dirname(__file__), "data", "j1939", "pump.dbc")
ROOT = hasattr(os, "geteuid") and os.geteuid() == 0


@unittest.skipIf(sync_playwright is None and not REQUIRED, "Playwright for Python is not installed")
class Base(unittest.TestCase):
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
        self.context = self.browser.new_context()
        self.addCleanup(self.context.close)
        self.page = self.context.new_page()
        self.page.set_default_timeout(10000)
        self.errors = []
        self.page.on("pageerror", lambda e: self.errors.append(str(e)))
        # The API's refusals show as failed loads; the page handles those.
        self.page.on("console", lambda m: self.errors.append(m.text)
                     if m.type == "error" and not m.text.startswith("Failed to load resource") else None)

    def tearDown(self):
        self.assertEqual(self.errors, [])

    def copy(self, src, name="plant"):
        folder = os.path.join(self.dir, name)
        shutil.copytree(src, folder)
        return folder

    def start(self, choice, path):
        pg = self.page
        pg.goto(self.server.url)
        pg.click(choice)
        pg.fill("#browser-path", path)
        pg.click("#browser-open")

    def open(self, folder):
        self.start("#start-standalone", folder)
        self.page.wait_for_selector("#editor:not([hidden])")
        self.settled()

    def settled(self):
        self.page.wait_for_function("() => document.body.dataset.checking === '0'")

    def problems(self, none=True):
        try:
            self.page.wait_for_function(
                "(none) => (document.querySelector('#problem-count').innerText === 'none') === none", arg=none,
                timeout=5000)
        except Exception:
            pass
        self.settled()
        return self.page.inner_text("#problem-count"), self.page.inner_text("#problem-list")

    def answer(self, value):
        self.page.click('#modal-buttons button[data-value="%s"]' % value)

    def tab(self, name):
        self.page.click('#net-bar button[role=tab]:has-text("%s")' % name)

    def draft(self, expr):
        return self.page.evaluate("() => JSON.parse(JSON.stringify(%s))" % expr)


class StartPage(Base):
    def test_open_existing_or_new(self):
        pg = self.page
        missing = os.path.join(self.dir, "typo-standalone")
        self.start("#start-standalone", missing)
        pg.wait_for_selector("#banner:has-text('does not exist')")
        self.assertTrue(pg.is_visible("#start"))
        self.assertEqual(pg.get_attribute("#start-standalone", "aria-pressed"), "true")
        self.assertEqual(pg.get_attribute("#start-new", "aria-pressed"), "false")
        self.assertIn("Nothing opened yet", pg.inner_text("#recent"))
        self.assertFalse(os.path.exists(missing))
        # New on a folder with a config: offered to open it instead.
        folder = self.copy(os.path.join(PLANT, "canworks"))
        pg.click("#start-new")
        pg.fill("#browser-path", folder)
        pg.click("#browser-open")
        pg.wait_for_selector("#modal[open]")
        self.assertIn("already has a canworks.json. Open it instead?", pg.inner_text("#modal-text"))
        self.answer("open")
        pg.wait_for_selector("#editor:not([hidden])")
        self.assertIn("standalone " + folder, pg.inner_text("#mode"))

    def test_folder_browser_and_recent(self):
        pg = self.page
        folder = self.copy(os.path.join(PLANT, "canworks"))
        self.open(folder)
        pg.click("#btn-close")
        pg.wait_for_selector("#start:not([hidden])")
        pg.wait_for_selector("#recent [data-forget]")
        # Go on a missing path drops the old list; a good Go clears the error.
        pg.fill("#browser-path", os.path.join(self.dir, "missing"))
        pg.click("#browser-go")
        pg.wait_for_selector("#banner:has-text('is not a folder')")
        self.assertEqual(pg.inner_text("#browser-list"), "No folder listed")
        pg.fill("#browser-path", self.dir)
        pg.click("#browser-go")
        pg.wait_for_selector("#browser-list li:has-text('plant')")
        self.assertNotIn("is not a folder", pg.inner_text("#banner"))
        # Remove from Recent: the folder stays.
        pg.click('#recent [data-forget="%s"]' % folder)
        pg.wait_for_selector("#recent li:has-text('Nothing opened yet')")
        self.assertTrue(os.path.isfile(os.path.join(folder, "canworks.json")))

    def test_favicon(self):
        pg = self.page
        failed = []
        pg.on("response", lambda r: failed.append(r.url) if r.status >= 400 else None)
        pg.goto(self.server.url)
        pg.wait_for_selector("#start-project")
        pg.wait_for_timeout(300)
        self.assertEqual(failed, [])
        self.assertEqual(pg.evaluate("async () => (await fetch('favicon.svg')).status"), 200)

    @unittest.skipIf(ROOT, "root reads and writes every folder")
    def test_unreadable_folder(self):
        pg = self.page
        folder = self.copy(os.path.join(PLANT, "canworks"))
        os.chmod(folder, 0)
        self.addCleanup(os.chmod, folder, 0o755)
        self.start("#start-standalone", folder)
        pg.wait_for_selector("#banner:has-text('cannot read the folder')")
        self.assertIn("permission denied", pg.inner_text("#banner"))
        self.assertTrue(pg.is_visible("#start"))
        self.assertIn("Nothing opened yet", pg.inner_text("#recent"))
        pg.reload()
        pg.wait_for_selector("#start-project")
        os.chmod(folder, 0o755)
        self.open(folder)

    @unittest.skipIf(ROOT, "root reads and writes every folder")
    def test_read_only_folder_on_save(self):
        pg = self.page
        folder = self.copy(os.path.join(PLANT, "canworks"))
        self.open(folder)
        os.chmod(folder, 0o555)
        self.addCleanup(os.chmod, folder, 0o755)
        pg.fill('#view input[data-path="master.heartbeat_ms"]', "150")
        self.settled()
        pg.click("#btn-save")
        pg.wait_for_selector("#banner:has-text('cannot write to the folder')")
        self.assertIn(folder, pg.inner_text("#banner"))
        self.assertTrue(pg.is_visible("#editor"))


class ProjectFiles(Base):
    def test_move_keeps_the_simulation(self):
        pg = self.page
        folder = self.copy(os.path.join(PLANT, "canworks"))
        project = os.path.join(self.dir, "target")
        os.makedirs(os.path.join(project, "canworks"))
        with open(os.path.join(project, "project.json"), "w") as f:
            json.dump({"meta": {"name": "target"}}, f)
        self.open(folder)
        pg.evaluate("() => { document.querySelector('#menu-project').open = true; }")
        pg.click("#btn-move")
        pg.fill("#modal-extra input", project)
        self.answer("move")
        pg.wait_for_selector("#modal-text:has-text('already has a canworks/ folder')")
        self.answer("replace")
        pg.wait_for_selector("#mode:has-text('project target')")
        target = os.path.join(project, "canworks")
        self.assertEqual(load(os.path.join(target, "simulation.json")), load(os.path.join(folder, "simulation.json")))
        self.assertTrue(os.path.isfile(os.path.join(target, "cell_eds.json")))
        pg.click("#nav-simulation")
        pg.wait_for_selector('[data-sim="file-state"]:has-text("Saved")')

    def test_slave_eds_from_its_description(self):
        pg = self.page
        folder = self.copy(os.path.join(PLANT, "canworks"))
        self.open(folder)
        self.tab("cell")
        pg.wait_for_selector("#view h2:has-text('Bus and slave device')")
        pg.evaluate("() => { document.querySelector('details[data-advanced=\"slave-build\"]').open = true; }")
        desc = load(os.path.join(folder, "cell_eds.json"))
        self.assertEqual(pg.input_value('[data-advanced="slave-build"] input[data-desc="device_name"]'), desc["device_name"])
        self.assertEqual(pg.locator("[data-desc-object]").count(), len(desc["objects"]))
        bound = self.draft("S.config.slave")
        pg.click("[data-generate]")
        pg.wait_for_selector("#modal-buttons button[data-value=keep]")
        text = pg.inner_text("#modal-text")
        self.assertIn("Generated cell.eds", text)
        self.assertNotIn("()", text)
        self.answer("keep")
        pg.wait_for_selector("#banner:has-text('Generated cell.eds')")
        self.assertEqual(self.draft("S.config.slave"), bound)
        count, text = self.problems()
        self.assertEqual(count, "none", text)


class Editing(Base):
    def setUp(self):
        super().setUp()
        self.folder = self.copy(os.path.join(PLANT, "canworks"))

    def test_rename_network_and_node_id_carry_into_the_gateway(self):
        pg = self.page
        self.open(self.folder)
        self.tab("io")
        pg.click('#net-bar button[data-net-action="rename"]')
        pg.wait_for_selector("#modal[open]")
        self.assertEqual(pg.evaluate("() => document.activeElement.dataset.net"), "name")
        pg.fill('#modal-extra input[data-net="name"]', "field")
        pg.press('#modal-extra input[data-net="name"]', "Enter")
        pg.wait_for_selector('#net-bar button[role=tab]:has-text("field")')
        self.assertEqual([r["field"]["network"] for r in self.draft("S.model.top.gateway.routes")], ["field", "field"])
        # Node 6 dio -> 16: the route that writes it follows, also when typed over.
        pg.click('#node-list [data-node="1"]')
        pg.fill('#view input[data-path="nodes[1].node_id"]', "")
        pg.type('#view input[data-path="nodes[1].node_id"]', "16")
        self.assertEqual([r["field"]["node"] for r in self.draft("S.model.top.gateway.routes")], [5, 16])
        count, text = self.problems()
        self.assertEqual(count, "none", text)

    def test_remove_the_upper_network_asks_about_the_gateway(self):
        pg = self.page
        self.open(self.folder)
        self.tab("cell")
        pg.click('#net-bar button[data-net-action="remove"]')
        pg.wait_for_selector("#modal[open]")
        self.assertIn("gateway's upper network: the gateway and its 2 routes are removed too", pg.inner_text("#modal-text"))
        self.answer("remove")
        pg.wait_for_selector("#banner:has-text('Removed network cell and the gateway')")
        self.assertIsNone(self.draft("S.model.top.gateway || null"))
        self.assertTrue(pg.is_hidden("#nav-gateway"))
        # Left to fix: the field entry the routes wrote now needs a location.
        count, text = self.problems(False)
        self.assertEqual(count, "1 problem", text)
        self.assertIn("Node 6 dio, RPDO 1, 0x6411:1", text)
        self.assertNotIn("upper network", text)

    def test_new_network_heading(self):
        pg = self.page
        self.open(self.folder)
        pg.click('#net-bar button[data-net-action="add"]')
        self.answer("canopen")
        pg.wait_for_selector("#view h2:has-text('Bus and master: network 5')")
        self.assertNotIn("network network", pg.inner_text("#view h2"))
        count, text = self.problems(False)
        self.assertNotIn('network ""', text)

    def test_remove_pdo_and_startup_sdo_twice(self):
        pg = self.page
        # PDOs numbered by their place.
        path = os.path.join(self.folder, "canworks.json")
        cfg = load(path)
        for p in cfg["networks"][3]["nodes"][0]["tx_pdos"]:
            p.pop("number")
        with open(path, "w") as f:
            json.dump(cfg, f, indent=2)
        self.open(self.folder)
        self.tab("host")
        pg.click('#node-list [data-node="0"]')
        pg.evaluate("() => document.querySelectorAll('details.section').forEach((d) => { d.open = true; })")
        # Emptying TPDO 1 entry by entry drops it; the PDOs after it keep their numbers.
        for _ in range(2):
            pg.click('tr[data-path="nodes[0].tx_pdos[0].entries[0]"] button[aria-label^="Remove"]')
        self.assertEqual([(p.get("number"), len(p["entries"])) for p in self.draft("S.config.nodes[0].tx_pdos")],
                         [(2, 2), (3, 1), (4, 1)])
        # Remove PDO in one step, and Undo brings it back.
        pg.click('[data-remove-pdo="nodes[0].tx_pdos[2]"]')
        self.assertEqual([p["number"] for p in self.draft("S.config.nodes[0].tx_pdos")], [2, 3])
        pg.click("#banner [data-undo]")
        self.assertEqual([p["number"] for p in self.draft("S.config.nodes[0].tx_pdos")], [2, 3, 4])
        count, text = self.problems()
        self.assertEqual(count, "none", text)
        # The same startup SDO object twice is marked.
        self.tab("motion")
        pg.click('#node-list [data-node="0"]')
        pg.evaluate("() => document.querySelectorAll('details.section').forEach((d) => { d.open = true; })")
        pg.fill('input[aria-label="SDO index"]', "0x6065")
        pg.fill('input[aria-label="SDO subindex"]', "0")
        pg.click("button:has-text('Add write')")
        pg.wait_for_selector("#banner:has-text('already written at startup')")
        self.assertEqual(pg.locator("[data-twice]").count(), 2)

    def test_clearing_a_receive_timeout_is_one_undo_step(self):
        pg = self.page
        self.open(self.folder)
        self.tab("io")
        pg.click('#node-list [data-node="0"]')
        pg.evaluate("() => document.querySelectorAll('details.section').forEach((d) => { d.open = true; })")
        pg.select_option('select[data-path="nodes[0].tx_pdos[0].on_timeout"]', "zero")
        pg.fill('input[data-path="nodes[0].tx_pdos[0].timeout_location"]', "%IX90.0")
        before = self.draft("S.config.nodes[0].tx_pdos[0]")
        pg.wait_for_timeout(1100)
        pg.fill('input[data-path="nodes[0].tx_pdos[0].timeout_ms"]', "")
        pg.press('input[data-path="nodes[0].tx_pdos[0].timeout_ms"]', "Tab")
        after = self.draft("S.config.nodes[0].tx_pdos[0]")
        self.assertNotIn("on_timeout", after)
        self.assertNotIn("timeout_location", after)
        pg.keyboard.press("Control+z")
        self.assertEqual(self.draft("S.config.nodes[0].tx_pdos[0]"), before)

    def test_typed_back_value_is_clean(self):
        pg = self.page
        self.open(self.folder)
        self.tab("io")
        path = '#view input[data-path="master.heartbeat_ms"]'
        old = pg.input_value(path)
        pg.fill(path, "999")
        pg.wait_for_selector("#btn-save:has-text('Save')")
        self.assertFalse(pg.inner_text("#btn-save") == "Saved")
        pg.fill(path, old)
        pg.wait_for_selector("#btn-save:text-is('Saved')")
        self.assertTrue(pg.is_disabled("#btn-save"))

    def test_declarations_wording(self):
        pg = self.page
        self.open(self.folder)
        pg.click('.nav-item[data-view="declarations"]')
        pg.wait_for_selector("#view h2:has-text('Variable declarations')")
        text = pg.inner_text("#view")
        self.assertIn("into the VAR block of the program", text)
        self.assertNotIn("in the global list", text)


class J1939Dbc(Base):
    def test_second_dbc_asks(self):
        pg = self.page
        folder = self.copy(J1939, "j1939")
        self.open(folder)
        pg.set_input_files('input[data-j1939="dbc-input"]', PUMP_DBC)
        pg.wait_for_selector("#modal[open]")
        self.assertIn("come from machine.dbc", pg.inner_text("#modal-text"))
        self.answer("cancel")
        self.assertEqual(self.draft("S.config.j1939.dbc"), "machine.dbc")
        pg.set_input_files('input[data-j1939="dbc-input"]', PUMP_DBC)
        self.answer("replace")
        pg.wait_for_selector("#modal-text:has-text('pump.dbc')")
        self.answer("add")
        pg.wait_for_selector("#banner:has-text('from pump.dbc')")
        self.assertEqual(self.draft("S.config.j1939.dbc"), "pump.dbc")
