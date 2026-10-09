#!/usr/bin/env python3
"""Rename the project from openplc-canopen to canworks (change
rename-to-canworks).

  rename_to_canworks.py [--root DIR]   rename paths and text in place
  rename_to_canworks.py --check        list old project names, exit 1 if any

Only project-level names change: the repository, PC tools package, commands,
plugin name and library, install path, config file and folder, generated
folder, environment variables, schema files and the PLC library. CANopen
itself keeps its name: spec capabilities `canopen-*`, the CANopen example
configs (`canopen_config.json`), the C++ namespace and source files, CANopen
block names and links to Lely's CANopen documentation.

A line containing `rename-keep` is left alone, so code that has to name an
old install (the install script's cleanup) can do so. Archived OpenSpec
changes, this script, its test, the rename change itself and the
toolkit-names spec (which lists the retired names) are skipped. Running the script twice changes nothing the second time.
"""

import argparse
import os
import re
import subprocess
import sys

KEEP = "rename-keep"

SKIP_PREFIXES = (
    "openspec/changes/archive/",
    "openspec/changes/rename-to-canworks/",
)
SKIP_FILES = {
    "LICENSE",
    "openspec/specs/toolkit-names/spec.md",  # names the old names it retires
    "scripts/rename_to_canworks.py",
    "test/ci/test_rename.py",
}

# Text rules, applied in order to every line (and, for paths, to the path).
RULES = [
    (r"openplc_canopen_deploy", "canworks"),
    (r"openplc_canopen_hook", "canworks_hook"),
    (r"openplc_canopen_trace", "canworks_trace"),
    (r"openplc-canopen-editor-hook", "canworks-editor-hook"),
    (r"openplc-canopen-sim-runtime", "canworks-sim-runtime"),
    (r"openplc-canopen-(deploy|config|diag|sim)\b", r"canworks-\1"),
    (r"openplc_canopen", "canworks"),
    (r"/opt/openplc-canopen\b", "/opt/canworks"),
    # The repository and plain folder names; not the private repository and
    # not the dropped openplc-canopen-runtime alias (removed by hand).
    (r"openplc-canopen(?![-\w])", "canworks"),
    (r"OPENPLC_CANOPEN_", "CANWORKS_"),
    (r"CANOPEN_FORCE_SIMULATE", "CANWORKS_FORCE_SIMULATE"),
    (r"libcanopen_plugin", "libcanworks_plugin"),
    # Schema files, also where the version is filled in (%d, ${v}).
    (r"(?<![\w-])canopen(-sim|-machine)?\.v(\d+|%d|\$\{\w+\})\.schema", r"canworks\1.v\2.schema"),
    (r"(?<![\w.-])canopen\.json", "canworks.json"),
    (r"(?<![\w.])\.canopen(?=[/'\"`\s)]|$)", ".canworks"),
    (r"(?<!lely\.com/)(?<!src/)(?<![\w.-])canopen/", "canworks/"),
    (r"([\"'])canopen\1", r"\1canworks\1"),
    (r"(?<![\w-])canopen,(?=\S)", "canworks,"),
    (r"\bcanopen (line|lines|plugin)\b", r"canworks \1"),
]
# Only in build files: the CMake target (the C++ namespace keeps its name).
BUILD_RULES = [(r"(?<![\w/])canopen_plugin(?![\w.])", "canworks_plugin")]
BUILD_FILE = re.compile(r"(^|/)(CMakeLists\.txt|[^/]*\.cmake|[^/]*\.sh|[^/]*\.ya?ml)$")

# Old names --check reports.
OLD = re.compile(r"openplc[-_]canopen(?!-private)|OPENPLC_CANOPEN_|CANOPEN_FORCE_SIMULATE|libcanopen_plugin"
                 r"|(?<![\w.-])canopen\.json|conf/canopen/"
                 r"|(?<![\w-])canopen(-sim|-machine)?\.v(\d+|%d|\$\{\w+\})\.schema")

_RULES = [(re.compile(p), r) for p, r in RULES]
_BUILD = [(re.compile(p), r) for p, r in BUILD_RULES]


def skipped(path):
    return path in SKIP_FILES or path.startswith(SKIP_PREFIXES)


def rename_text(text, build=False):
    out = []
    for line in text.splitlines(keepends=True):
        if KEEP not in line:
            for rx, rep in _RULES + (_BUILD if build else []):
                line = rx.sub(rep, line)
        out.append(line)
    return "".join(out)


# A project's config folder (examples/*/canopen/); not plugin sources.
PROJECT_FOLDER = re.compile(r"^(?!plugin/)(.+/)?canopen(?=/)")


def rename_path(path):
    path = PROJECT_FOLDER.sub(lambda m: (m.group(1) or "") + "canworks", path)
    return "/".join(rename_text(part) for part in path.split("/"))


def tracked(root):
    r = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True)
    return [p for p in r.stdout.decode().split("\0") if p]


def read(root, path):
    full = os.path.join(root, path)
    if os.path.islink(full) or not os.path.isfile(full):
        return None
    with open(full, "rb") as f:
        data = f.read()
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def apply(root):
    changed = 0
    for path in tracked(root):
        if skipped(path):
            continue
        text = read(root, path)
        if text is not None:
            new = rename_text(text, build=bool(BUILD_FILE.search(path)))
            if new != text:
                with open(os.path.join(root, path), "w", encoding="utf-8", newline="") as f:
                    f.write(new)
                changed += 1
        dest = rename_path(path)
        if dest != path:
            os.makedirs(os.path.dirname(os.path.join(root, dest)) or root, exist_ok=True)
            subprocess.run(["git", "mv", path, dest], cwd=root, check=True)
            changed += 1
    return changed


def check(root):
    found = []
    # Main specs are synced from the change's deltas when it is archived.
    pending = os.path.isdir(os.path.join(root, "openspec", "changes", "rename-to-canworks"))
    for path in tracked(root):
        if skipped(path) or (pending and path.startswith("openspec/specs/")):
            continue
        if OLD.search(path) or PROJECT_FOLDER.match(path):
            found.append("%s: path" % path)
        text = read(root, path)
        if text is None:
            continue
        for n, line in enumerate(text.splitlines(), 1):
            if KEEP not in line:
                m = OLD.search(line)
                if m:
                    found.append("%s:%d: %s" % (path, n, m.group(0)))
    return found


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--root", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ap.add_argument("--check", action="store_true", help="only list old names; exit 1 if any")
    a = ap.parse_args(argv)
    if a.check:
        found = check(a.root)
        for f in found:
            print(f)
        print("old project names: %d" % len(found))
        return 1 if found else 0
    print("files changed or moved: %d" % apply(a.root))
    return 0


if __name__ == "__main__":
    sys.exit(main())
