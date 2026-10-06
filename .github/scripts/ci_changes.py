#!/usr/bin/env python3
"""Classify a push or pull request for CI: code (run the full suite) or docs
(documentation and specs only: skip the build and test jobs).

  ci_changes.py <base> <head>   prints code=true|false and the changed files

The documentation allow-list is openspec/**, docs/** and Markdown outside
test/, config/ and tools/ (fixtures and packaged files a test may read).
Anything else, the workflows included, is code. A missing or unknown base
(new branch, force push) is code.
"""

import subprocess
import sys

NOT_DOCS_MD = ("test/", "config/", "tools/")


def is_docs(path):
    if path.startswith(("openspec/", "docs/")):
        return True
    return path.endswith(".md") and not path.startswith(NOT_DOCS_MD)


def is_code(paths):
    return not paths or not all(is_docs(p) for p in paths)


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
    for p in paths or []:
        sys.stderr.write(f"{'docs' if is_docs(p) else 'code'}  {p}\n")
    if paths is None:
        sys.stderr.write("base unknown: full suite\n")
    print(f"code={'true' if code else 'false'}")


if __name__ == "__main__":
    main(sys.argv)
