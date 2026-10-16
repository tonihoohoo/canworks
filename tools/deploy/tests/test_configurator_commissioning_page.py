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
from unittest import mock

from canworks.configurator import online

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


class NotesPage(Page):
    def test_notes_written_at_once(self):
        # Commission a device has the configurator's Notes tab; with no Save
        # there, a note is written at once next to the EDS, logged, and
        # undone by Ctrl+Z (notes-row-pick-and-commission-notes).
        pg = self.page
        od, ro = rtd_od(5)
        self.device(5, od=od, ro=ro, identity=IDENTITY, heartbeat_s=0.1)
        self.open_node(5, "notes", "rtd8.eds")
        pg.wait_for_selector("[data-node-notes] [data-notes-live]:has-text('rtd8.eds.notes.json')")
        notes = os.path.join(pg.evaluate("() => S.state.canopen_dir"), "rtd8.eds.notes.json")
        self.assertFalse(os.path.exists(notes))
        # Add note…: a click on the row's name picks the object.
        pg.click("[data-node-notes] button[data-add-note]")
        pg.fill("#modal [data-note-picker-filter]", "2000:2")
        pg.click('#modal tr[data-note-pick-row="0x2000:2"] td:nth-child(2)')
        pg.wait_for_selector('#modal .note-editor[data-note-editor="0x2000:2"]')
        pg.fill('#modal [data-note-field="text"]', "Delay before the first reading")
        pg.click('#modal button[data-value="save"]')
        pg.wait_for_selector('[data-note-row="0x2000:2"][data-note-source="mine"]')
        self.assertEqual(load(notes)["objects"]["0x2000:2"], {"name": "Start delay ms", "text": "Delay before the first reading"})
        pg.wait_for_selector("#banner [data-notes-undo]")
        self.assertEqual(pg.inner_text('button[data-online-tab="notes"]').strip(), "Notes 1")
        self.assertIn("Note 0x2000:2", pg.evaluate("() => S.commLog.map((e) => e.what).join(\"\\n\")"))
        audit(pg, "Commission notes tab")
        # The Object dictionary tab shows the new note.
        pg.click('button[data-online-tab="od"]')
        pg.wait_for_selector('[data-note="text"]:has-text("Delay before the first reading")', state="attached")
        # Ctrl+Z puts the file back as it was (here: none).
        pg.click('button[data-online-tab="notes"]')
        pg.wait_for_selector('[data-note-row="0x2000:2"]')
        pg.click("[data-online=node-heading]")
        pg.keyboard.press("Control+z")
        pg.wait_for_selector('[data-notes-empty="mine"]')
        self.assertFalse(os.path.exists(notes))
        self.assertIn("Undo: Note 0x2000:2", pg.evaluate("() => S.commLog.map((e) => e.what).join(\"\\n\")"))
        # A row of the Notes tab opens its note on a click.
        pg.click('[data-notes-view-pick="all"]')
        pg.click('[data-note-row="0x1017:0"] td:nth-child(3)')
        pg.wait_for_selector('#modal .note-editor[data-note-editor="0x1017"]')
        pg.click('#modal button[data-value="cancel"]')
        # Import: the preview, then written at once.
        path = os.path.join(self.dir, "colleague.notes.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"format": "canworks-notes.v1", "objects": {"0x2000:2": {"unit": "ms"}}}, f)
        pg.click("[data-node-notes] button[data-import-notes]")
        pg.set_input_files("#modal [data-import-notes-file]", path)
        pg.click('#modal button[data-value="next"]')
        pg.wait_for_selector("#modal [data-import-preview]")
        pg.click('#modal button[data-value="import"]')
        pg.wait_for_selector('[data-note-row="0x2000:2"][data-note-source="mine"]')
        self.assertEqual(load(notes)["objects"]["0x2000:2"]["unit"], "ms")
        # Export of one's own notes.
        pg.click("[data-node-notes] button[data-export-notes]")
        with pg.expect_download() as dl:
            pg.click('#modal button[data-value="own"]')
        self.assertEqual(dl.value.suggested_filename, "rtd8.eds.notes.json")
        with open(dl.value.path(), encoding="utf-8") as f:
            self.assertEqual(list(json.load(f)["objects"]), ["0x2000:2"])


class FrameLabPage(Page):
    def test_examples_after_coming_back(self):
        """Commission a device: the Frame lab's Examples tab shows the node's
        examples after the Nodes tab and back, and after Build and back
        (fix-frame-lab-examples-text)."""
        pg = self.page
        self.open_node(5, "params", "rtd8.eds")
        for leave in ('button[data-view="nodes"]', "[data-fx-mode=build]"):
            pg.click('button[data-view="framelab"]')
            pg.wait_for_selector("[data-fx=examples] .chip")
            pg.click(leave)
            if leave.startswith("[data-fx"):
                pg.click("[data-fx-mode=examples]")
            else:
                pg.click('button[data-view="framelab"]')
            pg.wait_for_selector("[data-fx=examples] .chip")
            self.assertNotIn("[object ", pg.inner_text("#fx-lab-panel"))
            self.assertIn("Boot-up", pg.inner_text("#fx-lab-panel"))


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
        # Browse… opens the folder dialog over this one; the picked folder fills the field.
        pg.fill('input[data-online="add-folder"]', os.path.join(self.dir, "editor"))
        pg.select_option('select[data-online="add-mode"]', "project")
        pg.click('button[data-online="add-folder-browse"]')
        pg.wait_for_selector('dialog[data-folder="dialog"][open]')
        self.assertEqual(pg.input_value('[data-folder="path"]'), self.dir)  # the nearest folder that exists
        audit(pg, "folder dialog over add to a config")
        pg.click('[data-folder-path="%s"]' % folder)
        pg.wait_for_function("(f) => document.querySelector('[data-folder=path]').value === f", arg=folder)
        pg.click('dialog[data-folder="dialog"] button[data-value="use"]')
        pg.wait_for_selector('dialog[data-folder="dialog"]', state="detached")
        self.assertTrue(pg.is_visible("#modal[open]"))
        self.assertEqual(pg.input_value('input[data-online="add-folder"]'), folder)
        pg.wait_for_function("() => document.querySelector('select[data-online=add-mode]').value === 'standalone'")
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

    def test_add_to_a_config_carries_the_eds(self):
        """A node added from an EDS in Commission keeps that EDS in the config
        it is added to (carry-commission-eds-into-config)."""
        pg = self.page
        self.device(23, od=fixed_io_od(23), heartbeat_s=0.1)
        folder = os.path.join(self.dir, "bench")
        os.makedirs(folder)
        shutil.copy(os.path.join(PINGPONG, "cpp-slave.eds"), folder)
        with open(os.path.join(folder, "canworks.json"), "w") as f:
            json.dump(load(os.path.join(PINGPONG, "canopen_config.json")), f)
        self.open_node(23, "status", "fixed-io.eds")
        pg.click('button[data-online="add-to-config"]')
        pg.fill('input[data-online="add-folder"]', folder)
        # The EDS is known: the dialog names it and asks for no file.
        self.assertEqual(pg.locator('input[data-online="add-eds"]').count(), 0)
        self.assertIn("EDS: fixed-io.eds", pg.inner_text("#modal"))
        pg.click('#modal button[data-value="add"]')
        pg.wait_for_function("() => (S.config.nodes || []).some((n) => Number(n.node_id) === 23)")
        node = pg.evaluate("() => S.config.nodes.find((n) => Number(n.node_id) === 23)")
        self.assertEqual(node["eds"], "fixed-io.eds")
        self.assertIn("Added node 23 (fixed-io.eds)", pg.inner_text("#banner"))
        self.assertNotIn("only EDS files", pg.inner_text("#banner"))
        self.assertFalse(pg.evaluate("() => S.state.commission"))

    def test_close_asks_to_save_the_log(self):
        pg = self.page
        self.commission()
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


class EdsLibraryPage(Page):
    """The EDS library folder row on the Nodes tab (browse-eds-library-folder)."""

    def library(self):
        lib = os.path.join(self.dir, "eds-lib")
        os.makedirs(os.path.join(lib, "vendor"))
        shutil.copy(FIXED_IO, lib)
        shutil.copy(os.path.join(RTD, "rtd8.eds"), os.path.join(lib, "vendor"))
        return lib

    def choose(self, folder):
        """Choose folder…, then the keyboard alone: the path typed, Enter, Use this folder."""
        pg = self.page
        pg.click('button[data-online="library-choose"]')
        pg.wait_for_selector('dialog[data-folder="dialog"][open]')
        pg.fill('[data-folder="path"]', folder)
        pg.press('[data-folder="path"]', "Enter")
        pg.wait_for_function("(f) => document.querySelector('[data-folder=here]') && "
                             "document.querySelector('[data-folder=path]').value === f", arg=folder)
        pg.focus('dialog[data-folder="dialog"] button[data-value="use"]')
        pg.keyboard.press("Enter")
        pg.wait_for_selector('dialog[data-folder="dialog"]', state="detached")

    def test_choose_cancel_and_clear(self):
        pg = self.page
        lib = self.library()
        self.commission()
        self.assertEqual(pg.inner_text('[data-online="library"]'), "None chosen")
        self.assertFalse(pg.is_visible('button[data-online="library-clear"]'))
        self.assertEqual(pg.locator('#view input[aria-label="EDS library folder"]').count(), 0)
        # The parent folder's list shows the library with its EDS count.
        pg.click('button[data-online="library-choose"]')
        pg.wait_for_selector('dialog[data-folder="dialog"][open]')
        pg.fill('[data-folder="path"]', self.dir)
        pg.press('[data-folder="path"]', "Enter")
        pg.wait_for_selector('[data-folder-path="%s"]:has-text("1 EDS")' % lib)
        audit(pg, "folder dialog")
        # Arrow keys move in the list, Enter opens a folder.
        pg.focus('[data-folder-path="%s"]' % lib)
        pg.keyboard.press("Enter")
        pg.wait_for_selector('[data-folder=here]:has-text("1 EDS file in this folder")')
        pg.wait_for_selector('[data-folder-path="%s"]:has-text("1 EDS")' % os.path.join(lib, "vendor"))
        self.assertEqual(pg.evaluate("() => document.activeElement.dataset.folderPath"), os.path.join(lib, "vendor"))
        pg.keyboard.press("Backspace")
        pg.wait_for_function("(f) => document.querySelector('[data-folder=path]').value === f", arg=self.dir)
        # Escape cancels: nothing changes, focus is back on the button.
        pg.keyboard.press("Escape")
        pg.wait_for_selector('dialog[data-folder="dialog"]', state="detached")
        self.assertEqual(pg.inner_text('[data-online="library"]'), "None chosen")
        self.assertEqual(pg.evaluate("() => document.activeElement.dataset.online"), "library-choose")
        # Choose it: path, count, kept on this PC.
        self.choose(lib)
        pg.wait_for_selector('[data-online="library"]:has-text("%s")' % lib)
        self.assertEqual(pg.inner_text('[data-online="library-count"]'), "2 EDS files (with subfolders).")
        self.assertEqual(pg.evaluate("() => api('GET', '/api/online/settings')")["eds_library"], lib)
        self.assertEqual(pg.evaluate("() => document.activeElement.dataset.online"), "library-choose")
        # Opens in the library folder next time.
        pg.click('button[data-online="library-choose"]')
        pg.wait_for_selector('dialog[data-folder="dialog"][open]')
        pg.wait_for_function("(f) => document.querySelector('[data-folder=path]').value === f", arg=lib)
        pg.click('dialog[data-folder="dialog"] button[data-value="cancel"]')
        pg.wait_for_selector('dialog[data-folder="dialog"]', state="detached")
        # A folder without EDS files is kept, and says so.
        empty = os.path.join(self.dir, "no-eds")
        os.makedirs(empty)
        self.choose(empty)
        pg.wait_for_selector('[data-online="library-count"]:has-text("No EDS files")')
        audit(pg, "nodes with a library")
        pg.click('button[data-online="library-clear"]')
        pg.wait_for_selector('[data-online="library"]:has-text("None chosen")')
        self.assertFalse(pg.is_visible('button[data-online="library-clear"]'))
        self.assertEqual(pg.evaluate("() => api('GET', '/api/online/settings')")["eds_library"], "")

    def test_large_folder(self):
        pg = self.page
        lib = self.library()
        with mock.patch.object(online, "EDS_COUNT_LIMIT", 1):
            with mock.patch.object(online.count_eds, "__defaults__", (1,)):
                self.commission()
                self.choose(lib)
                pg.wait_for_selector('[data-online="library-count"]:has-text("Large folder")')
