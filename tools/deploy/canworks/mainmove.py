"""Moving an OpenPLC project's `main` from the located variables the removed
canworks plugin had it declare (`rtd_ok : BOOL AT %IX10.0;`) to the
`canworks` variable list of OpenPLC through Modbus (`canworks.rtd_ok`)
(canopen-configurator "Old located variables in an OpenPLC project's main").

Only declarations whose names are members of the `canworks` list move; the
user's own located I/O, other POUs and the config stay as they are."""

import os
import re
import shutil

from .userdirs import replace_file

MAIN = os.path.join("pous", "programs", "main.st")
BACKUP = os.path.join("canworks", "main-before-move.st")
# The comment the plugin's project creation put into main's body.
OLD_BODY = "(* CANopen I/O declared from canworks/canworks.json *)"

_VAR_START = re.compile(r"^\s*VAR(?:_[A-Z_]+)?\b(?:\s+[A-Z_]+)*\s*$", re.I)
_VAR_END = re.compile(r"^\s*END_VAR\b", re.I)
# One declaration per line, in the editor's form or the standard one, with
# an optional initial value and comment.
_LOCATED = [
    re.compile(r"^\s*(?P<name>[A-Za-z_]\w*)\s*:\s*[^;:]+?\s+AT\s+(?P<loc>%[IQ][XBWDL]?[\d.]+)\s*(?::=[^;]*)?;\s*"
               r"(?:\(\*.*\*\)|//.*)?\s*$", re.I),
    re.compile(r"^\s*(?P<name>[A-Za-z_]\w*)\s+AT\s+(?P<loc>%[IQ][XBWDL]?[\d.]+)\s*:\s*[^;]+?;\s*"
               r"(?:\(\*.*\*\)|//.*)?\s*$", re.I),
]
_PLAIN = re.compile(r"^\s*(?P<names>[A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)*)\s*:(?!=)", re.I)
_IDENT = re.compile(r"[A-Za-z_]\w*")


class MainError(Exception):
    pass


def _located(line):
    for rx in _LOCATED:
        m = rx.match(line)
        if m:
            return m.group("name"), m.group("loc")
    return None


def scan(text, members):
    """The located declarations of `text` (a main.st) whose names are in
    `members` (the canworks list's member names), as [(name, location)], and
    the names also declared without a location (clashes, left alone)."""
    wanted = {m.lower() for m in members}
    found, plain = [], set()
    in_var = False
    for line in text.splitlines():
        if _VAR_START.match(line):
            in_var = True
            continue
        if _VAR_END.match(line):
            in_var = False
            continue
        if not in_var:
            continue
        hit = _located(line)
        if hit:
            if hit[0].lower() in wanted:
                found.append(hit)
            continue
        m = _PLAIN.match(line)
        if m:
            plain.update(n.strip().lower() for n in m.group("names").split(","))
    clashes = sorted({n for n, _ in found if n.lower() in plain})
    return [(n, loc) for n, loc in found if n not in clashes], clashes


def _replace_uses(code, names):
    """`code` with every use of `names` (lower case -> the list's spelling)
    written as canworks.<name>, outside comments and strings and not after
    a '.'; returns (code, number of uses)."""
    out, i, uses, n = [], 0, 0, len(code)
    while i < n:
        c = code[i]
        if code.startswith("(*", i):
            j = code.find("*)", i + 2)
            j = n if j < 0 else j + 2
        elif code.startswith("//", i):
            j = code.find("\n", i)
            j = n if j < 0 else j
        elif c in "'\"":
            j = i + 1
            while j < n and code[j] != c:
                j += 2 if code[j] == "$" else 1
            j = min(j + 1, n)
        else:
            m = _IDENT.match(code, i)
            if not m:
                out.append(c)
                i += 1
                continue
            word = m.group(0)
            k = i - 1
            while k >= 0 and code[k] in " \t\r\n":
                k -= 1
            name = names.get(word.lower())
            if name and (k < 0 or code[k] != ".") and not code.startswith("#", m.end()):
                out.append("canworks." + name)
                uses += 1
            else:
                out.append(word)
            i = m.end()
            continue
        out.append(code[i:j])
        i = j
    return "".join(out), uses


def move(text, members):
    """`text` with canworks' old located declarations removed and their uses
    written as canworks.<name>. Returns (text, moved [(name, location)],
    number of uses, clashes)."""
    found, clashes = scan(text, members)
    moving = {n.lower() for n, _ in found}
    names = {m.lower(): m for m in members if m.lower() in moving}  # the list's spelling
    lines = text.splitlines(keepends=True)
    kept, in_var, code_from = [], False, None
    for line in lines:
        if _VAR_START.match(line):
            in_var = True
        elif _VAR_END.match(line):
            in_var = False
        elif in_var:
            hit = _located(line)
            if hit and hit[0].lower() in names:
                continue
        elif line.strip() == OLD_BODY:
            continue
        kept.append(line)
    # The code is what follows the last END_VAR.
    for k, line in enumerate(kept):
        if _VAR_END.match(line):
            code_from = k + 1
    if code_from is None:
        code_from = 1 if kept and kept[0].lstrip().upper().startswith("PROGRAM") else 0
    head, code = "".join(kept[:code_from]), "".join(kept[code_from:])
    code, uses = _replace_uses(code, names)
    return head + code, found, uses, clashes


def project_scan(project_dir, members):
    """scan() of the project's main.st: {"count", "locations" (the first
    few), "clashes"}, or None when main.st is missing or declares none."""
    path = os.path.join(project_dir, MAIN)
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return None
    found, clashes = scan(text, members)
    if not found:
        return None
    return {"count": len(found), "locations": [loc for _, loc in found[:3]], "clashes": clashes}


def move_project(project_dir, members):
    """Moves the project's main.st, keeping the old text as BACKUP. Returns
    {"moved", "uses", "clashes", "backup"}."""
    path = os.path.join(project_dir, MAIN)
    try:
        with open(path, encoding="utf-8", newline="") as f:
            text = f.read()
    except OSError as e:
        raise MainError("cannot read %s: %s" % (MAIN, e))
    new, found, uses, clashes = move(text, members)
    if not found:
        raise MainError("main declares no canworks values at plugin locations")
    backup = os.path.join(project_dir, BACKUP)
    os.makedirs(os.path.dirname(backup), exist_ok=True)
    shutil.copyfile(path, backup)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(new)
    replace_file(tmp, path)
    return {"moved": [n for n, _ in found], "uses": uses, "clashes": clashes,
            "backup": BACKUP.replace(os.sep, "/")}
