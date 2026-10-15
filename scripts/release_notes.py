#!/usr/bin/env python3
"""Release notes for the PC tools release deploy-v<version> (canopen-pc-install).

  release_notes.py --version V --repo OWNER/REPO --sha SHA [--previous TAG] --out FILE

The notes are tools/deploy/release-notes.md with {version}, {owner} and {repo}
filled in, then "What's new": one entry per pull request merged between the
previous release tag and SHA (from the "(#N)" at the end of the squash commit
subjects), the linked title and the PR description's "After:" paragraph, and
a "Full changelog" compare link. Commits without a PR are listed by subject.
Without --previous there is no "What's new".

The PR descriptions are read with `gh api` (REST). Before the notes are
written, the template text and every entry pass the banned-word check
(scripts/check-banned-words.py, same word list); a finding names the PR or
commit, never the word, and the script exits 1 without writing the file."""

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, "..", "tools", "deploy", "release-notes.md")
PR_SUBJECT = re.compile(r"\(#(\d+)\)\s*$")


def render_template(text, version, repo):
    owner = repo.split("/")[0]
    return text.replace("{version}", version).replace("{owner}", owner.lower()).replace("{repo}", repo)


def after_paragraph(body):
    """The text of the description's "After:" paragraph (up to the next blank
    line), as one line, or None."""
    lines = (body or "").replace("\r\n", "\n").split("\n")
    for i, line in enumerate(lines):
        m = re.match(r"\s*(?:\*\*)?After:(?:\*\*)?\s*(.*)$", line)
        if not m:
            continue
        parts = [m.group(1).strip()]
        for more in lines[i + 1:]:
            if not more.strip():
                break
            parts.append(more.strip())
        text = " ".join(p for p in parts if p)
        return text[:1].upper() + text[1:] if text else None
    return None


def commits(previous, sha):
    """Subjects of the commits after previous up to sha, oldest first."""
    out = subprocess.run(["git", "log", "--reverse", "--format=%h %s", "%s..%s" % (previous, sha)],
                         check=True, stdout=subprocess.PIPE, text=True).stdout
    return [tuple(line.split(" ", 1)) for line in out.splitlines() if line.strip()]


def gh_pull(repo, number):
    out = subprocess.run(["gh", "api", "repos/%s/pulls/%d" % (repo, number)],
                         check=True, stdout=subprocess.PIPE, text=True).stdout
    return json.loads(out)


def entries(subjects, repo, fetch=gh_pull):
    """(where, markdown line) per commit: "PR #N" or "commit <short sha>"."""
    result = []
    for short, subject in subjects:
        m = PR_SUBJECT.search(subject)
        if not m:
            result.append(("commit %s" % short, "- %s" % subject.strip()))
            continue
        number = int(m.group(1))
        pr = fetch(repo, number)
        title = (pr.get("title") or subject[:m.start()]).strip()
        url = pr.get("html_url") or "https://github.com/%s/pull/%d" % (repo, number)
        line = "- **[%s](%s)**" % (title, url)
        after = after_paragraph(pr.get("body"))
        if after:
            line += ": " + after
        result.append(("PR #%d" % number, line))
    return result


def compose(header, items, repo, previous, version):
    text = header.rstrip("\n") + "\n"
    if previous is None:
        return text
    text += "\n## What's new\n\n"
    text += "\n".join(line for _, line in items) + "\n" if items else "No pull requests since %s.\n" % previous
    text += "\n**Full changelog**: https://github.com/%s/compare/%s...deploy-v%s\n" % (repo, previous, version)
    return text


def banned_findings(header, items):
    """Findings of the banned-word check, or None when no word list is set."""
    spec = importlib.util.spec_from_file_location("check_banned_words", os.path.join(HERE, "check-banned-words.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    patterns = module.load_patterns()
    if patterns is None:
        return None
    checker = module.Checker(patterns)
    checker.scan("release notes template", header.encode("utf-8"))
    for where, line in items:
        checker.scan(where, line.encode("utf-8"))
    # One finding per place is enough: the line number of a one-line entry says nothing.
    return sorted({f.split(":")[0] if not f.startswith("release notes template") else f for f in checker.findings})


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--version", required=True)
    p.add_argument("--repo", required=True)
    p.add_argument("--sha", required=True)
    p.add_argument("--previous")
    p.add_argument("--template", default=TEMPLATE)
    p.add_argument("--out", required=True)
    args = p.parse_args(argv)

    with open(args.template, encoding="utf-8") as f:
        header = render_template(f.read(), args.version, args.repo)
    items = entries(commits(args.previous, args.sha), args.repo) if args.previous else []

    findings = banned_findings(header, items)
    if findings is None:
        print("release notes: no banned-word list given; not checked")
    elif findings:
        for where in findings:
            print("%s: banned word; fix the text there and run the release again" % where)
        return 1

    with open(args.out, "w", encoding="utf-8") as f:
        f.write(compose(header, items, args.repo, args.previous, args.version))
    print("release notes: %d entries since %s" % (len(items), args.previous or "the start"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
