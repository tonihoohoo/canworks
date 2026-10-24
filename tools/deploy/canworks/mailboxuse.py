"""Which mailbox blocks a program uses (mailboxes-on-demand; canopen-configurator
"Mailbox blocks the OpenPLC program declares"). The table of the library's
mailbox blocks and the parts of `bridge.mailboxes` each needs, the scan of
an OpenPLC Editor project's Structured Text for their instances, and the
parts a set of blocks needs.

The blocks over the bridge (CO_SDO_READ, CO_SDO_WRITE, CO_NMT,
CO_NODE_LIVE) need no mailbox and are not in the table.
"""

import json
import os
import re

from . import mailboxlayout

# Block -> parts: "request", "receive", "cyclic", "info".
BLOCK_PARTS = {
    "CO_SDO_READ_BYTES": ("request",),
    "CO_SDO_READ_STRING": ("request",),
    "CO_SDO_READ_REAL": ("request",),
    "CO_SDO_WRITE_BYTES": ("request",),
    "CO_SDO_WRITE_STRING": ("request",),
    "CO_SDO_WRITE_REAL": ("request",),
    "CAN_SEND": ("request",),
    "J1939_SEND": ("request",),
    "J1939_REQUEST": ("request",),
    "J1939_FIND_ECU": ("request",),
    "J1939_DM_READ": ("request",),
    "J1939_DM_CLEAR": ("request",),
    "CAN_RECEIVE": ("request", "receive"),
    "J1939_RECEIVE": ("request", "receive"),
    "CO_RECV_EMCY": ("request", "receive"),
    "CAN_SEND_CYCLIC": ("request", "cyclic"),
    "CAN_BUS_INFO": ("info",),
    "J1939_ECU_INFO": ("info",),
}

PART_WORDS = {"request": "a request mailbox", "receive": "the receive mailbox",
              "cyclic": "cyclic jobs", "info": "network info"}

# The canworks blocks' choices on a connection (modbus-connections "Canworks
# blocks choice of a connection") and the parts each needs.
CHOICE_PARTS = {"none": (), "sdo_send": ("request",), "receive": ("request", "receive"),
                "all": ("request", "receive", "cyclic", "info")}

# Generated programs that hold no instance of the program's own.
GENERATED = ("canworks_in", "canworks_out")

_COMMENT = re.compile(r"\(\*.*?\*\)|//[^\n]*|'(?:[^'$]|\$.)*'|\"(?:[^\"$]|\$.)*\"", re.S)
# `a, b : [ARRAY[...] OF ...] [ns.]TYPE`: the names, the bounds of every
# ARRAY level and the type without its namespace.
_DECL = re.compile(r"([A-Za-z_][\w]*(?:\s*,\s*[A-Za-z_][\w]*)*)\s*:\s*"
                   r"((?:ARRAY\s*\[[^\]]*\]\s*OF\s*)*)(?:[A-Za-z_]\w*\s*\.\s*)*([A-Za-z_]\w*)\b", re.I)
_ARRAY = re.compile(r"ARRAY\s*\[([^\]]*)\]", re.I)
_POU = re.compile(r"\b(PROGRAM|FUNCTION_BLOCK|FUNCTION)\s+([A-Za-z_]\w*)", re.I)
_CONSTANTS = re.compile(r"\bVAR(?:_GLOBAL)?\s+CONSTANT\b(.*?)\bEND_VAR\b", re.I | re.S)
_CONSTANT = re.compile(r"([A-Za-z_]\w*)\s*:\s*[A-Za-z_]\w*\s*:=\s*([^;]+);")
_WORD = re.compile(r"[A-Za-z_]\w*")
# POU files that are not Structured Text (ladder, FBD, SFC, the editor's
# JSON): only the type names they mention are read, each an unknown count.
_ST_EXT = (".st", ".il")
_OTHER_EXT = (".ld", ".fbd", ".sfc", ".json", ".xml", ".gvl", ".txt")


def strip(text):
    """ST text without comments and string literals (kept as blanks, so
    positions stay)."""
    return _COMMENT.sub(lambda m: " " * len(m.group(0)), text)


def _value(expr, constants):
    """The integer an array bound or constant stands for: integer literals,
    the project's constants and + - * between them; None otherwise."""
    tokens = re.findall(r"\d+|[A-Za-z_]\w*|[-+*()]|\S", expr)
    out = []
    for t in tokens:
        if t.isdigit():
            out.append(t)
        elif t in "+-*()":
            out.append(t)
        elif t.upper() in constants and constants[t.upper()] is not None:
            out.append(str(constants[t.upper()]))
        else:
            return None
    if not out or "**" in "".join(out):
        return None
    try:
        v = eval("".join(out), {"__builtins__": {}}, {})  # digits, + - * and parentheses only
    except (SyntaxError, TypeError, ValueError, ZeroDivisionError):
        return None
    return v if isinstance(v, int) else None


def _count(arrays, constants):
    """Elements of an `ARRAY[...] OF ... OF` prefix: the product of every
    dimension, None when a bound cannot be worked out."""
    n = 1
    for dims in _ARRAY.findall(arrays):
        for dim in dims.split(","):
            lo, sep, hi = dim.partition("..")
            lo, hi = _value(lo, constants), _value(hi, constants) if sep else None
            if lo is None or hi is None:
                return None
            n *= max(0, hi - lo + 1)
    return n


class _Program:
    """The POUs of a project and what each declares, read file by file and
    counted at the end, once every constant and function block is known."""

    def __init__(self):
        self.kinds = {}  # POU -> PROGRAM, FUNCTION_BLOCK, FUNCTION or LIST
        self.decls = []  # (pou, names, array prefix or None for unknown, type)
        self.constants = {}

    def add_text(self, text, fallback_name):
        clean = strip(text)
        for body in _CONSTANTS.findall(clean):
            for m in _CONSTANT.finditer(body):
                self.constants.setdefault(m.group(1).upper(), m.group(2))
        pous = [(m.start(), m.group(2), m.group(1).upper()) for m in _POU.finditer(clean)]
        for start, name, kind in pous:
            self.kinds.setdefault(name, kind)
        for m in _DECL.finditer(clean):
            pou = fallback_name
            for start, name, kind in pous:
                if start <= m.start():
                    pou = name
            names = [n for n in m.group(1).split(",") if n.strip()]
            self.decls.append((pou, len(names), m.group(2), m.group(3)))

    def add_words(self, text, pou):
        """A file the scan cannot parse: every word is a possible instance
        of an unknown count."""
        self.kinds.setdefault(pou, "PROGRAM")
        for word in set(_WORD.findall(text)):
            self.decls.append((pou, 1, None, word))

    def add_list(self, name, type_name):
        self.kinds.setdefault(name, "LIST")
        self.decls.append((name, 1, "", type_name))

    def found(self):
        constants = dict.fromkeys(self.constants)
        for _ in range(4):  # constants that use other constants
            for name, expr in self.constants.items():
                constants[name] = expr if isinstance(expr, int) else _value(str(expr), constants)
        fbs = {n.upper(): n for n, k in self.kinds.items() if k == "FUNCTION_BLOCK"}
        unknown = object()
        # Instances of each user FB inside each POU: {fb: [(pou, n or unknown)]}.
        users = {}
        direct = []
        for pou, names, arrays, type_name in self.decls:
            if pou in GENERATED:
                continue
            elements = _count(arrays, constants) if arrays is not None else None
            n = unknown if elements is None else names * elements
            t = type_name.upper()
            if t in BLOCK_PARTS:
                direct.append((pou, t, n))
            elif t in fbs and fbs[t] != pou:
                users.setdefault(fbs[t], []).append((pou, n))
        memo = {}

        def instances(pou, seen=()):
            if pou in memo:
                return memo[pou]
            if self.kinds.get(pou) != "FUNCTION_BLOCK" or pou not in users or pou in seen:
                return 1  # programs, lists, and FBs no POU declares: once
            total = 0
            for user, n in users[pou]:
                inner = instances(user, seen + (pou,))
                if n is unknown or inner is unknown:
                    total = unknown
                    break
                total += n * inner
            memo[pou] = total
            return total

        out = {}
        for pou, block, n in direct:
            k = instances(pou)
            per = out.setdefault(block, {})
            if n is unknown or k is unknown or per.get(pou, 0) is None:
                per[pou] = None
            else:
                per[pou] = per.get(pou, 0) + n * k
        return out


def scan_text(text, fallback_name="?"):
    """{block: {pou: instances}} of the mailbox block instances declared in
    one ST text (canopen-configurator "Mailbox detection in programs"). An
    array counts its elements, with constant bounds from the text; a block
    inside a function block counts once per instance of that FB, through
    nested FBs. None for a count the scan cannot work out."""
    prog = _Program()
    prog.add_text(text, fallback_name)
    return prog.found()


def scan_project(project_dir):
    """{block: {pou or variable list: instances}} of an OpenPLC Editor
    project: every POU file under pous/ (Structured Text and IL parsed, the
    other files by the type names they mention, an unknown count each) and
    the global variable lists of project.json, with its constants. {} when
    the folder has none."""
    prog = _Program()
    pous = os.path.join(project_dir, "pous")
    for root, dirs, files in os.walk(pous):
        dirs.sort()
        for name in sorted(files):
            stem, ext = os.path.splitext(name)
            ext = ext.lower()
            if stem in GENERATED or ext not in _ST_EXT + _OTHER_EXT:
                continue
            try:
                with open(os.path.join(root, name), encoding="utf-8", errors="replace") as f:
                    text = f.read()
            except OSError:
                continue
            if ext in _ST_EXT:
                prog.add_text(text, stem)
            elif not any(os.path.isfile(os.path.join(root, stem + e)) for e in _ST_EXT):
                # (a POU kept as text too is read from its text)
                prog.add_words(text, stem)
    try:
        with open(os.path.join(project_dir, "project.json"), encoding="utf-8") as f:
            data = (json.load(f) or {}).get("data") or {}
    except (OSError, ValueError, AttributeError):
        data = {}
    for lst in data.get("globalVariableLists") or []:
        if not isinstance(lst, dict):
            continue
        for v in lst.get("variables") or []:
            if not isinstance(v, dict):
                continue
            t = v.get("type")
            value = (t.get("value") if isinstance(t, dict) else t) or ""
            if not isinstance(value, str):
                continue
            init = v.get("initialValue")
            if "constant" in str(v.get("class") or "").lower() and isinstance(init, (int, str)) \
                    and isinstance(v.get("name"), str):
                prog.constants.setdefault(v["name"].upper(), init if isinstance(init, int) else str(init))
            prog.add_list(lst.get("name") or "global", value)
    return prog.found()


def parts_needed(found):
    """{part: count} the blocks need: request 1, receive 1, cyclic the
    instances of CAN_SEND_CYCLIC (4 to 16, 16 when a count is unknown),
    info 1."""
    need = {}
    for block, per in found.items():
        for part in BLOCK_PARTS.get(block, ()):
            if part == "cyclic":
                n = mailboxlayout.MAX_CYCLIC_JOBS if None in per.values() else sum(per.values())
                need["cyclic"] = need.get("cyclic", 0) + n
            else:
                need[part] = 1
    if "cyclic" in need:
        need["cyclic"] = min(mailboxlayout.MAX_CYCLIC_JOBS, max(4, need["cyclic"]))
    return need


def choice_parts(choice):
    """{part: count} a connection's canworks blocks choice needs."""
    need = {}
    for part in CHOICE_PARTS.get(choice or "none", ()):
        need[part] = 4 if part == "cyclic" else 1
    return need


def missing(mailboxes, need):
    """The parts of `need` that `mailboxes` (bridge.mailboxes, or None)
    lacks, in table order."""
    if not need:
        return []
    if not isinstance(mailboxes, dict):
        return [p for p in ("request", "receive", "cyclic", "info") if p in need]
    s = mailboxlayout.settings(mailboxes, 1)
    have = {"request": s["requests"] > 0, "receive": s["receive"], "cyclic": s["cyclic_jobs"] >= need.get("cyclic", 0),
            "info": bool(mailboxes.get("network_info", True))}
    return [p for p in ("request", "receive", "cyclic", "info") if p in need and not have[p]]


def mailboxes_for(need, current=None):
    """The `bridge.mailboxes` object that adds `need` to `current` (kept,
    locations included): only the parts needed are on in a new one."""
    if isinstance(current, dict):
        mb = dict(current)
        s = mailboxlayout.settings(current, 1)
        if "request" in need and s["requests"] < 1:
            mb["requests"] = 1
        if "receive" in need and not s["receive"]:
            mb["receive"] = True
        if "cyclic" in need and s["cyclic_jobs"] < need["cyclic"]:
            mb["cyclic_jobs"] = need["cyclic"]
        if "info" in need and not current.get("network_info", True):
            mb["network_info"] = True
        # Opening a receiver or a cyclic job needs a request mailbox.
        t = mailboxlayout.settings(mb, 1)
        if t["requests"] < 1 and (t["receive"] or t["cyclic_jobs"]):
            mb["requests"] = 1
        return mb
    opens = "receive" in need or need.get("cyclic", 0)
    return {"requests": 1 if "request" in need or opens else 0, "receive": "receive" in need,
            "cyclic_jobs": need.get("cyclic", 0), "network_info": "info" in need}


def describe(block, per, parts):
    """'main declares CAN_RECEIVE, which needs the request and receive
    mailboxes' (parts: the missing ones)."""
    where = ", ".join(sorted(per))
    words = [PART_WORDS[p] for p in parts]
    if parts == ["request", "receive"]:
        what = "the request and receive mailboxes"
    else:
        what = " and ".join(words)
    return "%s declare%s %s, which needs %s" % (where, "s" if len(per) == 1 else "", block, what)
