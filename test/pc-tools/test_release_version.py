"""The version checks and release decision the release workflow runs."""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "..", "scripts", "release_version.py")
spec = importlib.util.spec_from_file_location("release_version", SCRIPT)
release_version = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release_version)


def fake_package(pyproject, module):
    d = tempfile.mkdtemp()
    os.makedirs(os.path.join(d, "canworks"))
    with open(os.path.join(d, "pyproject.toml"), "w") as f:
        f.write('[project]\nname = "x"\nversion = "%s"\n' % pyproject)
    with open(os.path.join(d, "canworks", "__init__.py"), "w") as f:
        f.write('__version__ = "%s"\n' % module)
    return d


class ReleaseVersionTest(unittest.TestCase):
    def package(self, pyproject, module=None):
        d = fake_package(pyproject, module or pyproject)
        self.addCleanup(shutil.rmtree, d, True)
        return d

    def test_matching_tag(self):
        self.assertEqual(release_version.check("deploy-v0.16.0", self.package("0.16.0")), "0.16.0")

    def test_tag_names_both_versions_when_it_differs(self):
        with self.assertRaises(ValueError) as e:
            release_version.check("deploy-v0.16.1", self.package("0.16.0"))
        self.assertIn("0.16.1", str(e.exception))
        self.assertIn("0.16.0", str(e.exception))

    def test_pyproject_and_module_must_agree(self):
        with self.assertRaises(ValueError) as e:
            release_version.check("deploy-v0.16.0", self.package("0.16.0", "0.15.0"))
        self.assertIn("__version__", str(e.exception))

    def test_other_tag_prefix(self):
        with self.assertRaises(ValueError):
            release_version.check("v0.16.0", self.package("0.16.0"))

    def test_repo_package_is_consistent(self):
        pyproject, module = release_version.package_versions()
        self.assertEqual(pyproject, module)
        self.assertEqual(release_version.check("deploy-v" + pyproject), pyproject)

    def test_package_version(self):
        self.assertEqual(release_version.package_version(self.package("0.21.0")), "0.21.0")
        with self.assertRaises(ValueError):
            release_version.package_version(self.package("0.21.0", "0.20.0"))


def completed(conclusion):
    return [{"status": "completed", "conclusion": conclusion}]


class DecideTest(unittest.TestCase):
    def state(self, runs):
        return release_version.run_state(runs)

    def test_run_states(self):
        self.assertEqual(self.state([]), "none")
        self.assertEqual(self.state([{"status": "in_progress", "conclusion": ""}]), "pending")
        self.assertEqual(self.state([{"status": "queued", "conclusion": ""}]), "pending")
        self.assertEqual(self.state(completed("success")), "success")
        self.assertEqual(self.state(completed("failure")), "failure")
        self.assertEqual(self.state(completed("cancelled")), "failure")
        # Newest run first, as gh run list orders them.
        self.assertEqual(self.state(completed("success") + completed("failure")), "success")

    def test_both_green(self):
        self.assertEqual(release_version.decide("success", "success"), "release")

    def test_pc_tools_did_not_run(self):
        self.assertEqual(release_version.decide("success", "none"), "release")

    def test_one_still_running(self):
        self.assertEqual(release_version.decide("success", "pending"), "wait")
        self.assertEqual(release_version.decide("pending", "success"), "wait")

    def test_failed(self):
        self.assertEqual(release_version.decide("success", "failure"), "refuse")
        self.assertEqual(release_version.decide("failure", "success"), "refuse")
        self.assertEqual(release_version.decide("failure", "pending"), "refuse")

    def test_ci_must_have_run(self):
        self.assertEqual(release_version.decide("none", "success"), "refuse")


class VersionOrderTest(unittest.TestCase):
    def test_numeric_order(self):
        key = release_version.version_key
        self.assertLess(key("0.9.0"), key("0.10.0"))
        self.assertLess(key("0.17.0"), key("0.17.1"))

    def test_previous_tag(self):
        tags = ["deploy-v0.9.0", "deploy-v0.17.1", "deploy-v0.10.0", "deploy-v0.17.0", "other-tag", "deploy-v0.21.0"]
        self.assertEqual(release_version.previous_tag(tags, "0.20.0"), "deploy-v0.17.1")
        self.assertEqual(release_version.previous_tag(tags, "0.10.0"), "deploy-v0.9.0")
        self.assertIsNone(release_version.previous_tag(tags, "0.9.0"))


class CommandLineTest(unittest.TestCase):
    def run_script(self, *args, stdin=""):
        return subprocess.run([sys.executable, SCRIPT] + list(args), input=stdin,
                              capture_output=True, text=True)

    def test_decide(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        ci, pc = os.path.join(d, "ci.json"), os.path.join(d, "pc.json")
        with open(ci, "w") as f:
            json.dump(completed("success"), f)
        with open(pc, "w") as f:
            json.dump([], f)
        r = self.run_script("--decide", ci, pc)
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "release"))

    def test_superseded(self):
        self.assertEqual(self.run_script("--superseded", "0.20.0", "0.21.0").returncode, 0)
        self.assertEqual(self.run_script("--superseded", "0.20.0", "0.20.0").returncode, 1)

    def test_previous_tag(self):
        r = self.run_script("--previous-tag", "0.20.0", stdin="deploy-v0.17.0\ndeploy-v0.17.1\n")
        self.assertEqual(r.stdout.strip(), "deploy-v0.17.1")
        r = self.run_script("--previous-tag", "0.1.0", stdin="deploy-v0.17.0\n")
        self.assertEqual((r.returncode, r.stdout), (0, ""))

    def test_package(self):
        r = self.run_script("--package")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), release_version.package_versions()[0])

    def test_usage(self):
        self.assertEqual(self.run_script().returncode, 2)


if __name__ == "__main__":
    unittest.main()
