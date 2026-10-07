"""IEC locations an editor project already uses, read from its files.

The editor's file layout changes between releases, so this does not read
fields by name: every JSON string anywhere in the project that parses as a
located address is a use, and so is every `<name> AT <location>` or
`<name> : <type> AT <location>` (the editor's own form) in a text file (POU
sources). Uses under devices/ are producers (Modbus remote devices,
EtherCAT channels, pin mapping); everything else is a located variable. An
alias name (`lamp`) does not parse as a location and is skipped.
"""

import json
import os
import re

from ..iec import parse_location

SKIP_DIRS = {"build", "canopen", ".git", "node_modules"}
TEXT_EXT = {".st", ".il", ".ld", ".fbd", ".sfc", ".gvl", ".txt"}
_AT = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*(?:\([^)]*\))?\s+AT\s+(%[IQM][XBWDL]?[0-9]+(?:\.[0-9]+)?)", re.IGNORECASE)
# The editor's own form, `name : TYPE AT %loc;`: the name is before the colon.
_TYPE_AT = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*:\s*[^;:=()]*?(?:\([^)]*\))?\s+AT\s+(%[IQM][XBWDL]?[0-9]+(?:\.[0-9]+)?)",
                      re.IGNORECASE)


def located(line):
    """[(name, location text)] for every located declaration on one line,
    in either `name AT loc : TYPE` or `name : TYPE AT loc` form."""
    found, taken = [], []
    for m in _TYPE_AT.finditer(line):
        found.append((m.start(), m.group(1), m.group(2)))
        taken.append(m.span(2))
    for m in _AT.finditer(line):
        if m.span(2) not in taken:
            found.append((m.start(), m.group(1), m.group(2)))
    return [(name, loc) for _, name, loc in sorted(found)]
MAX_FILE = 8 * 1024 * 1024


class Use:
    def __init__(self, file, path, loc, kind, name=None):
        self.file = file  # relative to the project, with /
        self.path = path  # JSON path, or "line N" in a text file
        self.loc = loc
        self.kind = kind  # "device" or "variable"
        self.name = name

    def key(self):
        return (self.loc.area, self.loc.size, self.loc.element)

    def describe(self):
        who = " (%s)" % self.name if self.name else ""
        return "%s %s%s" % (self.file, self.path, who)

    def as_dict(self):
        return {"file": self.file, "path": self.path, "location": str(self.loc), "kind": self.kind,
                "name": self.name}


def _json_path(parts):
    out = ""
    for p in parts:
        out += "[%d]" % p if isinstance(p, int) else ("." if out else "") + str(p)
    return out


def _walk(value, file, parts, kind, out, owner=None):
    if isinstance(value, dict):
        name = value.get("name") if isinstance(value.get("name"), str) else owner
        for key, child in value.items():
            if isinstance(child, str):
                loc = parse_location(child)
                if loc is not None:
                    out.append(Use(file, _json_path(parts + [key]), loc, kind, name))
            else:
                _walk(child, file, parts + [key], kind, out, name)
    elif isinstance(value, list):
        for i, child in enumerate(value):
            _walk(child, file, parts + [i], kind, out, owner)


def scan(project_dir):
    """Returns (uses, problems). Files that cannot be read are listed in
    problems and otherwise skipped."""
    uses, problems = [], []
    for root, dirs, files in os.walk(project_dir):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith("."))
        for name in sorted(files):
            full = os.path.join(root, name)
            rel = os.path.relpath(full, project_dir).replace(os.sep, "/")
            ext = os.path.splitext(name)[1].lower()
            if ext != ".json" and ext not in TEXT_EXT:
                continue
            try:
                if os.path.getsize(full) > MAX_FILE:
                    problems.append("%s: larger than %d bytes, not scanned" % (rel, MAX_FILE))
                    continue
                with open(full, encoding="utf-8", errors="replace") as f:
                    text = f.read()
            except OSError as e:
                problems.append("%s: %s" % (rel, e))
                continue
            kind = "device" if rel.startswith("devices/") else "variable"
            if ext == ".json":
                if not text.strip():
                    continue
                try:
                    doc = json.loads(text)
                except ValueError as e:
                    problems.append("%s: not readable JSON (%s); its locations are not checked" % (rel, e))
                    continue
                _walk(doc, rel, [], kind, uses)
            else:
                for n, line in enumerate(text.splitlines(), 1):
                    for name, text in located(line):
                        loc = parse_location(text)
                        if loc is not None:
                            uses.append(Use(rel, "line %d" % n, loc, "variable", name))
    return uses, problems
