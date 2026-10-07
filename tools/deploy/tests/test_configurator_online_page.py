"""The configurator's online view and scan page in a real browser, against a
fake plugin (add-online-diagnostics tasks 3.2-3.5). Needs Playwright, like
test_configurator_page.py."""

import hashlib
import json
import os
import shutil
import threading
import unittest

from openplc_canopen_deploy import diag
from openplc_canopen_deploy.configurator import server as srv

from .fake_diag import SLAVE_NETWORK, TOKEN, TWO_NETWORKS, FakePlugin, closed_port, slave_status
from .helpers import PINGPONG, REPO, tmpdir
from .test_configurator_page import FIXTURE, REQUIRED, RTD, load, sync_playwright


@unittest.skipIf(sync_playwright is None and not REQUIRED, "Playwright for Python is not installed")
class OnlineBase(unittest.TestCase):
    """A browser on the configurator with the ping-pong config in a copy of
    the editor fixture project; the tests are in subclasses."""

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
        os.environ["OPENPLC_CANOPEN_CONFIG_DIR"] = self.cfg_dir
        self.addCleanup(os.environ.pop, "OPENPLC_CANOPEN_CONFIG_DIR", None)
        self.project = os.path.join(self.dir, "rtd-monitor")
        shutil.copytree(FIXTURE, self.project)
        # The ping-pong config, moved off the fixture project's EtherCAT addresses.
        cfg = load(os.path.join(PINGPONG, "canopen_config.json"))
        cfg["nodes"][0]["tx_pdos"][0]["entries"][0]["iec_location"] = "%ID300"
        cfg["nodes"][0]["rx_pdos"][0]["entries"][0]["iec_location"] = "%QD300"
        cfg["nodes"][0]["status_location"] = "%IX300.0"
        self.cfg = cfg
        os.makedirs(os.path.join(self.project, "canopen"))
        shutil.copy(os.path.join(PINGPONG, "cpp-slave.eds"), os.path.join(self.project, "canopen"))
        self.write_config()
        self.server = srv.Server()
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.context = self.browser.new_context()
        self.context.grant_permissions(["clipboard-read", "clipboard-write"])
        self.addCleanup(self.context.close)
        self.page = self.context.new_page()
        self.page.set_default_timeout(10000)
        self.errors = []
        self.page.on("pageerror", lambda e: self.errors.append(str(e)))

    def tearDown(self):
        self.assertEqual(self.errors, [])

    @property
    def config_path(self):
        return os.path.join(self.project, "canopen", "canopen.json")

    def write_config(self, diagnostics=None):
        cfg = json.loads(json.dumps(self.cfg))
        if diagnostics:
            cfg["master"]["diagnostics"] = diagnostics
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)

    def remember(self, host, token=TOKEN, library=None):
        os.makedirs(self.cfg_dir, exist_ok=True)
        data = {"projects": {self.project: {"host": host, "token": token}}}
        if library:
            data["eds_library"] = library
        with open(os.path.join(self.cfg_dir, "online.json"), "w") as f:
            json.dump(data, f)

    def open(self):
        self.page.goto(self.server.url)
        self.page.click("#start-project")
        self.page.fill("#browser-path", self.project)
        self.page.click("#browser-open")
        self.page.wait_for_selector("#editor:not([hidden])")

    def online(self, fake, allow=False, **diag_fields):
        self.write_config(dict({"token_sha256": diag.hash_token(TOKEN), "allow_changes": allow}, **diag_fields))
        self.remember(fake.runtime if fake else "127.0.0.1:%d" % closed_port())
        self.open()
        self.page.click('button[data-view="online"]')



class OnlinePage(OnlineBase):
    # -- settings -----------------------------------------------------------
    def test_enable_online_access(self):
        pg = self.page
        self.open()
        pg.check('input[data-online="enable"]')
        pg.wait_for_selector('input[data-path="master.diagnostics.port"]')
        self.assertIn("This PC has the token", pg.inner_text('[data-online="token-state"]'))
        pg.check('input[data-path="master.diagnostics.allow_changes"]')
        pg.click('#modal button[data-value="allow"]')
        pg.wait_for_selector("text=Changes are allowed")
        self.page.fill('input[data-online="host"]', "plc.local")
        self.page.press('input[data-online="host"]', "Tab")
        pg.wait_for_function("() => document.body.dataset.checking === '0'")
        pg.click("#btn-save")
        pg.wait_for_selector("#banner:has-text('Saved')")
        saved = load(self.config_path)["master"]["diagnostics"]
        settings = load(os.path.join(self.cfg_dir, "online.json"))["projects"][self.project]
        self.assertEqual(saved, {"token_sha256": hashlib.sha256(settings["token"].encode()).hexdigest(),
                                 "allow_changes": True})
        self.assertEqual(settings["host"], "plc.local")
        with open(self.config_path, encoding="utf-8") as f:
            self.assertNotIn(settings["token"], f.read())
        pg.click("text=Copy token")
        self.assertEqual(pg.evaluate("navigator.clipboard.readText()"), settings["token"])

    def test_token_from_another_pc(self):
        pg = self.page
        self.write_config({"token_sha256": diag.hash_token(TOKEN)})
        self.open()
        self.assertIn("no token", pg.inner_text('[data-online="token-state"]'))
        pg.click("text=Enter token…")
        pg.fill("#modal-extra input", "wrong")
        pg.click('#modal button[data-value="set"]')
        pg.wait_for_selector("#banner:has-text('does not match')")
        pg.click("text=Enter token…")
        pg.fill("#modal-extra input", TOKEN)
        pg.click('#modal button[data-value="set"]')
        pg.wait_for_selector('[data-online="token-state"]:has-text("This PC has the token")')

    def test_connect_says_what_is_missing(self):
        # Connect used to redraw the same form without a word when the host
        # was left empty (the placeholder looked like a value) or no token was
        # on this PC.
        pg = self.page
        with FakePlugin() as fp:
            self.write_config({"token_sha256": diag.hash_token(TOKEN)})
            self.open()
            pg.click('button[data-view="online"]')
            pg.click('button[data-online="connect"]')
            pg.wait_for_selector('[data-online="connect-msg"]:has-text("Enter the runtime\'s host")')
            pg.fill('input[data-online="host"]', fp.runtime)
            pg.click('button[data-online="connect"]')
            pg.wait_for_selector("#modal-extra input")
            pg.click('#modal button[data-value="cancel"]')
            pg.wait_for_selector('[data-online="connect-msg"]:has-text("Enter the access token")')
            pg.click('button[data-online="connect"]')
            pg.fill("#modal-extra input", TOKEN)
            pg.click('#modal button[data-value="set"]')
            pg.wait_for_selector("text=Connected to")

    # -- online view --------------------------------------------------------
    def test_online_view_read_only(self):
        pg = self.page
        with FakePlugin() as fp:
            self.online(fp)
            pg.wait_for_selector("text=Connected to")
            self.assertIn("read-only", pg.inner_text("#online-conn"))
            # The runtime reports another config fingerprint.
            pg.wait_for_selector('[data-online="fingerprint"]')
            row = pg.inner_text('tr[data-online-node="23"]')
            self.assertIn("error J: the configuration download failed", row)
            self.assertIn("(retrying)", row)
            self.assertIn("0x4210 temperature (3)", pg.inner_text('tr[data-online-node="2"]'))
            self.assertIn("(uptime) = 42", pg.inner_text('tr[data-online-node="2"]'))
            self.assertIn("error-active", pg.inner_text('[data-online="bus"]'))
            self.assertEqual(pg.inner_text('[data-online="sync"]'),
                             "PLC cycle, every 2 cycles, 500 sent, interval 10012 µs (min 9870, max 10240), "
                             "skipped 0, late PDOs 3")
            pg.click('tr[data-online-node="2"]')
            pg.wait_for_selector('[data-online="emcy"] table')
            self.assertIn("temperature", pg.inner_text('[data-online="emcy"]'))
            # SDO read through the EDS picker: 0x1018 sub 4 decodes as UNSIGNED32.
            pg.select_option('select[data-online="object"]', "0x1018:4")
            self.assertEqual(pg.input_value('select[data-online="type"]'), "UNSIGNED32")
            pg.click('button[data-online="read"]')
            pg.wait_for_selector('[data-online="sdo-result"]:has-text("305419896 (0x12345678)")')
            pg.fill('input[data-online="index"]', "0x6000")
            pg.fill('input[data-online="subindex"]', "1")
            pg.click('button[data-online="read"]')
            pg.wait_for_selector('[data-online="sdo-result"]:has-text("object does not exist")')
            self.assertTrue(pg.is_disabled('button[data-online="write"]'))
            self.assertTrue(pg.is_disabled('button[data-nmt="stop"]'))
            self.assertIn("not allowed", pg.inner_text('[data-online="no-changes"]'))
            # Leaving the view closes the connection.
            pg.click('button[data-view="bus"]')
            pg.wait_for_function("() => true")
            for _ in range(50):
                if not self.server.connection.connected:
                    break
                pg.wait_for_timeout(50)
            self.assertFalse(self.server.connection.connected)

    def test_same_config(self):
        pg = self.page
        with FakePlugin() as fp:
            self.write_config({"token_sha256": diag.hash_token(TOKEN)})
            with open(self.config_path, "rb") as f:
                fp.status["config_sha256"] = hashlib.sha256(f.read()).hexdigest()
            self.remember(fp.runtime)
            self.open()
            pg.click('button[data-view="online"]')
            pg.wait_for_selector("text=Connected to")
            pg.wait_for_timeout(700)
            self.assertEqual(pg.locator('[data-online="fingerprint"]').count(), 0)

    def test_online_changes(self):
        pg = self.page
        with FakePlugin(allow_changes=True) as fp:
            self.online(fp, allow=True)
            pg.wait_for_selector("text=changes allowed")
            pg.click('tr[data-online-node="2"]')
            pg.wait_for_selector('button[data-nmt="stop"]:not([disabled])')
            pg.click('button[data-nmt="stop"]')
            pg.click('#modal button[data-value="go"]')
            pg.wait_for_selector('tr[data-online-node="2"]:has-text("held STOPPED by operator")')
            pg.fill('input[data-online="index"]', "0x2000")
            pg.fill('input[data-online="subindex"]', "0")
            pg.select_option('select[data-online="type"]', "UNSIGNED32")
            pg.fill('input[data-online="value"]', "30")
            pg.click('button[data-online="write"]')
            pg.wait_for_selector('[data-online="sdo-result"]:has-text("Written")')
            self.assertEqual(fp.objects[(2, 0x2000, 0)], (30).to_bytes(4, "little"))
            # A plugin-configured object asks first.
            pg.fill('input[data-online="index"]', "0x1017")
            pg.select_option('select[data-online="type"]', "UNSIGNED16")
            pg.fill('input[data-online="value"]', "70000")
            pg.click('button[data-online="write"]')
            self.assertIn("configures 0x1017 itself", pg.inner_text("#modal-text"))
            pg.click('#modal button[data-value="write"]')
            pg.wait_for_selector('[data-online="sdo-result"]:has-text("out of range for UNSIGNED16")')

    def test_connection_error_shown(self):
        pg = self.page
        self.online(None)
        pg.wait_for_selector("#online-conn:has-text('Not connected (port closed)')")

    # -- scan ---------------------------------------------------------------
    def test_scan_and_add_node(self):
        pg = self.page
        lib = os.path.join(self.dir, "eds-library")
        os.makedirs(lib)
        with open(os.path.join(RTD, "rtd8.eds"), encoding="latin-1") as f:
            text = f.read()
        with open(os.path.join(lib, "rtd.eds"), "w", encoding="latin-1") as f:
            f.write(text.replace("VendorNumber=0x00F0F0F0", "VendorNumber=0xAB").replace("ProductNumber=0x00000404", "ProductNumber=0x1234")
                    .replace("RevisionNumber=0x00010003", "RevisionNumber=0x00010002"))
        with FakePlugin() as fp:
            fp.scan_nodes[0].update(product_code=5, match="configured, different device",
                                    differs="product code 0x00000005, expected 0x00000000")
            self.write_config({"token_sha256": diag.hash_token(TOKEN)})
            self.remember(fp.runtime, library=lib)
            self.open()
            pg.click('button[data-view="scan"]')
            self.assertEqual(pg.input_value('input[data-online="library"]'), lib)
            pg.wait_for_selector("text=No scan has run")
            pg.click('button[data-online="scan"]')
            pg.wait_for_selector('tr[data-scan-node="40"]')
            self.assertIn("openplc-canopen test devices", pg.inner_text('tr[data-scan-node="40"]'))
            self.assertIn("RTD sensor", pg.inner_text('tr[data-scan-node="40"]'))
            compare = pg.inner_text('tr[data-scan-node="2"] [data-online="compare"]')
            self.assertIn("0x00000005", compare)
            self.assertEqual(pg.locator('tr[data-scan-node="2"] tr.bad').count(), 1)
            self.assertIn("Pick EDS file", pg.inner_text('tr[data-scan-node="41"]'))
            pg.check('tr[data-scan-node="40"] input[type="checkbox"]')
            pg.click('tr[data-scan-node="40"] button[data-online="add-node"]')
            pg.wait_for_selector('tr[data-scan-node="40"]:has-text("added")')
            self.assertFalse(os.path.exists(os.path.join(self.project, "canopen", "rtd.eds")))
            self.assertEqual(len(load(self.config_path)["nodes"]), 1)
            pg.wait_for_function("() => document.body.dataset.checking === '0'")
            pg.click("#btn-save")
            pg.wait_for_selector("#banner:has-text('Saved')")
        nodes = load(self.config_path)["nodes"]
        self.assertEqual(nodes[1], {"node_id": 40, "name": "rtd_sensor", "eds": "rtd.eds",
                                    "revision_number": 0x00010002, "serial_number": 99})
        self.assertTrue(os.path.isfile(os.path.join(self.project, "canopen", "rtd.eds")))

    # -- LSS ----------------------------------------------------------------
    def test_lss_commission_new_device(self):
        pg = self.page
        with FakePlugin(allow_changes=True, scan_polls=1) as fp:
            fp.lss_devices[(0x360, 0, 0, 0x43)] = 255
            self.online(fp, allow=True)
            pg.wait_for_selector('[data-online="lss"] button[data-online="lss-find"]:not([disabled])')
            pg.click('button[data-online="lss-find"]')
            row = 'tr[data-lss-device="66"]'
            pg.wait_for_selector(row)
            self.assertIn("0x00000042", pg.inner_text(row))
            self.assertIn("none", pg.inner_text(row))
            self.assertIn("cpp-slave.eds", pg.inner_text(row))
            pg.click(row + ' button[data-online="lss-set-id"]')
            self.assertEqual(pg.input_value('#modal input[data-online="lss-node-id"]'), "3")  # lowest free
            self.assertFalse(pg.is_checked('#modal input[data-online="lss-store"]'))
            pg.fill('#modal input[data-online="lss-node-id"]', "40")
            pg.check('#modal input[data-online="lss-store"]')
            pg.click('#modal button[data-value="set"]')
            pg.wait_for_selector('#modal button[data-value="add"]')
            req = [r for r in fp.requests if r["op"] == "lss_set_id"][-1]
            self.assertEqual((req["node"], req["store"], req["serial_number"]), (40, True, 0x42))
            pg.click('#modal button[data-value="add"]')
            pg.wait_for_selector('#banner:has-text("Added node 40")')
            self.assertEqual(len(load(self.config_path)["nodes"]), 1)  # unsaved
            pg.wait_for_function("() => document.body.dataset.checking === '0'")
            pg.click("#btn-save")
            pg.wait_for_selector("#banner:has-text('Saved')")
            node = load(self.config_path)["nodes"][1]
            self.assertEqual((node["node_id"], node["eds"], node["serial_number"], node["lss"]),
                             (40, "cpp-slave.eds", 0x42, {"assign": True}))
            # The next device: the store box is unticked again, and 3 is still the lowest free ID.
            pg.click('button[data-view="online"]')
            pg.wait_for_selector('button[data-online="lss-find"]:not([disabled])')
            pg.click('button[data-online="lss-find"]')
            pg.wait_for_selector('tr[data-lss-device="67"]')
            pg.click('tr[data-lss-device="67"] button[data-online="lss-set-id"]')
            self.assertFalse(pg.is_checked('#modal input[data-online="lss-store"]'))
            pg.click('#modal button[data-value="cancel"]')
            # Set bit rate: says it applies after a power cycle; stores only when ticked.
            pg.click('tr[data-lss-device="67"] button[data-online="lss-set-bitrate"]')
            self.assertIn("next power cycle", pg.inner_text("#modal-text"))
            self.assertFalse(pg.is_checked('#modal input[data-online="lss-store"]'))
            pg.select_option('#modal select[data-online="lss-bitrate"]', "250")
            pg.click('#modal button[data-value="set"]')
            pg.wait_for_selector('#banner:has-text("Bit rate 250 kbit/s set")')
            req = [r for r in fp.requests if r["op"] == "lss_set_bitrate"][-1]
            self.assertEqual((req["bitrate_kbit"], req["store"]), (250, False))

    def test_lss_read_only(self):
        pg = self.page
        with FakePlugin() as fp:
            self.online(fp)
            pg.wait_for_selector('[data-online="lss-no-changes"]')
            self.assertTrue(pg.is_disabled('button[data-online="lss-find"]'))
        self.assertFalse(any(r["op"].startswith("lss_") for r in fp.requests))

    def test_scan_use_for_node(self):
        pg = self.page
        with FakePlugin() as fp:
            fp.scan_nodes.append({"node_id": 5, "vendor_id": 0x360, "product_code": 0, "revision_number": 0,
                                  "serial_number": 0x5678, "match": "not configured"})
            self.write_config({"token_sha256": diag.hash_token(TOKEN)})
            self.remember(fp.runtime)
            self.open()
            pg.click('button[data-view="scan"]')
            pg.click('button[data-online="scan"]')
            pg.wait_for_selector('tr[data-scan-node="5"] select[data-online="use-for"]')
            self.assertEqual(pg.locator('tr[data-scan-node="41"] select[data-online="use-for"]').count(), 0)
            pg.select_option('tr[data-scan-node="5"] select[data-online="use-for"]', "0")
            pg.wait_for_selector('#banner:has-text("becomes node 2 at the next PLC start")')
            self.assertNotIn("lss", load(self.config_path)["nodes"][0])  # unsaved
            pg.wait_for_function("() => document.body.dataset.checking === '0'")
            pg.click("#btn-save")
            pg.wait_for_selector("#banner:has-text('Saved')")
        node = load(self.config_path)["nodes"][0]
        self.assertEqual((node["serial_number"], node["lss"]), (0x5678, {"assign": True}))


class SlaveOnlinePage(OnlineBase):
    """The online view on a slave network and a gateway's upper network
    (add-canopen-slave tasks 4.2 and 6.8)."""

    def use(self, name):
        folder = os.path.join(REPO, "config", name)
        self.cfg = load(os.path.join(folder, "canopen_config.json"))
        for f in os.listdir(folder):
            if f.endswith(".eds"):
                shutil.copy(os.path.join(folder, f), os.path.join(self.project, "canopen"))

    def write_config(self, diagnostics=None):
        if self.cfg.get("schema_version") != 2:
            return super().write_config(diagnostics)
        cfg = json.loads(json.dumps(self.cfg))
        if diagnostics:
            cfg["diagnostics"] = diagnostics
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)

    def test_slave_network(self):
        pg = self.page
        self.use("slave")
        with FakePlugin(networks=[SLAVE_NETWORK], allow_changes=True) as fp:
            self.online(fp, allow=True)
            pg.wait_for_selector('[data-online="slave-state"]:has-text("OPERATIONAL")')
            self.assertEqual(pg.inner_text('[data-online="slave-node"]'), "node 10")
            self.assertEqual(pg.inner_text('[data-online="slave-comm"]'), "TRUE")
            self.assertEqual(pg.inner_text('[data-online="slave-sync"]'), "42")
            self.assertEqual(pg.inner_text('[data-online="slave-emcy"]'), "0x4210 temperature, error register 0x09")
            self.assertIn("need a master network", pg.inner_text('[data-online="slave-note"]'))
            # The mappings in force, with the objects the config binds.
            tpdo = pg.inner_text('tr[data-slave-pdo="tx1"]')
            self.assertIn("0x18A", tpdo)
            self.assertIn("0x2100:2 (16 bits) %QW301", tpdo)
            self.assertIn("0x28A (off)", pg.inner_text('tr[data-slave-pdo="tx2"]'))
            rpdo = pg.inner_text('tr[data-slave-pdo="rx1"]')
            self.assertIn("0x2000:1 (16 bits) %IW300 speed_setpoint", rpdo)
            self.assertIn("0x2002:1 (1 bit) %IX300.0", rpdo)
            # No master tools: node list, LSS, NMT, parameters.
            self.assertEqual(pg.locator("table.online-nodes").count(), 0)
            self.assertEqual(pg.locator('[data-online="lss"]').count(), 0)
            self.assertEqual(pg.locator('[data-online="gateway"]').count(), 0)
            pg.wait_for_selector('#online-node h2:has-text("Node 10 this PLC")')
            self.assertEqual(pg.locator("button[data-nmt]").count(), 0)
            self.assertEqual(pg.locator('button[data-online-tab="params"]').count(), 0)
            # SDO on its own dictionary; a bound object asks first.
            pg.select_option('select[data-online="object"]', "0x2000:1")
            pg.click('button[data-online="read"]')
            pg.wait_for_selector('[data-online="sdo-result"]:has-text("5")')
            pg.fill('input[data-online="value"]', "9")
            pg.click('button[data-online="write"]')
            self.assertIn("bound to %IW300 speed_setpoint", pg.inner_text("#modal-text"))
            pg.click('#modal button[data-value="write"]')
            pg.wait_for_selector('[data-online="sdo-result"]:has-text("Written")')
            self.assertEqual(fp.objects[(10, 0x2000, 1)], b"\x09\x00")
            # The object dictionary of the slave's EDS, bound objects marked.
            pg.click('button[data-online-tab="od"]')
            pg.fill('input[data-online="od-filter"]', "0x2000")
            row = 'tr[data-od-key="%d:1"]' % 0x2000
            pg.wait_for_selector(row, state="visible")
            self.assertIn("%IW300 speed_setpoint", pg.inner_text(row))
            self.assertTrue(pg.is_disabled(row + ' button[data-online="od-st"]'))
            pg.click(row + ' button[data-online="od-read"]')
            pg.wait_for_selector(row + ' [data-online="od-shown"]:has-text("9")')
            # Scanning needs a master network.
            pg.click('button[data-view="scan"]')
            pg.wait_for_selector('[data-online="scan-slave"]')
            self.assertEqual(pg.locator('button[data-online="scan"]').count(), 0)
        self.assertFalse([r for r in fp.requests if r["op"] not in ("status", "sdo_read", "sdo_write")])

    def test_gateway_upper_network(self):
        pg = self.page
        self.use("gateway")
        nets = [dict(TWO_NETWORKS[0], name="field"), dict(SLAVE_NETWORK, name="upper", node_id=20)]
        with FakePlugin(networks=nets) as fp:
            fp.network("upper").status.update(slave_status(gateway=True), network="upper")
            self.online(fp)
            # The field network first, as before.
            pg.wait_for_selector('tr[data-online-node="2"]')
            pg.select_option('select[data-online="network"]', "upper")
            pg.wait_for_selector('[data-online="gateway"]')
            self.assertEqual(pg.inner_text('[data-online="gw-routes"]'), "2")
            self.assertIn("missing", pg.inner_text('[data-online="gw-upper"]'))
            self.assertEqual(pg.inner_text('[data-online="gw-errors"]'), "1 active")
            self.assertIn("0x2101:1 (16 bits) route pong", pg.inner_text('tr[data-slave-pdo="tx1"]'))
            self.assertIn("0x2100:1 (16 bits) %QX300.0", pg.inner_text('tr[data-slave-pdo="tx1"]'))
            # Back on the field network the node list returns.
            pg.select_option('select[data-online="network"]', "field")
            pg.wait_for_selector('tr[data-online-node="2"]')
            self.assertEqual(pg.locator('[data-online="gateway"]').count(), 0)


if __name__ == "__main__":
    unittest.main()
