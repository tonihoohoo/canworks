#!/usr/bin/env python3
"""Classify a push or pull request for CI: code (run the full suite) or docs
(documentation and specs only: skip the build and test jobs), and the
protocol areas the code changes touch.

  ci_changes.py <base> <head>   prints code=, areas=, canopen= and j1939=,
                                and the changed files on stderr

The documentation allow-list is openspec/**, docs/** and Markdown outside
test/, config/ and tools/ (fixtures and packaged files a test may read).
Anything else, the workflows included, is code. A missing or unknown base
(new branch, force push) is code in every area.

Areas: each code path is "canopen", "j1939" or "shared" by the rules in
.github/ci/areas.txt. canopen=true when a CANopen or shared path changed (the
CANopen-only jobs and steps run), j1939=true likewise for J1939.
"""

import fnmatch
import os
import subprocess
import sys

NOT_DOCS_MD = ("test/", "config/", "tools/")
AREAS = ("canopen", "j1939", "shared")
RULES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "ci", "areas.txt")


def is_docs(path):
    if path.startswith(("openspec/", "docs/")):
        return True
    return path.endswith(".md") and not path.startswith(NOT_DOCS_MD)


def is_code(paths):
    return not paths or not all(is_docs(p) for p in paths)


def load_rules(path=RULES_FILE):
    rules = []
    with open(path) as f:
        for line in f:
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            area, pattern = line.split(None, 1)
            if area not in AREAS:
                raise ValueError("%s: unknown area %r" % (path, area))
            rules.append((area, pattern))
    return rules


def area_of(path, rules):
    for area, pattern in rules:
        if fnmatch.fnmatchcase(path, pattern):
            return area
    return "shared"


def areas(paths, rules):
    """The areas of the code paths; every area when the paths are unknown."""
    if paths is None:
        return set(AREAS)
    return {area_of(p, rules) for p in paths if not is_docs(p)}


def changed(base, head):
    if not base or set(base) == {"0"}:
        return None
    r = subprocess.run(["git", "diff", "--name-only", f"{base}...{head}"], capture_output=True, text=True)
    if r.returncode != 0:
        sys.stderr.write(r.stderr)
        return None
    return [p for p in r.stdout.splitlines() if p]


def main(argv):
    paths = changed(argv[1] if len(argv) > 1 else "", argv[2] if len(argv) > 2 else "HEAD")
    code = paths is None or is_code(paths)
    rules = load_rules()
    for p in paths or []:
        sys.stderr.write(f"{'docs' if is_docs(p) else area_of(p, rules):7}  {p}\n")
    if paths is None:
        sys.stderr.write("base unknown: full suite\n")
    found = areas(paths, rules) if code else set()
    shared = "shared" in found
    print(f"code={'true' if code else 'false'}")
    print("areas=" + ",".join(a for a in AREAS if a in found))
    print(f"canopen={'true' if shared or 'canopen' in found else 'false'}")
    print(f"j1939={'true' if shared or 'j1939' in found else 'false'}")


if __name__ == "__main__":
    main(sys.argv)
