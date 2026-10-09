"""The EDS lint the plugin runs before dcfgen, shared by the configurator and
the deploy tool (canopen-master-bringup: "Prepared EDS copy", "EDS lint scope").

prepare() makes the copy every PLC reader uses (Lely's EDS parser in the
plugin and dcfgen): UTF-8, "$NODEID+<n>", REAL values as Lely's hex bit
pattern, OCTET_STRING/DOMAIN values Lely cannot read cleared. lint() runs
dcfgen's own lint and read step on that copy (Lely's dcf package, vendored in
_lely_dcf at the commit the PLC builds) and sorts the findings: blocking ones
are in the communication area 0x1000-0x1FFF and not limit-only.

On the PLC the plugin runs:
  python -m canworks.edslint --json --node-id N --mode MODE
         --label LABEL --name NAME --out COPY EDS
and reads one JSON object from stdout (see main()): "prepared" (COPY when a
correction applied, else null), "notes" (one log line per correction),
"error" (the load must stop) and "warning" (accepted findings), both in the
plugin's words, besides the raw "corrections" and "findings".
"""

import argparse
import functools
import io
import json
import os
import re
import struct
import sys
import tempfile
import warnings

from ._lely_dcf import parse as _lely_parse
from ._lely_dcf.device import Device as _Device
from ._lely_dcf.lint import lint as _lint
from ._lely_dcf.parse import parse_file as _parse_file
from .eds import to_utf8

# Lely's parse_file opens the EDS without an encoding, so it reads in the
# locale's encoding: UTF-8 on the PLC, but CP1252 on Windows. Files reach it
# prepared as UTF-8 (to_utf8), so read them as UTF-8 everywhere, as on the PLC.
# The vendored file stays unchanged; only the name it looks up is replaced.
_lely_parse.open = functools.partial(io.open, encoding="utf-8")

MODES = ("communication", "all", "off")
DEFAULT_MODE = "communication"

_REAL32, _REAL64 = 0x0008, 0x0011
_OCTET_STRING, _DOMAIN = 0x000A, 0x000F
_VALUE_KEYS = ("defaultvalue", "parametervalue")
_NUMBER_KEYS = _VALUE_KEYS + ("lowlimit", "highlimit")

# The integer ranges of dcf.lint (__limits), for the limit-only rule.
_TYPE_RANGE = {
    0x0001: (0, 1), 0x0002: (-0x80, 0x7F), 0x0003: (-0x8000, 0x7FFF), 0x0004: (-0x80000000, 0x7FFFFFFF),
    0x0005: (0, 0xFF), 0x0006: (0, 0xFFFF), 0x0007: (0, 0xFFFFFFFF), 0x0010: (-0x800000, 0x7FFFFF),
    0x0012: (-0x8000000000, 0x7FFFFFFFFF), 0x0013: (-0x800000000000, 0x7FFFFFFFFFFF),
    0x0014: (-0x80000000000000, 0x7FFFFFFFFFFFFF), 0x0015: (-0x8000000000000000, 0x7FFFFFFFFFFFFFFF),
    0x0016: (0, 0xFFFFFF), 0x0018: (0, 0xFFFFFFFFFF), 0x0019: (0, 0xFFFFFFFFFFFF),
    0x001A: (0, 0xFFFFFFFFFFFFFF), 0x001B: (0, 0xFFFFFFFFFFFFFFFF),
}

_SECTION = re.compile(r"^\s*\[([^\]]*)\]")
_ENTRY = re.compile(r"^(\s*([A-Za-z_0-9]+)\s*=\s*)(.*?)(\s*([;#].*)?)$")
_NODEID_SUFFIX = re.compile(r"^(0x[0-9a-f]+|[0-9]+)\s*\+\s*\$NODEID$", re.IGNORECASE)
_DECIMAL_REAL = re.compile(r"^[+-]?(\d+\.\d*|\.\d+|\d+(?=[eE]))([eE][+-]?\d+)?$")
_VALUE = re.compile(r"^(\$NODEID\s*\+\s*)?(-?0x[0-9a-f]+|-?[0-9]+)$", re.IGNORECASE)


class Correction:
    """One kind of change prepare() made, with each change it made."""

    def __init__(self, kind, text):
        self.kind, self.text, self.items = kind, text, []

    def to_json(self):
        return {"kind": self.kind, "text": self.text, "count": len(self.items), "items": self.items}


def _lines(text):
    """(line without its end, line end) for each line."""
    for line in text.splitlines(True):
        body = line.rstrip("\r\n")
        yield body, line[len(body):]


def _data_types(text):
    """{section name (lower case): DataType} for the sections that give one."""
    types, section = {}, None
    for line, _ in _lines(text):
        m = _SECTION.match(line)
        if m:
            section = m.group(1).strip().lower()
            continue
        m = _ENTRY.match(line)
        if section and m and m.group(2).lower() == "datatype":
            try:
                types[section] = int(m.group(3), 0)
            except ValueError:
                pass
    return types


def _real_hex(value, data_type):
    """Lely's form of a decimal REAL value: the hexadecimal bit pattern, or
    None when the value does not fit."""
    try:
        if data_type == _REAL32:
            return "0x%08X" % struct.unpack(">I", struct.pack(">f", float(value)))[0]
        return "0x%016X" % struct.unpack(">Q", struct.pack(">d", float(value)))[0]
    except (OverflowError, struct.error, ValueError):
        return None


def prepare(data):
    """(prepared text, [Correction]) for an EDS file's bytes. Only kinds that
    changed something are returned; the text is the input when none did."""
    raw, converted = to_utf8(data)
    text = raw.decode("utf-8")
    utf8 = Correction("utf8", "converted from CP1252 to UTF-8")
    if converted:
        utf8.items.append({})
    nodeid = Correction("nodeid", "\"<number>+$NODEID\" rewritten as \"$NODEID+<number>\"")
    real = Correction("real", "decimal REAL values rewritten as Lely's hexadecimal bit pattern")
    octets = Correction("string", "OCTET_STRING/DOMAIN values Lely cannot read cleared")
    types = _data_types(text)

    out, section = [], None
    for line, end in _lines(text):
        m = _SECTION.match(line)
        if m:
            section = m.group(1).strip()
        m = None if _SECTION.match(line) else _ENTRY.match(line)
        if m and section is not None:
            head, key, value, tail = m.group(1), m.group(2).lower(), m.group(3), m.group(4)
            data_type = types.get(section.lower())
            new = None
            where = {"section": section, "key": m.group(2), "old": value}
            if key in _NUMBER_KEYS and _NODEID_SUFFIX.match(value):
                new = "$NODEID+" + _NODEID_SUFFIX.match(value).group(1)
                nodeid.items.append(dict(where, new=new))
            elif key in _NUMBER_KEYS and data_type in (_REAL32, _REAL64) and _DECIMAL_REAL.match(value):
                new = _real_hex(value, data_type)
                if new is not None:
                    real.items.append(dict(where, new=new))
            elif (key in _VALUE_KEYS and data_type in (_OCTET_STRING, _DOMAIN) and value
                  and value[0] not in "0123456789abcdefABCDEF"):
                # Lely reads these as hex digits; a value that does not start
                # with one is a parse error ("unable to parse DefaultValue").
                new = ""
                octets.items.append(dict(where, new=new))
            if new is not None:
                line = head + new + tail
        out.append(line + end)
    corrections = [c for c in (utf8, nodeid, real, octets) if c.items]
    return ("".join(out) if corrections else text), corrections


# -- lint -----------------------------------------------------------------

_SECTION_IN_MESSAGE = re.compile(r"\[([^\]]+)\]")
_INDEX_IN_MESSAGE = re.compile(r"0x([0-9A-Fa-f]{4})\b")
_OBJECT_SECTION = re.compile(r"^([0-9A-Fa-f]{4})(sub[0-9A-Fa-f]+|value|name)?$", re.IGNORECASE)
# Messages about an object list's classification, not the object itself.
_LISTING = re.compile(r"is not mandatory|is manufacturer-specific|is not manufacturer-specific|"
                      r"data type objects are not supported")
_LIMIT = re.compile(r"^(invalid (LowLimit|HighLimit) in|(LowLimit|HighLimit) (overflow|underflow|not supported) in)")
_VALUE_RANGE = re.compile(r"^(DefaultValue|ParameterValue) (overflow|underflow) in \[([^\]]+)\]$")


class Finding:
    def __init__(self, message, section, index, limit_only, blocking):
        self.message, self.section, self.index = message, section, index
        self.limit_only, self.blocking = limit_only, blocking

    def where(self):
        if self.index is None:
            return "[%s]" % self.section if self.section else "file"
        m = _OBJECT_SECTION.match(self.section or "")
        sub = m.group(2) if m else None
        if sub and sub.lower().startswith("sub"):
            return "0x%04X sub %d" % (self.index, int(sub[3:], 16))
        return "0x%04X" % self.index

    def to_json(self):
        return {"message": self.message, "section": self.section, "index": self.index,
                "object": self.where(), "limit_only": self.limit_only, "blocking": self.blocking}


def _value_inside_type(cfg, section, entry, node_id):
    """True when the DefaultValue/ParameterValue of a section lies inside its
    data type's range (with $NODEID at node_id), so a range finding about it
    can only be about the section's own limits."""
    try:
        sec = cfg[section]
        data_type = int(sec["DataType"], 0)
        value = sec[entry].strip()
    except (KeyError, ValueError):
        return False
    if data_type in (_REAL32, _REAL64):
        return True  # any bit pattern is a REAL; a range finding is about the limits
    if data_type not in _TYPE_RANGE:
        return False
    if value.upper() == "$NODEID":
        number = node_id
    else:
        m = _VALUE.match(value)
        if not m:
            return False
        try:
            number = int(m.group(2), 0) + (node_id if m.group(1) else 0)
        except ValueError:
            return False
    low, high = _TYPE_RANGE[data_type]
    return low <= number <= high


def classify(cfg, message, node_id):
    """A Finding for one dcf.lint message."""
    m = _SECTION_IN_MESSAGE.search(message)
    section = m.group(1) if m else None
    index = None
    om = _OBJECT_SECTION.match(section or "")
    if om:
        index = int(om.group(1), 16)
    elif section is None:
        im = _INDEX_IN_MESSAGE.search(message)
        if im:
            index = int(im.group(1), 16)
    elif message.startswith("unknown section in DCF: "):
        pass
    limit_only = bool(_LIMIT.match(message))
    vm = _VALUE_RANGE.match(message)
    if vm:
        limit_only = _value_inside_type(cfg, vm.group(3), vm.group(1), node_id)
    blocking = (index is not None and 0x1000 <= index <= 0x1FFF and not limit_only
                and not _LISTING.search(message))
    return Finding(message, section, index, limit_only, blocking)


class Result:
    def __init__(self, read_error, findings):
        self.read_error, self.findings = read_error, findings

    def failing(self, mode):
        """The findings that stop the PLC under an eds_lint mode."""
        if mode == "off":
            return []
        if mode == "all":
            return list(self.findings)
        return [f for f in self.findings if f.blocking]

    def accepted(self, mode):
        failing = self.failing(mode)
        return [f for f in self.findings if f not in failing]


def lint_text(text, node_id=1):
    """Result of dcfgen's lint and read on a prepared EDS text."""
    fd, path = tempfile.mkstemp(suffix=".eds", prefix="edslint-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        return lint_file(path, node_id)
    finally:
        os.remove(path)


def lint_file(path, node_id=1):
    """Result of dcfgen's lint and read on a prepared EDS file."""
    try:
        cfg = _parse_file(path)
    except Exception as e:  # configparser errors, a file dcfgen cannot read
        return Result("dcfgen cannot read the file: %s" % str(e).splitlines()[0], [])
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            _lint(cfg)
        except Exception as e:
            return Result("dcfgen's lint fails on the file: %s: %s" % (type(e).__name__, e), [])
    findings = [classify(cfg, str(w.message), node_id) for w in caught]
    # dcfgen's next step: build the device (a Value for every sub-object).
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            _Device(cfg, {"NODEID": node_id})
        except Exception as e:
            return Result("dcfgen cannot read the file: %s: %s" % (type(e).__name__, e), findings)
    return Result(None, findings)


def check(data, node_id=1):
    """(prepared text, [Correction], Result) for an EDS file's bytes."""
    text, corrections = prepare(data)
    return text, corrections, lint_text(text, node_id)


def effective_mode(master):
    """The eds_lint mode of a config's master object (strict_eds read as the
    pre-contract alias); the default when neither is given or valid."""
    master = master if isinstance(master, dict) else {}
    mode = master.get("eds_lint")
    if mode in MODES:
        return mode
    strict = master.get("strict_eds")
    if isinstance(strict, bool) and "eds_lint" not in master:
        return "all" if strict else "off"
    return DEFAULT_MODE


def error_text(label, eds_name, failing, mode):
    """The plugin's error for findings that stop the load."""
    other = "\"off\"" if any(f.blocking for f in failing) else "\"communication\""
    parts = "; ".join("%s: %s" % (f.where(), f.message) for f in failing)
    return ("%sEDS %s fails dcfgen's lint (eds_lint \"%s\"): %s; eds_lint: %s would accept it"
            % (label + ": " if label else "", eds_name, mode, parts, other))


def warning_text(eds_name, accepted, mode=DEFAULT_MODE):
    """The plugin's one warning for findings that do not stop the load."""
    first = "; ".join("%s: %s" % (f.where(), f.message) for f in accepted[:3])
    why = "eds_lint \"off\"" if mode == "off" else "not in the communication objects, or only about limits"
    return ("EDS %s: %d lint finding%s accepted (%s): %s%s"
            % (eds_name, len(accepted), "" if len(accepted) == 1 else "s", why, first,
               "; ..." if len(accepted) > 3 else ""))


def _object_name(section):
    m = _OBJECT_SECTION.match(section or "")
    if not m:
        return "[%s]" % section
    return Finding("", section, int(m.group(1), 16), False, False).where()


def prepared_note(label, eds_name, corrections, prepared):
    """The plugin's one log line for a node whose EDS needed corrections:
    each kind with its count, cleared values with their object and old text."""
    parts = []
    for c in corrections:
        if c.kind == "utf8":
            parts.append(c.text)
            continue
        part = "%s (%d)" % (c.text, len(c.items))
        if c.kind == "string":
            part += ": " + ", ".join("%s %s was \"%s\"" % (_object_name(i["section"]), i["key"], i["old"])
                                     for i in c.items)
        parts.append(part)
    return "%s: EDS %s read through a prepared copy%s: %s" % (
        label, eds_name, " (%s)" % prepared if prepared else "", "; ".join(parts))


def verdict(label, eds_name, corrections, result, mode, prepared=None):
    """(error or None, warning or None, [note]) for one node's EDS under an
    eds_lint mode, in the plugin's words."""
    notes = [prepared_note(label, eds_name, corrections, prepared)] if corrections else []
    if result.read_error:
        return "%s: EDS %s: %s" % (label, eds_name, result.read_error), None, notes
    failing, accepted = result.failing(mode), result.accepted(mode)
    error = error_text(label, eds_name, failing, mode) if failing else None
    warning = warning_text(eds_name, accepted, mode) if accepted else None
    return error, warning, notes


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m canworks.edslint",
                                description="Prepare an EDS for dcfgen and run dcfgen's lint, sorted by the "
                                            "plugin's rule.")
    p.add_argument("eds")
    p.add_argument("--node-id", type=int, default=1)
    p.add_argument("--out", help="write the prepared copy here (only when a correction applies)")
    p.add_argument("--json", action="store_true", help="print one JSON object")
    p.add_argument("--mode", choices=MODES, default=DEFAULT_MODE, help="eds_lint mode for the verdict")
    p.add_argument("--label", default=None, help="the node in messages, such as \"node 2 (valve)\"")
    p.add_argument("--name", default=None, help="the EDS in messages (default: the file name)")
    args = p.parse_args(argv)
    try:
        with open(args.eds, "rb") as f:
            data = f.read()
    except OSError as e:
        print(json.dumps({"error": str(e)}) if args.json else str(e), file=sys.stdout if args.json else sys.stderr)
        return 2
    text, corrections, result = check(data, args.node_id)
    prepared = None
    if corrections and args.out:
        with open(args.out, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        prepared = args.out
    label = args.label or "node %d" % args.node_id
    error, warning, notes = verdict(label, args.name or os.path.basename(args.eds), corrections, result, args.mode,
                                   prepared)
    if args.json:
        json.dump({"prepared": prepared, "corrections": [c.to_json() for c in corrections],
                   "read_error": result.read_error, "findings": [f.to_json() for f in result.findings],
                   "mode": args.mode, "error": error, "warning": warning, "notes": notes},
                  sys.stdout)
        sys.stdout.write("\n")
        return 0
    for c in corrections:
        print("correction: %s (%d)" % (c.text, len(c.items)))
    if result.read_error:
        print("error: " + result.read_error)
    for f in result.findings:
        print("%s %s: %s" % ("BLOCKS" if f in result.failing(args.mode) else "ok    ", f.where(), f.message))
    return 1 if result.read_error or result.failing(args.mode) else 0


if __name__ == "__main__":
    sys.exit(main())
