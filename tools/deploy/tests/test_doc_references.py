"""README.md, docs/*.md and the specs (openspec/specs/*/spec.md) must not
name a PC tool subcommand or a repository file that does not exist: a
backticked `canworks-deploy WORD`, `canworks-diag WORD` or
`canworks-local-runtime WORD` must use one of the tool's subcommands, and a
backticked path under one of the repository's folders must match a file or
folder (globs allowed; `<placeholder>` paths and anchors are skipped).
Archived changes are history and are not checked. No dependencies, so it runs
in spec-check next to test_readme.py."""

import glob
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TOOLS = ROOT / "tools" / "deploy" / "canworks"

SUBCOMMAND = re.compile(r"`(canworks-deploy|canworks-diag|canworks-local-runtime) ([a-z][a-z0-9-]*)(\.\.\.)?")
PATH = re.compile(r"`((?:scripts|tools|plugin|config|docs|test|examples|library|schema|docker|\.github)/[^`\s]+)`")
ADD_PARSER = re.compile(r'add_parser\(\s*"([a-z0-9-]+)"')

# Paths a text names on purpose although they do not exist (none yet).
NOT_FILES = set()


def texts():
    files = [ROOT / "README.md"] + sorted((ROOT / "docs").glob("*.md")) + sorted((ROOT / "openspec" / "specs").glob("*/spec.md"))
    return [(f.relative_to(ROOT).as_posix(), f.read_text(encoding="utf-8")) for f in files]


def subcommands():
    def parsers(*modules):
        return {w for m in modules for w in ADD_PARSER.findall((TOOLS / m).read_text(encoding="utf-8"))}
    # canworks-deploy dispatches its subcommands on argv[0] before argparse.
    deploy = set(re.findall(r'argv\[:1\] == \["([a-z0-9-]+)"\]', (TOOLS / "cli.py").read_text(encoding="utf-8")))
    return {"canworks-deploy": deploy, "canworks-diag": parsers("diag.py", "simcli.py"),
            "canworks-local-runtime": parsers("localruntime.py")}


class DocReferences(unittest.TestCase):
    def test_subcommands_exist(self):
        known = subcommands()
        self.assertIn("status", known["canworks-diag"])
        self.assertIn("notes", known["canworks-deploy"])
        bad = []
        for name, text in texts():
            for m in SUBCOMMAND.finditer(text):
                tool, word, prefix = m.groups()
                ok = any(k.startswith(word) for k in known[tool]) if prefix else word in known[tool]
                if not ok:
                    bad.append(f"{name}: {tool} {word}")
        self.assertEqual(bad, [], "these name a subcommand the tool does not have:\n" + "\n".join(bad))

    def test_paths_exist(self):
        bad = []
        for name, text in texts():
            for m in PATH.finditer(text):
                path = m.group(1).split("#")[0].rstrip("/.,:;")
                if "<" in path or "{" in path or path in NOT_FILES:
                    continue
                if not glob.glob(str(ROOT / path)):
                    bad.append(f"{name}: {path}")
        self.assertEqual(bad, [], "these name repository files that do not exist:\n" + "\n".join(bad))


if __name__ == "__main__":
    unittest.main()
