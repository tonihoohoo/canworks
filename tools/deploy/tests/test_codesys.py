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
GANTRY = os.path.join(EXAMPLES, "gantry-cell", "canworks", "canworks.json")
BRIDGE = os.path.join(EXAMPLES, "modbus-bridge", "canworks.json")
PLANT = os.path.join(EXAMPLES, "virtual-plant", "canworks", "canworks.json")


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

    def test_golden_gantry_cell(self):
        self.check_golden("gantry-cell.json", GANTRY)

    def test_golden_modbus_bridge(self):
        self.check_golden("modbus-bridge.json", BRIDGE)

    def test_golden_virtual_plant(self):
        self.check_golden("virtual-plant.json", PLANT)

    def test_network_number_from_interface_and_override(self):
        plan, _ = cplan.build(load(GANTRY), GANTRY)
        self.assertEqual(plan["networks"][0]["net_id"], 1)  # can1
        plan, _ = cplan.build(load(GANTRY), GANTRY, overrides={"motion": 0})
        self.assertEqual(plan["networks"][0]["net_id"], 0)
        with self.assertRaises(cplan.ExportFailed) as e:
            cplan.build(load(GANTRY), GANTRY, overrides={"drives": 1})
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
                       "note": "not exported: a slave network: use `canworks-deploy slave-eds` for the other "
                               "master's tool"}, plan["notes"])
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
        folder, _ = export(self, GANTRY)
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

    def test_no_project_open(self):
        folder, _ = export(self, GANTRY)
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
        folder, _ = export(self, GANTRY)  # network number 1
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
        folder, _ = export(self, GANTRY)
        w = fake_codesys.World(missing_manager_ids=(288,))
        report = w.run(folder, primary=self.project(w))
        self.assertTrue(report.startswith("result: ok"), report)
        self.assertIn("master node ID not set: this CODESYS has no parameter 288", report)

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
        self.assertIn("several devices (PLC, HMI)", report)
        set_plan(folder, plc="HMI")
        report = w.run(folder, primary=proj)
        self.assertTrue(report.startswith("result: ok"), report)
        self.assertEqual(len(proj.find("HMI")[0].get_children()), 1)

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
