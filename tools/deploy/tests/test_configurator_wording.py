"""The configurator page's word list (visual-refresh, docs/wording.md): no
human-readable string in the page's files or the configurator server's
messages uses a term the list rules out. No browser needed.

Human-readable means a string literal with a space and a word in it, so
identifiers and config keys ("bitrate", "node_id") are not checked."""

import ast
import json
import re
import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIGURATOR = ROOT / "canworks" / "configurator"
STATIC = CONFIGURATOR / "static"
WORDING = Path(__file__).resolve().parent / "data" / "wording" / "wording.json"
HUMAN = re.compile(r"[A-Za-z]{2,}.*\s|\s.*[A-Za-z]{2,}", re.S)
REGEX_BEFORE = set("(,=:[!&|?{};+-*%<>~^")


def js_strings(source):
    """Yield (line, text) for each string literal in JavaScript source, with
    template substitutions replaced by "X". Comments and regex literals are
    skipped. A small scanner, good enough for this code base."""
    i, n, line, last = 0, len(source), 1, ""
    while i < n:
        c = source[i]
        if c == "\n":
            line += 1
            i += 1
            continue
        if source.startswith("//", i):
            j = source.find("\n", i)
            i = n if j < 0 else j
            continue
        if source.startswith("/*", i):
            j = source.find("*/", i + 2)
            j = n if j < 0 else j + 2
            line += source.count("\n", i, j)
            i = j
            continue
        if c == "/" and (last in REGEX_BEFORE or last == "" or re.search(r"\b(return|typeof|case)\s*$", source[max(0, i - 8):i])):
            j, in_class = i + 1, False
            while j < n and source[j] != "\n":
                if source[j] == "\\":
                    j += 2
                    continue
                if source[j] == "[":
                    in_class = True
                elif source[j] == "]":
                    in_class = False
                elif source[j] == "/" and not in_class:
                    break
                j += 1
            i, last = j + 1, "/"
            continue
        if c in "\"'`":
            start_line, j, out, depth = line, i + 1, [], 0
            while j < n:
                d = source[j]
                if d == "\\":
                    out.append(source[j + 1:j + 2] if source[j + 1:j + 2] not in "nt" else " ")
                    j += 2
                    continue
                if c == "`" and source.startswith("${", j):
                    depth, j = 1, j + 2
                    while j < n and depth:
                        depth += {"{": 1, "}": -1}.get(source[j], 0)
                        if source[j] == "\n":
                            line += 1
                        j += 1
                    out.append("X")
                    continue
                if d == c:
                    break
                if d == "\n":
                    line += 1
                out.append(d)
                j += 1
            yield start_line, "".join(out)
            i, last = j + 1, "s"
            continue
        if not c.isspace():
            last = c
        i += 1


class _HTMLText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.found, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        for k, v in attrs:
            if k in ("title", "aria-label", "placeholder", "alt", "aria-description") and v:
                self.found.append((self.getpos()[0], v))

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip and data.strip():
            self.found.append((self.getpos()[0], " ".join(data.split())))


def html_strings(source):
    p = _HTMLText()
    p.feed(source)
    return p.found


def py_strings(source):
    tree = ast.parse(source)
    docs = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                docs.add(id(first.value))
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            text = "".join(v.value if isinstance(v, ast.Constant) else "X" for v in node.values)
            yield node.lineno, text
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs:
            yield node.lineno, node.value


def page_strings():
    for path in sorted(STATIC.glob("*.js")):
        for line, text in js_strings(path.read_text(encoding="utf-8")):
            yield path, line, text
    for path in sorted(STATIC.glob("*.html")):
        for line, text in html_strings(path.read_text(encoding="utf-8")):
            yield path, line, text
    for path in sorted(CONFIGURATOR.glob("*.py")):
        for line, text in py_strings(path.read_text(encoding="utf-8")):
            yield path, line, text


def findings(strings, wording):
    rules = [(re.compile(r["pattern"]), r["preferred"]) for r in wording["rules"]]
    allow = wording.get("allow", [])
    for path, line, text in strings:
        if not HUMAN.search(text) or any(a in text for a in allow):
            continue
        for rx, preferred in rules:
            m = rx.search(text)
            if m:
                yield f"{path.relative_to(ROOT).as_posix()}:{line}: \"{m.group(0).strip()}\" in {text.strip()[:90]!r}: use {preferred}"


class Wording(unittest.TestCase):
    def wording(self):
        return json.loads(WORDING.read_text())

    def test_page_follows_the_word_list(self):
        found = list(findings(page_strings(), self.wording()))
        self.assertEqual(found, [], "\n" + "\n".join(found))

    def test_ruled_out_term_is_caught(self):
        fake = [(STATIC / "app.js", 12, "Set baudrate"), (STATIC / "app.js", 13, "Error: no node id given")]
        found = list(findings(fake, self.wording()))
        self.assertEqual(len(found), 3, found)
        self.assertIn("static/app.js:12", found[0])
        self.assertIn("bit rate", found[0])

    def test_identifiers_are_not_checked(self):
        fake = [(STATIC / "app.js", 1, "bitrate"), (STATIC / "app.js", 2, "node_id")]
        self.assertEqual(list(findings(fake, self.wording())), [])

    def test_scanner(self):
        src = 'const a = "x"; // "Baud rate" in a comment\nconst r = /"[^"]*"/g; el("p", null, `Node ${id} at ${rate}kbps`);'
        self.assertEqual([t for _, t in js_strings(src)], ["x", "p", "Node X at Xkbps"])


if __name__ == "__main__":
    unittest.main()
