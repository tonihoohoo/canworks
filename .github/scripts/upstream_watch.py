#!/usr/bin/env python3
"""Upstream's newest OpenPLC runtime and editor releases against the
recorded state (.github/ci/upstream-watch.json): the release canworks is
tested with, and the sha256 of the files its OpenPLC through Modbus target
follows (the runtime's Modbus master config model, the editor's remote
device format and its generator of the runtime's config).

    upstream_watch.py [--state FILE]

Prints the issue body (Markdown) when a repository has a newer release or a
watched file differs at it, else nothing. Exit 1 when upstream cannot be
read. Fetches tags with git ls-remote and files from raw.githubusercontent.com.
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STATE = os.path.join(ROOT, ".github", "ci", "upstream-watch.json")


def version_key(tag):
    return tuple(int(x) for x in tag[1:].split("."))


def newest_tag(url):
    out = subprocess.run(["git", "ls-remote", "--tags", "--refs", url, "v*"], capture_output=True, text=True,
                         check=True, timeout=120).stdout
    tags = [line.rsplit("refs/tags/", 1)[1] for line in out.splitlines() if "refs/tags/" in line]
    tags = [t for t in tags if re.fullmatch(r"v\d+\.\d+\.\d+", t)]
    if not tags:
        raise RuntimeError("no release tags at %s" % url)
    return max(tags, key=version_key)


def file_sha(url, ref, path):
    """The sha256 of `path` at `ref`, or None when the file is gone."""
    raw = url.replace("https://github.com/", "https://raw.githubusercontent.com/") + "/%s/%s" % (ref, path)
    try:
        with urllib.request.urlopen(raw, timeout=60) as r:
            return hashlib.sha256(r.read()).hexdigest()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def report(state):
    lines = []
    for name, repo in sorted(state["repos"].items()):
        if "tested_file" in repo:
            with open(os.path.join(ROOT, repo["tested_file"]), encoding="utf-8") as f:
                tested = f.read().strip()
        else:
            tested = repo["tested"]
        newest = newest_tag(repo["url"])
        print("%s: tested %s, upstream's newest %s" % (name, tested, newest), file=sys.stderr)
        if version_key(newest) <= version_key(tested):
            continue
        changed = []
        for path, sha in sorted(repo["files"].items()):
            now = file_sha(repo["url"], newest, path)
            if now != sha:
                changed.append("`%s` %s" % (path, "is gone" if now is None else "changed"))
        lines.append("- %s %s is out ([release](%s/releases/tag/%s)); canworks is tested with %s. Watched files: %s."
                     % (name, newest, repo["url"], newest, tested, "; ".join(changed) if changed else "unchanged"))
    return lines


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--state", default=STATE)
    args = ap.parse_args()
    with open(args.state, encoding="utf-8") as f:
        state = json.load(f)
    try:
        lines = report(state)
    except (OSError, RuntimeError, subprocess.SubprocessError, urllib.error.URLError) as e:
        print("cannot read upstream: %s" % e, file=sys.stderr)
        return 1
    if lines:
        print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
