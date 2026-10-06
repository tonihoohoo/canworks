#!/usr/bin/env python3
"""Fails when a banned word appears in the repository, its commits or a PR.

The words are kept out of the repository: one extended regular expression per
line (case-insensitive, '#' lines and blank lines ignored), read from the file
in $BANNED_WORDS_FILE, else from $BANNED_WORDS (CI passes a repository secret
there), else from ~/.config/openplc-canopen/banned-words.txt. Without a list
the check says so and passes.

Findings name the place and the number of the list line that matched, never
the matched text, so a public CI log does not show the words either.

  check-banned-words.py --files                 tracked files: names and contents
  check-banned-words.py --staged                staged files (pre-commit hook)
  check-banned-words.py --range BASE..HEAD      commit messages, author and committer
  check-banned-words.py --message-file FILE     a commit message (commit-msg hook)
  check-banned-words.py --env-text VAR          text in an environment variable (PR title and body)
  --exclude PATH                                leave out files under PATH (repeatable)
"""

import argparse
import os
import re
import subprocess
import sys

DEFAULT_LIST = os.path.join(os.path.expanduser("~"), ".config", "openplc-canopen", "banned-words.txt")


def load_patterns():
    path = os.environ.get("BANNED_WORDS_FILE")
    if path:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    elif os.environ.get("BANNED_WORDS", "").strip():
        text = os.environ["BANNED_WORDS"]
    elif os.path.isfile(DEFAULT_LIST):
        with open(DEFAULT_LIST, encoding="utf-8") as f:
            text = f.read()
    else:
        return None
    patterns = []
    for number, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if line and not line.startswith("#"):
            patterns.append((number, re.compile(line.encode("utf-8"), re.IGNORECASE)))
    return patterns


def git(*args):
    return subprocess.run(["git"] + list(args), check=True, stdout=subprocess.PIPE).stdout


class Checker:
    def __init__(self, patterns):
        self.patterns = patterns
        self.findings = []

    def scan(self, where, data):
        """data: bytes. Records one finding per matching line and list entry."""
        for lineno, line in enumerate(data.split(b"\n"), 1):
            for number, rx in self.patterns:
                if rx.search(line):
                    self.findings.append("%s:%d: banned word (list line %d)" % (where, lineno, number))

    def scan_name(self, path):
        for number, rx in self.patterns:
            if rx.search(path.encode("utf-8", "surrogateescape")):
                self.findings.append("%s: banned word in the file name (list line %d)" % (path, number))


def excluded(path, excludes):
    return any(path == e or path.startswith(e.rstrip("/") + "/") for e in excludes)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--files", action="store_true")
    p.add_argument("--staged", action="store_true")
    p.add_argument("--range")
    p.add_argument("--message-file")
    p.add_argument("--env-text", action="append", default=[])
    p.add_argument("--exclude", action="append", default=[])
    args = p.parse_args(argv)

    patterns = load_patterns()
    if patterns is None:
        print("banned-word check: no list given (BANNED_WORDS_FILE, BANNED_WORDS or %s); skipped" % DEFAULT_LIST)
        return 0
    c = Checker(patterns)
    excludes = [e for e in args.exclude if e]

    if args.files:
        for path in git("ls-files", "-z").decode("utf-8", "surrogateescape").split("\0"):
            if not path or excluded(path, excludes):
                continue
            c.scan_name(path)
            if os.path.isfile(path) and not os.path.islink(path):
                with open(path, "rb") as f:
                    c.scan(path, f.read())
    if args.staged:
        names = git("diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z")
        for path in names.decode("utf-8", "surrogateescape").split("\0"):
            if not path or excluded(path, excludes):
                continue
            c.scan_name(path)
            c.scan(path, git("show", ":" + path))
    base = (args.range or "").split("..")[0]
    if args.range and base.strip("0") == "":
        print("banned-word check: no base commit in %r; commits not checked" % args.range)
    elif args.range:
        for sha in git("rev-list", args.range).decode().split():
            c.scan("commit %s message" % sha[:12], git("log", "-1", "--format=%B", sha))
            c.scan("commit %s author/committer" % sha[:12], git("log", "-1", "--format=%an <%ae>%n%cn <%ce>", sha))
    if args.message_file:
        with open(args.message_file, "rb") as f:
            c.scan("commit message", f.read())
    for var in args.env_text:
        c.scan(var, os.environ.get(var, "").encode("utf-8"))

    for f in c.findings:
        print(f)
    if c.findings:
        print("banned-word check: %d finding(s)" % len(c.findings), file=sys.stderr)
        return 1
    print("banned-word check: clean (%d words)" % len(patterns))
    return 0


if __name__ == "__main__":
    sys.exit(main())
