"""The CI change classification (.github/scripts/ci_changes.py)."""

import importlib.util
import os
import unittest

_path = os.path.join(os.path.dirname(__file__), "..", "..", ".github", "scripts", "ci_changes.py")
_spec = importlib.util.spec_from_file_location("ci_changes", _path)
ci = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ci)


class Classify(unittest.TestCase):
    def test_archive_commit_is_docs(self):
        self.assertFalse(ci.is_code([
            "openspec/changes/archive/2026-10-05-x/proposal.md",
            "openspec/specs/canopen-ci/spec.md",
            "openspec/changes/archive/2026-10-05-x/.openspec.yaml",
        ]))

    def test_docs_and_readme_are_docs(self):
        self.assertFalse(ci.is_code(["docs/deploy.md", "README.md", ".claude/skills/a/SKILL.md"]))

    def test_source_is_code(self):
        self.assertTrue(ci.is_code(["docs/deploy.md", "plugin/src/can/plugin.cpp"]))

    def test_workflow_is_code(self):
        self.assertTrue(ci.is_code([".github/workflows/ci.yml"]))

    def test_markdown_tests_or_tools_may_read_is_code(self):
        for p in ("test/pingpong/README.md", "config/rtd-sensor/README.md", "tools/deploy/README.md"):
            self.assertTrue(ci.is_code([p]), p)

    def test_no_files_is_code(self):
        self.assertTrue(ci.is_code([]))

    def test_unknown_base_is_code(self):
        self.assertIsNone(ci.changed("0000000000000000000000000000000000000000", "HEAD"))
        self.assertIsNone(ci.changed("", "HEAD"))


class Areas(unittest.TestCase):
    def setUp(self):
        self.rules = ci.load_rules()

    def test_protocol_paths(self):
        self.assertEqual(ci.areas(["plugin/src/j1939/j1939_network.cpp", "tools/deploy/canworks/j1939/sim.py",
                                   "examples/j1939/machine.dbc"], self.rules), {"j1939"})
        self.assertEqual(ci.areas(["plugin/src/canopen/bus.cpp", "test/pingpong/run.sh"], self.rules), {"canopen"})

    def test_everything_else_is_shared(self):
        for p in ("plugin/src/can/diag.cpp", "tools/deploy/canworks/contract.py", ".github/workflows/ci.yml",
                  "scripts/install-stock.sh"):
            self.assertEqual(ci.areas([p], self.rules), {"shared"}, p)

    def test_docs_have_no_area(self):
        self.assertEqual(ci.areas(["docs/j1939.md", "openspec/specs/j1939-ecu/spec.md"], self.rules), set())

    def test_unknown_paths_are_every_area(self):
        self.assertEqual(ci.areas(None, self.rules), {"canopen", "j1939", "shared"})

    def test_every_rule_matches_a_file(self):
        root = os.path.join(os.path.dirname(__file__), "..", "..")
        files = []
        for d, _, names in os.walk(root):
            if "/.git" in d or "__pycache__" in d:
                continue
            files += [os.path.relpath(os.path.join(d, n), root) for n in names]
        import fnmatch
        for area, pattern in self.rules:
            self.assertTrue(any(fnmatch.fnmatchcase(f, pattern) for f in files), "%s %s" % (area, pattern))


if __name__ == "__main__":
    unittest.main()
