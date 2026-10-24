"""The repository's texts must not name a PC tool subcommand, option, file or
heading that does not exist.

In README.md, SECURITY.md, docs/*.md, tools/deploy/README.md, the release
notes template, the example and config READMEs and the specs
(openspec/specs/*/spec.md): a backticked `canworks-deploy WORD`,
`canworks-diag WORD` or `canworks-local-runtime WORD` must use one of the
tool's subcommands, and a backticked path under one of the repository's
folders must match a file or folder (globs allowed; `<placeholder>` paths and
anchors are skipped).

In the same texts but the specs (whose scenarios change with their changes):
every relative link must reach a file, and a heading or <a id> in it when it
has an anchor; every `--option` in code after a PC tool's name must be one
that tool takes, read from its argparse parsers built here, subcommand by
subcommand; and an `--option` in other code must be one of some PC tool,
install script or other program of the repository (SOURCES), unless the
code is another program's command line (OTHER_PROGRAMS) or the option is in
NOT_OPTIONS.

Archived changes are history and are not checked. No dependencies (the PC
tools' parsers import none), so it runs in spec-check next to test_readme.py."""

import argparse
import glob
import re
import sys
import unittest
from pathlib import Path

try:
    from .test_readme import LINK, anchors
except ImportError:  # run as a script in spec-check
    from test_readme import LINK, anchors

ROOT = Path(__file__).resolve().parents[3]
TOOLS = ROOT / "tools" / "deploy" / "canworks"

SUBCOMMAND = re.compile(r"`(canworks-deploy|canworks-diag|canworks-local-runtime) ([a-z][a-z0-9-]*)(\.\.\.)?")
PATH = re.compile(r"`((?:scripts|tools|plugin|config|docs|test|examples|library|schema|docker|\.github)/[^`\s]+)`")
ADD_PARSER = re.compile(r'add_parser\(\s*"([a-z0-9-]+)"')
CODE = re.compile(r"`([^`\n]+)`")
OPTION = re.compile(r"(?<![\w-])(--[a-z][a-z0-9-]*)")

# Paths a text names on purpose although they do not exist (none yet).
NOT_FILES = set()
# Code that starts with one of these is another program's command line.
OTHER_PROGRAMS = ("uv ", "git ", "cmake", "ctest", "pip", "npm", "node ", "docker", "podman", "wsl ", "sudo apt",
                  "openspec ", "CODESYS.exe", "./OpenPLC.Editor")
# Options of other programs that a text names without their command line.
NOT_OPTIONS = {"--appimage-extract-and-run"}  # the OpenPLC Editor AppImage
# The other programs of the repository (the bridge, the simulator, the C++
# test programs, CI's scripts and the install scripts): an option in their
# sources is one of theirs.
SOURCES = [(ROOT / "plugin" / "src", "*.cpp"), (ROOT / "tools", "*.cpp"), (ROOT / "test", "*.cpp"), (ROOT / "test", "*.sh"),
           (ROOT / ".github" / "scripts", "*.py"), (ROOT / "scripts", "*.sh"), (ROOT / "scripts", "*.ps1")]


def pages():
    """Every text but the specs."""
    files = ([ROOT / "README.md", ROOT / "SECURITY.md", ROOT / "tools" / "deploy" / "README.md",
              ROOT / "tools" / "deploy" / "release-notes.md"]
             + sorted((ROOT / "docs").glob("*.md"))
             + sorted(ROOT.glob("examples/*/README*")) + sorted(ROOT.glob("config/*/README*")))
    return [(f, f.read_text(encoding="utf-8")) for f in files]


def texts():
    files = [f for f, _ in pages()] + sorted((ROOT / "openspec" / "specs").glob("*/spec.md"))
    return [(f.relative_to(ROOT).as_posix(), f.read_text(encoding="utf-8")) for f in files]


def subcommands():
    def parsers(*modules):
        return {w for m in modules for w in ADD_PARSER.findall((TOOLS / m).read_text(encoding="utf-8"))}
    # canworks-deploy dispatches its subcommands on argv[0] before argparse.
    deploy = set(re.findall(r'argv\[:1\] == \["([a-z0-9-]+)"\]', (TOOLS / "cli.py").read_text(encoding="utf-8")))
    return {"canworks-deploy": deploy, "canworks-diag": parsers("diag.py", "simcli.py"),
            "canworks-local-runtime": parsers("localruntime.py")}


def tree(parser):
    """(long options, {subcommand: tree}) of an argparse parser."""
    options, subs = set(), {}
    for action in parser._actions:
        options.update(o for o in action.option_strings if o.startswith("--"))
        if isinstance(action, argparse._SubParsersAction):
            subs.update((name, tree(p)) for name, p in action.choices.items())
    return options, subs


def commands():
    """Every PC tool's parser tree, built from its own parser functions."""
    sys.path.insert(0, str(TOOLS.parent))
    try:
        from canworks import cli, diag, localruntime
        from canworks.configurator import start
        from canworks.j1939 import sim
        from canworks.link import device
    finally:
        sys.path.pop(0)
    deploy = tree(cli.parser())
    # Dispatched on argv[0] before cli.parser() (see subcommands()).
    deploy[1].update(notes=tree(cli.notes_parser()), library=tree(cli.library_parser()),
                     **{"slave-eds": tree(cli.slave_eds_parser())})
    return {"canworks-deploy": deploy, "canworks-diag": tree(diag.parser()),
            "canworks-local-runtime": tree(localruntime.parser()), "canworks-config": tree(start.parser()),
            "canworks-j1939-sim": tree(sim.parser()), "canworks-link": tree(device.parser())}


def all_options(trees):
    def walk(node):
        options, subs = node
        return options.union(*(walk(s) for s in subs.values()))
    known = set().union(*(walk(t) for t in trees.values()))
    for folder, pattern in SOURCES:
        for f in folder.rglob(pattern):
            known.update(OPTION.findall(f.read_text(encoding="utf-8")))
    return known


def unknown_options(code, trees, known):
    """The options in one code span that its command (or, without one, any
    tool) does not take."""
    words = re.split(r"\s+(?:\||&&|;)\s+", code)[0].split()
    for i, word in enumerate(words):
        if word.rsplit("/", 1)[-1] in trees:
            options, subs = trees[word.rsplit("/", 1)[-1]]
            options = set(options)
            for w in words[i + 1:]:
                if w in subs:  # the path of subcommands, each adding its options
                    options, subs = options | subs[w][0], subs[w][1]
            return [o for o in OPTION.findall(" ".join(words[i + 1:])) if o not in options and not o.endswith("-")]
    if code.startswith(OTHER_PROGRAMS):
        return []
    # `--doc-*` names a group of options.
    return [o for o in OPTION.findall(code) if o not in known and o not in NOT_OPTIONS and not o.endswith("-")]


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

    def test_links_reach_a_file_and_anchor(self):
        bad = []
        for page, text in pages():
            for m in LINK.finditer(text):
                target = m.group(1) or m.group(2)
                if re.match(r"[a-z]+:", target) or "{" in target:
                    continue
                path, _, anchor = target.partition("#")
                file = page if not path else (page.parent / path).resolve()
                name = page.relative_to(ROOT).as_posix()
                if not file.exists():
                    bad.append(f"{name}: {target}: no such file")
                elif anchor and file.suffix == ".md" and anchor not in anchors(file):
                    bad.append(f"{name}: {target}: no such heading")
        self.assertEqual(bad, [], "these link to files or headings that are gone:\n" + "\n".join(bad))

    def test_options_exist(self):
        trees = commands()
        self.assertIn("--into-project", trees["canworks-deploy"][0])
        self.assertIn("--msef", trees["canworks-diag"][1]["sim"][1]["fault"][1]["emcy"][0])
        known = all_options(trees)
        bad = []
        for page, text in pages():
            for code in CODE.findall(text):
                for o in unknown_options(code, trees, known):
                    bad.append(f"{page.relative_to(ROOT).as_posix()}: {o} in `{code}`")
        self.assertEqual(bad, [], "these name options the command does not take:\n" + "\n".join(bad))

    def test_allow_list_is_used(self):
        named = {o for _, text in pages() for code in CODE.findall(text) for o in OPTION.findall(code)}
        self.assertEqual(sorted(NOT_OPTIONS - named), [], "NOT_OPTIONS lists options no text names any more")


if __name__ == "__main__":
    unittest.main()
