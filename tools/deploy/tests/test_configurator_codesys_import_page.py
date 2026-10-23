"""Import from CODESYS and the Build's remove question in a real browser
(spec canopen-configurator "Import from CODESYS", "Import preview", "Build
asks before removing nodes"): a PLCopenXML file into a new config, a node
without an EDS and Add EDS…, a .project through CODESYS on this PC with the
device list, a .project without CODESYS, Add to this config with Rename and
Replace, and Remove or Keep on Build. Needs Playwright, like
test_configurator_page.py."""

import gzip
import json
import os
import shutil
from unittest import mock

from canworks.codesys import plan as cplan
from canworks.codesys import xmlimport
from canworks.configurator import online, server as srv

from .helpers import REPO, tree_view
from .test_configurator_online_page import OnlineBase
from .test_configurator_page import load

PLANT_XML = os.path.join(os.path.dirname(__file__), "data", "codesys-import", "virtual-plant.xml.gz")
PLANT_DIR = os.path.join(REPO, "examples", "virtual-plant", "canworks")


class CodesysImportPage(OnlineBase):
    def setUp(self):
        super().setUp()
        self.src = os.path.join(self.dir, "src")
        os.makedirs(self.src)
        self.xml = os.path.join(self.src, "plant.xml")
        with gzip.open(PLANT_XML) as f, open(self.xml, "wb") as out:
            out.write(f.read())

    def library(self, path=PLANT_DIR):
        online.Settings(self.cfg_dir).set_eds_library(path)

    def with_codesys(self, devices):
        """CODESYS 'installed'; the runner answers the export script with
        `devices` and, for a named device or the only one, the fixture."""
        root = os.path.join(self.dir, "Program Files")
        install = os.path.join(root, "CODESYS 3.5.22.40", "CODESYS")
        os.makedirs(os.path.join(install, "Common"))
        os.makedirs(os.path.join(install, "Profiles"))
        open(os.path.join(install, "Common", "CODESYS.exe"), "w").close()
        open(os.path.join(install, "Profiles", "CODESYS V3.5 SP22.profile.xml"), "w").close()
        patches = [mock.patch.dict(os.environ, {"PROGRAMFILES": root}),
                   mock.patch("canworks.codesys.run.repository_roots", return_value=[])]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        runs = []

        def runner(line):
            folder = os.path.dirname(line.split('--runscript="')[1].rstrip('"'))
            job = load(os.path.join(folder, "canworks-export.json"))
            runs.append(job)
            with open(os.path.join(folder, "devices.json"), "w", encoding="utf-8") as f:
                json.dump(devices, f)
            if job["device"] or len(devices) == 1:
                shutil.copy(self.xml, os.path.join(folder, "canworks-export.xml"))
            with open(os.path.join(folder, "export_report.txt"), "w", encoding="utf-8") as f:
                f.write("result: ok\n")
        self.server.codesys_runner = runner
        return runs

    def pick(self, path, start="#start-codesys-import"):
        pg = self.page
        pg.click(start)
        pg.wait_for_selector('dialog[data-folder="dialog"][open]')
        pg.fill('[data-folder="path"]', os.path.dirname(path))
        pg.press('[data-folder="path"]', "Enter")
        pg.click('[data-file-path="%s"]' % path)

    def create(self, name):
        pg = self.page
        pg.click('#modal-buttons button[data-value="create"]')
        pg.wait_for_selector("[data-ci-new=form]")
        pg.fill("[data-ci-new=name]", name)
        pg.fill("[data-ci-new=location]", self.dir)
        pg.click('#modal-buttons button[data-value="create"]')
        pg.wait_for_selector("#editor:not([hidden])")
        return os.path.join(self.dir, name)

    def test_xml_into_a_new_config(self):
        pg = self.page
        self.library()
        pg.goto(self.server.url)
        self.pick(self.xml)
        pg.wait_for_selector("[data-ci-preview]")
        self.assertIn("plant.xml: 3 networks, 5 nodes.", pg.inner_text("#modal-text"))
        self.assertEqual(pg.locator("[data-ci-network]").count(), 3)
        self.assertEqual(pg.inner_text('[data-ci-node="rtd"] [data-ci-eds]').split(" ")[:4], ["EDS", "from", "the", "library"])
        self.assertEqual(pg.locator("[data-ci-report]").count(), 1)
        # Nothing written before Create.
        self.assertFalse(os.path.exists(os.path.join(self.dir, "plant")))
        folder = self.create("plant")
        cfg = load(os.path.join(folder, "canworks.json"))
        self.assertEqual(len(cfg["networks"]), 3)
        self.assertEqual(cfg["networks"][0]["codesys"]["managed"], [5, 6, 7])
        for name in ("rtd8.eds", "dio16.eds", "conveyor.eds", "cell.eds"):
            self.assertTrue(os.path.isfile(os.path.join(folder, name)), name)
        self.assertIn("into a new CODESYS config", pg.inner_text("#banner"))
        tree_view(pg, "project")
        self.assertEqual(pg.input_value('select[data-target="1"]'), "codesys")
        self.assertFalse(pg.evaluate("() => S.dirty"))

    def test_missing_eds_and_add_eds(self):
        pg = self.page
        self.library(os.path.join(self.dir, "empty"))
        os.makedirs(os.path.join(self.dir, "empty"))
        pg.goto(self.server.url)
        self.pick(self.xml)
        pg.wait_for_selector("[data-ci-missing]")
        self.assertIn("5 nodes have no EDS", pg.inner_text("[data-ci-missing]"))
        self.assertTrue(pg.is_disabled('#modal-buttons button[data-value="create"]'))
        # One EDS per CODESYS device type: dio and new_io share theirs.
        for device, eds in (("rtd", "rtd8.eds"), ("dio", "dio16.eds"), ("conveyor", "conveyor.eds"), ("cell", "cell.eds")):
            pg.set_input_files('[data-ci-add-eds="%s"]' % device, os.path.join(PLANT_DIR, eds))
            pg.wait_for_selector('[data-ci-node="%s"] [data-ci-eds]:has-text("EDS added")' % device)
        self.assertIn("EDS added", pg.inner_text('[data-ci-node="new_io"] [data-ci-eds]'))
        self.assertEqual(pg.locator("[data-ci-missing]").count(), 0)
        self.assertFalse(pg.is_disabled('#modal-buttons button[data-value="create"]'))
        folder = self.create("plant")
        self.assertTrue(os.path.isfile(os.path.join(folder, "cell.eds")))

    def test_project_without_codesys(self):
        pg = self.page
        open(os.path.join(self.src, "line2.project"), "w").close()
        pg.goto(self.server.url)
        pg.click("#start-codesys-import")
        pg.wait_for_selector('dialog[data-folder="dialog"][open]')
        self.assertIn("CODESYS is not installed on this PC", pg.inner_text('dialog[data-folder="dialog"]'))
        pg.fill('[data-folder="path"]', self.src)
        pg.press('[data-folder="path"]', "Enter")
        pg.wait_for_selector('[data-file-path="%s"]' % self.xml)
        self.assertEqual(pg.locator('[data-file-path$=".project"]').count(), 0)

    def test_project_with_device_list(self):
        pg = self.page
        self.library()
        runs = self.with_codesys([{"name": "PLC", "buses": ["CANbus"], "nodes": 5, "active": False},
                                  {"name": "Panel", "buses": ["CANbus"], "nodes": 1, "active": True}])
        project = os.path.join(self.src, "line2.project")
        open(project, "w").close()
        pg.goto(self.server.url)
        self.pick(project)
        pg.wait_for_selector("[data-ci-devices]")
        self.assertIn("line2.project has 2 devices", pg.inner_text("#modal-text"))
        self.assertTrue(pg.is_checked('[data-ci-device="Panel"]'))
        pg.click('label:has([data-ci-device="PLC"])')
        pg.click('#modal-buttons button[data-value="import"]')
        pg.wait_for_selector("[data-ci-preview]")
        self.assertEqual([r["device"] for r in runs], [None, "PLC"])
        self.assertIn("device PLC", pg.inner_text("#modal-text"))
        folder = self.create("line2")
        cfg = load(os.path.join(folder, "canworks.json"))
        self.assertEqual(cfg["codesys"], {"project": project, "device": "PLC"})
        tree_view(pg, "codesys")
        self.assertEqual(pg.input_value('input[data-path="codesys.project"]'), project)

    def test_add_to_this_config(self):
        pg = self.page
        self.library()
        # A CODESYS config holding the plant already.
        res = xmlimport.convert(xmlimport.choices(xmlimport.read(PLANT_XML))[0],
                                xmlimport.library_finder(xmlimport.folder_matcher([("library", PLANT_DIR)])))
        folder = os.path.join(self.dir, "line")
        xmlimport.write(res, folder)
        pg.goto(self.server.url)
        pg.evaluate("p => api('POST', '/api/open', {path: p, mode: 'auto'})", folder)
        pg.reload()
        pg.wait_for_selector("#editor:not([hidden])")
        tree_view(pg, "codesys")
        self.pick(self.xml, "[data-codesys-import]")
        pg.wait_for_selector("[data-ci-preview]")
        pg.click('#modal-buttons button[data-value="add"]')
        # Every network clashes: the first is added as a new network, the others replace theirs.
        answers = ["rename", "replace", "replace"]
        for a in answers:
            pg.wait_for_selector("#modal[open] #modal-buttons button[data-value=rename]")
            self.assertIn("clashes with", pg.inner_text("#modal-text"))
            pg.click('#modal-buttons button[data-value="%s"]' % a)
        pg.wait_for_selector("#banner:has-text('Added 3 networks from plant.xml')")
        nets = pg.evaluate("() => fileConfig().networks")
        self.assertEqual([n["name"] for n in nets], [n["name"] for n in res.cfg["networks"]] + ["io2"])
        self.assertNotEqual(nets[3]["codesys"]["net_id"], nets[0]["codesys"]["net_id"])
        self.assertTrue(pg.evaluate("() => S.dirty"))
        # Same EDS files: nothing new to copy.
        self.assertEqual(sorted(f for f in os.listdir(folder) if f.endswith(".eds")),
                         ["cell.eds", "conveyor.eds", "dio16.eds", "rtd8.eds"])


class BuildRemoveQuestion(OnlineBase):
    def setUp(self):
        super().setUp()
        res = xmlimport.convert(xmlimport.choices(xmlimport.read(PLANT_XML))[0],
                                xmlimport.library_finder(xmlimport.folder_matcher([("library", PLANT_DIR)])))
        self.folder = os.path.join(self.dir, "line")
        xmlimport.write(res, self.folder)
        self.config = os.path.join(self.folder, "canworks.json")
        cfg = load(self.config)
        cfg["codesys"]["project"] = os.path.join(self.dir, "line.project")
        open(cfg["codesys"]["project"], "w").close()
        # new_io (node 7) deleted in canworks.
        cfg["networks"][0]["nodes"] = [n for n in cfg["networks"][0]["nodes"] if n["node_id"] != 7]
        with open(self.config, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
        root = os.path.join(self.dir, "Program Files")
        install = os.path.join(root, "CODESYS 3.5.22.40", "CODESYS")
        os.makedirs(os.path.join(install, "Common"))
        os.makedirs(os.path.join(install, "Profiles"))
        open(os.path.join(install, "Common", "CODESYS.exe"), "w").close()
        open(os.path.join(install, "Profiles", "CODESYS V3.5 SP22.profile.xml"), "w").close()
        p = mock.patch.dict(os.environ, {"PROGRAMFILES": root})
        p.start()
        self.addCleanup(p.stop)
        self.plans = []

        def runner(line):
            folder = os.path.dirname(line.split('--runscript="')[1].rstrip('"'))
            self.plans.append(load(os.path.join(folder, cplan.PLAN_NAME)))
            with open(os.path.join(folder, cplan.REPORT_NAME), "w", encoding="utf-8") as f:
                f.write("result: ok\nwarnings: 0\n\ndevice   PLC (only device)\n")
        self.server.codesys_runner = runner
        pg = self.page
        pg.goto(self.server.url)
        pg.evaluate("p => api('POST', '/api/open', {path: p, mode: 'auto'})", self.folder)
        pg.reload()
        pg.wait_for_selector("#editor:not([hidden])")

    def build(self, answer):
        pg = self.page
        pg.click("#btn-codesys-build")
        pg.wait_for_selector("#modal[open] [data-codesys-removals]")
        self.assertIn("a node that canworks built earlier", pg.inner_text("#modal-text"))
        self.assertEqual(pg.inner_text("[data-codesys-removals]").strip(), "%s: node 7" % load(self.config)["networks"][0]["name"])
        pg.click('#modal-buttons button[data-value="%s"]' % answer)

    def test_cancel_builds_nothing(self):
        self.build("cancel")
        self.assertEqual(self.plans, [])

    def test_keep(self):
        pg = self.page
        self.build("keep")
        pg.wait_for_selector("#modal[open] [data-codesys-report]", timeout=60000)
        self.assertEqual(self.plans[0]["networks"][0]["remove"], [])
        pg.click('#modal-buttons button[data-value="close"]')
        # Kept nodes leave the managed list, so the next build does not ask again.
        self.assertEqual(load(self.config)["networks"][0]["codesys"]["managed"], [5, 6])
        pg.wait_for_function("() => !S.dirty && fileConfig().networks[0].codesys.managed.length === 2")

    def test_remove(self):
        pg = self.page
        self.build("remove")
        pg.wait_for_selector("#modal[open] [data-codesys-report]", timeout=60000)
        self.assertEqual(self.plans[0]["networks"][0]["remove"], [7])


if __name__ == "__main__":
    import unittest
    unittest.main()
