"""A live node's parameters: read all, back up as a DCF, compare, restore and
store (canopen-device-parameters spec).

Everything runs on the PC over the diagnostics channel's sdo_read, sdo_write
and nmt operations, one SDO at a time. The configurator and
canworks-diag both use this module. Storing to 0x1010 is its own
function and no other function here ever writes 0x1010.
"""

import datetime
import os
import re
import struct

from . import __version__, edslint
from . import eds as eds_mod
from .dcfexport import _Lines, parameter_value
from .diag import DiagError, abort_text, decode, type_name

READABLE = ("ro", "rw", "rwr", "rww", "const")
WRITABLE = ("rw", "rwr", "rww")
COMPARED = WRITABLE + ("const",)
DOMAIN = 0x000F
READ_TIMEOUT_MS = 500
STORE_TIMEOUT_MS = 5000
SILENT_LIMIT = 3  # timeouts in a row that stop a read-all
TIMEOUT_ABORT = 0x05040000
SAVE = b"save"  # 0x65766173, "save" in CiA 301
NEVER_RESTORED = ((0x1010, 0x1011, "store/restore command"),
                  (0x1400, 0x1BFF, "PDO object, set by the configuration or the device"),
                  (0x1F50, 0x1F57, "program download object"))


class ParameterError(Exception):
    pass


class Entry:
    """One sub-object of the node's EDS."""

    def __init__(self, index, sub, obj, parent_name=""):
        self.index, self.sub, self.obj = index, sub, obj
        self.parent_name = parent_name

    @property
    def key(self):
        return (self.index, self.sub)

    @property
    def name(self):
        if self.parent_name:
            return "%s: %s" % (self.parent_name, self.obj.name) if self.obj.name else self.parent_name
        return self.obj.name

    @property
    def data_type(self):
        return self.obj.data_type

    @property
    def access(self):
        return self.obj.access

    def label(self):
        return "0x%04X sub %d" % (self.index, self.sub)

    def to_json(self, node_id=0):
        d = {"index": self.index, "subindex": self.sub, "name": self.name, "type": type_name(self.data_type)
             or "0x%04X" % self.data_type, "access": self.access, "default": self.obj.default,
             "sub_name": self.obj.name}
        for key, text in (("low_limit", getattr(self.obj, "low_limit", "")),
                          ("high_limit", getattr(self.obj, "high_limit", ""))):
            v = limit_number(text, self.data_type, node_id)
            if v is not None:
                d[key] = v
        return d


def entries(eds):
    """Every sub-object of an Eds, in index/sub-index order."""
    return [Entry(i, s, o, eds.names.get(i, "")) for i, s, o in eds.items()]


def readable(eds):
    """The entries a read-all reads: readable access, no DOMAIN."""
    return [e for e in entries(eds) if e.access in READABLE and e.data_type != DOMAIN]


def read_eds(path=None, text=None, name=None):
    """(Eds, prepared EDS text) for an EDS file or its text."""
    if text is None:
        with open(path, "rb") as f:
            text, _ = edslint.prepare(f.read())
    try:
        return eds_mod.Eds.read(name or path or "EDS", text), text
    except eds_mod.EdsError as e:
        raise ParameterError("%s: %s" % (name or path, e))


# -- values ------------------------------------------------------------------

def _int_type(code):
    name = type_name(code) or ""
    for prefix, signed in (("INTEGER", True), ("UNSIGNED", False)):
        if name.startswith(prefix) and name[len(prefix):].isdigit():
            return int(name[len(prefix):]) // 8, signed
    return None


def value_text(data, code):
    """The CiA 306 ParameterValue text of bytes read from an object of EDS
    type `code`, or None when the type has no text form here."""
    text = parameter_value(data, code)
    if text is not None:
        return text
    name = type_name(code)
    if name == "VISIBLE_STRING":
        s = data.split(b"\0", 1)[0].decode("latin-1")
        return s if all(32 <= ord(c) < 127 for c in s) and s == s.strip() else None
    if name == "OCTET_STRING":
        return data.hex().upper()
    if code in (0x000C, 0x000D) and len(data) == 6:  # TIME_OF_DAY / TIME_DIFFERENCE
        ms = int.from_bytes(data[:4], "little") & 0x0FFFFFFF
        return "%d %d" % (int.from_bytes(data[4:], "little"), ms)
    return None


def text_value(text, code, node_id):
    """Bytes for a ParameterValue/DefaultValue text of EDS type `code`, or
    None when it cannot be read ($NODEID resolved)."""
    text = (text or "").strip()
    name = type_name(code)
    if name == "VISIBLE_STRING":
        if len(text) >= 2 and text[0] == text[-1] and text[0] in "'\"":
            text = text[1:-1]
        try:
            return text.encode("latin-1")
        except UnicodeEncodeError:
            return None
    if name == "OCTET_STRING":
        try:
            return bytes.fromhex(text)
        except ValueError:
            return None
    if code in (0x000C, 0x000D):
        try:
            days, ms = (int(t, 0) for t in text.split())
        except ValueError:
            return None
        return (ms & 0x0FFFFFFF).to_bytes(4, "little") + (days & 0xFFFF).to_bytes(2, "little")
    if not text:
        return None
    total = 0
    for t in (p.strip() for p in text.split("+")):
        if t.upper() == "$NODEID":
            total += node_id
            continue
        try:
            total += int(t, 0)
        except ValueError:
            if name in ("REAL32", "REAL64") and len(text.split("+")) == 1:
                try:
                    return struct.pack("<f" if name == "REAL32" else "<d", float(t))
                except (ValueError, OverflowError):
                    return None
            return None
    if name == "BOOLEAN":
        return b"\x01" if total else b"\x00"
    if name in ("REAL32", "REAL64"):
        size = 4 if name == "REAL32" else 8
        return (total & ((1 << size * 8) - 1)).to_bytes(size, "little")
    it = _int_type(code)
    if not it:
        return None
    size, signed = it
    total &= (1 << size * 8) - 1
    return total.to_bytes(size, "little")


def limit_number(text, code, node_id):
    """An EDS LowLimit/HighLimit as a number of the entry's type ($NODEID
    resolved, two's-complement hex of a signed type read as negative), or
    None when absent or not a number of that type."""
    if not (text or "").strip():
        return None
    name = type_name(code) or ""
    data = text_value(text, code, node_id)
    if data is None:
        return None
    if name == "REAL32":
        return struct.unpack("<f", data)[0]
    if name == "REAL64":
        return struct.unpack("<d", data)[0]
    it = _int_type(code)
    if not it:
        return None
    return int.from_bytes(data, "little", signed=it[1])


def same(a, b, code):
    """Whether two values of type `code` are equal: numbers by value (so a
    shorter startup SDO equals the same number), strings without trailing
    NULs, other types byte for byte."""
    if a is None or b is None:
        return False
    name = type_name(code)
    if name == "VISIBLE_STRING":
        return a.rstrip(b"\0") == b.rstrip(b"\0")
    it = _int_type(code)
    if it or name == "BOOLEAN":
        signed = bool(it and it[1])
        return int.from_bytes(a, "little", signed=signed) == int.from_bytes(b, "little", signed=signed)
    return a == b


def shown(data, code):
    return decode(code, data)["text"] if data is not None else ""


# -- reading -------------------------------------------------------------------

class Reading:
    """The result of reading a node's entries."""

    def __init__(self, node_id):
        self.node_id = node_id
        self.values = {}  # (index, sub): bytes
        self.failed = {}  # (index, sub): (abort code or None, text)
        self.stopped = None  # why the read stopped early
        self.cancelled = False
        self.total = 0

    @property
    def done(self):
        return len(self.values) + len(self.failed)

    def to_json(self, eds_entries=None):
        types = {e.key: e.data_type for e in eds_entries or []}
        return {"node_id": self.node_id, "total": self.total, "read": len(self.values), "failed": len(self.failed),
                "stopped": self.stopped, "cancelled": self.cancelled,
                "values": [{"index": i, "subindex": s, "data": data.hex(" ").upper(),
                            "text": shown(data, types.get((i, s)))} for (i, s), data in sorted(self.values.items())],
                "failures": [{"index": i, "subindex": s, "abort_code": c, "error": t}
                             for (i, s), (c, t) in sorted(self.failed.items())]}


def _timeout(res):
    return res.get("abort_code") in (None, TIMEOUT_ABORT)


def read_entries(client, node_id, keys, progress=None, cancel=None, timeout_ms=READ_TIMEOUT_MS):
    """Reads (index, sub) keys of a node one at a time. Stops after
    SILENT_LIMIT timeouts in a row, or when cancel() is true."""
    r = Reading(node_id)
    r.total = len(keys)
    silent = 0
    for n, (index, sub) in enumerate(keys):
        if cancel and cancel():
            r.cancelled = True
            break
        try:
            res = client.sdo_read(node_id, index, sub, timeout_ms)
        except DiagError as e:
            if e.kind != "refused" or "more than" not in str(e):
                raise
            r.failed[(index, sub)] = (None, str(e))
            silent = 0
        else:
            if res.get("success"):
                r.values[(index, sub)] = bytes.fromhex(res.get("data") or "")
                silent = 0
            else:
                code = res.get("abort_code")
                text = abort_text(code) if code is not None else (res.get("error") or "failed")
                r.failed[(index, sub)] = (code, text if code != TIMEOUT_ABORT else "timeout")
                silent = silent + 1 if _timeout(res) else 0
        if progress:
            progress(n + 1, len(keys))
        if silent >= SILENT_LIMIT:
            r.stopped = ("node %d does not answer SDO (%d timeouts in a row); it may be STOPPED or not on the bus"
                         % (node_id, SILENT_LIMIT))
            break
    return r


def read_all(client, node_id, eds, progress=None, cancel=None):
    return read_entries(client, node_id, [e.key for e in readable(eds)], progress, cancel)


# -- the backup DCF -------------------------------------------------------------

def _section_for(lines, eds_text_cfg, index, sub):
    """Where a sub-object's ParameterValue goes: (section, key)."""
    obj = "%04X" % index
    if lines.find("%ssub%X" % (obj, sub)) is not None:
        return "%ssub%X" % (obj, sub), "ParameterValue"
    compact = eds_text_cfg.get(index)
    if compact and sub >= 1:
        return obj + "Value", str(sub)
    if sub == 0 and lines.find(obj) is not None and not compact:
        return obj, "ParameterValue"
    return None, None


def _compact_objects(text):
    """{index: True} for objects written with CompactSubObj (no sub-sections)."""
    out = {}
    cur = None
    for line in text.splitlines():
        m = re.match(r"^\s*\[([0-9A-Fa-f]{1,4})\]\s*$", line)
        if m:
            cur = int(m.group(1), 16)
            continue
        if line.strip().startswith("["):
            cur = None
            continue
        m = re.match(r"^\s*CompactSubObj\s*=\s*(\S+)", line, re.I)
        if cur is not None and m:
            try:
                if int(m.group(1), 0):
                    out[cur] = True
            except ValueError:
                pass
    return out


def backup_name(node_id, name=None, now=None):
    now = now or datetime.datetime.now()
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", name or "").strip("_")
    return "node%d%s-%s.dcf" % (node_id, "-" + safe if safe else "", now.strftime("%Y%m%d-%H%M%S"))


def build_backup(eds_text, eds, eds_name, reading, bitrate_kbit=None, node_name=None, host="", now=None,
                 boot_state=None):
    """(DCF text, file name) of a backup."""
    now = now or datetime.datetime.now()
    node_id = reading.node_id
    name = backup_name(node_id, node_name, now)
    lines = _Lines(eds_text)
    compact = _compact_objects(eds_text)
    types = {e.key: e for e in entries(eds)}
    unwritten = []
    for (index, sub), data in sorted(reading.values.items()):
        e = types.get((index, sub))
        text = value_text(data, e.data_type) if e else None
        section, key = _section_for(lines, compact, index, sub)
        if text is None or section is None:
            unwritten.append("0x%04X sub %d read as %s (not written as a ParameterValue)"
                             % (index, sub, data.hex(" ").upper() or "no bytes"))
            continue
        lines.set(section, key, text)
        if key.isdigit():
            where = lines.find(section)
            count = sum(1 for i in range(where[0] + 1, where[1])
                        if re.match(r"^\s*\d+\s*=", lines.lines[i]))
            lines.set(section, "NrOfEntries", str(count))

    lines.drop_section("DeviceComissioning")
    lines.set("DeviceComissioning", "NodeID", str(node_id))
    lines.set("DeviceComissioning", "NodeName", node_name or "node_%d" % node_id)
    if bitrate_kbit:
        lines.set("DeviceComissioning", "Baudrate", str(bitrate_kbit))
    serial = reading.values.get((0x1018, 4))
    if serial is not None and len(serial) == 4:
        lines.set("DeviceComissioning", "LSS_SerialNumber", "0x%08X" % int.from_bytes(serial, "little"))
    when = now.strftime("%Y-%m-%d %H:%M:%S")
    where = " read from %s" % host if host else ""
    state = " (%s)" % boot_state if boot_state else ""
    lines.set("FileInfo", "FileName", name)
    lines.set("FileInfo", "Description", "Backup of node %d%s%s at %s" % (node_id, state, where, when))
    lines.set("FileInfo", "CreatedBy", "canworks-diag %s" % __version__)
    lines.set("FileInfo", "ModifiedBy", "canworks-diag %s" % __version__)
    lines.set("FileInfo", "ModificationDate", now.strftime("%m-%d-%Y"))
    lines.set("FileInfo", "ModificationTime", "%02d:%02d%s" % ((now.hour + 11) % 12 + 1, now.minute,
                                                                 "AM" if now.hour < 12 else "PM"))
    lines.set("FileInfo", "LastEDS", os.path.basename(eds_name))

    comment = ["CiA 306 DCF: parameter backup of node %d%s%s at %s, by canworks-diag %s."
               % (node_id, " (%s)" % node_name if node_name else "", where, when, __version__),
               "ParameterValue: the value each object held when it was read.",
               "%d entries read, %d not read." % (len(reading.values), len(reading.failed))]
    if (0x1018, 1) not in reading.values or (0x1018, 2) not in reading.values:
        comment.append("The identity (0x1018 sub 1 and 2) could not be read: restore cannot check the device.")
    if reading.stopped:
        comment.append("Incomplete: " + reading.stopped)
    if reading.cancelled:
        comment.append("Incomplete: the read was cancelled.")
    for (index, sub), (code, text) in sorted(reading.failed.items()):
        comment.append("not read: 0x%04X sub %d: %s%s" % (index, sub, "0x%08X " % code if code is not None else "",
                                                          text))
    comment += unwritten
    lines.prepend(comment + [""])
    return lines.text(), name


def lint_backup(text, eds_text, node_id):
    """Lint findings of a backup that its EDS does not already have."""
    known = {f.message for f in edslint.lint_text(eds_text, node_id).findings}
    res = edslint.lint_text(text, node_id)
    if res.read_error:
        return ["Lely cannot read the DCF: %s" % res.read_error]
    return [f.message for f in res.findings if f.message not in known]


class Backup:
    """A DCF read back: its object dictionary, values and identity."""

    def __init__(self, eds, text, values, node_id, name=""):
        self.eds, self.text, self.values, self.node_id, self.name = eds, text, values, node_id, name

    def identity(self):
        out = {}
        for sub, key in ((1, "vendor_id"), (2, "product_code"), (3, "revision_number"), (4, "serial_number")):
            data = self.values.get((0x1018, sub))
            if data is not None:
                out[key] = int.from_bytes(data, "little")
        return out


def read_backup(text, name="backup", node_id=None):
    """Reads a DCF (ours, or another tool's with ParameterValue lines)."""
    if isinstance(text, bytes):
        text, _ = edslint.prepare(text)
    eds, _ = read_eds(text=text, name=name)
    dc = re.search(r"^\s*\[DeviceComissioning\](.*?)(?=^\s*\[|\Z)", text, re.M | re.S | re.I)
    nid = node_id
    if nid is None and dc:
        m = re.search(r"^\s*NodeID\s*=\s*(\S+)", dc.group(1), re.M | re.I)
        if m:
            try:
                nid = int(m.group(1), 0)
            except ValueError:
                nid = None
    values = {}
    by_key = {}
    for e in entries(eds):
        by_key[e.key] = e
        if e.obj.parameter:
            data = text_value(e.obj.parameter, e.data_type, nid or 0)
            if data is not None:
                values[e.key] = data
    # CompactSubObj objects keep their values in [XXXXValue] sections.
    for m in re.finditer(r"^\s*\[([0-9A-Fa-f]{1,4})Value\](.*?)(?=^\s*\[|\Z)", text, re.M | re.S | re.I):
        index = int(m.group(1), 16)
        for line in m.group(2).splitlines():
            kv = re.match(r"^\s*(\d+)\s*=\s*(.*?)\s*$", line)
            if not kv or (index, int(kv.group(1))) not in by_key:
                continue
            e = by_key[(index, int(kv.group(1)))]
            data = text_value(kv.group(2), e.data_type, nid or 0)
            if data is not None:
                values[e.key] = data
    return Backup(eds, text, values, nid, name)


# -- compare -------------------------------------------------------------------

def reference_from_eds(eds, node_id):
    out = {}
    for e in entries(eds):
        if e.obj.default:
            data = text_value(e.obj.default, e.data_type, node_id)
            if data is not None:
                out[e.key] = data
    return out


def compare_keys(eds, reference, include_ro=False, only_reference=False):
    """The (index, sub) keys a compare reads: compared access types, and
    with only_reference just those with a reference value."""
    access = COMPARED + (("ro",) if include_ro else ())
    keys = [e.key for e in readable(eds) if e.access in access]
    if only_reference:
        keys = [k for k in keys if k in reference]
    return keys


def compare(eds, reading, reference, include_ro=False, only_reference=False):
    """Rows {index, subindex, name, type, access, result, reference, device,
    error}, differences first. result: equal, different, not readable,
    no reference."""
    by_key = {e.key: e for e in entries(eds)}
    rows = []
    for key in compare_keys(eds, reference, include_ro, only_reference):
        if key not in reading.values and key not in reading.failed:
            continue  # not read (stopped or cancelled)
        e = by_key[key]
        ref = reference.get(key)
        dev = reading.values.get(key)
        row = {"index": key[0], "subindex": key[1], "name": e.name, "type": type_name(e.data_type),
               "access": e.access, "reference": shown(ref, e.data_type) if ref is not None else None,
               "device": shown(dev, e.data_type) if dev is not None else None}
        if dev is None:
            code, text = reading.failed[key]
            row["result"] = "not readable"
            row["error"] = ("0x%08X " % code if code is not None else "") + text
        elif ref is None:
            row["result"] = "no reference"
        else:
            row["result"] = "equal" if same(ref, dev, e.data_type) else "different"
        rows.append(row)
    order = {"different": 0, "not readable": 1, "equal": 2, "no reference": 3}
    rows.sort(key=lambda r: (order[r["result"]], r["index"], r["subindex"]))
    return rows


def summary(rows):
    out = {"equal": 0, "different": 0, "not readable": 0, "no reference": 0}
    for r in rows:
        out[r["result"]] += 1
    return out


# -- configuration -----------------------------------------------------------------

def config_writes(cfg, config_path, node_id, eds_paths=None):
    """{(index, sub): data} the plugin writes to a node at boot, and
    {(index, sub): SDO variable name} of the node's write SDO variables."""
    from . import dcfexport
    nodes = [n for n in cfg.get("nodes", []) if int(str(n.get("node_id")), 0) == node_id]
    if not nodes:
        raise ParameterError("node %d is not in the configuration" % node_id)
    downloads = dcfexport.plugin_downloads(cfg, config_path, eds_paths)
    writes = downloads[node_id].final_values() if node_id in downloads else {}
    owned = {}
    for v in nodes[0].get("sdo_variables", []):
        if v.get("direction") == "write":
            owned[(int(str(v["index"]), 0), int(str(v.get("subindex", 0)), 0))] = v.get("name", "")
    return writes, owned


# -- restore -----------------------------------------------------------------------

IDENTITY_FIELDS = (("vendor_id", "vendor ID"), ("product_code", "product code"),
                   ("revision_number", "revision number"), ("serial_number", "serial number"))


class Plan:
    def __init__(self):
        self.writes = []  # dicts: index, subindex, name, data (bytes), backup, device
        self.unchanged = []  # dicts: index, subindex, name
        self.skipped = []  # dicts: index, subindex, name, reason
        self.identity = []  # dicts: field, backup, device, level (refuse, warning, info)
        self.refused = None  # why nothing may be written

    def to_json(self):
        return {"writes": [{k: v for k, v in w.items() if k != "data"} for w in self.writes],
                "unchanged": self.unchanged, "skipped": self.skipped, "identity": self.identity,
                "refused": self.refused}


def never_reason(index):
    for lo, hi, why in NEVER_RESTORED:
        if lo <= index <= hi:
            return why
    return None


def restore_candidates(backup, eds, include_comm=False, config=None, owned=None):
    """([(Entry, data)] to consider, [skipped dict]) for a backup."""
    config, owned = config or {}, owned or {}
    by_key = {e.key: e for e in entries(eds)}
    out, skipped = [], []
    for key, data in sorted(backup.values.items()):
        e = by_key.get(key) or next((x for x in entries(backup.eds) if x.key == key), None)
        name = e.name if e else ""
        base = {"index": key[0], "subindex": key[1], "name": name}
        if e is None or e.access not in WRITABLE:
            if e is not None and e.access in ("ro", "const"):
                continue  # read-only values are in the backup for compare only
            skipped.append(dict(base, reason="not writable in the EDS"))
            continue
        why = never_reason(key[0])
        if why:
            skipped.append(dict(base, reason=why))
        elif key[0] < 0x2000 and not include_comm:
            skipped.append(dict(base, reason="communication object (include communication objects to restore it)"))
        elif key[0] > 0x9FFF:
            skipped.append(dict(base, reason="outside 0x1000-0x9FFF"))
        elif key in config:
            skipped.append(dict(base, reason="written by the configuration at boot"))
        elif key in owned:
            skipped.append(dict(base, reason=("written by SDO variable %s" % (owned[key] or "")).strip()))
        else:
            out.append((e, data))
    return out, skipped


def _restore_order(items):
    """Ascending index; within an object sub-indices 1..n before sub 0."""
    return sorted(items, key=lambda it: (it[0].index, it[0].sub == 0, it[0].sub))


def restore_plan(backup, eds, live, include_comm=False, config=None, owned=None, ignore_identity=False):
    """A Plan from a backup, the node's EDS and a Reading of the candidates
    and 0x1018 sub 1-4 (live)."""
    plan = Plan()
    want = backup.identity()
    for key, label in IDENTITY_FIELDS:
        sub = 1 + [k for k, _ in IDENTITY_FIELDS].index(key)
        data = live.values.get((0x1018, sub))
        have = int.from_bytes(data, "little") if data is not None and len(data) == 4 else None
        if key in ("vendor_id", "product_code"):
            if key not in want:
                plan.identity.append({"field": label, "backup": None, "device": have, "level": "refuse",
                                      "text": "the backup has no %s, so the device cannot be checked" % label})
            elif have is None:
                plan.identity.append({"field": label, "backup": want[key], "device": None, "level": "refuse",
                                      "text": "the device's %s could not be read" % label})
            elif have != want[key]:
                plan.identity.append({"field": label, "backup": want[key], "device": have, "level": "refuse",
                                      "text": "%s differs: backup 0x%08X, device 0x%08X" % (label, want[key], have)})
        elif key in want and have is not None and have != want[key]:
            level = "warning" if key == "revision_number" else "info"
            plan.identity.append({"field": label, "backup": want[key], "device": have, "level": level,
                                  "text": "%s differs: backup 0x%08X, device 0x%08X" % (label, want[key], have)})
    refusals = [i["text"] for i in plan.identity if i["level"] == "refuse"]
    if refusals and not ignore_identity:
        plan.refused = "; ".join(refusals)

    candidates, plan.skipped = restore_candidates(backup, eds, include_comm, config, owned)
    for e, data in _restore_order(candidates):
        base = {"index": e.index, "subindex": e.sub, "name": e.name}
        dev = live.values.get(e.key)
        if dev is not None and same(data, dev, e.data_type):
            plan.unchanged.append(base)
            continue
        plan.writes.append(dict(base, data=data, type=type_name(e.data_type), backup=shown(data, e.data_type),
                                device=shown(dev, e.data_type) if dev is not None else None))
    return plan


def plan_keys(backup, eds, include_comm=False, config=None, owned=None):
    """The keys to read before planning: 0x1018 sub 1-4 and the candidates."""
    candidates, _ = restore_candidates(backup, eds, include_comm, config, owned)
    keys = [(0x1018, s) for s in range(1, 5)]
    return keys + [e.key for e, _ in candidates if e.key not in keys]


def restore(client, node_id, plan, hold=False, progress=None, cancel=None, timeout_ms=1000):
    """Writes a plan. Returns {written, failed, skipped, unchanged, held,
    released, cancelled, note}. Never writes 0x1010."""
    if plan.refused:
        raise ParameterError("restore refused: %s" % plan.refused)
    result = {"written": [], "failed": [], "skipped": plan.skipped, "unchanged": plan.unchanged, "held": False,
              "released": None, "cancelled": False,
              "note": "the restored values are not stored on the device: they are lost at power off until "
                      "Store on device (0x1010) is used"}
    if hold:
        client.nmt(node_id, "preop")
        result["held"] = True
    try:
        for n, w in enumerate(plan.writes):
            if cancel and cancel():
                result["cancelled"] = True
                break
            assert w["index"] != 0x1010
            base = {"index": w["index"], "subindex": w["subindex"], "name": w["name"]}
            res = client.sdo_write(node_id, w["index"], w["subindex"], w["data"], timeout_ms)
            if res.get("success"):
                result["written"].append(dict(base, value=w["backup"]))
            else:
                code = res.get("abort_code")
                result["failed"].append(dict(base, value=w["backup"], abort_code=code,
                                             error=abort_text(code) if code is not None else res.get("error")))
            if progress:
                progress(n + 1, len(plan.writes))
    finally:
        if hold:
            try:
                client.nmt(node_id, "start")
                result["released"] = True
            except DiagError as e:
                result["released"] = False
                result["release_error"] = str(e)
    return result


# -- store -------------------------------------------------------------------------

def store(client, node_id, eds, subindex=1):
    """Writes "save" to 0x1010 `subindex`; the separate, explicit store."""
    if not eds.has(0x1010):
        raise ParameterError("node %d's EDS has no object 0x1010: the device has no store object" % node_id)
    if eds.find(0x1010, subindex) is None:
        raise ParameterError("node %d's EDS has no 0x1010 sub %d" % (node_id, subindex))
    res = client.sdo_write(node_id, 0x1010, subindex, SAVE, STORE_TIMEOUT_MS)
    if res.get("success"):
        return {"stored": True, "subindex": subindex}
    code = res.get("abort_code")
    return {"stored": False, "subindex": subindex, "abort_code": code,
            "error": abort_text(code) if code is not None else res.get("error") or "failed"}


# -- where a node's EDS and configuration come from ---------------------------------

DEFAULT_CONFIG = os.path.join("canworks", "canworks.json")


class NodeContext:
    """A node's EDS and, when it comes from a config, its configuration."""

    def __init__(self, node_id, eds, eds_text, eds_name, name=None, bitrate_kbit=None, cfg=None,
                 config_path=None, eds_paths=None):
        self.node_id, self.eds, self.eds_text, self.eds_name = node_id, eds, eds_text, eds_name
        self.name, self.bitrate_kbit = name, bitrate_kbit
        self.cfg, self.config_path, self.eds_paths = cfg, config_path, eds_paths

    @property
    def configured(self):
        return self.cfg is not None

    def config_refs(self):
        """(boot writes, write SDO variables) of a configured node, else ({}, {})."""
        if not self.configured:
            return {}, {}
        return config_writes(self.cfg, self.config_path, self.node_id, self.eds_paths)


def _num(v):
    return int(str(v), 0)


def node_context(node_id, config_path=None, eds_path=None, cfg=None, eds_paths=None, network=None):
    """A NodeContext from --eds, or from a config (the node's EDS, name and
    the bus bit rate). With neither, canworks/canworks.json when it exists.
    `network` names the config's network the node is on; a config with
    several networks needs it."""
    import json
    from . import bundle, contract
    if eds_path:
        eds, text = read_eds(eds_path)
        return NodeContext(node_id, eds, text, eds_path)
    if cfg is None:
        config_path = config_path or (DEFAULT_CONFIG if os.path.isfile(DEFAULT_CONFIG) else None)
        if not config_path:
            raise ParameterError("give the node's EDS with --eds, or the configuration with --config "
                                 "(no %s here)" % DEFAULT_CONFIG)
        try:
            with open(config_path, encoding="utf-8") as f:
                cfg = json.load(f)
        except (OSError, ValueError) as e:
            raise ParameterError("cannot read %s: %s" % (config_path, e))
    try:
        cfg = contract.network_config(cfg, network)
    except ValueError as e:
        raise ParameterError("%s: %s%s" % (config_path, e, " with --network NAME" if network is None else ""))
    node = next((n for n in cfg.get("nodes", []) if _num(n.get("node_id")) == node_id), None)
    if node is None:
        where = "on network '%s' in %s" % (network, config_path) if network else "in %s" % config_path
        raise ParameterError("node %d is not %s; give its EDS with --eds" % (node_id, where))
    paths = eds_paths if eds_paths is not None else bundle.eds_files(cfg, config_path)
    path = paths[node["eds"]]
    eds, text = read_eds(path)
    adapter = cfg.get("adapter") if isinstance(cfg.get("adapter"), dict) else cfg
    bitrate = adapter.get("bitrate")
    kbit = _num(bitrate) // 1000 if bitrate is not None else None
    return NodeContext(node_id, eds, text, node["eds"], node.get("name"), kbit, cfg, config_path, eds_paths)
