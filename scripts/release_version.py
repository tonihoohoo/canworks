#!/usr/bin/env python3
"""Version checks for the PC tools release (canopen-pc-install).

  release_version.py TAG                 exit 0 and print the version if the
                                         deploy-v<version> tag matches the package
  release_version.py --package           print the package version (pyproject.toml
                                         and __version__ must agree)
  release_version.py --decide CI PC      release, wait or refuse, from the
                                         `gh run list --json status,conclusion`
                                         output files of CI and PC tools on a commit
  release_version.py --superseded A B    exit 0 if version B is newer than A
  release_version.py --previous-tag V    read tags on stdin, print the newest
                                         deploy-v tag older than V (or nothing)"""

import json
import os
import re
import sys

DEPLOY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools", "deploy")
PREFIX = "deploy-v"


def package_versions(deploy=DEPLOY):
    """(pyproject.toml version, __version__) of the tools package."""
    with open(os.path.join(deploy, "pyproject.toml"), encoding="utf-8") as f:
        pyproject = re.search(r'^version\s*=\s*"([^"]+)"', f.read(), re.M).group(1)
    with open(os.path.join(deploy, "openplc_canopen_deploy", "__init__.py"), encoding="utf-8") as f:
        module = re.search(r'^__version__\s*=\s*"([^"]+)"', f.read(), re.M).group(1)
    return pyproject, module


def package_version(deploy=DEPLOY):
    """The package version, or a ValueError when the two files disagree."""
    pyproject, module = package_versions(deploy)
    if pyproject != module:
        raise ValueError("pyproject.toml says %s but openplc_canopen_deploy.__version__ says %s" % (pyproject, module))
    return pyproject


def check(tag, deploy=DEPLOY):
    """The version, or a ValueError naming what differs."""
    if not tag.startswith(PREFIX):
        raise ValueError("tag %s does not start with %s" % (tag, PREFIX))
    wanted = tag[len(PREFIX):]
    pyproject = package_version(deploy)
    if wanted != pyproject:
        raise ValueError("tag %s is version %s but the package version is %s" % (tag, wanted, pyproject))
    return pyproject


def version_key(version):
    """Sort key: 0.9.0 < 0.10.0 < 0.10.1. A non-numeric part sorts as 0."""
    return tuple(int(p) if p.isdigit() else 0 for p in re.split(r"[.+-]", version))


def run_state(runs):
    """none, pending, success or failure for the newest run in a `gh run list` result."""
    if not runs:
        return "none"
    run = runs[0]
    if run.get("status") != "completed":
        return "pending"
    return "success" if run.get("conclusion") == "success" else "failure"


def decide(ci, pc):
    """release, wait or refuse, from the CI and PC tools run states on one commit.

    CI must have succeeded; PC tools must have succeeded or not run at all."""
    if "failure" in (ci, pc) or ci == "none":
        return "refuse"
    if "pending" in (ci, pc):
        return "wait"
    return "release"


def previous_tag(tags, version):
    """The newest deploy-v tag older than version, or None."""
    older = [t for t in tags if t.startswith(PREFIX) and version_key(t[len(PREFIX):]) < version_key(version)]
    return max(older, key=lambda t: version_key(t[len(PREFIX):]), default=None)


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main(argv):
    try:
        if argv == ["--package"]:
            print(package_version())
        elif len(argv) == 3 and argv[0] == "--decide":
            print(decide(run_state(_load(argv[1])), run_state(_load(argv[2]))))
        elif len(argv) == 3 and argv[0] == "--superseded":
            return 0 if version_key(argv[2]) > version_key(argv[1]) else 1
        elif len(argv) == 2 and argv[0] == "--previous-tag":
            tag = previous_tag(sys.stdin.read().split(), argv[1])
            if tag:
                print(tag)
        elif len(argv) == 1 and not argv[0].startswith("--"):
            print(check(argv[0]))
        else:
            print(__doc__.strip(), file=sys.stderr)
            return 2
    except ValueError as e:
        print("release_version: %s" % e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
