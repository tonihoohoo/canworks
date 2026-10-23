"""The Modbus bridge page in a real browser (spec canopen-configurator
"Bridge settings panel", "Register map preview and export", "Export for
another PLC", "Reachability warnings for other PLCs"; modbus-connections):
the example as a plain bridge project, packed, a live list added and
suggested, the map filtered, Connections with their Downloads (the files
canworks-deploy writes), out-of-date rows, the writers following the
connections, a truST connection with the PLC link offer and the loopback
error, the plc_cycle problem, and an OpenPLC connection added as one undo
step. Needs Playwright, like test_configurator_page.py."""

import json
import os
import shutil
import zipfile

from canworks import editorproject, modbusmap, nodered, plcopen_targets
from canworks.configurator import server as srv

from .helpers import REPO, add_connection, tree_view
from .test_configurator_layout import FIT_CHECK, audit
from .test_configurator_online_page import OnlineBase
from .test_configurator_page import load

EXAMPLE = os.path.join(REPO, "examples", "modbus-bridge")


class BridgePage(OnlineBase):
    def setUp(self):
        super().setUp()
        # The example as a plain bridge project: the bridge settings a switch
        # to the bridge writes, every location packed.
        cfg = load(os.path.join(EXAMPLE, "canworks.json"))
        del cfg["bridge"]
        self.cfg = srv.Session().switch_target(cfg, "bridge", openplc=False)["config"]
        for name in ("rtd8.eds", "dio16.eds"):
            shutil.copy(os.path.join(EXAMPLE, name), os.path.join(self.project, "canworks"))
        self.write_config()

    def write_config(self, diagnostics=None):
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(self.cfg, f, indent=2)

    def checked(self):
        self.page.wait_for_function("() => document.body.dataset.checking === '0'")

    def to_bridge(self):
        self.open()
        tree_view(self.page, "bus")
        self.checked()

    def open_settings(self, i):
        """Opens connection `i`'s Settings (adding one opens its own)."""
        if not self.page.evaluate("i => document.querySelector(`[data-conn-settings-of=\"${i}\"]`).open", i):
            self.page.click('[data-conn-settings-of="%d"] > summary' % i)

    def download(self, i):
        """Download on connection `i`: the download."""
        with self.page.expect_download() as dl:
            self.page.click('[data-conn-download="%d"]' % i)
        return dl.value

    def test_bridge_page_and_connections(self):
        pg = self.page
        self.to_bridge()
        tree_view(pg, "bridge")
        pg.wait_for_selector("h2:has-text('Modbus bridge')")
        # Connections first, empty, saying who connects here.
        self.assertIn("connect here", pg.inner_text("[data-connections-empty]"))
        legends = pg.eval_on_selector_all("#view fieldset > legend", "ls => ls.map(l => l.textContent)")
        self.assertEqual(legends[0], "Connections")
        # Without connections, Writers is a field: empty is nobody, and the hint
        # names how to let every host write.
        self.assertEqual(pg.evaluate("() => S.model.top.bridge.writers"), [])
        self.assertEqual(pg.text_content("#problem-list").strip(), "No problems.")
        self.assertEqual(pg.get_attribute('input[data-path="bridge.writers"]', "placeholder"), "nobody writes")
        self.assertIn("0.0.0.0/0, ::/0", pg.inner_text('label:has(input[data-path="bridge.writers"])'))
        pg.fill('input[data-path="bridge.writers"]', "0.0.0.0/0, ::/0")
        self.assertEqual(pg.evaluate("() => S.model.top.bridge.writers"), ["0.0.0.0/0", "::/0"])
        pg.fill('input[data-path="bridge.writers"]', "")
        self.assertEqual(pg.evaluate("() => S.model.top.bridge.writers"), [])  # empty: nobody, never missing
        pg.fill('input[data-path="bridge.max_clients_per_address"]', "2")
        self.checked()
        self.assertEqual(pg.text_content("#problem-list").strip(), "No problems.")
        self.assertEqual(pg.input_value('input[data-path="bridge.listen"]'), "0.0.0.0")
        self.assertEqual(pg.input_value('input[data-bridge="port"]'), "502")
        pg.wait_for_selector('#bridge-map tr[data-bridge-row="rtd.0x7130:1"]')
        self.assertIn("Input registers", pg.inner_text('tr[data-bridge-row="rtd.0x7130:1"]'))
        # Packed: the rtd's four words are input registers 0-3, the dio's outputs from holding register 0.
        self.assertIn("%IW6", pg.inner_text('tr[data-bridge-row="rtd.0x7130:4"]'))
        self.assertIn("%QB0", pg.inner_text('tr[data-bridge-row="dio.0x6200:1"]'))

        # A live list for the network "field", placed by Suggest after the packed data.
        pg.click('button[data-bridge="add-live-list"]')
        pg.wait_for_selector('tr[data-live-list="0"]')
        self.assertEqual(pg.input_value('select[data-path="bridge.live_lists[0].network"]'), "field")
        pg.fill('input[data-path="bridge.live_lists[0].location"]', "")
        pg.click('button[data-bridge-suggest="live_list:0"]')
        pg.wait_for_function("() => document.querySelector('input[data-path=\"bridge.live_lists[0].location\"]').value === '%IB24'")
        self.checked()
        row = pg.wait_for_selector('#bridge-map tr[data-bridge-row="bridge.live_list.field"]')
        self.assertIn("12..19", row.inner_text())
        self.assertIn("8 registers", row.inner_text())
        self.assertEqual(pg.text_content("#problem-list").strip(), "No problems.")

        # The filter, and the suggested client channels.
        pg.fill('input[data-bridge="filter"]', "live")
        self.assertEqual(pg.locator("#bridge-map tr[data-bridge-row]").count(), 1)
        pg.fill('input[data-bridge="filter"]', "")
        self.assertIn("read input registers", pg.inner_text('[data-bridge="channels"]'))
        self.assertIn("write holding registers", pg.inner_text('[data-bridge="channels"]'))
        # No export buttons of its own, and none in Export ▾ for the program.
        self.assertTrue(pg.is_visible("[data-bridge-exports-hint]"))
        pg.click("#menu-export > summary")
        shown = pg.eval_on_selector_all("#menu-export button.item", "bs => bs.filter(b => !b.hidden).map(b => b.textContent)")
        self.assertEqual(shown, ["All DCFs", "This node's DCF", "DBC", "Documentation"])
        pg.click("#menu-export > summary")

        # Add connection → HMI, SCADA or script: Line HMI, not writing. The
        # writers follow the connections: nobody, shown as Who may write.
        add_connection(pg, "hmi", name="Line HMI", address="192.168.10.20", writes=False)
        pg.wait_for_selector('[data-connection="Line HMI"]')
        self.assertIn("Not downloaded yet", pg.inner_text('[data-connection="Line HMI"]'))
        self.assertEqual(pg.evaluate("() => S.model.top.bridge.writers"), [])
        self.assertEqual(pg.inner_text("[data-bridge-who]"), "nobody")
        self.assertEqual(pg.locator('input[data-path="bridge.writers"]').count(), 0)
        pg.click("#btn-save")
        pg.wait_for_selector("#banner:has-text('Saved')")
        saved = load(self.config_path)
        self.assertEqual(saved["schema_version"], 2)
        self.assertEqual(saved["bridge"], {"listen": "0.0.0.0:502", "writers": [], "max_clients_per_address": 2,
                                           "live_lists": [{"network": "field", "location": "%IB24"}],
                                           "connections": [{"kind": "hmi", "name": "Line HMI", "address": "192.168.10.20",
                                                            "writes": False, "format": "csv"}]})

        # Its format ST: Download gives the file canworks-deploy --export-modbus-map map.st writes,
        # and the row is in sync.
        self.open_settings(0)
        pg.select_option('select[data-path="bridge.connections[0].format"]', "st")
        got = self.download(0)
        self.assertEqual(got.suggested_filename, "rtd-monitor-Line-HMI.st")
        with open(got.path(), encoding="utf-8") as f:
            self.assertEqual(f.read(), modbusmap.to_st(saved, modbusmap.register_map(saved)))
        pg.wait_for_selector("#banner:has-text('Downloaded rtd-monitor-Line-HMI.st')")
        self.assertEqual(pg.evaluate("() => S.model.top.bridge.connections[0].map_hash"),
                         "0x%08x" % modbusmap.map_hash(saved))
        pg.wait_for_selector('[data-connection="Line HMI"] [data-conn-state="up_to_date"]')

        # A value moved: the row is out of date, Problems warns, Download again clears both.
        pg.evaluate("() => { S.model.top.bridge.live_lists[0].location = '%IB40'; changed(true); }")
        tree_view(pg, "bridge")
        pg.wait_for_selector('[data-connection="Line HMI"] [data-conn-state="out_of_date"]')
        # The check after the change lists the warning.
        pg.wait_for_function("() => document.querySelector('#problem-list').textContent"
                             ".includes('Line HMI: its downloaded file was made for another map')")
        self.assertEqual(pg.inner_text('[data-conn-download="0"]'), "Download again")
        with pg.expect_download():
            pg.click('#problem-list [data-problem-fix="download"]')
        pg.wait_for_selector('[data-connection="Line HMI"] [data-conn-state="up_to_date"]')
        self.checked()
        self.assertEqual(pg.text_content("#problem-list").strip(), "No problems.")

        # Node-RED, writing: the writers follow in one undo step, and its
        # Download is the flow canworks-deploy --export-nodered writes.
        add_connection(pg, "nodered", name="Flows", address="192.168.10.30", writes=True)
        pg.wait_for_selector('[data-connection="Flows"]')
        self.assertEqual(pg.evaluate("() => S.model.top.bridge.writers"), ["192.168.10.30"])
        pg.click('[data-connection="Line HMI"] input[data-path="bridge.connections[0].writes"]')
        self.assertEqual(pg.evaluate("() => S.model.top.bridge.writers"), ["192.168.10.20", "192.168.10.30"])
        self.assertEqual(pg.inner_text("[data-bridge-who]"), "192.168.10.20, 192.168.10.30")
        pg.evaluate("() => document.activeElement && document.activeElement.blur()")
        pg.keyboard.press("Control+z")
        pg.wait_for_function("() => JSON.stringify(S.model.top.bridge.writers) === '[\"192.168.10.30\"]'")
        cfg = pg.evaluate("() => fileConfig()")
        got = self.download(1)
        self.assertEqual(got.suggested_filename, "rtd-monitor-Flows.json")
        with open(got.path(), encoding="utf-8") as f:
            self.assertEqual(f.read(), nodered.to_json(nodered.flow(cfg, "rtd-monitor-Flows")[0]))
        pg.wait_for_selector("#banner:has-text('it needs the package %s')" % nodered.package_name())
        # Package on the row: the .tgz canworks-deploy --export-nodered-package writes.
        with pg.expect_download() as dl:
            pg.click('[data-conn-package="1"]')
        self.assertEqual(dl.value.suggested_filename, nodered.package_name())
        with open(dl.value.path(), "rb") as f:
            self.assertEqual(f.read(), nodered.package_tgz())
        pg.wait_for_selector("#banner:has-text('Manage palette > Install > upload')")

        # A stopped download: each finding its own Problems row, no message bar.
        pg.evaluate("""() => {
          const f = window.fetch;
          window.fetch = (u, o) => String(u).endsWith('/api/connections/download')
            ? Promise.resolve(new Response(JSON.stringify({ errors: 2, items: [
                { level: 'error', message: 'map finding A', paths: [] }, { level: 'error', message: 'map finding B', paths: [] }] }),
                { headers: { 'Content-Type': 'application/json' } }))
            : f(u, o);
        }""")
        pg.click('[data-conn-download="0"]')
        pg.wait_for_selector("#problems-bars .notice-error:has-text('Line HMI export stopped')")
        texts = pg.eval_on_selector_all("#problem-list li", "ls => ls.map((l) => l.textContent)")
        self.assertEqual([t for t in texts if "map finding" in t], ["map finding A", "map finding B"], texts)
        tree_view(pg, "bridge")
        pg.wait_for_selector('#bridge-map tr[data-bridge-row]')

        # Fits and is accessible, in the dark theme too.
        pg.emulate_media(color_scheme="dark")
        pg.set_viewport_size({"width": 1000, "height": 800})
        pg.wait_for_timeout(300)
        self.assertEqual(pg.evaluate(FIT_CHECK), [])
        audit(pg, "Modbus bridge page")

    def test_trust_connection(self):
        """A truST connection (plcopen-export): the PLC link offered on its row
        as one undo step, its settings, the zip canworks-deploy
        --export-plcopen --for trust writes, the missing bridge address and
        the loopback error with Listen on all addresses."""
        pg = self.page
        self.to_bridge()
        add_connection(pg, "trust", name="Cell PLC", address="192.168.10.7")
        pg.wait_for_selector('[data-connection="Cell PLC"]')
        self.assertTrue(pg.is_checked('input[data-path="bridge.connections[0].writes"]'))
        self.assertEqual(pg.evaluate("() => S.model.top.bridge.writers"), ["192.168.10.7"])
        self.assertNotIn("plc_link", pg.evaluate("() => S.model.top.bridge"))
        self.open_settings(0)
        self.assertIn("PLC link", pg.inner_text('[data-conn-plc-link="0"]'))
        pg.click('[data-conn-plc-link="0"] [data-plc-link-on]')
        pg.wait_for_function("() => S.model.top.bridge.plc_link === true")
        # The row renders again once the repack is back.
        pg.wait_for_selector("[data-conn-plc-link]", state="detached")
        # Turning the link on and its repack were one step.
        pg.evaluate("() => document.activeElement && document.activeElement.blur()")
        pg.keyboard.press("Control+z")
        pg.wait_for_function("() => !('plc_link' in S.model.top.bridge)")
        pg.keyboard.press("Control+Shift+z")
        pg.wait_for_function("() => S.model.top.bridge.plc_link === true")
        # canworks blocks (mailboxes-on-demand): truST offers None and SDO and
        # send, which turns on one request mailbox, placed, in one undo step.
        self.open_settings(0)
        sel = 'select[data-path="bridge.connections[0].blocks"]'
        self.assertEqual(pg.eval_on_selector_all(sel + " option", "os => os.map(o => o.textContent)"),
                         ["None", "SDO and send"])
        pg.select_option(sel, "sdo_send")
        pg.wait_for_function("() => !!(S.model.top.bridge.mailboxes || {}).output_location")
        mb = pg.evaluate("() => S.model.top.bridge.mailboxes")
        self.assertEqual((mb["requests"], mb["receive"], mb["cyclic_jobs"], mb["network_info"]), (1, False, 0, False))
        self.assertEqual(pg.inner_text('[data-conn-blocks="0"]'), "canworks blocks: SDO and send (1 request mailbox)")
        pg.wait_for_selector('[data-bridge-mailbox-who]:has-text("Cell PLC: canworks blocks SDO and send")')
        pg.evaluate("() => document.activeElement && document.activeElement.blur()")
        pg.keyboard.press("Control+z")
        pg.wait_for_function("() => !S.model.top.bridge.mailboxes && !S.model.top.bridge.connections[0].blocks")
        pg.keyboard.press("Control+Shift+z")
        pg.wait_for_function("() => !!S.model.top.bridge.mailboxes && S.model.top.bridge.connections[0].blocks === 'sdo_send'")
        # No bridge address: the listen address is a wildcard, so the row's PLC
        # needs one; Problems says so.
        self.checked()
        self.assertIn("Cell PLC: the PLC needs the bridge's address", pg.inner_text("#problem-list"))
        tree_view(pg, "bridge")
        self.open_settings(0)
        pg.fill('input[data-path="bridge.connections[0].bridge_host"]', "192.168.10.5")
        self.checked()
        self.assertNotIn("needs the bridge's address", pg.inner_text("#problem-list"))
        audit(pg, "truST connection")
        cfg = pg.evaluate("() => fileConfig()")
        got = self.download(0)
        self.assertEqual(got.suggested_filename, "rtd-monitor-Cell-PLC.zip")
        decls = editorproject.declarations(cfg, self.config_path)
        files = plcopen_targets.files(cfg, decls, "trust", host="192.168.10.5", library=True)
        with zipfile.ZipFile(got.path()) as z:
            self.assertEqual(sorted(z.namelist()), sorted(files))
            for n in files:
                self.assertEqual(z.read(n).decode("utf-8"), files[n], n)
        # A loopback listen: the truST connection cannot reach it; one click listens everywhere.
        tree_view(pg, "bridge")
        pg.fill('input[data-path="bridge.listen"]', "127.0.0.1")
        self.checked()
        self.assertIn("Cell PLC connects from 192.168.10.7, but the bridge listens on 127.0.0.1:502 only",
                      pg.inner_text("#problem-list"))
        pg.click('#problem-list [data-problem-fix="listen-all"]')
        pg.wait_for_function("() => S.model.top.bridge.listen === '0.0.0.0:502'")

    def test_trust_cannot_download(self):
        """A truST connection whose Download would be refused
        (trust-connection-check): Cannot download on its row with the
        reason, and the two Problems fixes, the trim one undo step."""
        pg = self.page
        ses = srv.Session()
        cfg = ses.add_connection(self.cfg, {"kind": "trust", "name": "Cell PLC", "address": "192.168.10.7",
                                            "bridge_host": "192.168.10.5"})["config"]
        cfg["bridge"].update(plc_link=True, watchdog_ms=100,
                             mailboxes={"input_location": "%IB0", "output_location": "%QB0"})
        self.cfg = ses.bridge_pack(cfg)["config"]
        self.write_config()
        self.to_bridge()
        tree_view(pg, "bridge")
        pg.wait_for_selector('[data-connection="Cell PLC"] [data-conn-state="cannot_download"]')
        self.assertIn("truST's Modbus driver moves one request each way",
                      pg.get_attribute('[data-connection="Cell PLC"] [data-conn-state]', "title"))
        problems = pg.inner_text("#problem-list")
        self.assertIn("Cell PLC: Download refused: ", problems)
        pg.click('#problem-list [data-problem-fix="watchdog-trust"]')
        pg.wait_for_function("() => S.model.top.bridge.watchdog_ms === 500")
        self.checked()
        pg.click('#problem-list [data-problem-fix="trim-trust"]')
        pg.wait_for_function("() => S.model.top.bridge.mailboxes.receive === false")
        self.checked()
        pg.wait_for_function("() => !document.querySelector('#problem-list').textContent.includes('Download refused')")
        mb = pg.evaluate("() => S.model.top.bridge.mailboxes")
        self.assertEqual((mb["requests"], mb["network_info"], mb["cyclic_jobs"]), (1, False, 0))
        tree_view(pg, "bridge")
        pg.wait_for_selector('[data-connection="Cell PLC"] [data-conn-state="not_downloaded"]')
        # The trim and its repack were one step.
        pg.evaluate("() => document.activeElement && document.activeElement.blur()")
        pg.keyboard.press("Control+z")
        pg.wait_for_function("() => S.model.top.bridge.mailboxes.receive !== false")
        self.assertEqual(pg.evaluate("() => S.model.top.bridge.watchdog_ms"), 500)

    def test_other_plc_formats(self):
        """An Other PLC connection: PLCopen XML or ST, no CODESYS choice, and
        the line pointing CODESYS to its own target."""
        pg = self.page
        self.to_bridge()
        add_connection(pg, "plc", name="Line PLC", address="192.168.10.8")
        pg.wait_for_selector('[data-connection="Line PLC"]')
        self.open_settings(0)
        self.assertEqual(pg.eval_on_selector_all('select[data-path="bridge.connections[0].format"] option',
                                                 "os => os.map(o => o.textContent)"), ["PLCopen XML", "ST"])
        self.assertIn("pick the CODESYS target", pg.inner_text("[data-conn-codesys]"))

    def test_function_blocks_section(self):
        """The Function blocks section (add-bridge-mailboxes): off for a
        plain bridge; on, Suggest places both areas after the data; the
        cost line and which blocks need which part; a count change keeps
        the places for another client."""
        pg = self.page
        self.to_bridge()
        tree_view(pg, "bridge")
        pg.wait_for_selector('[data-bridge-mailboxes="0"]')
        # Off: what works without them, who needs which part and what turning them on would add.
        self.assertIn("Without mailboxes: the config's values, CO_NMT", pg.inner_text("[data-bridge-without]"))
        self.assertIn("a received CAN message or J1939 PGN", pg.inner_text("[data-bridge-mailbox-needs]"))
        pg.wait_for_selector('[data-bridge-mailbox-cost]:has-text("would take +227 input / +79 holding registers")')
        pg.check('input[data-path="bridge.mailboxes"]')
        pg.wait_for_function("() => !!(S.model.top.bridge.mailboxes || {}).output_location")
        self.assertEqual(pg.evaluate("() => S.model.top.bridge.mailboxes"),
                         {"input_location": "%IB24", "output_location": "%QB6"})
        self.checked()
        self.assertEqual(pg.text_content("#problem-list").strip(), "No problems.")
        cost = pg.wait_for_selector('[data-bridge-mailbox-cost]:has-text("input")')
        # 72 response + 120 receive + 18 info + 17 cyclic table; 72 request + 3 ack + 4 keepalives.
        self.assertEqual(cost.inner_text(), "The mailboxes take +227 input / +79 holding registers. Receiving: 9 CAN frames "
                                            "per batch, one batch per two of your client's polls.")
        needs = pg.inner_text('[data-bridge-mailbox-needs]')
        self.assertIn("CAN_RECEIVE, J1939_RECEIVE and CO_RECV_EMCY", needs)
        self.assertEqual(pg.locator("[data-bridge-mailbox-update]").count(), 0)  # OpenPLC only
        pg.fill('input[data-path="bridge.mailboxes.requests"]', "2")
        pg.uncheck('input[data-path="bridge.mailboxes.receive"]')
        pg.wait_for_selector('[data-bridge-mailbox-cost]:has-text("+179 input")')
        self.assertEqual(pg.evaluate("() => S.model.top.bridge.mailboxes.input_location"), "%IB24")
        pg.wait_for_selector('#bridge-map tr[data-bridge-row="bridge.mailbox.1.response"]')
        pg.click("#btn-save")
        pg.wait_for_selector("#banner:has-text('Saved')")
        self.assertEqual(load(self.config_path)["bridge"]["mailboxes"],
                         {"input_location": "%IB24", "output_location": "%QB6", "requests": 2, "receive": False})
        self.assertEqual(pg.evaluate(FIT_CHECK), [])
        audit(pg, "Modbus bridge page with function blocks")

    def test_example_live_list_follows_the_network(self):
        """The example as it is: defaults written out show as the default,
        a network rename carries the live list along, a removal takes it."""
        pg = self.page
        self.cfg = load(os.path.join(EXAMPLE, "canworks.json"))
        self.write_config()
        self.open()
        tree_view(pg, "bridge")
        pg.wait_for_selector("h2:has-text('Modbus bridge')")
        for path, label in (("bridge.word_order", "High word first"), ("bridge.on_client_loss", "Stop")):
            self.assertEqual(pg.eval_on_selector('select[data-path="%s"]' % path,
                                                 "s => s.selectedOptions[0].textContent"), label)
        self.assertNotIn("as in the file", pg.inner_text("#view"))
        add = 'button[data-bridge="add-live-list"]'
        self.assertTrue(pg.is_disabled(add))
        self.assertIn("Every CANopen master network has a live list", pg.get_attribute(add, "title"))
        pg.click('#tree [data-net-menu="0"]')
        pg.click('[data-menu-pop] [data-value="rename"]')
        pg.fill('#modal-extra input[data-net="name"]', "plant")
        pg.press('#modal-extra input[data-net="name"]', "Enter")
        self.assertEqual(pg.evaluate("() => S.model.top.bridge.live_lists[0].network"), "plant")
        self.checked()
        self.assertEqual(pg.text_content("#problem-list").strip(), "No problems.")
        # A second network, then the first removed: its live list goes with it.
        pg.click('#tree [data-action="add-network"] > .tree-row')
        pg.click('#modal button[data-value="canopen"]')
        pg.click('#tree [data-net-menu="0"]')
        pg.click('[data-menu-pop] [data-value="remove"]')
        self.assertIn("Its Modbus bridge live list is removed too", pg.inner_text("#modal-text"))
        pg.click('#modal button[data-value="remove"]')
        self.assertIsNone(pg.evaluate("() => S.model.top.bridge.live_lists || null"))

    def test_plc_cycle_and_openplc_connection(self):
        pg = self.page
        self.to_bridge()
        # The master's PLC stop field; the bridge has no PLC scan, so no PLC cycle SYNC.
        self.assertEqual(pg.input_value('select[data-path="master.on_plc_stop"]'), "")
        pg.select_option('select[data-path="master.on_plc_stop"]', "stop")
        self.assertIn("NMT STOP", pg.inner_text('label:has(select[data-path="master.on_plc_stop"])'))
        pg.select_option('select[data-path="master.on_plc_stop"]', "")
        self.assertIsNone(pg.evaluate("() => S.config.master.on_plc_stop || null"))
        self.assertEqual(pg.locator('select[data-path="master.sync_source"] option[value="plc_cycle"]').count(), 0)
        # A PLC cycle SYNC the config still has is an error, shown as the config's value.
        pg.evaluate("() => { S.config.master.sync_source = 'plc_cycle'; delete S.config.master.sync_period_us; changed(true); }")
        # The check runs after a short delay, so wait for its result.
        pg.wait_for_selector("#problem-list:has-text('needs a PLC cycle, which the Modbus bridge does not have')")
        # The SYNC choice offers Off and Timer only; a timer period replaces it.
        pg.evaluate("() => { delete S.config.master.sync_source; changed(true); render(); }")
        pg.select_option('select[data-path="master.sync_source"]', "timer")
        pg.fill('input[data-path="master.sync_period_us"]', "20")
        self.checked()
        self.assertEqual(pg.text_content("#problem-list").strip(), "No problems.")

        # A hand-made config in an editor project: the Project page offers Use
        # with this OpenPLC project, which adds the connection as Add connection does.
        tree_view(pg, "project")
        self.assertIn("no OpenPLC connection", pg.inner_text('[data-editor-project="project"]'))
        pg.click("button[data-use-with-project]")
        pg.wait_for_selector("[data-conn-added=openplc]")
        self.checked()
        self.assertEqual(pg.text_content("#problem-list").strip(), "No problems.")
        b = pg.evaluate("() => S.model.top.bridge")
        self.assertEqual((b["plc_link"], b["listen"], b["writers"], b["word_order"], b["watchdog_ms"]),
                         (True, "127.0.0.1:1502", ["127.0.0.1"], "low_first", 50))
        self.assertNotIn("mailboxes", b)  # mailboxes-on-demand
        # Adding it and its repack are one step: undo takes it back, redo adds it.
        pg.evaluate("() => document.activeElement && document.activeElement.blur()")
        pg.keyboard.press("Control+z")
        pg.wait_for_function("() => !hasOpenplc() && !S.model.top.bridge.plc_link")
        pg.keyboard.press("Control+Shift+z")
        pg.wait_for_function("() => hasOpenplc()")
        self.checked()
        pg.click("#btn-save")
        pg.wait_for_selector("#banner:has-text('Saved')")
        conn = load(self.config_path)["bridge"]["connections"]
        self.assertEqual(conn, [{"kind": "openplc", "name": "OpenPLC", "address": "127.0.0.1", "writes": True}])
        self.assertTrue(os.path.isfile(os.path.join(self.project, "devices", "remote", "canworks.json")))
        # Removing it asks first and leaves the editor files on disk.
        tree_view(pg, "bridge")
        pg.click('[data-conn-remove="0"]')
        self.assertIn("files already in the editor project stay on disk", pg.inner_text("#modal-text"))
        pg.click('#modal-buttons button[data-value="remove"]')
        self.assertEqual(pg.evaluate("() => connectionsOf().length"), 0)
        self.assertTrue(os.path.isfile(os.path.join(self.project, "devices", "remote", "canworks.json")))


if __name__ == "__main__":
    import unittest
    unittest.main()
