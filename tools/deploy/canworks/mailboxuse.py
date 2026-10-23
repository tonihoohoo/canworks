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
_DECL = re.compile(r"([A-Za-z_][\w]*(?:\s*,\s*[A-Za-z_][\w]*)*)\s*:\s*"
                   r"(?:ARRAY\s*\[\s*(-?\d+)\s*\.\.\s*(-?\d+)\s*\]\s*OF\s*)?([A-Za-z_][\w]*)\b", re.I)
_POU = re.compile(r"\b(PROGRAM|FUNCTION_BLOCK|FUNCTION)\s+([A-Za-z_]\w*)", re.I)


def strip(text):
    """ST text without comments and string literals (kept as blanks, so
    positions stay)."""
    return _COMMENT.sub(lambda m: " " * len(m.group(0)), text)


def scan_text(text, fallback_name="?"):
    """{block: {pou: instances}} of the mailbox block instances declared in
    one ST text. An ARRAY[a..b] OF a block counts b - a + 1."""
    clean = strip(text)
    pous = [(m.start(), m.group(2)) for m in _POU.finditer(clean)]
    found = {}
    for m in _DECL.finditer(clean):
        block = m.group(4).upper()
        if block not in BLOCK_PARTS:
            continue
        names = [n for n in m.group(1).split(",") if n.strip()]
        n = len(names)
        if m.group(2) is not None:
            n *= max(0, int(m.group(3)) - int(m.group(2)) + 1)
        pou = fallback_name
        for start, name in pous:
            if start <= m.start():
                pou = name
        if pou in GENERATED:
            continue
        per = found.setdefault(block, {})
        per[pou] = per.get(pou, 0) + n
    return found


def _merge(into, found):
    for block, per in found.items():
        dst = into.setdefault(block, {})
        for pou, n in per.items():
            dst[pou] = dst.get(pou, 0) + n


def scan_project(project_dir):
    """{block: {pou or variable list: instances}} of an OpenPLC Editor
    project: every .st file under pous/ and the global variable lists of
    project.json. {} when the folder has neither."""
    found = {}
    pous = os.path.join(project_dir, "pous")
    for root, dirs, files in os.walk(pous):
        dirs.sort()
        for name in sorted(files):
            if not name.lower().endswith(".st"):
                continue
            stem = os.path.splitext(name)[0]
            if stem in GENERATED:
                continue
            try:
                with open(os.path.join(root, name), encoding="utf-8", errors="replace") as f:
                    _merge(found, scan_text(f.read(), stem))
            except OSError:
                continue
    try:
        with open(os.path.join(project_dir, "project.json"), encoding="utf-8") as f:
            data = (json.load(f) or {}).get("data") or {}
    except (OSError, ValueError, AttributeError):
        data = {}
    for lst in data.get("globalVariableLists") or []:
        if not isinstance(lst, dict):
            continue
        for v in lst.get("variables") or []:
            t = v.get("type") if isinstance(v, dict) else None
            value = (t.get("value") if isinstance(t, dict) else t) or ""
            if isinstance(value, str) and value.upper() in BLOCK_PARTS:
                _merge(found, {value.upper(): {lst.get("name") or "global": 1}})
    return found


def parts_needed(found):
    """{part: count} the blocks need: request 1, receive 1, cyclic the
    instances of CAN_SEND_CYCLIC (4 to 16), info 1."""
    need = {}
    for block, per in found.items():
        for part in BLOCK_PARTS.get(block, ()):
            if part == "cyclic":
                need["cyclic"] = need.get("cyclic", 0) + sum(per.values())
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
        return mb
    return {"requests": 1 if "request" in need else 0, "receive": "receive" in need,
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
