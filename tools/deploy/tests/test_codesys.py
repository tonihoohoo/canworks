"""CODESYS export (codesys-export spec): the plan, the export folder, the
command line, and import_canworks.py run against a stand-in for CODESYS's
scripting API (tests/fake_codesys.py)."""

import contextlib
import io
import json
import os
import shutil
import unittest
from unittest import mock

from canworks import cli
from canworks.codesys import plan as cplan
from canworks.codesys import run as crun

from . import fake_codesys
from .helpers import tmpdir
from .test_contract import REPO

GOLDEN = os.path.join(os.path.dirname(__file__), "data", "codesys")
EXAMPLES = os.path.join(REPO, "examples")
BRIDGE = os.path.join(EXAMPLES, "modbus-bridge", "canworks.json")
PLANT = os.path.join(EXAMPLES, "virtual-plant", "canworks", "canworks.json")
# Three CiA 402 drives and an I/O module on network "motion" (sim1), with
# the virtual-plant EDS files.
MOTION = os.path.join(os.path.dirname(__file__), "data", "codesys-motion", "canworks.json")


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def deploy(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(list(argv))
    return code, out.getvalue(), err.getvalue()


def export(test, config, **kw):
    folder = os.path.join(tmpdir(test), "codesys")
    files, plan = cplan.export_files(load(config), config, **kw)
    crun.write_folder(files, folder)
    return folder, plan


def set_plan(folder, **changes):
    path = os.path.join(folder, cplan.PLAN_NAME)
    plan = load(path)
    plan.update(changes)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(plan, f)


class Plan(unittest.TestCase):
    def check_golden(self, name, config):
        plan, _ = cplan.build(load(config), config)
        plan["tool"] = "canworks-deploy"
        path = os.path.join(GOLDEN, name)
        text = json.dumps(plan, indent=2) + "\n"
        if os.environ.get("CANWORKS_UPDATE_GOLDEN"):
            os.makedirs(GOLDEN, exist_ok=True)
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
        with open(path, encoding="utf-8") as f:
            self.assertEqual(json.loads(f.read()), json.loads(text))

    def test_golden_modbus_bridge(self):
        self.check_golden("modbus-bridge.json", BRIDGE)

    def test_golden_virtual_plant(self):
        self.check_golden("virtual-plant.json", PLANT)

    def test_network_number_from_interface_and_override(self):
        plan, _ = cplan.build(load(MOTION), MOTION)
        self.assertEqual(plan["networks"][0]["net_id"], 1)  # can1
        plan, _ = cplan.build(load(MOTION), MOTION, overrides={"motion": 0})
        self.assertEqual(plan["networks"][0]["net_id"], 0)
        with self.assertRaises(cplan.ExportFailed) as e:
            cplan.build(load(MOTION), MOTION, overrides={"drives": 1})
        self.assertIn("drives", str(e.exception))

    def test_channels_use_the_editor_names(self):
        plan, _ = cplan.build(load(BRIDGE), BRIDGE)
        dio = [n for n in plan["networks"][0]["nodes"] if n["name"] == "dio"][0]
        self.assertIn({"dir": "in", "mapping": 0x1A00, "index": 0x6000, "sub": 1,
                       "variable": "dio_Read_input_8_bit_1"}, dio["channels"])
        self.assertIn({"dir": "out", "mapping": 0x1600, "index": 0x6200, "sub": 1,
                       "variable": "dio_Write_output_8_bit_1"}, dio["channels"])
        plan, _ = cplan.build(load(BRIDGE), BRIDGE, variables=False)
        self.assertEqual([n["channels"] for n in plan["networks"][0]["nodes"]], [[], []])

    def test_bit_channels_named_in_the_plan(self):
        cfg = load(BRIDGE)
        dio = [n for n in cfg["networks"][0]["nodes"] if n["name"] == "dio"][0]
        dio["tx_pdos"][0]["entries"][0]["bits"] = [{"bit": 3, "name": "jog_x_plus"}, {"bit": 0}]
        plan, _ = cplan.build(cfg, BRIDGE)
        node = [n for n in plan["networks"][0]["nodes"] if n["name"] == "dio"][0]
        channel = [c for c in node["channels"] if c["index"] == 0x6000 and c["sub"] == 1][0]
        self.assertEqual(channel["bits"], [{"bit": 3, "variable": "dio_jog_x_plus"},
                                           {"bit": 0, "variable": "dio_Read_input_8_bit_1_bit0"}])

    def test_not_carried(self):
        plan, _ = cplan.build(load(BRIDGE), BRIDGE)
        notes = {(n["where"], n["setting"]) for n in plan["notes"]}
        self.assertIn(("field/rtd", "emcy_code_location"), notes)
        self.assertIn(("field/master", "bus_state_location"), notes)
        self.assertIn(("config", "bridge"), notes)
        self.assertIn(("field/rtd", "tx_pdos[0].timeout_location"), notes)

    def test_only_master_networks(self):
        plan, files = cplan.build(load(PLANT), PLANT)
        self.assertEqual([n["name"] for n in plan["networks"]], ["io", "motion", "host"])
        self.assertIn({"where": "cell", "setting": "network",
                       "note": "not exported: a slave network stays with canworks: give the other master the "
                               "slave's EDS (canworks-deploy slave-eds)"}, plan["notes"])
        self.assertTrue(all(name.split("/")[0] in ("io", "motion", "host") for name in files))
        names = [n["name"] for net in plan["networks"] for n in net["nodes"]]
        self.assertEqual(len(names), len({n.lower() for n in names}))

    def test_one_network(self):
        plan, files = cplan.build(load(PLANT), PLANT, network="motion")
        self.assertEqual([n["name"] for n in plan["networks"]], ["motion"])
        self.assertTrue(all(name.startswith("motion/") for name in files))

    def test_folder_contents_match_the_dcf_export(self):
        from canworks import dcfexport
        folder, _ = export(self, BRIDGE)
        self.assertEqual(sorted(os.listdir(folder)), ["README.txt", "canworks-codesys.json", "field",
                                                      "import_canworks.py"])
        dcfs, _ = dcfexport.export(load(BRIDGE), BRIDGE)
        for name, text in dcfs.items():
            with open(os.path.join(folder, "field", name), encoding="utf-8", newline="") as f:
                got = f.read()
            strip = lambda t: [l for l in t.splitlines() if not l.startswith("Modification")]
            self.assertEqual(strip(got), strip(text))

    def test_numbers_written_as_strings(self):
        cfg = load(BRIDGE)
        for node in cfg["networks"][0]["nodes"]:
            node["node_id"] = "0x%02x" % node["node_id"]
            for key in ("tx_pdos", "rx_pdos"):
                for i, p in enumerate(node.get(key) or []):
                    p["number"] = str(p.get("number") or i + 1)
        want, want_files = cplan.build(load(BRIDGE), BRIDGE)
        got, got_files = cplan.build(cfg, BRIDGE)
        self.assertEqual(got["networks"], want["networks"])
        self.assertTrue(any(n["channels"] for n in got["networks"][0]["nodes"]))
        self.assertEqual(sorted(got_files), sorted(want_files))

    def test_channel_failure_names_the_field(self):
        cfg = load(BRIDGE)
        dio = [n for n in cfg["networks"][0]["nodes"] if n["name"] == "dio"][0]
        dio["tx_pdos"][0]["entries"][0]["index"] = "zz"
        with self.assertRaises(cplan.ExportFailed) as e:
            cplan.build(cfg, BRIDGE)
        self.assertTrue(any("tx_pdos[0].entries[0].index" in p for _, paths in e.exception.problems for p in paths),
                        e.exception.problems)

    def test_channel_failure_is_reported(self):
        with mock.patch.object(cplan, "channels", side_effect=TypeError("boom")):
            with self.assertRaises(cplan.ExportFailed) as e:
                cplan.build(load(BRIDGE), BRIDGE)
        self.assertIn("I/O channels", str(e.exception))

    def test_config_error_writes_nothing(self):
        cfg = load(BRIDGE)
        cfg["networks"][0]["nodes"][1]["rx_pdos"][0]["entries"][0]["index"] = "0x6000"  # read-only input
        with self.assertRaises(cplan.ExportFailed):
            cplan.build(cfg, BRIDGE)


class CommandLine(unittest.TestCase):
    def test_export(self):
        out = os.path.join(tmpdir(self), "out")
        code, stdout, err = deploy("--config", BRIDGE, "--export-codesys", out)
        self.assertEqual(code, 0, err)
        for name in ("field/node_5.dcf", "field/node_6.dcf", "canworks-codesys.json", "import_canworks.py",
                     "README.txt"):
            self.assertTrue(os.path.isfile(os.path.join(out, name)), name)
        self.assertIn("Execute Script File", stdout)

    def test_unknown_network_override(self):
        out = os.path.join(tmpdir(self), "out")
        code, _, err = deploy("--config", BRIDGE, "--export-codesys", out, "--codesys-net", "drives=1")
        self.assertEqual(code, 1)
        self.assertIn("drives", err)
        self.assertFalse(os.path.exists(out))
        code, _, err = deploy("--config", BRIDGE, "--export-codesys", out, "--codesys-net", "field")
        self.assertIn("NAME=N", err)

    def test_can_interface_option(self):
        out = os.path.join(tmpdir(self), "out")
        code, _, err = deploy("--config", BRIDGE, "--export-codesys", out, "--codesys-can", "field=CAN2")
        self.assertEqual(code, 0, err)
        self.assertEqual(load(os.path.join(out, cplan.PLAN_NAME))["networks"][0]["interface"], "CAN2")
        code, _, err = deploy("--config", BRIDGE, "--export-codesys", os.path.join(out, "b"), "--codesys-can",
                              "drives=CAN2")
        self.assertEqual(code, 1)
        self.assertIn("--codesys-can names drives", err)
        code, _, err = deploy("--config", BRIDGE, "--export-codesys", out, "--codesys-can", "field")
        self.assertIn("NETWORK=OBJECT", err)

    def test_options_need_the_export(self):
        code, _, err = deploy("--config", BRIDGE, "--export-dcf", os.path.join(tmpdir(self), "d"), "--codesys-plc", "PLC")
        self.assertEqual(code, 1)
        self.assertIn("--codesys-plc needs --export-codesys or --codesys-import", err)
        code, _, err = deploy("--config", BRIDGE, "--export-codesys", "x", "--codesys-exe", "c.exe")
        self.assertIn("--codesys-exe needs --codesys-import", err)

    def test_codesys_not_found(self):
        d = tmpdir(self)
        project = os.path.join(d, "p.project")
        open(project, "w").close()
        with mock.patch.object(crun, "find_codesys", return_value=None):
            code, _, err = deploy("--config", BRIDGE, "--codesys-import", project)
        self.assertEqual(code, 1)
        self.assertIn("CODESYS not found", err)

    def test_missing_project_needs_codesys_new(self):
        code, _, err = deploy("--config", BRIDGE, "--codesys-import", os.path.join(tmpdir(self), "none.project"))
        self.assertIn("--codesys-new", err)

    def test_project_path_gets_the_extension(self):
        self.assertEqual(crun.project_path("C:\\Projects.v2\\cell"), "C:\\Projects.v2\\cell.project")
        self.assertEqual(crun.project_path("C:\\Projects\\cell.project"), "C:\\Projects\\cell.project")
        self.assertEqual(crun.project_path("/p/Cell.PROJECT"), "/p/Cell.PROJECT")
        code, _, err = deploy("--config", BRIDGE, "--codesys-import", os.path.join(tmpdir(self), "none"))
        self.assertIn("none.project does not exist", err)

    def run_import(self, report, new=None):
        d = tmpdir(self)
        exe = os.path.join(d, "CODESYS 3.5.22.40", "CODESYS", "Common", "CODESYS.exe")
        os.makedirs(os.path.dirname(exe))
        os.makedirs(os.path.join(d, "CODESYS 3.5.22.40", "CODESYS", "Profiles"))
        open(exe, "w").close()
        open(os.path.join(d, "CODESYS 3.5.22.40", "CODESYS", "Profiles", "CODESYS V3.5 SP22 Patch 4.profile.xml"),
             "w").close()
        project = os.path.join(d, "Line 2", "cell.project")
        os.makedirs(os.path.dirname(project))
        if not new:
            open(project, "w").close()
        folder = os.path.join(d, "export")
        lines = []

        def runner(line):
            lines.append(line)
            plan = load(os.path.join(folder, cplan.PLAN_NAME))
            lines.append(plan)
            with open(os.path.join(folder, cplan.REPORT_NAME), "w", encoding="utf-8") as f:
                f.write(report)
        args = cli.parser().parse_args(["--config", BRIDGE, "--codesys-import", project, "--codesys-dir", folder,
                                        "--codesys-exe", exe] + (["--codesys-new", new] if new else []))
        out = []
        cfg = load(BRIDGE)
        try:
            code = cli._codesys(args, cfg, None, out.append, runner=runner)
            failure = None
        except cli.Failure as e:
            code, failure = 1, str(e)
        return code, failure, out, lines, project, exe

    def test_import_runs_codesys_on_the_project(self):
        code, failure, out, lines, project, exe = self.run_import("result: ok\nwarnings: 0\n")
        self.assertEqual(code, 0, failure)
        self.assertEqual(lines[0], '"%s" --profile="CODESYS V3.5 SP22 Patch 4" --noUI --runscript="%s"'
                         % (exe, os.path.join(os.path.dirname(os.path.dirname(project)), "export",
                                              "import_canworks.py")))
        self.assertEqual(lines[1]["project"], os.path.abspath(project))
        self.assertIsNone(lines[1]["create"])
        self.assertIn("result: ok", out)

    def test_import_new_project(self):
        code, failure, _, lines, project, _ = self.run_import("result: ok\n", new="4096:0000 0004:3.5.22.40")
        self.assertEqual(code, 0, failure)
        self.assertEqual(lines[1]["create"], {"path": os.path.abspath(project),
                                              "device": {"type": 4096, "id": "0000 0004", "version": "3.5.22.40"}})

    def test_import_new_project_without_extension(self):
        d = tmpdir(self)
        exe = os.path.join(d, "CODESYS 3.5.22.40", "CODESYS", "Common", "CODESYS.exe")
        os.makedirs(os.path.dirname(exe))
        os.makedirs(os.path.join(d, "CODESYS 3.5.22.40", "CODESYS", "Profiles"))
        open(exe, "w").close()
        open(os.path.join(d, "CODESYS 3.5.22.40", "CODESYS", "Profiles", "CODESYS V3.5 SP22.profile.xml"), "w").close()
        folder = os.path.join(d, "export")
        plans = []

        def runner(line):
            plans.append(load(os.path.join(folder, cplan.PLAN_NAME)))
            with open(os.path.join(folder, cplan.REPORT_NAME), "w", encoding="utf-8") as f:
                f.write("result: ok\n")
        cfg = load(BRIDGE)
        del cfg["bridge"]
        cfg["codesys"] = {"project": os.path.join(d, "cell"), "create": "4096:0000 0004:3.5.22.40"}
        args = cli.parser().parse_args(["--config", BRIDGE, "--codesys-import", "--codesys-dir", folder,
                                        "--codesys-exe", exe])
        self.assertEqual(cli._codesys(args, cfg, None, [].append, runner=runner), 0)
        self.assertEqual(plans[0]["create"]["path"], os.path.join(d, "cell.project"))

    def test_installed_plc_devices(self):
        root = os.path.join(os.path.dirname(__file__), "data", "codesys-devices", "Devices")
        devices = crun.list_plc_devices([root])
        # PLCs only (no CANbus), newest version first, no hidden or unreadable description.
        self.assertEqual([(d["name"], d["id"], d["version"]) for d in devices], [
            ("CODESYS Control RTE V3", "0000 0002", "3.5.22.40"),
            ("CODESYS Control Win V3 x64", "0000 0004", "3.5.22.40"),
            ("CODESYS Control Win V3 x64", "0000 0004", "3.5.21.0")])
        self.assertEqual(devices[1], {"type": 4096, "id": "0000 0004", "version": "3.5.22.40",
                                      "name": "CODESYS Control Win V3 x64", "vendor": "CODESYS"})
        self.assertEqual(crun.list_plc_devices([os.path.join(tmpdir(self), "none")]), [])

    def test_repository_from_the_install(self):
        d = tmpdir(self)
        exe = os.path.join(d, "CODESYS 3.5.22.40", "CODESYS", "Common", "CODESYS.exe")
        settings = os.path.join(d, "CODESYS 3.5.22.40", "CODESYS", "Settings")
        os.makedirs(os.path.dirname(exe))
        os.makedirs(settings)
        devices = os.path.join(d, "Repo Data", "Devices")
        os.makedirs(devices)
        with open(os.path.join(settings, "RepositoryLocations.ini"), "w", encoding="utf-8-sig") as f:
            f.write("[Configuration]\nRepositoryRoot=%s\n[Default]\nDevices=%s\n" % (d, devices))
        self.assertEqual(crun.repository_roots(exe, environ={}), [devices])
        # No ini: ProgramData's CODESYS\Devices.
        data = os.path.join(d, "ProgramData")
        os.makedirs(os.path.join(data, "CODESYS", "Devices"))
        self.assertEqual(crun.repository_roots(os.path.join(d, "x", "y", "CODESYS.exe"), environ={"PROGRAMDATA": data}),
                         [os.path.join(data, "CODESYS", "Devices")])

    def test_import_report_error(self):
        code, failure, _, _, _, _ = self.run_import("result: error (1)\nwarnings: 0\n\nerror    x\n")
        self.assertEqual(code, 1)
        self.assertIn("reported errors", failure)

    def test_find_codesys_and_profile(self):
        d = tmpdir(self)
        for v in ("3.5.19.0", "3.5.22.40"):
            exe = os.path.join(d, "CODESYS %s" % v, "CODESYS", "Common", "CODESYS.exe")
            os.makedirs(os.path.dirname(exe))
            open(exe, "w").close()
        found = crun.find_codesys({"PROGRAMFILES": d})
        self.assertIn("3.5.22.40", found)
        prof = os.path.join(d, "CODESYS 3.5.22.40", "CODESYS", "Profiles")
        os.makedirs(prof)
        for name in ("CODESYS V3.5 SP22.profile.xml", "CODESYS V3.5 SP22 Patch 4.profile.xml"):
            open(os.path.join(prof, name), "w").close()
        self.assertEqual(crun.find_profile(found), "CODESYS V3.5 SP22 Patch 4")
        self.assertIsNone(crun.find_codesys({}))


class Script(unittest.TestCase):
    """import_canworks.py against the stand-in API."""

    def project(self, world, path=None):
        if path is None:
            path = os.path.join(tmpdir(self), "Line 2", "cell.project")
            os.makedirs(os.path.dirname(path))
            open(path, "w").close()
        return world.project_with_plc(path)

    def test_open_project_new_canbus_and_nodes(self):
        folder, _ = export(self, MOTION)
        w = fake_codesys.World()
        proj = self.project(w)
        report = w.run(folder, primary=proj)
        self.assertTrue(report.startswith("result: ok"), report)
        plc = proj.find("PLC")[0]
        bus = plc.find("CANbus")[0]
        self.assertEqual((fake_codesys.param(bus, 2).value, fake_codesys.param(bus, 0).value), ("1", "500"))
        mgr = bus.find("CANopen_Manager")[0]
        self.assertEqual(fake_codesys.param(mgr, 288).value, "1")
        self.assertEqual([c.get_name() for c in mgr.get_children()], ["x", "y", "z", "io"])
        x = mgr.find("x")[0]
        self.assertEqual(fake_codesys.param(x, 1).value, "4")
        self.assertEqual(fake_codesys.channels_of(x)[0x11A00010], "x_Statusword")
        opts = {e.identifier: e.value for e in fake_codesys.param(x, 2)}
        self.assertEqual(opts["FLAG_Optional"], "FALSE")  # mandatory in the config
        self.assertFalse(proj.saved)  # the IDE run leaves saving to the user
        self.assertEqual(w.builds, 1)
        imports = [e[1] for e in w.log if e[0] == "import"]
        adds = [e for e in w.log if e[0] in ("import", "add")]
        # every node is added right after its own DCF is installed
        self.assertEqual([a[0] for a in adds[-8:]], ["import", "add"] * 4)
        self.assertEqual(imports, ["node_4.dcf", "node_5.dcf", "node_6.dcf", "node_10.dcf"])

    def test_virtual_plant_plan(self):
        """The example's plan, every master network on its own CANbus (codesys-export: CI)."""
        folder, _ = export(self, PLANT)
        w = fake_codesys.World()
        proj = self.project(w)
        report = w.run(folder, primary=proj)
        self.assertTrue(report.startswith("result: ok"), report)
        self.assertIn("built    0 errors, 0 warnings", report)
        plc = proj.find("PLC")[0]
        buses = [plc.find(name)[0] for name in ("CANbus", "CANbus_2", "CANbus_3")]
        self.assertEqual([(fake_codesys.param(b, 2).value, fake_codesys.param(b, 0).value) for b in buses],
                         [("0", "250"), ("1", "500"), ("2", "250")])
        self.assertEqual([[c.get_name() for c in b.get_children()[0].get_children()] for b in buses],
                         [["rtd", "dio", "new_io"], ["drive"], ["cell"]])
        drive = buses[1].get_children()[0].find("drive")[0]
        self.assertEqual(fake_codesys.channels_of(drive)[0x11A00010], "motion_drive_Statusword")
        self.assertEqual([e[1] for e in w.log if e[0] == "import"],
                         ["node_5.dcf", "node_6.dcf", "node_7.dcf", "node_4.dcf", "node_20.dcf"])

    def test_no_project_open(self):
        folder, _ = export(self, MOTION)
        w = fake_codesys.World()
        report = w.run(folder)
        self.assertIn("open a project in CODESYS first", report)
        self.assertTrue(report.startswith("result: error"))
        self.assertEqual(w.log, [])

    def test_command_line_opens_and_saves(self):
        folder, _ = export(self, BRIDGE)
        w = fake_codesys.World()
        proj = self.project(w)
        set_plan(folder, project=proj.path)
        report = w.run(folder)
        self.assertTrue(report.startswith("result: ok"), report)
        self.assertTrue(proj.saved)
        self.assertTrue(proj.closed)

    def test_command_line_project_in_use(self):
        folder, _ = export(self, BRIDGE)
        w = fake_codesys.World()
        proj = self.project(w)
        w.in_use.add(proj.path)
        set_plan(folder, project=proj.path)
        report = w.run(folder)
        self.assertTrue(report.startswith("result: error"), report)
        self.assertIn("is open in CODESYS (The selected project is currently in use", report)
        self.assertIn("close it there first", report)
        self.assertNotIn("unexpected", report)
        self.assertNotIn("opened", report)

    def test_command_line_creates_a_project(self):
        folder, _ = export(self, BRIDGE)
        w = fake_codesys.World()
        new = os.path.join(tmpdir(self), "new.project")
        set_plan(folder, create={"path": new,
                                 "device": {"type": 4096, "id": "0000 0004", "version": "3.5.22.40"}})
        report = w.run(folder)
        self.assertTrue(report.startswith("result: ok"), report)
        proj = w.stored[new]
        self.assertTrue(proj.saved)
        self.assertEqual([c.get_name() for c in proj.find("PLC")[0].find("CANbus")[0].get_children()],
                         ["CANopen_Manager"])

    def test_device_with_its_own_can_interfaces(self):
        folder, _ = export(self, MOTION)  # network number 1
        w = fake_codesys.World(canbus_version="4.2.0.0", manager_versions=("4.2.0.0", "4.4.0.0"))
        proj = self.project(w)
        plc = proj.find("PLC")[0]
        plc.add("CAN0", 15, "181015", "4.2.0.0")
        plc.add("CAN1", 15, "181015", "4.2.0.0")
        fake_codesys.param(plc.find("CAN1")[0], 2).value = "1"
        report = w.run(folder, primary=proj)
        self.assertTrue(report.startswith("result: ok"), report)
        self.assertEqual([c.get_name() for c in plc.get_children()], ["CAN0", "CAN1"])
        self.assertEqual(plc.find("CAN0")[0].get_children(), [])
        mgr = plc.find("CAN1")[0].get_children()[0]
        self.assertEqual(mgr.ident.version, "4.2.0.0")  # the manager matches the device's CANbus

    def test_highest_installed_versions(self):
        folder, _ = export(self, BRIDGE)
        w = fake_codesys.World(canbus_version="4.4.0.0", manager_versions=("4.3.0.0", "4.5.0.0"))
        w.repo.devices.append(fake_codesys.DeviceId(15, "181015", "4.10.0.0"))
        proj = self.project(w)
        report = w.run(folder, primary=proj)
        self.assertTrue(report.startswith("result: ok"), report)
        bus = proj.find("PLC")[0].find("CANbus")[0]
        self.assertEqual((bus.ident.version, bus.get_children()[0].ident.version), ("4.10.0.0", "4.5.0.0"))

    def test_rerun_replaces_managed_nodes_and_keeps_others(self):
        folder, _ = export(self, BRIDGE)
        w = fake_codesys.World()
        proj = self.project(w)
        w.run(folder, primary=proj)
        mgr = proj.find("PLC")[0].find("CANbus")[0].get_children()[0]
        mgr.add("by_hand", 18, w.repo.devices[-1].id, w.repo.devices[-1].version)
        fake_codesys.param(mgr.find("by_hand")[0], 1).value = "20"
        report = w.run(folder, primary=proj)
        self.assertTrue(report.startswith("result: ok"), report)
        bus = proj.find("PLC")[0].find("CANbus")
        self.assertEqual(len(bus), 1)
        self.assertEqual(len(bus[0].get_children()), 1)
        self.assertEqual(sorted(c.get_name() for c in mgr.get_children()), ["by_hand", "dio", "rtd"])
        self.assertIn("replaced network field node 5 (rtd)", report)
        self.assertIn("by_hand (node 20) is not in the canworks config", report)

    def test_missing_parameter_is_reported(self):
        folder, _ = export(self, MOTION)
        w = fake_codesys.World(missing_manager_ids=(288,))
        report = w.run(folder, primary=self.project(w))
        self.assertTrue(report.startswith("result: ok"), report)
        self.assertIn("master node ID not set: this CODESYS has no parameter 288", report)

    def test_bit_channels_mapped_or_reported(self):
        cfg = load(BRIDGE)
        dio = [n for n in cfg["networks"][0]["nodes"] if n["name"] == "dio"][0]
        dio["tx_pdos"][0]["entries"][0]["bits"] = [{"bit": 3, "name": "jog_x_plus"}]
        dio["rx_pdos"][0]["entries"][0]["bits"] = [{"bit": 1, "name": "lamp"}]
        folder = os.path.join(tmpdir(self), "codesys")
        files, _ = cplan.export_files(cfg, BRIDGE)
        crun.write_folder(files, folder)
        w = fake_codesys.World()
        report = w.run(folder, primary=self.project(w))
        self.assertTrue(report.startswith("result: ok"), report)
        # The stand-in's channels have no bit elements: the report says what to map by hand.
        self.assertIn("0x6000:1 (PDO mapping 0x1A00) bit 3 has no bit channel here: map dio_jog_x_plus to it by hand",
                      report)
        # CODESYS refuses an output bit's variable while its channel has one: the output maps its bits only.
        self.assertIn("0x6200:1 (PDO mapping 0x1600): dio_Write_output_8_bit_1 left unmapped, the output goes through its bits",
                      report)
        self.assertNotIn("0x6200:1 (PDO mapping 0x1600) -> ", report)

    def test_variable_name_taken(self):
        folder, _ = export(self, BRIDGE)
        w = fake_codesys.World()
        w.globals.append("rtd_AI0_Input_PV")
        proj = self.project(w)
        set_plan(folder, project=proj.path)
        report = w.run(folder)
        self.assertTrue(report.startswith("result: error"), report)
        self.assertIn("Duplicate definition of identifier 'rtd_ai0_input_pv'", report)
        self.assertIn("not saved because of the errors above", report)
        self.assertFalse(proj.saved)

    def test_several_devices_need_a_name(self):
        folder, _ = export(self, BRIDGE)
        w = fake_codesys.World()
        proj = self.project(w)
        proj.add("HMI", 4096, "0000 0004", "3.5.22.40")
        report = w.run(folder, primary=proj)
        self.assertIn("several devices (PLC, HMI) and no active application", report)
        self.assertIn("Set Active Application", report)
        self.assertEqual(proj.find("PLC")[0].get_children(), [])
        set_plan(folder, plc="HMI")
        report = w.run(folder, primary=proj)
        self.assertTrue(report.startswith("result: ok"), report)
        self.assertEqual(len(proj.find("HMI")[0].get_children()), 1)

    def two_devices(self, w):
        proj = self.project(w)
        proj.add("HMI", 4096, "0000 0004", "3.5.22.40")
        plc, hmi = proj.find("PLC")[0], proj.find("HMI")[0]
        return proj, plc, hmi

    def test_active_device_gets_the_bus(self):
        folder, _ = export(self, BRIDGE)
        w = fake_codesys.World()
        proj, plc, hmi = self.two_devices(w)
        w.add_application(proj, plc, active=False)
        w.add_application(proj, hmi)
        report = w.run(folder, primary=proj)
        self.assertTrue(report.startswith("result: ok"), report)
        self.assertIn("device   HMI (active application)", report)
        self.assertEqual(len(hmi.find("CANbus")), 1)
        self.assertEqual(plc.find("CANbus"), [])

    def test_named_device_differs_from_active(self):
        folder, _ = export(self, BRIDGE)
        set_plan(folder, plc="PLC")
        w = fake_codesys.World()
        proj, plc, hmi = self.two_devices(w)
        w.add_application(proj, hmi)
        report = w.run(folder, primary=proj)
        self.assertIn("device   PLC (named in canworks-codesys.json)", report)
        self.assertIn("the active application is on HMI, so the build checks HMI, not PLC", report)
        self.assertEqual(len(plc.find("CANbus")), 1)

    def test_nested_active_device(self):
        folder, _ = export(self, BRIDGE)
        w = fake_codesys.World()
        proj, plc, hmi = self.two_devices(w)
        hmi.add("Controller", 4096, "0000 0004", "3.5.22.40")
        inner = hmi.find("Controller")[0]
        w.add_application(proj, inner)
        report = w.run(folder, primary=proj)
        self.assertTrue(report.startswith("result: ok"), report)
        self.assertIn("device   Controller (active application)", report)
        self.assertEqual(len(inner.find("CANbus")), 1)

    def test_only_device_without_application(self):
        folder, _ = export(self, BRIDGE)
        w = fake_codesys.World()
        proj = self.project(w)
        report = w.run(folder, primary=proj)
        self.assertIn("device   PLC (only device)", report)

    def test_switching_the_active_device_warns(self):
        folder, _ = export(self, BRIDGE)
        w = fake_codesys.World()
        proj, plc, hmi = self.two_devices(w)
        w.add_application(proj, plc)
        self.assertTrue(w.run(folder, primary=proj).startswith("result: ok"))
        w.add_application(proj, hmi)
        report = w.run(folder, primary=proj)
        self.assertIn("device PLC also has a CANopen Manager on network number 0", report)
        self.assertEqual(len(plc.find("CANbus")[0].get_children()[0].get_children()), 2)  # PLC kept its nodes
        self.assertEqual(len(hmi.find("CANbus")), 1)

    def display(self, w, accepts_canbus=True, names=("CAN",)):
        """A device whose description brings Communication > CAN and refuses a CANbus at its root."""
        proj = self.project(w)
        dev = proj.find("PLC")[0]
        dev.accepts = set()
        comm = w.add_object(dev, "Communication", 9000, accepts=set())
        w.add_object(comm, "Ethernet", 9001, accepts=set())
        cans = [w.add_object(comm, n, 9002, accepts={15} if accepts_canbus else {16}) for n in names]
        return proj, dev, cans

    def test_canbus_under_the_devices_can_interface(self):
        folder, _ = export(self, BRIDGE)
        w = fake_codesys.World()
        proj, dev, (can,) = self.display(w)
        report = w.run(folder, primary=proj)
        self.assertTrue(report.startswith("result: ok"), report)
        self.assertIn("under PLC/Communication/CAN, network number 0", report)
        bus = can.find("CANbus")[0]
        self.assertEqual(len(bus.find("CANopen_Manager")), 1)
        report = w.run(folder, primary=proj)  # re-run reuses it
        self.assertTrue(report.startswith("result: ok"), report)
        self.assertEqual(len(can.get_children()), 1)

    def test_manager_directly_under_the_can_interface(self):
        folder, _ = export(self, BRIDGE)
        w = fake_codesys.World()
        proj, dev, (can,) = self.display(w, accepts_canbus=False)
        report = w.run(folder, primary=proj)
        self.assertTrue(report.startswith("result: ok"), report)
        self.assertIn("directly under the CAN interface PLC/Communication/CAN", report)
        mgr = can.find("CANopen_Manager")[0]
        self.assertEqual(len(mgr.get_children()), 2)
        self.assertIn("CAN interface CAN has no network number parameter", report)
        report = w.run(folder, primary=proj)  # re-run reuses the interface and its manager
        self.assertTrue(report.startswith("result: ok"), report)
        self.assertIn("reused   network field: CAN interface PLC/Communication/CAN as the bus", report)
        self.assertEqual([c.get_name() for c in can.get_children()], ["CANopen_Manager"])
        self.assertEqual(len(mgr.get_children()), 2)

    def test_network_number_on_a_can_interface_bus(self):
        folder, _ = export(self, MOTION)  # network number 1
        w = fake_codesys.World()
        proj, dev, (can,) = self.display(w, accepts_canbus=False)
        can.connectors = [fake_codesys.Connector([]), fake_codesys.Connector(
            [fake_codesys.Param(0, "Baudrate", "250"), fake_codesys.Param(2, "NetID", "0")])]
        report = w.run(folder, primary=proj)
        self.assertTrue(report.startswith("result: ok"), report)
        self.assertEqual((fake_codesys.param(can, 2).value, fake_codesys.param(can, 0).value), ("1", "500"))

    def test_several_can_interfaces(self):
        folder, _ = export(self, MOTION)  # network number 1
        w = fake_codesys.World()
        proj, dev, (can0, can1) = self.display(w, names=("CAN0", "CAN1"))
        report = w.run(folder, primary=proj)
        self.assertTrue(report.startswith("result: ok"), report)
        self.assertEqual(can0.get_children(), [])
        self.assertEqual(len(can1.find("CANbus")), 1)

    def test_several_can_interfaces_without_a_match(self):
        folder, _ = export(self, MOTION)
        w = fake_codesys.World()
        proj, dev, cans = self.display(w, names=("CAN_A", "CAN_B"))
        report = w.run(folder, primary=proj)
        self.assertIn("several CAN interfaces (PLC/Communication/CAN_A, PLC/Communication/CAN_B)", report)
        self.assertIn("--codesys-can motion=OBJECT", report)
        set_plan(folder, networks=[dict(n, interface="CAN_B") for n in load(
            os.path.join(folder, cplan.PLAN_NAME))["networks"]])
        report = w.run(folder, primary=proj)
        self.assertTrue(report.startswith("result: ok"), report)
        self.assertEqual(len(cans[1].find("CANbus")), 1)

    def test_nowhere_to_add_the_bus(self):
        folder, _ = export(self, BRIDGE)
        w = fake_codesys.World()
        proj, dev, (can,) = self.display(w)
        can.accepts = set()
        report = w.run(folder, primary=proj)
        self.assertTrue(report.startswith("result: error"), report)
        self.assertIn("CODESYS takes neither a CANbus nor a CANopen Manager under PLC/Communication/CAN", report)
        self.assertIn("cannot be added or inserted here", report)
        self.assertIn("CANbus tried: 181015 4.4.0.0: Exception was raised: The device cannot be added", report)
        self.assertIn("PLC/Communication/Ethernet", report)

    def vendor_display(self, w, proj, name):
        """A display whose Communication > CAN takes only its vendor's CANbus."""
        proj.add(name, 4096, "0000 0004", "3.5.22.40")
        dev = proj.find(name)[0]
        dev.accepts = set()
        comm = w.add_object(dev, "Communication", 9000, accepts=set())
        return dev, w.add_object(comm, "CAN", 9002, accepts={(15, "vendor_bus")})

    def test_vendor_canbus_from_another_device(self):
        folder, _ = export(self, BRIDGE)
        w = fake_codesys.World()
        w.repo.devices += [fake_codesys.DeviceId(15, "vendor_bus", "2.1.0.0"),
                           fake_codesys.DeviceId(16, "vendor_mgr", "2.1.0.0")]
        proj = w.projects.create(os.path.join(tmpdir(self), "rig.project"))
        template, tcan = self.vendor_display(w, proj, "TemplateDevice")
        tcan.add("CANbus_display", 15, "vendor_bus", "2.1.0.0")
        tcan.find("CANbus_display")[0].add("CANopen_Manager", 16, "vendor_mgr", "2.1.0.0")
        app, can = self.vendor_display(w, proj, "ExampleApp")
        w.add_application(proj, app)
        report = w.run(folder, primary=proj)
        self.assertTrue(report.startswith("result: ok"), report)
        self.assertIn("(vendor_bus 2.1.0.0, as on device TemplateDevice) under ExampleApp/Communication/CAN", report)
        bus = can.find("CANbus")[0]
        self.assertEqual(bus.get_device_identification().id, "vendor_bus")
        mgr = bus.find("CANopen_Manager")[0]
        self.assertEqual(mgr.get_device_identification().id, "vendor_mgr")
        self.assertEqual(len(mgr.get_children()), 2)
        self.assertFalse([e for e in w.log if e[0] == "add" and e[4] == "181015"])  # the standard one not tried

    def test_vendor_canbus_installed_only(self):
        folder, _ = export(self, BRIDGE)
        w = fake_codesys.World()
        w.repo.devices.append(fake_codesys.DeviceId(15, "vendor_bus", "2.1.0.0"))
        proj = w.projects.create(os.path.join(tmpdir(self), "rig.project"))
        app, can = self.vendor_display(w, proj, "ExampleApp")
        report = w.run(folder, primary=proj)
        self.assertTrue(report.startswith("result: ok"), report)
        self.assertIn("(vendor_bus 2.1.0.0, installed)", report)
        self.assertEqual([c.get_device_identification().id for c in can.get_children()], ["vendor_bus"])

    def test_many_other_devices_one_warning(self):
        folder, _ = export(self, BRIDGE)  # network number 0
        w = fake_codesys.World()
        proj = self.project(w)
        for i in range(7):
            proj.add("Variant%d" % i, 4096, "0000 0004", "3.5.22.40")
            dev = proj.find("Variant%d" % i)[0]
            dev.add("CANbus", 15, "181015", "4.4.0.0")
            dev.find("CANbus")[0].add("CANopen_Manager", 16, "181016", "4.4.0.0")
        w.add_application(proj, proj.find("PLC")[0])
        report = w.run(folder, primary=proj)
        self.assertTrue(report.startswith("result: ok"), report)
        self.assertIn("7 other devices also have a CANopen Manager on network number 0 and were left as they are: "
                      "Variant0, Variant1, Variant2, Variant3, Variant4 and 2 more", report)
        self.assertEqual(report.count("also ha"), 1)

    def test_scanner_is_not_a_can_interface(self):
        folder, _ = export(self, BRIDGE)
        w = fake_codesys.World()
        proj = self.project(w)
        w.add_object(proj.find("PLC")[0], "Scanner", 9003, accepts=set())
        report = w.run(folder, primary=proj)
        self.assertTrue(report.startswith("result: ok"), report)

    def test_canopen_device_on_the_canbus(self):
        folder, _ = export(self, BRIDGE)  # network number 0
        w = fake_codesys.World()
        proj = self.project(w)
        plc = proj.find("PLC")[0]
        plc.add("CANbus", 15, "181015", "4.4.0.0")
        plc.find("CANbus")[0].add("Local", 17, "0000 0012", "4.4.0.0")
        report = w.run(folder, primary=proj)
        self.assertIn("holds a CANopen device (CODESYS as a slave)", report)
        self.assertTrue(report.startswith("result: error"))

    def test_script_has_no_python3_only_syntax(self):
        # CODESYS runs IronPython 2.7: no f-strings, no nonlocal, no keyword-only arguments.
        with open(cplan.SCRIPT_PATH, encoding="utf-8") as f:
            text = f.read()
        self.assertNotRegex(text, r"\bf\"|\bf'|\bnonlocal\b|, \*,|async |await ")
        compile(text, "import_canworks.py", "exec")


if __name__ == "__main__":
    unittest.main()
