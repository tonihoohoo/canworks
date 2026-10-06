"""--into-project: a config and its EDS files in an editor project's canopen/
folder (canopen-editor-upload: "Put a config into an editor project")."""

import json
import os
import shutil
import subprocess
import unittest

from openplc_canopen_deploy import contract, project

from .helpers import REPO, pingpong_config, tmpdir
from .test_deploy import deploy

RTD = os.path.join(REPO, "config", "rtd-sensor")
CANOPEN_CHECK = os.environ.get("CANOPEN_CHECK", os.path.join(REPO, "build", "canopen_check"))


def read(path):
    with open(path, "rb") as f:
        return f.read()


class IntoProject(unittest.TestCase):
    def setUp(self):
        self.dir = tmpdir(self)
        self.project = os.path.join(self.dir, "rtd-monitor")
        os.makedirs(self.project)
        with open(os.path.join(self.project, "project.json"), "w") as f:
            f.write("{}\n")
        self.canopen = os.path.join(self.project, "canopen")

    def test_rtd_sensor(self):
        config = os.path.join(RTD, "canopen_config.json")
        code, out, err = deploy("--config", config, "--into-project", self.project)
        self.assertEqual(code, 0, err)
        self.assertEqual(sorted(os.listdir(self.canopen)), ["canopen.json", "rtd8.eds"])
        with open(os.path.join(self.canopen, "canopen.json"), encoding="utf-8") as f:
            cfg = json.load(f)
        self.assertEqual(cfg["nodes"][0]["eds"], "rtd8.eds")
        self.assertEqual(read(os.path.join(self.canopen, "rtd8.eds")), read(os.path.join(RTD, "rtd8.eds")))
        r = contract.check_config(cfg, os.path.join(self.canopen, "canopen.json"))
        self.assertTrue(r.ok, r.errors)
        self.assertNotIn("converted", out)

    def program_config(self, data):
        config = pingpong_config(self.dir)
        with open(os.path.join(self.dir, "node2.fw"), "wb") as f:
            f.write(data)
        with open(config, encoding="utf-8") as f:
            cfg = json.load(f)
        cfg["nodes"][0].update(software_file="node2.fw", software_version=2)
        with open(config, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        return config

    def test_program_file_copied(self):
        code, _, err = deploy("--config", self.program_config(b"S00F000068656C6C6F\n"), "--into-project", self.project)
        self.assertEqual(code, 0, err)
        self.assertEqual(sorted(os.listdir(self.canopen)), ["canopen.json", "cpp-slave.eds", "node2.fw"])
        with open(os.path.join(self.canopen, "canopen.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["nodes"][0]["software_file"], "node2.fw")

    def test_binary_program_file_refused(self):
        code, _, err = deploy("--config", self.program_config(b"\x02\x00\xff\xfe"), "--into-project", self.project)
        self.assertEqual(code, 1)
        self.assertIn("is binary: the editor's project upload would corrupt it", err)
        self.assertFalse(os.path.exists(self.canopen))

    def test_checks_run_first(self):
        config = pingpong_config(self.dir)
        with open(config, encoding="utf-8") as f:
            cfg = json.load(f)
        cfg["nodes"][0]["node_id"] = 200
        with open(config, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        code, _, err = deploy("--config", config, "--into-project", self.project)
        self.assertEqual(code, 1)
        self.assertIn("node_id", err)
        self.assertFalse(os.path.exists(self.canopen))

    def test_refuses_existing_folder(self):
        config = pingpong_config(self.dir)
        os.makedirs(self.canopen)
        with open(os.path.join(self.canopen, "keep.txt"), "w") as f:
            f.write("mine")
        code, _, err = deploy("--config", config, "--into-project", self.project)
        self.assertEqual(code, 1)
        self.assertIn("already exists; pass --force", err)
        self.assertEqual(os.listdir(self.canopen), ["keep.txt"])
        code, _, err = deploy("--config", config, "--into-project", self.project, "--force")
        self.assertEqual(code, 0, err)
        self.assertEqual(sorted(os.listdir(self.canopen)), ["canopen.json", "cpp-slave.eds"])

    def test_not_a_project(self):
        os.remove(os.path.join(self.project, "project.json"))
        code, _, err = deploy("--config", pingpong_config(self.dir), "--into-project", self.project)
        self.assertEqual(code, 1)
        self.assertIn("not an OpenPLC editor project", err)

    def test_cp1252_eds_converted(self):
        # The pingpong EDS with a CP1252 degree sign and euro sign in names.
        config = pingpong_config(self.dir)
        eds = os.path.join(self.dir, "cpp-slave.eds")
        text = read(eds).decode("ascii")
        self.assertIn("ProductName=", text)
        cp = text.replace("ProductName=", "ProductName=Temperatur °C € ", 1).encode("cp1252")
        with open(eds, "wb") as f:
            f.write(cp)
        self.assertRaises(UnicodeDecodeError, cp.decode, "utf-8")
        code, out, err = deploy("--config", config, "--into-project", self.project)
        self.assertEqual(code, 0, err)
        self.assertIn("converted cpp-slave.eds from CP1252 to UTF-8", out)
        stored = read(os.path.join(self.canopen, "cpp-slave.eds"))
        self.assertEqual(stored.decode("utf-8"), cp.decode("cp1252"))
        self.assertNotIn(b"\xef\xbf\xbd", stored)
        if not os.access(CANOPEN_CHECK, os.X_OK):
            self.skipTest("canopen_check not built (%s)" % CANOPEN_CHECK)
        for cfg_path in (config, os.path.join(self.canopen, "canopen.json")):
            r = subprocess.run([CANOPEN_CHECK, "--no-dcfgen", cfg_path], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_canopen_check_runs_the_lint(self):
        if not os.access(CANOPEN_CHECK, os.X_OK):
            self.skipTest("canopen_check not built (%s)" % CANOPEN_CHECK)
        lint = os.path.join(REPO, "test", "fixtures", "eds", "lint")
        config = pingpong_config(self.dir)
        eds = os.path.join(self.dir, "cpp-slave.eds")
        cases = (("comm-broken.eds", 1, "error: node 2 (pingpong): EDS cpp-slave.eds fails dcfgen's lint "
                                        "(eds_lint \"communication\"): 0x1A00 sub 0"),
                 ("signed-hex.eds", 0, "warning: node 2 (pingpong): EDS cpp-slave.eds: 2 lint findings accepted"),
                 ("octet-string.eds", 0, "note: node 2 (pingpong): EDS cpp-slave.eds read through a prepared copy"))
        for name, code, line in cases:
            shutil.copy(os.path.join(lint, name), eds)
            r = subprocess.run([CANOPEN_CHECK, "--no-dcfgen", config], capture_output=True, text=True)
            self.assertEqual(r.returncode, code, r.stdout + r.stderr)
            self.assertIn(line, r.stdout)

    def test_to_utf8(self):
        self.assertEqual(project.to_utf8(b"plain"), (b"plain", False))
        self.assertEqual(project.to_utf8("°C".encode("utf-8")), ("°C".encode("utf-8"), False))
        self.assertEqual(project.to_utf8(b"\xb0C \x80 \x81"), ("°C € \x81".encode("utf-8"), True))


if __name__ == "__main__":
    unittest.main()
