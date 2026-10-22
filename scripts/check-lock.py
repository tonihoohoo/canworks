#!/usr/bin/env python3
"""tools/deploy/uv.lock still matches tools/deploy/pyproject.toml
(lock-dependency-versions), for CI and by hand:

  python3 scripts/check-lock.py

Runs `uv lock --check` on a copy of the two files in which the lock's own
canworks version follows pyproject.toml, so a version bump alone needs no new
lock. Exits 1 with uv's message when a dependency changed without
`uv lock --project tools/deploy`."""

import os
import re
import shutil
import subprocess
import sys
import tempfile

DEPLOY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools", "deploy")


def main():
    with open(os.path.join(DEPLOY, "pyproject.toml"), encoding="utf-8") as f:
        pyproject = f.read()
    version = re.search(r'^version = "([^"]+)"$', pyproject, re.M).group(1)
    with open(os.path.join(DEPLOY, "uv.lock"), encoding="utf-8") as f:
        lock = f.read()
    lock, n = re.subn(r'(\[\[package\]\]\nname = "canworks"\nversion = )"[^"]*"', r'\g<1>"%s"' % version, lock)
    if n != 1:
        sys.exit("check-lock: tools/deploy/uv.lock has no canworks package; run uv lock --project tools/deploy")
    work = tempfile.mkdtemp(prefix="canworks-lock-")
    try:
        with open(os.path.join(work, "pyproject.toml"), "w", encoding="utf-8") as f:
            f.write(pyproject)
        with open(os.path.join(work, "uv.lock"), "w", encoding="utf-8") as f:
            f.write(lock)
        r = subprocess.run(["uv", "lock", "--check", "--project", work])
    finally:
        shutil.rmtree(work, ignore_errors=True)
    if r.returncode:
        print("check-lock: tools/deploy/uv.lock does not match tools/deploy/pyproject.toml; "
              "run uv lock --project tools/deploy and commit uv.lock", file=sys.stderr)
    return r.returncode


if __name__ == "__main__":
    sys.exit(main())
