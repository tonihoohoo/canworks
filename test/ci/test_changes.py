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


if __name__ == "__main__":
    unittest.main()
