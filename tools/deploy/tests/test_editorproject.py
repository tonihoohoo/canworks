"""An editor project made from a CANopen config (add-editor-project-template
tasks 2.1-2.2)."""

import json
import os
import subprocess
import sys
import unittest
from unittest import mock

from canworks import cli, editorproject

from .helpers import REPO, fake_editor_cli, pingpong_config, tmpdir

RTD = os.path.join(REPO, "config", "rtd-sensor")
RTD_CONFIG = os.path.join(RTD, "canopen_config.json")


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


class Interval(unittest.TestCase):
    def test_accepted(self):
        for text in ("T#20ms", "t#10MS", "TIME#1s", "T#1s_500ms", "T#1.5ms", "T#1m"):
            self.assertEqual(editorproject.check_interval(text), text)

    def test_refused(self):
        for text in ("10ms", "T#0ms", "T#500us", "T#", "T#20", "T#20 ms", "", None, "T#20msx"):
            with self.assertRaises(editorproject.NewProjectError, msg=text):
                editorproject.check_interval(text)


class Create(unittest.TestCase):
    def setUp(self):
        self.dir = tmpdir(self)
        self.cli = fake_editor_cli(self.dir)
        patcher = mock.patch.dict(os.environ, {"OPENPLC_CLI": self.cli})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.target = os.path.join(self.dir, "work", "rtd-monitor")
        os.makedirs(os.path.dirname(self.target))

    def args(self):
        return load(os.path.join(self.dir, "cli-args.json"))

    def test_rtd(self):
        lines = []
        path, decls = editorproject.create(load(RTD_CONFIG), RTD_CONFIG, self.target, progress=lines.append,
                                           runtime_address="plc.local")
        self.assertEqual(path, self.target)
        self.assertEqual(self.args(), ["create", "rtd-monitor", "--path=" + os.path.dirname(self.target),
                                       "--language=st", "--time=T#20ms", "--no-json"])
        self.assertTrue(lines[0].startswith("$ "))
        device = load(os.path.join(self.target, "devices", "configuration.json"))
        self.assertEqual(device, {"deviceBoard": "OpenPLC Runtime v4", "communicationPort": "",
                                  "selectedPlatformOptions": {}, "runtimeIpAddress": "plc.local"})
        self.assertEqual(load(os.path.join(self.target, "project.json"))["meta"]["name"], "rtd-monitor")
        main = read(os.path.join(self.target, "pous", "programs", "main.st"))
        self.assertTrue(main.startswith("PROGRAM main\n  VAR\n    rtd_ok "), main)
        self.assertIn("    rtd_ok           : BOOL AT %IX10.0; (* node rtd (5): operational *)\n", main)
        self.assertIn("    rtd_AI0_Input_PV : INT AT %IW100; (* node rtd (5) TPDO1 0x7130:1 AI0_Input_PV *)\n", main)
        self.assertIn(" : USINT AT %IB103;", main)
        self.assertTrue(main.endswith("  END_VAR\n\n%s\n\nEND_PROGRAM" % editorproject.BODY), main)
        self.assertEqual(len(decls), 9)
        self.assertEqual(main.count(" AT %"), 9)
        canopen = load(os.path.join(self.target, "canworks", "canworks.json"))
        self.assertEqual(canopen["nodes"][0]["eds"], "rtd8.eds")
        self.assertTrue(os.path.isfile(os.path.join(self.target, "canworks", "rtd8.eds")))
        for d in ("pous/functions", "pous/function-blocks", "datatypes"):
            self.assertTrue(os.path.isdir(os.path.join(self.target, d)))

    def test_interval_and_no_address(self):
        editorproject.create(load(RTD_CONFIG), RTD_CONFIG, self.target, interval="T#10ms")
        self.assertIn("--time=T#10ms", self.args())
        self.assertNotIn("runtimeIpAddress", load(os.path.join(self.target, "devices", "configuration.json")))

    def test_no_locations(self):
        cfg = load(RTD_CONFIG)
        node = cfg["nodes"][0]
        del node["status_location"]
        for p in node["tx_pdos"]:
            for e in p["entries"]:
                del e["iec_location"]
        with mock.patch("canworks.contract.check_config") as check:
            check.return_value = mock.Mock(ok=True, errors=[])
            with mock.patch("canworks.project.contract.check_config", check):
                editorproject.create(cfg, RTD_CONFIG, self.target)
        main = read(os.path.join(self.target, "pous", "programs", "main.st"))
        self.assertTrue(main.startswith("PROGRAM main\n  VAR\n  END_VAR\n"), main)

    def test_existing_folder_untouched(self):
        os.makedirs(self.target)
        with open(os.path.join(self.target, "keep.txt"), "w") as f:
            f.write("mine")
        with self.assertRaisesRegex(editorproject.NewProjectError, "already exists"):
            editorproject.create(load(RTD_CONFIG), RTD_CONFIG, self.target)
        self.assertEqual(os.listdir(self.target), ["keep.txt"])
        self.assertFalse(os.path.exists(os.path.join(self.dir, "cli-args.json")))
        # An empty folder is refused too: openplc-cli create refuses it.
        empty = os.path.join(self.dir, "work", "empty")
        os.makedirs(empty)
        with self.assertRaisesRegex(editorproject.NewProjectError, "already exists"):
            editorproject.create(load(RTD_CONFIG), RTD_CONFIG, empty)

    def test_invalid_config_runs_nothing(self):
        cfg = load(RTD_CONFIG)
        cfg["nodes"][0]["tx_pdos"][0]["entries"][0]["type"] = "INTEGER32"
        with self.assertRaises(editorproject.NewProjectError):
            editorproject.create(cfg, RTD_CONFIG, self.target)
        self.assertFalse(os.path.exists(self.target))
        self.assertFalse(os.path.exists(os.path.join(self.dir, "cli-args.json")))

    def test_bad_interval_runs_nothing(self):
        with self.assertRaisesRegex(editorproject.NewProjectError, "IEC duration"):
            editorproject.create(load(RTD_CONFIG), RTD_CONFIG, self.target, interval="10ms")
        self.assertFalse(os.path.exists(self.target))

    def test_failure_after_create_removes_folder(self):
        with mock.patch("canworks.project.write",
                        side_effect=editorproject.project_mod.ProjectError("disk full")):
            with self.assertRaisesRegex(editorproject.NewProjectError, "disk full.*removed"):
                editorproject.create(load(RTD_CONFIG), RTD_CONFIG, self.target)
        self.assertTrue(os.path.exists(os.path.join(self.dir, "cli-args.json")))
        self.assertFalse(os.path.exists(self.target))

    def test_cli_fails(self):
        fake_editor_cli(self.dir, fail=True)
        with self.assertRaisesRegex(editorproject.NewProjectError, "(?s)exit 4.*on purpose"):
            editorproject.create(load(RTD_CONFIG), RTD_CONFIG, self.target)
        self.assertFalse(os.path.exists(self.target))

    def test_cli_missing(self):
        with mock.patch.dict(os.environ, {"OPENPLC_CLI": os.path.join(self.dir, "nope")}):
            with self.assertRaisesRegex(editorproject.NewProjectError, "install-cli.*OPENPLC_CLI"):
                editorproject.create(load(RTD_CONFIG), RTD_CONFIG, self.target)
        self.assertFalse(os.path.exists(self.target))


class FindCli(unittest.TestCase):
    """openplc-cli found by its bare name on PATH, as the editor installs it
    (a .cmd or PowerShell shim on Windows, which Windows will not start by a
    bare name)."""

    def setUp(self):
        self.dir = tmpdir(self)
        self.bin = os.path.join(self.dir, "bin")
        os.makedirs(self.bin)
        self.target = os.path.join(self.dir, "work", "rtd-monitor")
        os.makedirs(os.path.dirname(self.target))
        patcher = mock.patch.dict(os.environ, {"PATH": self.bin + os.pathsep + os.environ.get("PATH", "")})
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop("OPENPLC_CLI", None)

    def create(self):
        path, _ = editorproject.create(load(RTD_CONFIG), RTD_CONFIG, self.target)
        self.assertTrue(os.path.isfile(os.path.join(path, "project.json")))
        self.assertEqual(load(os.path.join(self.bin, "cli-args.json"))[:2], ["create", "rtd-monitor"])

    def test_bare_name_on_path(self):
        fake_editor_cli(self.bin)
        self.assertEqual(editorproject.cli_program(), "openplc-cli")
        self.create()

    @unittest.skipUnless(os.name == "nt", "PowerShell shims exist on Windows only")
    def test_powershell_shim_on_path(self):
        script = fake_editor_cli(self.dir)
        py = script[:-len(".cmd")] + ".py"
        with open(os.path.join(self.bin, "openplc-cli.ps1"), "w", encoding="utf-8") as f:
            f.write('& "%s" "%s" @args\r\nexit $LASTEXITCODE\r\n' % (sys.executable, py))
        self.assertEqual(editorproject.cli_command("openplc-cli")[0], "powershell")
        path, _ = editorproject.create(load(RTD_CONFIG), RTD_CONFIG, self.target)
        self.assertTrue(os.path.isfile(os.path.join(path, "project.json")))
        self.assertEqual(load(os.path.join(self.dir, "cli-args.json"))[:2], ["create", "rtd-monitor"])

    def test_not_on_path(self):
        self.assertIsNone(editorproject.cli_command("openplc-cli-not-installed"))

    def test_cmd_special_characters_refused_on_windows(self):
        fake_editor_cli(self.bin)
        target = os.path.join(self.dir, "R&D", "rtd-monitor")
        os.makedirs(os.path.dirname(target))
        with mock.patch.object(editorproject, "WINDOWS", True):
            with self.assertRaisesRegex(editorproject.NewProjectError, "contains '&'"):
                editorproject.create(load(RTD_CONFIG), RTD_CONFIG, target)
            self.assertFalse(os.path.exists(os.path.join(self.bin, "cli-args.json")), "nothing run")
            for c in '&|^%<>"':
                self.assertIn("'%s'" % c, editorproject.unsafe_for_cmd(["openplc-cli", "compile", "C:\\a%sb" % c]))
            self.assertIsNone(editorproject.unsafe_for_cmd(["openplc-cli", "compile", "C:\\R and D\\pump"]))
        self.assertIsNone(editorproject.unsafe_for_cmd(["openplc-cli", "compile", "/home/r&d"]))  # not Windows

    def test_cmd_special_characters_refused_by_deploy_on_windows(self):
        fake_editor_cli(self.bin)
        with mock.patch.object(editorproject, "WINDOWS", True), mock.patch.object(subprocess, "call") as call:
            with self.assertRaisesRegex(cli.Failure, "contains '&'"):
                cli.build_project(os.path.join(self.dir, "R&D"), "openplc-v4", lambda m: None)
        call.assert_not_called()


@unittest.skipUnless(os.environ.get("CANWORKS_EDITOR_CLI"),
                     "set CANWORKS_EDITOR_CLI to a real openplc-cli to create and compile with the editor")
class RealEditor(unittest.TestCase):
    """Creates projects with the installed editor and builds them."""

    def test_create_and_compile(self):
        cli = os.environ["CANWORKS_EDITOR_CLI"]
        d = tmpdir(self)
        pp = os.path.join(d, "pp")
        os.makedirs(pp)
        configs = {"rtd": RTD_CONFIG, "pingpong": pingpong_config(pp)}
        with mock.patch.dict(os.environ, {"OPENPLC_CLI": cli}):
            for name, config in configs.items():
                project = os.path.join(d, name)
                editorproject.create(load(config), config, project)
                run = subprocess.run([cli, "compile", project, "--target", editorproject.TARGET, "--no-json"],
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
                self.assertEqual(run.returncode, 0, run.stdout)


if __name__ == "__main__":
    unittest.main()
