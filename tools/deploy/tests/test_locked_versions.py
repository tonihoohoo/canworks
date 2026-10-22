"""Pinned versions that live in two places stay the same
(lock-dependency-versions): the OpenPLC runtime CI tests against and the
Lely commit the dcf-tools constraints were made for. Reads the checkout's
files; no network."""

import os
import re
import unittest

from canworks.devices import plan

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


class LockedVersions(unittest.TestCase):
    def test_tested_runtime(self):
        self.assertEqual(plan.TESTED_RUNTIME, read("docker", "local-runtime", "runtime-version").strip(),
                         "bump TESTED_RUNTIME in canworks/devices/plan.py with docker/local-runtime/runtime-version")

    def test_dcf_tools_constraints_follow_lely(self):
        made_for = re.search(r"^# lely-ref: ([0-9a-f]{40})$", read("scripts", "dcf-tools-constraints.txt"), re.M)
        self.assertIsNotNone(made_for, "scripts/dcf-tools-constraints.txt names no lely-ref")
        self.assertEqual(made_for.group(1), read("tools", "deploy", "canworks", "_lely_dcf", "VERSION").strip(),
                         "the Lely commit changed (tools/deploy/canworks/_lely_dcf/VERSION): check the dcf-tools "
                         "versions in scripts/dcf-tools-constraints.txt and update its lely-ref")

    def test_dcf_tools_constraints_exact(self):
        for line in read("scripts", "dcf-tools-constraints.txt").splitlines():
            if line.strip() and not line.startswith("#"):
                self.assertRegex(line, r"^[A-Za-z0-9_.-]+==[0-9][^ ;]*$", "exact versions only")


if __name__ == "__main__":
    unittest.main()
