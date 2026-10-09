"""scripts/rename_to_canworks.py: the mapping, what it leaves alone, and that a
second run changes nothing."""

import importlib.util
import os
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "..", "scripts", "rename_to_canworks.py")
spec = importlib.util.spec_from_file_location("rename_to_canworks", SCRIPT)
rn = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rn)


class Mapping(unittest.TestCase):
    def test_project_names(self):
        cases = {
            "import openplc_canopen_deploy.diag": "import canworks.diag",
            "openplc-canopen-diag status": "canworks-diag status",
            "openplc-canopen-sim-runtime start": "canworks-sim-runtime start",
            "/opt/openplc-canopen/lib/libcanopen_plugin.so": "/opt/canworks/lib/libcanworks_plugin.so",
            "OPENPLC_CANOPEN_TOKEN": "CANWORKS_TOKEN",
            "CANOPEN_FORCE_SIMULATE=1": "CANWORKS_FORCE_SIMULATE=1",
            "https://github.com/tonihoohoo/openplc-canopen": "https://github.com/tonihoohoo/canworks",
            "conf/canopen.json and conf/canopen/eds": "conf/canworks.json and conf/canworks/eds",
            'DIR = "canopen"': 'DIR = "canworks"',
            "LINE=\"canopen,$LIB,0,1,\"": "LINE=\"canworks,$LIB,0,1,\"",
            "schema/canopen.v2.schema.json": "schema/canworks.v2.schema.json",
            "schema/canopen-sim.v1.schema.json": "schema/canworks-sim.v1.schema.json",
            "out/.canopen/net": "out/.canworks/net",
            'open("canopen.v%d.schema.json" % v)': 'open("canworks.v%d.schema.json" % v)',
            "`canopen.v${from}.schema.json`": "`canworks.v${from}.schema.json`",
            "schema/canopen-machine.v1.schema.json": "schema/canworks-machine.v1.schema.json",
            "library/openplc_canopen.stlib": "library/canworks.stlib",
        }
        for old, new in cases.items():
            self.assertEqual(rn.rename_text(old), new, old)

    def test_canopen_itself_kept(self):
        for text in ("config/pingpong/canopen_config.json", "openspec/specs/canopen-pdo-io/spec.md",
                     "namespace canopen_plugin {", "https://opensource.lely.com/canopen/docs/",
                     "tonihoohoo/openplc-canopen-private", "CANopen master", "plugin/src/canopen/",
                     "the canopen-local-runtime spec", "# rename-keep: /opt/openplc-canopen"):
            self.assertEqual(rn.rename_text(text), text, text)

    def test_project_folder_path(self):
        self.assertEqual(rn.rename_path("examples/gantry-cell/canopen/servo402.eds"),
                         "examples/gantry-cell/canworks/servo402.eds")
        self.assertEqual(rn.rename_path("plugin/src/canopen/master.cpp"), "plugin/src/canopen/master.cpp")
        self.assertEqual(rn.rename_path("canopen/x.json"), "canworks/x.json")

    def test_cmake_target_only_in_build_files(self):
        self.assertEqual(rn.rename_text("--target canopen_plugin", build=True), "--target canworks_plugin")
        self.assertEqual(rn.rename_text("canopen_plugin.cpp", build=True), "canopen_plugin.cpp")
        self.assertEqual(rn.rename_text("--target canopen_plugin"), "--target canopen_plugin")

    def test_idempotent(self):
        text = "openplc-canopen-diag /opt/openplc-canopen conf/canopen.json \"canopen\"\n"
        once = rn.rename_text(text)
        self.assertEqual(rn.rename_text(once), once)


class OnARepository(unittest.TestCase):
    def test_apply_then_check(self):
        with tempfile.TemporaryDirectory() as d:
            def git(*a):
                subprocess.run(["git", *a], cwd=d, check=True, capture_output=True)
            git("init", "-q")
            os.makedirs(os.path.join(d, "tools", "deploy", "openplc_canopen_deploy"))
            with open(os.path.join(d, "tools", "deploy", "openplc_canopen_deploy", "cli.py"), "w") as f:
                f.write('PROJECT = "canopen"\nCMD = "openplc-canopen-deploy"\n')
            os.makedirs(os.path.join(d, "openspec", "changes", "archive", "x"))
            with open(os.path.join(d, "openspec", "changes", "archive", "x", "a.md"), "w") as f:
                f.write("openplc-canopen-diag\n")
            git("add", "-A")
            self.assertTrue(rn.check(d))
            rn.apply(d)
            self.assertEqual(rn.check(d), [])
            with open(os.path.join(d, "tools", "deploy", "canworks", "cli.py")) as f:
                self.assertEqual(f.read(), 'PROJECT = "canworks"\nCMD = "canworks-deploy"\n')
            with open(os.path.join(d, "openspec", "changes", "archive", "x", "a.md")) as f:
                self.assertEqual(f.read(), "openplc-canopen-diag\n")
            self.assertEqual(rn.apply(d), 0)


class ThisRepository(unittest.TestCase):
    def test_no_old_names(self):
        found = rn.check(os.path.join(HERE, "..", ".."))
        self.assertEqual(found, [], "\n".join(found[:20]))


if __name__ == "__main__":
    unittest.main()
