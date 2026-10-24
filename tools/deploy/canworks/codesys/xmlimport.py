"""Import from CODESYS (codesys-import spec): reads a CODESYS PLCopenXML
export and makes canworks CANopen master networks from its CANopen Manager
networks.

CODESYS writes every device of the export as a <configuration> holding the
device's parameters by their numeric ParameterId (the same ids the build
script sets, see plan.py), and its child devices as nested configurations.
The reader goes by id only: CODESYS shows parameter names in the user's
language. What it cannot carry over goes into the report, never silently
away."""

import gzip
import io
import os
import re
import xml.etree.ElementTree as ET

from ..configurator import declare
from ..eds import Eds, EdsError, mapping_info, uses_device_mapping

NS = "{http://www.plcopen.org/xml/tc6_0200}"

# Device types (DeviceIdentification Type).
CANBUS, MANAGER, LOCAL_DEVICE, REMOTE_DEVICE = 15, 16, 17, 18
# CANbus.
BUS_BAUDRATE, BUS_NET_ID = 0, 2
# CANopen Manager.
M_SYNC_PERIOD, M_SYNC_ON, M_SYNC_COB_ID, M_SYNC_WINDOW, M_SYNC_CONSUMER = 256, 257, 258, 259, 260
M_AUTOSTART, M_START_SLAVES, M_START_ALL, M_POLL_OPTIONAL, M_NMT_ERROR = 261, 262, 263, 264, 265
M_NMT_INHIBIT = 266
M_HB_MS, M_HB_ON, M_HB_NODE, M_HB_RATIO = 272, 273, 274, 275
M_SDO_TIMEOUT = 277
M_NODE_ID = 288
M_TIME_COB_ID, M_TIME_PERIOD = 290, 291
# A new manager's values: left out of the config, as a build leaves them.
MGR_DEFAULTS = {M_SYNC_WINDOW: 1200, M_NMT_INHIBIT: 10, M_SDO_TIMEOUT: 1000}
# Remote device.
D_NODE_ID, D_OPTIONS = 1, 2
D_SDO_TIMEOUT = 17
D_RESET_SUB = 16846848
D_GUARDING = 0x0100C000
D_TIME = 0x01012000
D_EMCY = 0x01014000
D_HEARTBEAT = 0x01017000
D_HB_CONSUMER = 0x11016000  # + sub-index << 4
D_IDENTITY = {0x11018010: "vendor", 0x11018020: "product", 0x11018030: "revision"}
D_SDO_LIST = 0x20001000
# The checks CODESYS ticks on a new device.
DEFAULT_CHECKS = ["vendor"]
CHECKS = ("vendor", "product", "revision")

# A CODESYS size in bits -> the canworks type when the EDS does not name one.
_SIZE_TYPES = {1: "BOOLEAN", 8: "UNSIGNED8", 16: "UNSIGNED16", 24: "UNSIGNED24", 32: "UNSIGNED32",
               64: "UNSIGNED64"}
_SIGNED_BITS = {"INTEGER8": 8, "INTEGER16": 16, "INTEGER24": 24, "INTEGER32": 32, "INTEGER64": 64}
_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,15}$")
# The names CODESYS gives a new CAN bus object (CANbus, CANbus_2, ...).
_DEFAULT_BUS = re.compile(r"^CANbus(?:_\d+)?$", re.I)


class ImportError_(Exception):
    """The source cannot be imported (not PLCopenXML, no CANopen Manager)."""


# ---------------------------------------------------------------------------
# Reading the XML


class Param(object):
    """One device parameter: `value` its text (None for a struct), `elements`
    every element of a struct by name, `rows` the values of an array of
    structs (the SDO list), `mapping` its I/O variable, `fixed` its manual
    IEC address, `download` False when CODESYS does not download it (an
    identity check that is off), `bits` {bit: variable} of a channel."""

    def __init__(self, pid, name, ptype):
        self.id, self.name, self.type = pid, name, ptype
        self.value, self.elements, self.rows = None, {}, []
        self.mapping, self.fixed, self.download, self.bits = None, None, True, {}


class Device(object):
    def __init__(self, name, dtype, did, version, parent=None):
        self.name, self.type, self.id, self.version, self.parent = name, dtype, did, version, parent
        self.params, self.children = {}, []

    def path(self):
        names, d = [], self
        while d is not None:
            names.append(d.name)
            d = d.parent
        return "/".join(reversed(names))

    def get(self, pid):
        return self.params.get(pid)


def _elements(value, out):
    for e in value.findall("Element"):
        name = e.get("name")
        if name and name not in out:
            out[name] = (e.text or "").strip()
        _elements(e, out)
    return out


def _bits(value):
    """{bit: variable} of a channel's bit elements that have a variable."""
    out = {}
    for e in value.findall("Element"):
        m = re.search(r"_(\d+)$", e.get("name") or "")
        var = (e.findtext("Mapping") or "").strip()
        if m and var:
            out[int(m.group(1))] = var
    return out


def _param(p):
    try:
        pid = int(p.get("ParameterId"))
    except (TypeError, ValueError):
        return None
    out = Param(pid, (p.findtext("Name") or "").strip(), p.get("type") or "")
    attrs = p.find("Attributes")
    if attrs is not None and attrs.get("download") == "false":
        out.download = False
    out.fixed = p.get("FixedAddress") or None
    out.mapping = (p.findtext("Mapping") or "").strip() or None
    values = p.findall("Value")
    for v in values:
        row = {"elements": _elements(v, {}), "implicit": v.find("Custom/ImplicitSDO") is not None,
               "label": v.get("visiblename") or ""}
        out.rows.append(row)
    if values:
        first = values[0]
        out.elements = out.rows[0]["elements"]
        out.value = None if first.findall("Element") else (first.text or "").strip()
        out.bits = _bits(first)
    return out


def _device_of(conf):
    for d in conf.findall(NS + "addData/" + NS + "data"):
        if d.get("name") == "Device":
            return d.find("Device")
    return None


def _children_of(conf):
    for d in conf.findall(NS + "addData/" + NS + "data"):
        holder = d.find(NS + "configurations")
        if holder is not None:
            return holder.findall(NS + "configuration")
    return []


def _walk(conf, parent, out):
    xml_dev = _device_of(conf)
    if xml_dev is None:
        return
    ident = xml_dev.find("DeviceType/DeviceIdentification")
    try:
        dtype = int((ident.findtext("Type") or "").strip()) if ident is not None else None
    except ValueError:
        dtype = None
    dev = Device(conf.get("name") or "", dtype, (ident.findtext("Id") or "").strip() if ident is not None else "",
                 (ident.findtext("Version") or "").strip() if ident is not None else "", parent)
    for p in xml_dev.iter("Parameter"):
        param = _param(p)
        if param is not None and param.id not in dev.params:
            dev.params[param.id] = param
    out.append(dev)
    for c in _children_of(conf):
        _walk(c, dev, dev.children)


def read(source):
    """The top-level devices of a PLCopenXML export: a path (.xml or
    .xml.gz) or the XML bytes."""
    try:
        if isinstance(source, (bytes, bytearray)):
            root = ET.fromstring(bytes(source))
        elif str(source).lower().endswith(".gz"):
            with gzip.open(source, "rb") as f:
                root = ET.parse(f).getroot()
        else:
            root = ET.parse(source).getroot()
    except ET.ParseError as e:
        raise ImportError_("not an XML file: %s" % e)
    except OSError as e:
        raise ImportError_("cannot read %s: %s" % (source, e))
    if root.tag != NS + "project":
        raise ImportError_("not a PLCopenXML export (the root is <%s>, not <project>)" % root.tag.split("}")[-1])
    holder = root.find(NS + "instances/" + NS + "configurations")
    tops = []
    for conf in (holder.findall(NS + "configuration") if holder is not None else []):
        _walk(conf, None, tops)
    return tops


def project_name(source):
    """The project file name the export came from (its contentHeader), or None."""
    try:
        data = source if isinstance(source, (bytes, bytearray)) else None
        if data is None:
            opener = gzip.open if str(source).lower().endswith(".gz") else open
            with opener(source, "rb") as f:
                data = f.read(4096)
        m = re.search(rb'<contentHeader[^>]*\bname="([^"]*)"', bytes(data[:4096]))
        return m.group(1).decode("utf-8") if m else None
    except OSError:
        return None


def _all(devices):
    for d in devices:
        yield d
        for c in _all(d.children):
            yield c


def _top(dev):
    while dev.parent is not None:
        dev = dev.parent
    return dev


def choices(tops):
    """The devices with a CANopen Manager: [{name, buses, nodes, device}],
    `device` None for buses exported on their own (no device above them).
    A device's buses are its CANbus objects that hold a manager."""
    found = []
    for d in _all(tops):
        if d.type == MANAGER and d.parent is not None:
            bus = d.parent
            owner = _top(bus) if bus.parent is not None else None
            key = owner.name if owner is not None else None
            entry = next((c for c in found if c["name"] == key), None)
            if entry is None:
                entry = {"name": key, "device": owner, "buses": [], "nodes": 0}
                found.append(entry)
            if all(b is not bus for b in entry["buses"]):
                entry["buses"].append(bus)
            entry["nodes"] += len([c for c in d.children if c.type == REMOTE_DEVICE])
    return found


# ---------------------------------------------------------------------------
# Values


def number(text):
    """A CODESYS number: 123, 16#7B, 2#101, TRUE/FALSE, '16#185' (quoted)."""
    if text is None:
        return None
    s = str(text).strip().strip("'").replace("_", "")
    if not s:
        return None
    if s.upper() == "TRUE":
        return 1
    if s.upper() == "FALSE":
        return 0
    try:
        if s.upper().startswith("16#"):
            return int(s[3:], 16)
        if s.upper().startswith("2#"):
            return int(s[2:], 2)
        if s.upper().startswith("8#"):
            return int(s[2:], 8)
        return int(s, 0) if s.lower().startswith("0x") else int(s)
    except ValueError:
        return None


def _value(dev, pid, element=None):
    p = dev.get(pid)
    if p is None:
        return None
    return number(p.elements.get(element) if element else p.value)


def _flag(dev, pid, element=None):
    v = _value(dev, pid, element)
    return None if v is None else bool(v)


def generic_cob_id(text):
    """('node', offset) for '$NODEID+16#180', ('literal', value) for '16#185'."""
    s = (text or "").strip().strip("'").replace(" ", "")
    if "$NODEID" in s.upper():
        rest = re.sub(r"(?i)\$NODEID", "", s).strip("+")
        return "node", (number(rest) or 0) if rest else 0
    v = number(s)
    return ("literal", v) if v is not None else (None, None)


def default_cob_id(direction, n, node_id):
    """The CiA 301 default COB-ID of PDO n (1-4), else None."""
    if not 1 <= n <= 4:
        return None
    return (0x180 if direction == "tx" else 0x200) + 0x100 * (n - 1) + node_id


# ---------------------------------------------------------------------------
# The conversion


class Result(object):
    """The import: `cfg` the new config, `eds_files` {name: source path} to
    copy beside it, `nodes` one row per node for the preview, `report`
    [{where, setting, note}] of what was not carried, `missing` the nodes
    without an EDS."""

    def __init__(self):
        self.cfg, self.eds_files, self.nodes, self.report, self.missing = None, {}, [], [], []

    def note(self, where, setting, text):
        self.report.append({"where": where, "setting": setting, "note": text})

    def as_json(self):
        return {"config": self.cfg, "eds_files": sorted(self.eds_files), "nodes": self.nodes,
                "report": self.report, "missing": self.missing}


def _unique(base, taken, limit=None):
    name, n = base[:limit] if limit else base, 2
    while name.lower() in taken:
        suffix = "_%d" % n
        name = (base[:limit - len(suffix)] if limit else base) + suffix
        n += 1
    taken.add(name.lower())
    return name


def _network_prefix(mgr, node_names):
    """The network name the channel variables start with
    (<network>_<node>_...), when every named channel agrees on one."""
    seen = set()
    for dev, name in node_names:
        for p in dev.params.values():
            for var in [p.mapping] + list(p.bits.values()):
                if not var:
                    continue
                low = var.lower()
                marker = "_%s_" % name.lower()
                i = low.find(marker)
                if i > 0:
                    seen.add(var[:i])
                elif not low.startswith(name.lower() + "_"):
                    seen.add(None)
    seen.discard(None) if len(seen) > 1 else None
    if len(seen) == 1:
        only = next(iter(seen))
        if only and _NAME.match(only):
            return only
    return None


def _type_for(eds, index, sub, bits):
    o = eds.find(index, sub) if eds is not None else None
    if o is not None and o.type_name:
        return o.type_name, None
    t = _SIZE_TYPES.get(bits)
    return t, ("no type in the EDS; %s from its size (%d bit)" % (t, bits) if t else
               "no type in the EDS and an unknown size (%d bit)" % bits)


def _sdo_value(raw, type_name):
    v = number(raw)
    if v is None:
        return raw
    bits = _SIGNED_BITS.get(type_name)
    if bits and v >= 1 << (bits - 1):
        v -= 1 << bits
    if type_name == "BOOLEAN":
        return bool(v)
    return v


def _pdo_params(dev, direction):
    """[(number, comm parameter)] of the device's PDOs."""
    base = 0x01800000 if direction == "tx" else 0x01400000
    out = []
    for pid, p in dev.params.items():
        if base <= pid < base + 0x00200000 and pid & 0xFFF == 0 and "COBID" in p.elements:
            out.append((((pid - base) >> 12) + 1, p))
    return sorted(out)


def _mapping(dev, map_index):
    """[(entry parameter, channel parameter)] of a mapping object, in order."""
    base = 0x10000000 | (map_index << 12)
    found = []
    for pid, p in dev.params.items():
        if base <= pid < base + 0x1000 and pid & 0xF == 0 and "Index" in p.elements:
            found.append((pid, p, dev.get(pid + 1)))
    return [(p, ch) for _, p, ch in sorted(found, key=lambda x: x[0])]


class _Names(object):
    """Entry and bit names from CODESYS variables: no name when the variable
    is the one canworks would declare, the part after the prefix when it
    starts with the prefix, else the variable itself in codesys.variable."""

    def __init__(self, prefix):
        self.prefix = prefix

    def entry(self, var, label):
        if not var:
            return {}
        default = "%s_%s" % (self.prefix, declare.identifier(label))
        if var.lower() == default.lower():
            return {}
        if var.lower().startswith(self.prefix.lower() + "_") and len(var) > len(self.prefix) + 1:
            return {"name": var[len(self.prefix) + 1:]}
        return {"codesys": {"variable": var}}

    def bit(self, var, label, bit):
        default = "%s_%s" % (self.prefix, declare.bit_name(label, bit))
        if var.lower() == default.lower():
            return {}
        if var.lower().startswith(self.prefix.lower() + "_"):
            return {"name": var[len(self.prefix) + 1:]}
        return {"name": var}


def _node(dev, net, master_id, eds, names, res, where):
    """A canworks node from a CODESYS remote device."""
    node_id = _value(dev, D_NODE_ID)
    node = {"node_id": node_id, "name": names["node"]}
    cs = {}
    if names["node"] != dev.name:
        cs["device"] = dev.name

    def default(index, sub):
        o = eds.find(index, sub) if eds is not None else None
        return o.value(node_id) if o is not None else None

    if _flag(dev, D_OPTIONS, "FLAG_Optional") is False:
        node["mandatory"] = True
    if _flag(dev, D_OPTIONS, "FLAG_NotInitialize"):
        node["boot"] = False
    if _flag(dev, D_OPTIONS, "FLAG_ResetNode"):
        node["restore_configuration"] = _value(dev, D_RESET_SUB) or 1
    for flag, what in (("FLAG_DCF_Write", "write the DCF to the device"),
                       ("FLAG_CreateAllSDOs", "create all SDOs")):
        if _flag(dev, D_OPTIONS, flag):
            res.note(where, "General Options", "'%s' is on in CODESYS; canworks has no such setting" % what)
    hb = _value(dev, D_HEARTBEAT)
    if hb is not None and (hb > 0 or (default(0x1017, 0) or 0) != 0):
        node["heartbeat_ms"] = hb
    guard = _value(dev, D_GUARDING, "GuardTime")
    if guard:
        node["guard_time_ms"] = guard
        node["life_time_factor"] = _value(dev, D_GUARDING, "LifeTimeFactor") or 0
    watch, master_entry = [], False
    for sub in range(1, 128):
        p = dev.get(D_HB_CONSUMER | (sub << 4))
        if p is None:
            break
        who, ms = number(p.elements.get("HeartbeatConsumingNodeID")), number(p.elements.get("HeartbeatTime"))
        if not who or not ms:
            continue
        if who == master_id:
            master_entry = True
        else:
            watch.append({"node": who, "timeout_ms": ms})
    if master_entry:
        node["heartbeat_consumer"] = True
    elif eds is not None and ((default(0x1016, 1) or 0) >> 16) & 0xFF == master_id:
        node["heartbeat_consumer"] = False
    if watch:
        node["heartbeat_watch"] = watch
    t = dev.get(D_TIME)
    if t is not None and "TimeProducingCOBID" in t.elements:
        value = (number(t.elements.get("TimeProducingCOBID")) or 0) & 0x3FFFFFFF
        if number(t.elements.get("TimeConsumingEnable")):
            value |= 0x80000000
        if number(t.elements.get("TimeProducingEnable")):
            value |= 0x40000000
        if value != default(0x1012, 0) and (value & 0xC0000000 or default(0x1012, 0) is not None):
            node["time_cob_id"] = "0x%X" % value
    sdo_timeout = _value(dev, D_SDO_TIMEOUT)
    if sdo_timeout is not None and net.get("sdo_timeout_us") is not None and sdo_timeout != net["sdo_timeout_us"]:
        res.note(where, "SDO timeout", "%d ms on this device, %d ms on the manager; canworks has one SDO timeout per "
                 "network" % (sdo_timeout // 1000, net["sdo_timeout_us"] // 1000))
    if _flag(dev, D_EMCY, "EMCYEnable") is False:
        res.note(where, "EMCY", "EMCY is off for this device in CODESYS; canworks always listens for EMCY")
    # Identity checks.
    checks = [CHECKS[k] for k, pid in enumerate(sorted(D_IDENTITY)) if dev.get(pid) is not None
              and dev.get(pid).download]
    if checks != DEFAULT_CHECKS and any(dev.get(pid) is not None for pid in D_IDENTITY):
        cs["checks"] = checks
    # PDOs.
    for direction, key, map_base, comm_base in (("tx", "tx_pdos", 0x1A00, 0x1800), ("rx", "rx_pdos", 0x1600, 0x1400)):
        pdos = []
        for n, p in _pdo_params(dev, direction):
            cob = number(p.elements.get("COBID"))
            if cob is None or cob & 0x80000000:
                continue  # off: canworks switches off the PDOs it does not list
            label = "%sPDO%d" % ("T" if direction == "tx" else "R", n)
            pdo = {"number": n}
            kind, gen = generic_cob_id((dev.get(p.id + 1) or Param(0, "", "")).value)
            if kind == "literal" and gen is not None:
                cob = gen
            if (cob & 0x7FF) != default_cob_id(direction, n, node_id):
                pdo["cob_id"] = cob & 0x7FF
            tt = number(p.elements.get("TransmissionType"))
            if tt is not None:
                pdo["transmission"] = tt
            comm = comm_base + n - 1
            if direction == "tx" and number(p.elements.get("PDOInhibitTimeAvailable")):
                v = number(p.elements.get("InhibitTime"))
                if v is not None and v != default(comm, 3):
                    pdo["inhibit_time_us"] = v * 100
            if number(p.elements.get("PDOEventTimerAvailable")):
                v = number(p.elements.get("EventTimer"))
                if v is not None and v != default(comm, 5):
                    pdo["event_timer_ms"] = v
            if _flag(dev, p.id + 2) is False:
                pdo.setdefault("codesys", {})["by_manager"] = False
            entries = []
            for e, ch in _mapping(dev, map_base + n - 1):
                index, sub = number(e.elements.get("Index")), number(e.elements.get("SubIndex"))
                bits = number(e.elements.get("ObjectLength")) or 0
                if index is None or sub is None:
                    continue
                type_name, why = _type_for(eds, index, sub, bits)
                if why:
                    res.note(where, "%s 0x%04X:%d" % (label, index, sub), why)
                if type_name is None:
                    continue
                entry = {"index": "0x%04X" % index, "subindex": sub, "type": type_name}
                o = eds.find(index, sub) if eds is not None else None
                obj_label = (o.name if o is not None else "") or "x%04X_%d" % (index, sub)
                if ch is not None:
                    got = names["entries"].entry(ch.mapping, obj_label)
                    cs_entry = got.pop("codesys", {})
                    entry.update(got)
                    if ch.fixed:
                        cs_entry["address"] = ch.fixed
                    bit_list = [dict({"bit": b}, **names["entries"].bit(v, obj_label, b))
                                for b, v in sorted(ch.bits.items())]
                    if bit_list:
                        entry["bits"] = bit_list
                    if cs_entry:
                        entry["codesys"] = cs_entry
                    entry["_used"] = bool(ch.mapping or ch.bits)
                entries.append(entry)
            if eds is not None and uses_device_mapping({}, mapping_info(eds, map_base + n - 1)):
                used = [e for e in entries if e.get("_used")]
                if used:
                    entries = used
            for e in entries:
                e.pop("_used", None)
            if not entries:
                res.note(where, label, "on in CODESYS with no mapped objects; left out (canworks lists a PDO by its "
                         "entries)")
                continue
            pdo["entries"] = entries
            pdos.append(pdo)
        if pdos:
            node[key] = pdos
    # Startup SDOs: the rows the user added (CODESYS marks its own).
    p = dev.get(D_SDO_LIST)
    sdos = []
    for row in (p.rows if p is not None else []):
        el = row["elements"]
        index, sub = number(el.get("Index")), number(el.get("Subindex"))
        if index is None or sub is None:
            continue
        abort, jump, line = number(el.get("AbortIfError")), number(el.get("JumpToLine")), number(el.get("Line"))
        if row["implicit"]:
            if abort or jump:
                res.note(where, "SDO 0x%04X:%d" % (index, sub), "abort-on-error / jump-to-line on a row CODESYS "
                         "generates; set it again in CODESYS after a build")
            continue
        type_name, why = _type_for(eds, index, sub, number(el.get("Size")) or 0)
        if why:
            res.note(where, "SDO 0x%04X:%d" % (index, sub), why)
        if type_name is None:
            continue
        sdo = {"index": "0x%04X" % index, "subindex": sub, "type": type_name,
               "value": _sdo_value(el.get("Value"), type_name)}
        extra = {}
        if abort:
            extra["abort_on_error"] = True
        if jump:
            extra["jump_to_line"] = line or 0
        if extra:
            sdo["codesys"] = extra
        sdos.append(sdo)
    if sdos:
        node["sdo"] = sdos
    if cs:
        node["codesys"] = cs
    return node


def _master(mgr, res, where):
    m = {"node_id": _value(mgr, M_NODE_ID) or 127}
    if _flag(mgr, M_HB_ON):
        m["heartbeat_ms"] = _value(mgr, M_HB_MS) or 0
    if _flag(mgr, M_SYNC_ON):
        m["sync_period_us"] = _value(mgr, M_SYNC_PERIOD) or 0
        window = _value(mgr, M_SYNC_WINDOW)
        if window and window != MGR_DEFAULTS[M_SYNC_WINDOW]:
            m["sync_window_us"] = window
        cob = _value(mgr, M_SYNC_COB_ID)
        if cob is not None and cob & 0x7FF != 0x80:
            res.note(where, "SYNC COB-ID", "0x%X in CODESYS; canworks sends SYNC on 0x80" % (cob & 0x7FF))
    if _flag(mgr, M_AUTOSTART) is False:
        m["start"] = False
    if _flag(mgr, M_START_SLAVES) is False:
        m["start_nodes"] = False
    if _flag(mgr, M_START_ALL):
        m["start_all_nodes"] = True
    inhibit = _value(mgr, M_NMT_INHIBIT)
    if inhibit and inhibit != MGR_DEFAULTS[M_NMT_INHIBIT]:
        m["nmt_inhibit_time_us"] = inhibit * 100
    sdo = _value(mgr, M_SDO_TIMEOUT)
    if sdo and sdo != MGR_DEFAULTS[M_SDO_TIMEOUT]:
        m["sdo_timeout_ms"] = sdo
    period = mgr.get(M_TIME_PERIOD)
    if period is not None and period.download and number(period.value):
        m["time_period_ms"] = number(period.value)
        cob = _value(mgr, M_TIME_COB_ID)
        if cob is not None and cob & 0x1FFFFFFF != 0x100:
            m["time_cob_id"] = "0x%X" % (cob & 0x1FFFFFFF)
    if _flag(mgr, M_SYNC_CONSUMER):
        res.note(where, "SYNC consumer", "the manager consumes SYNC in CODESYS; canworks produces it")
    behaviour = _value(mgr, M_NMT_ERROR)
    if behaviour:
        res.note(where, "NMT error behaviour", "%d in CODESYS: set it again in CODESYS (canworks keeps "
                 "master.error_behavior for the bridge only)" % behaviour)
    ratio = _value(mgr, M_HB_RATIO)
    if ratio is not None and m.get("heartbeat_ms"):
        res.note(where, "heartbeat ratio", "CODESYS watches each node's heartbeat at %d %% of its period; it "
                 "keeps doing so (canworks's heartbeat_timeout_ms is for the bridge)" % ratio)
    return m


def convert(choice, find_eds, project=None):
    """The import of one choice of choices(): `find_eds(identity)` gives the
    EDS of a node as {path, state ("library", "repository" or "config"),
    note} or None, where identity is {vendor_id, product_code,
    revision_number, device} (`device` the CODESYS identification
    {type, id, version})."""
    res = Result()
    where_dev = choice["name"] or "the export"
    nets, net_names, node_names_taken = [], set(), set()
    buses = choice["buses"]
    for bus in buses:
        for c in bus.children:
            if c.type == LOCAL_DEVICE:
                res.note(bus.path(), "CANopen device %s" % c.name, "CODESYS as a CANopen slave is not carried (make "
                         "a slave network in canworks)")
    # Every bus of the device that is not a manager bus.
    if choice["device"] is not None:
        for d in _all([choice["device"]]):
            if d.type == CANBUS and all(d is not b for b in buses):
                kinds = ", ".join(sorted(set("%s (type %s)" % (c.name, c.type) for c in d.children))) or "nothing"
                res.note(d.path(), "CANbus", "holds no CANopen Manager (%s); not carried" % kinds)
    plan = []
    for bus in buses:
        mgr = next(c for c in bus.children if c.type == MANAGER)
        for c in bus.children:
            if c.type not in (MANAGER, LOCAL_DEVICE):
                res.note(bus.path(), c.name, "device type %s on the CANbus is not carried" % c.type)
        remotes = []
        for c in mgr.children:
            if c.type == REMOTE_DEVICE and _value(c, D_NODE_ID) is not None:
                remotes.append(c)
            else:
                res.note(c.path(), "device", "device type %s under the CANopen Manager is not carried" % c.type)
        named = [(c, _unique(declare.identifier(c.name), node_names_taken)) for c in remotes]
        plan.append((bus, mgr, named))
    several = len(plan) > 1
    for bus, mgr, named in plan:
        net_id = _value(bus, BUS_NET_ID) or 0
        # The bus object's name (the build names it after the network), else
        # the channels' network prefix, else the interface (codesys-import
        # "Network name from the bus object").
        own = declare.identifier(bus.name)
        if own.lower().endswith("_bus") and own[:-4].lower() in {n.lower() for _, n in named}:
            own = own[:-4]  # the build's name for a network named like one of its nodes
        own = own[:16]
        if _DEFAULT_BUS.match(bus.name or "") or not _NAME.match(own):
            own = None
        base = own or _network_prefix(mgr, named) or "can%d" % net_id
        name = _unique(base, net_names, 16)
        where = "network %s" % name
        master = _master(mgr, res, where)
        kbit = _value(bus, BUS_BAUDRATE) or 0
        net = {"name": name, "adapter": {"interface": "can%d" % net_id,
                                         "bitrate": kbit * 1000},
               "codesys": {"net_id": net_id}, "master": master, "nodes": []}
        ctx = {"sdo_timeout_us": (master.get("sdo_timeout_ms") or _value(mgr, M_SDO_TIMEOUT) or 1000) * 1000}
        managed = []
        for dev, node_name in named:
            node_id = _value(dev, D_NODE_ID)
            nwhere = "%s/%s" % (name, node_name)
            ident = {"vendor_id": _value(dev, 0x11018010), "product_code": _value(dev, 0x11018020),
                     "revision_number": _value(dev, 0x11018030),
                     "device": {"type": dev.type, "id": dev.id, "version": dev.version}}
            found = find_eds(ident)
            eds = None
            row = {"network": name, "node_id": node_id, "name": node_name, "device": dev.name,
                   "vendor_id": ident["vendor_id"], "product_code": ident["product_code"],
                   "revision_number": ident["revision_number"]}
            if found:
                try:
                    eds = Eds.read(found["path"])
                except (OSError, EdsError) as e:
                    found, row["note"] = None, "EDS %s cannot be read: %s" % (os.path.basename(found["path"]), e)
            if found:
                eds_name = _eds_name(found["path"], res.eds_files)
                res.eds_files[eds_name] = found["path"]
                row.update({"eds": eds_name, "eds_state": found["state"], "eds_path": found["path"]})
                if found.get("note"):
                    row["note"] = found["note"]
                    res.note(nwhere, "EDS", found["note"])
            else:
                row.update({"eds": None, "eds_state": "missing"})
                res.missing.append(dict(row))
            prefix_node = ("%s_%s" % (declare.identifier(name), node_name)) if several else node_name
            node = _node(dev, ctx, master["node_id"], eds, {"node": node_name, "entries": _Names(prefix_node)}, res,
                         nwhere)
            node["eds"] = row["eds"] or ""
            # eds right after name, as configs write it.
            ordered = {k: node[k] for k in ("node_id", "name", "eds") if k in node}
            ordered.update((k, v) for k, v in node.items() if k not in ordered)
            net["nodes"].append(ordered)
            res.nodes.append(row)
            managed.append(node_id)
        net["codesys"]["managed"] = sorted(managed)
        nets.append(net)
    cfg = {"schema_version": 2, "networks": nets, "codesys": {}}
    if project:
        cfg["codesys"]["project"] = project
    if choice["name"]:
        cfg["codesys"]["device"] = choice["name"]
    res.cfg = cfg
    if not nets:
        raise ImportError_("%s has no CANopen Manager" % where_dev)
    return res


def _eds_name(path, taken):
    base = os.path.basename(path)
    stem, ext = os.path.splitext(base)
    if ext.lower() == ".dcf":
        ext = ".eds"
    name, n = stem + ext, 2
    while name in taken and taken[name] != path:
        name = "%s_%d%s" % (stem, n, ext)
        n += 1
    return name


# ---------------------------------------------------------------------------
# Finding EDS files


def library_finder(index_matches, repository_roots=()):
    """A find_eds for convert(): `index_matches(vendor, product, revision)`
    lists EDS files of the config folder and the EDS library (the
    configurator's EDS index), exact revision first; then the device
    description file in CODESYS's device repository."""
    def find(ident):
        found = index_matches(ident["vendor_id"], ident["product_code"], ident["revision_number"]) \
            if ident["vendor_id"] is not None and ident["product_code"] is not None else []
        if found:
            m = found[0]
            out = {"path": m["path"], "state": "config" if m.get("where") == "project" else "library"}
            if not m.get("revision_match") and ident["revision_number"] is not None:
                out["note"] = "no EDS with revision 0x%X; took %s (revision %s)" % (
                    ident["revision_number"], m["name"],
                    "0x%X" % m["revision_number"] if m.get("revision_number") is not None else "not given")
            return out
        path = repository_file(ident["device"], repository_roots)
        if path:
            return {"path": path, "state": "repository"}
        return None
    return find


def repository_file(device, roots):
    """The EDS or DCF CODESYS installed for a remote device: in
    <root>\\<type>\\<id>\\<version>\\ (folder names as CODESYS writes them,
    so each device.xml is read to match)."""
    from .run import read_device
    for root in roots or ():
        top = os.path.join(root, str(device["type"]))
        for folder, _, names in os.walk(top):
            low = [n.lower() for n in names]
            if "device.xml" not in low:
                continue
            d = read_device(os.path.join(folder, names[low.index("device.xml")]))
            if not d or d["id"] != device["id"] or d["version"] != device["version"]:
                continue
            files = sorted(n for n in names if n.lower().endswith((".eds", ".dcf")))
            if files:
                return os.path.join(folder, files[0])
    return None


def folder_matcher(folders):
    """index_matches over EDS files in folders [(where, path)], for the
    command line (the configurator passes its own index)."""
    from ..configurator.online import EdsIndex
    index = EdsIndex()
    return lambda vendor, product, revision: index.matches(folders, vendor, product, revision)


def text(res):
    """The import report as lines."""
    lines = []
    for row in res.nodes:
        state = {"config": "EDS in the config folder", "library": "EDS from the library",
                 "repository": "EDS from CODESYS's device repository", "added": "EDS added", "missing": "EDS missing"}[row["eds_state"]]
        lines.append("node     %s/%s (node %s): %s%s" % (row["network"], row["name"], row["node_id"], state,
                                                         ", %s" % row["eds"] if row.get("eds") else ""))
    for n in res.report:
        lines.append("not carried  %s: %s: %s" % (n["where"], n["setting"], n["note"]))
    return "\n".join(lines) + ("\n" if lines else "")


def write(res, folder, name="canworks.json"):
    """Writes the imported config and copies its EDS files into folder;
    returns the config's path. Refuses while a node has no EDS."""
    import json
    import shutil
    if res.missing:
        raise ImportError_("no EDS for %s: add one for each and import again" % ", ".join(
            "%s/%s (node %s)" % (m["network"], m["name"], m["node_id"]) for m in res.missing))
    os.makedirs(folder, exist_ok=True)
    for eds_name, src in sorted(res.eds_files.items()):
        dst = os.path.join(folder, eds_name)
        if not (os.path.exists(dst) and os.path.samefile(src, dst)):
            shutil.copyfile(src, dst)
    path = os.path.join(folder, name)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(res.cfg, indent=2) + "\n")
    return path


def read_text(data):
    """Bytes of an .xml or .xml.gz upload."""
    if data[:2] == b"\x1f\x8b":
        return gzip.GzipFile(fileobj=io.BytesIO(data)).read()
    return data
