"""The bounded package install for CI runners (.github/scripts/apt_install.py)."""

import contextlib
import importlib.util
import io
import os
import subprocess
import tempfile
import unittest

_path = os.path.join(os.path.dirname(__file__), "..", "..", ".github", "scripts", "apt_install.py")
_spec = importlib.util.spec_from_file_location("apt_install", _path)
apt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(apt)


class FakeRunner:
    """Answers dpkg-query from a set of installed packages; apt-get from a list of return codes."""

    def __init__(self, installed=(), apt_rcs=(), dpkg_rc=0, debs_provide=()):
        self.installed = set(installed)
        self.apt_rcs = list(apt_rcs)
        self.dpkg_rc = dpkg_rc
        self.debs_provide = set(debs_provide)
        self.calls = []

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        if cmd[0] == "dpkg-query":
            ok = cmd[-1] in self.installed
            return subprocess.CompletedProcess(cmd, 0 if ok else 1, "install ok installed" if ok else "", "")
        if "dpkg" in cmd and "-i" in cmd:
            if self.dpkg_rc == 0:
                self.installed |= self.debs_provide
            return subprocess.CompletedProcess(cmd, self.dpkg_rc)
        if "apt-get" in cmd:
            return subprocess.CompletedProcess(cmd, self.apt_rcs.pop(0) if self.apt_rcs else 0)
        return subprocess.CompletedProcess(cmd, 0)

    def apt_calls(self):
        return [c for c in self.calls if "apt-get" in c]


def install(runner, packages, **kw):
    with contextlib.redirect_stdout(io.StringIO()):
        return apt.install(packages, run=runner, sleep=lambda s: None, **kw)


class Install(unittest.TestCase):
    def test_nothing_missing_runs_no_apt(self):
        r = FakeRunner(installed={"cmake", "tshark"})
        self.assertEqual(install(r, ["cmake", "tshark"]), 0)
        self.assertEqual(r.apt_calls(), [])

    def test_only_missing_packages_installed_with_bounded_apt(self):
        r = FakeRunner(installed={"cmake"})
        self.assertEqual(install(r, ["cmake", "tshark"], timeout=90, no_recommends=True), 0)
        update, inst = r.apt_calls()
        self.assertEqual(update[:5], ["sudo", "timeout", "-k", "10", "90"])
        self.assertIn("update", update)
        self.assertIn("Acquire::http::Timeout=20", update)
        self.assertIn("Acquire::Retries=3", inst)
        self.assertIn("--no-install-recommends", inst)
        self.assertEqual(inst[-1], "tshark")
        self.assertNotIn("cmake", inst)

    def test_stalled_attempt_retried_after_dpkg_repair(self):
        r = FakeRunner(apt_rcs=[0, 124, 0, 0])  # first install times out
        self.assertEqual(install(r, ["tshark"]), 0)
        self.assertEqual(len(r.apt_calls()), 4)
        self.assertIn(["sudo", "dpkg", "--configure", "-a"], r.calls)

    def test_failed_update_skips_install(self):
        r = FakeRunner(apt_rcs=[124, 0, 0])
        self.assertEqual(install(r, ["tshark"]), 0)
        self.assertEqual([("update" in c) for c in r.apt_calls()], [True, True, False])

    def test_cached_debs_installed_without_apt(self):
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "tshark_1_amd64.deb"), "w").close()
            r = FakeRunner(debs_provide={"tshark"})
            self.assertEqual(install(r, ["tshark"], debs=d), 0)
            self.assertEqual(r.apt_calls(), [])
            self.assertTrue(any("dpkg" in c and os.path.join(d, "tshark_1_amd64.deb") in c for c in r.calls))

    def test_empty_cache_fills_it_through_apt(self):
        with tempfile.TemporaryDirectory() as d:
            r = FakeRunner()
            self.assertEqual(install(r, ["tshark"], debs=d), 0)
            self.assertIn(f"Dir::Cache::Archives={d}", r.apt_calls()[1])
            self.assertTrue(os.path.isdir(os.path.join(d, "partial")))

    def test_broken_cache_falls_back_to_apt(self):
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "tshark_1_amd64.deb"), "w").close()
            r = FakeRunner(dpkg_rc=1)
            self.assertEqual(install(r, ["tshark"], debs=d), 0)
            self.assertEqual(len(r.apt_calls()), 2)

    def test_every_attempt_failing_fails(self):
        r = FakeRunner(apt_rcs=[100] * 10)
        self.assertEqual(install(r, ["tshark"], retries=1), 1)
        self.assertEqual(len(r.apt_calls()), 2)  # two updates, no install


if __name__ == "__main__":
    unittest.main()
