# -*- coding: utf-8 -*-
"""Builds a canworks CANopen bus in a CODESYS project.

Run it in CODESYS on the open project (Tools > Scripting > Execute Script
File...), or headless:

  CODESYS.exe --profile="<profile>" --noUI --runscript="<folder>\\import_canworks.py"

It reads canworks-codesys.json next to itself (written by canworks-deploy
--export-codesys or the configurator's Download for CODESYS), and writes
import_report.txt next to itself. With a project open in the IDE it changes
that project and does not save it; without one it opens or creates the
project the plan names and saves it when nothing failed.

This file is the same for every config: everything config specific is in
the plan. It runs on CODESYS's IronPython 2.7 and on CPython 3 (tests).
"""
from __future__ import print_function

import io
import json
import os
import traceback

PLAN_NAME = "canworks-codesys.json"
REPORT_NAME = "import_report.txt"
FORMAT = 2
# The CANopen EDS/DCF converter of CODESYS's device repository.
EDS_CONVERTER = "{1ce4a9c1-37d3-496c-9e80-cd99ad3807ee}"
CANBUS_TYPE, CANBUS_ID = 15, "181015"
MANAGER_TYPE, MANAGER_ID = 16, "181016"
LOCAL_DEVICE_TYPE = 17
CANBUS_NET_ID = 2
DEVICE_NODE_ID = 1
SDO_LIST = 0x20001000
# The identity checks: the download flag of the expected 0x1018 values.
CHECKS = (("vendor", 0x11018010), ("product", 0x11018020), ("revision", 0x11018030))
CHECK_LABELS = {"vendor": "vendor ID", "product": "product code", "revision": "revision number"}
# The manager's TIME producer: on when its COB-ID and period are downloaded.
TIME_PARAMS = (290, 291)


class Stop(Exception):
    """A failure that ends the run."""


class Report(object):
    def __init__(self):
        self.lines = []
        self.errors = 0
        self.warnings = 0

    def add(self, kind, text):
        if kind == "error":
            self.errors += 1
        elif kind == "warning":
            self.warnings += 1
        self.lines.append(u"%-8s %s" % (kind, text))

    def text(self):
        head = u"result: %s" % ("ok" if not self.errors else "error (%d)" % self.errors)
        return "\n".join([head, "warnings: %d" % self.warnings, ""] + self.lines) + "\n"


def _children(obj, recursive=False):
    try:
        return list(obj.get_children(recursive))
    except TypeError:
        return list(obj.get_children())


def _is_device(obj):
    try:
        return bool(obj.is_device)
    except Exception:
        return False


def _ident(obj):
    try:
        return obj.get_device_identification()
    except Exception:
        return None


def _type(obj):
    d = _ident(obj)
    return d.type if d is not None else None


def _params(obj):
    out = []
    try:
        for con in obj.connectors:
            out.extend(list(con.host_parameters))
    except Exception:
        pass
    try:
        out.extend(list(obj.device_parameters))
    except Exception:
        pass
    return out


def _param(obj, pid):
    for p in _params(obj):
        if p.id == pid:
            return p
    return None


def _number(text):
    s = str(text).strip().replace("_", "")
    if s.upper().startswith("16#"):
        return int(s[3:], 16)
    if s.upper().startswith("2#"):
        return int(s[2:], 2)
    return int(s, 0)


def _version_key(version):
    out = []
    for part in str(version).replace(",", ".").split("."):
        digits = "".join(c for c in part if c.isdigit())
        out.append(int(digits) if digits else 0)
    return out


def _highest(repo, dtype, did):
    best = None
    for d in repo.get_all_devices():
        i = d.device_id
        if i.type == dtype and i.id == did and (best is None or _version_key(i.version) > _version_key(best.version)):
            best = i
    return best


def _top(obj):
    """The top-level device holding obj (the object right below the project)."""
    while _parent(obj) is not None and _parent(_parent(obj)) is not None:
        obj = _parent(obj)
    return obj


def _unique_name(parent, base):
    """A name no other object of the device uses: CODESYS refuses a name
    taken anywhere in the device's tree (its I/O names are one namespace),
    not only among the new object's siblings."""
    top = _top(parent)
    taken = set(c.get_name().lower() for c in _children(top, True))
    taken.add(top.get_name().lower())
    name, n = base, 2
    while name.lower() in taken:
        name = "%s_%d" % (base, n)
        n += 1
    return name


def _add(parent, name, dtype, did, version):
    """Adds a device under parent and returns it (found by its new name)."""
    before = set(c.get_name() for c in _children(parent))
    parent.add(name, dtype, did, version)
    new = [c for c in _children(parent) if c.get_name() not in before]
    if not new:
        raise Stop("CODESYS added no %s under %s" % (name, parent.get_name()))
    return new[0]


def _norm(value):
    """A parameter value for comparing: a number when it reads as one
    (16#1A, 26, TRUE), else the text without quotes and spaces."""
    text = (u"%s" % value).strip().strip("'").replace(" ", "")
    if text.upper() in ("TRUE", "FALSE"):
        return text.upper() == "TRUE"
    try:
        return _number(text)
    except ValueError:
        return text.upper()


def _write(target, value, report, label, write):
    """Sets target.value when it differs: True when it differed."""
    if _norm(target.value) == _norm(value):
        return False
    if write:
        target.value = value
        report.add("set", "%s = %s" % (label, value))
    return True


def _elements(p):
    try:
        return dict((s.identifier, s) for s in p)
    except Exception:
        return {}


def apply_params(obj, params, report, where, write=True):
    """Sets each plan parameter whose value differs; returns the labels of
    the ones that differed (with write False: that differ)."""
    changed = []
    for spec in params:
        p = _param(obj, spec["id"])
        label = "%s: %s" % (where, spec.get("what") or spec.get("name"))
        if p is None:
            if write:
                report.add("warning", "%s not set: this CODESYS has no parameter %s (%s)"
                           % (label, spec["id"], spec.get("name")))
            continue
        try:
            if spec.get("element"):
                sub = _elements(p).get(spec["element"])
                if sub is None:
                    if write:
                        report.add("warning", "%s not set: %s has no %s" % (label, p.name, spec["element"]))
                    continue
                differs = _write(sub, spec["value"], report, label, write)
            else:
                differs = _write(p, spec["value"], report, label, write)
        except Exception as e:
            report.add("warning", "%s not set: %s" % (label, e))
            continue
        if differs:
            changed.append(label)
            if write and spec.get("name") and (u"%s" % p.name).lower() != spec["name"].lower():
                report.add("note", "%s: parameter %s is called %r here (expected %r)"
                           % (where, spec["id"], p.name, spec["name"]))
    return changed


def _mapping_of(params, map_index):
    """[[index, sub-index, length]] of a mapping object as the device has it."""
    base = 0x10000000 | (map_index << 12)
    out = []
    for pid in sorted(params):
        if base <= pid < base + 0x1000 and (pid & 0xF) == 0:
            el = _elements(params[pid])
            try:
                out.append([_number(el["Index"].value), _number(el["SubIndex"].value),
                            _number(el["ObjectLength"].value)])
            except (KeyError, ValueError):
                continue
    return out


def _sdo_rows(dev):
    """The rows of the device's SDO list that come from the DCF or the user
    (objects from 0x2000), as element dicts: CODESYS makes the rows for
    0x1000-0x1FFF itself from the communication settings."""
    p = _param(dev, SDO_LIST)
    out = []
    try:
        rows = list(p) if p is not None else []
    except Exception:
        rows = []
    for row in rows:
        el = _elements(row)
        try:
            if _number(el["Index"].value) >= 0x2000:
                out.append(el)
        except (KeyError, ValueError):
            continue
    return out


def structural_difference(dev, node):
    """Why the device cannot be updated in place (a PDO switched on or off,
    another mapping, another startup SDO list), or None."""
    params = dict((p.id, p) for p in _params(dev))
    for pdo in node.get("pdos") or []:
        label = "%sPDO%d" % ("T" if pdo["dir"] == "tx" else "R", pdo["number"])
        p = params.get(pdo["comm"] << 12)
        if p is None:
            return "%s is not in the CODESYS device" % label
        try:
            on = not _number(_elements(p)["COBID"].value) & 0x80000000
        except (KeyError, ValueError):
            return "%s has no COB-ID here" % label
        if on != pdo["enabled"]:
            return "%s switched %s" % (label, "on" if pdo["enabled"] else "off")
        if on:
            map_index = pdo["comm"] + 0x200
            want = (node.get("mapping") or {}).get("%04X" % map_index)
            if want is not None and _mapping_of(params, map_index) != want:
                return "PDO mapping changed (%s)" % label
    have = [(_number(r["Index"].value), _number(r["Subindex"].value), _number(r["Size"].value))
            for r in _sdo_rows(dev)]
    want = [(r["index"], r["sub"], r["size"]) for r in node.get("sdo") or []]
    if "sdo" in node and have != want:
        return "startup SDO list changed"
    return None


def update_device(dev, node, report, where, write=True):
    """Brings the device to the plan's values in place; returns the labels
    of what differed. With write False only compares (the read-back)."""
    changed = []
    if dev.get_name() != node["name"]:
        if write:
            try:
                dev.rename(node["name"])
                report.add("set", "%s: name = %s" % (where, node["name"]))
            except Exception as e:
                report.add("warning", "%s: kept the name %s (%s)" % (where, dev.get_name(), e))
        changed.append("%s: name" % where)
    changed += apply_params(dev, (node.get("params") or []) + (node.get("state_params") or []), report, where, write)
    params = dict((p.id, p) for p in _params(dev))
    for pdo in node.get("pdos") or []:
        label = "%s: %sPDO%d" % (where, "T" if pdo["dir"] == "tx" else "R", pdo["number"])
        base = pdo["comm"] << 12
        if base not in params:
            continue
        generic = params.get(base + 1)
        if generic is not None and _norm(generic.value) != _norm(pdo["cob_id"]):
            # A COB-ID written to the struct of a PDO that is on is ignored:
            # the generic setting is what CODESYS follows.
            if write:
                generic.value = "'%s'" % pdo["cob_id"]
                report.add("set", "%s COB-ID = %s" % (label, pdo["cob_id"]))
            changed.append(label + " COB-ID")
        el = _elements(params[base])
        for key, element in (("transmission", "TransmissionType"), ("inhibit", "InhibitTime"), ("event", "EventTimer")):
            if key in pdo and element in el and pdo["enabled"]:
                if _write(el[element], str(pdo[key]), report, "%s %s" % (label, element), write):
                    changed.append("%s %s" % (label, element))
        if "by_manager" in pdo and params.get(base + 2) is not None:
            if _write(params[base + 2], "TRUE" if pdo["by_manager"] else "FALSE", report,
                      label + " processed by the manager", write):
                changed.append(label + " processed by the manager")
    for row, want in zip(_sdo_rows(dev), node.get("sdo") or []):
        label = "%s: SDO 0x%04X:%d" % (where, want["index"], want["sub"])
        if _write(row["Value"], "16#%X" % (want["value"] & 0xFFFFFFFFFFFFFFFF), report, label, write):
            changed.append(label)
        if want.get("abort") and "AbortIfError" in row:
            if _write(row["AbortIfError"], "TRUE", report, label + " abort on error", write):
                changed.append(label + " abort on error")
        if want.get("jump") is not None and "JumpToLine" in row:
            if _write(row["JumpToLine"], "TRUE", report, label + " jump to line", write):
                changed.append(label + " jump to line")
            if "Line" in row and _write(row["Line"], str(want["jump"]), report, label + " line", write):
                changed.append(label + " line")
    changed += name_channels(dev, node.get("channels") or [], report, where, write)
    return changed


def _set_download(obj, values):
    """Sets the download flag of parameters {id: bool} through CODESYS's
    internal parameter set (no script API has it): raises when this CODESYS
    does not have it."""
    import clr
    clr.AddReference("DeviceObject")
    from System import Action, Array
    from System.Reflection import BindingFlags
    import _3S.CoDeSys.DeviceObject as DO
    flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance
    for con in obj.connectors:
        ids = set(p.id for p in con.host_parameters)
        mine = dict((k, v) for k, v in values.items() if k in ids)
        if not mine:
            continue
        hp = con.host_parameters
        hp.GetType().GetMethod("PerformWithWriteableCopy", flags).Invoke(
            hp, Array[object]([Action[DO.IParameterSet](_downloads(mine))]))


def _downloads(values):
    def fn(ps):
        for pid, on in values.items():
            ps.GetParameter(pid).SetDownload(on)
    return fn


def _downloaded(obj, pid):
    p = _param(obj, pid)
    try:
        return None if p is None else bool(p.downloaded_with_ioconfig)
    except Exception:
        return None


def set_checks(dev, wanted, report, where):
    """The identity checks CODESYS makes at startup (General tab ticks)."""
    values = {}
    for name, pid in CHECKS:
        have = _downloaded(dev, pid)
        if have is not None and have != (name in wanted):
            values[pid] = name in wanted
    if not values:
        return []
    names = [n for n, pid in CHECKS if pid in values]
    try:
        _set_download(dev, values)
    except Exception:
        report.add("not set", "%s: identity checks: tick %s in CODESYS by hand (this CODESYS does not let the "
                   "script set them)" % (where, ", ".join(
                       "%s %s" % ("on" if values[pid] else "off", CHECK_LABELS[n]) for n, pid in CHECKS if pid in values)))
        return []
    report.add("set", "%s: identity checks = %s" % (where, ", ".join(CHECK_LABELS[n] for n in wanted) or "none"))
    return ["%s: identity checks %s" % (where, ", ".join(names))]


def time_producer(mgr, report, where):
    """Switches the manager's TIME producer on (its COB-ID and period
    downloaded)."""
    values = dict((pid, True) for pid in TIME_PARAMS if _downloaded(mgr, pid) is False)
    if not values:
        return
    try:
        _set_download(mgr, values)
        report.add("set", "%s: TIME producer on" % where)
    except Exception:
        report.add("not set", "%s: TIME producer: the COB-ID and period are set; switch TIME producing on in the "
                   "manager in CODESYS" % where)


def name_channels(dev, channels, report, where, write=True):
    """A mapped object is a parameter with id 0x1MMMMEE0 (mapping object
    0xMMMM, entry EE) holding Index, SubIndex and ObjectLength; its I/O
    channel is the parameter with the next id. Sets each channel's variable
    and fixed address where they differ; returns what differed. An object
    mapped twice in one PDO has a channel per entry, taken in entry order."""
    params = dict((p.id, p) for p in _params(dev))
    maps = {}
    changed = []
    for pid in sorted(params):
        p = params[pid]
        if (pid & 0xF0000000) == 0x10000000 and (pid & 0xF) == 0:
            try:
                el = dict((s.identifier, s.value) for s in p)
                key = ((pid >> 12) & 0xFFFF, _number(el["Index"]), _number(el["SubIndex"]))
            except Exception:
                continue
            channel = params.get(pid + 1)
            if channel is not None:
                maps.setdefault(key, []).append(channel)
    taken = {}
    for ch in channels:
        key = (ch["mapping"], ch["index"], ch["sub"])
        k = taken.get(key, 0)
        taken[key] = k + 1
        p = maps[key][k] if k < len(maps.get(key, [])) else None
        what = "%s: 0x%04X:%d (PDO mapping 0x%04X)" % (where, ch["index"], ch["sub"], ch["mapping"])
        if p is None or p.io_mapping is None:
            if write:
                report.add("warning", "%s has no I/O channel in CODESYS, so %s is not mapped" % (what, ch["variable"]))
            continue
        # CODESYS refuses a variable on an output bit while its channel has
        # one (overlapping output mappings): an output with bits maps the bits only.
        if ch.get("dir") == "out" and ch.get("bits"):
            if write and p.io_mapping.variable != ch["variable"]:
                report.add("not set", "%s: %s left unmapped, the output goes through its bits" % (what, ch["variable"]))
        elif (p.io_mapping.variable or "") != ch["variable"]:
            changed.append(what)
            if write:
                try:
                    p.io_mapping.variable = ch["variable"]
                    report.add("set", "%s -> %s" % (what, ch["variable"]))
                except Exception as e:
                    report.add("warning", "%s: variable %s not set: %s" % (what, ch["variable"], e))
        if ch.get("address") and _address(p.io_mapping) != ch["address"].upper():
            changed.append(what + " address")
            if write:
                try:
                    # CODESYS takes a manual address set while the automatic one is on.
                    p.io_mapping.automatic_iec_address = True
                    p.io_mapping.manual_iec_address = ch["address"]
                    p.io_mapping.automatic_iec_address = False
                    report.add("set", "%s address = %s" % (what, ch["address"]))
                except Exception as e:
                    report.add("warning", "%s: address %s not set: %s" % (what, ch["address"], e))
        for b in ch.get("bits") or []:
            el = _bit_element(p, b["bit"])
            if el is None or getattr(el, "io_mapping", None) is None:
                if write:
                    report.add("warning", "%s bit %d has no bit channel here: map %s to it by hand"
                               % (what, b["bit"], b["variable"]))
                continue
            if (el.io_mapping.variable or "") == b["variable"]:
                continue
            changed.append("%s bit %d" % (what, b["bit"]))
            if not write:
                continue
            try:
                el.io_mapping.variable = b["variable"]
                report.add("set", "%s bit %d -> %s" % (what, b["bit"], b["variable"]))
            except Exception as e:
                report.add("warning", "%s bit %d: variable %s not set: %s" % (what, b["bit"], b["variable"], e))
    return changed


def _address(io_mapping):
    """The channel's manual IEC address, or None while it is automatic."""
    try:
        if io_mapping.automatic_iec_address:
            return None
        return (u"%s" % io_mapping.manual_iec_address).strip().upper() or None
    except Exception:
        return None


def _bit_element(channel, bit):
    """The I/O mapping element of one bit of a channel: CODESYS lists a
    BYTE, WORD, ... channel's bits as its sub-elements, bit 0 first, named
    <parameter id>_<bit> (3.5 SP22)."""
    try:
        subs = list(channel)
    except Exception:
        return None
    for s in subs:
        ident = (u"%s" % getattr(s, "identifier", "")).lower()
        if ident in ("bit%d" % bit, "bit %d" % bit) or ident.endswith("_%d" % bit):
            return s
    return subs[bit] if bit < len(subs) else None


def _same(a, b):
    """Script objects can be new wrappers on every call: compare by guid."""
    if a is None or b is None:
        return a is b
    try:
        return a.guid == b.guid
    except Exception:
        return a is b


def _parent(obj):
    try:
        return obj.parent
    except Exception:
        return None


def active_device(proj):
    """The device that holds the project's active application, or None."""
    try:
        obj = proj.active_application
    except Exception:
        return None
    seen = 0
    while obj is not None and seen < 64:
        if _same(obj, proj):
            return None
        if _is_device(obj):
            return obj
        obj = _parent(obj)
        seen += 1
    return None


def choose_plc(proj, plan, report, plan_name=PLAN_NAME):
    """The device that gets the bus: named in the plan, else the active
    application's device, else the only top-level device."""
    tops = [c for c in _children(proj) if _is_device(c)]
    active = active_device(proj)
    if plan.get("plc"):
        found = [c for c in _children(proj, True) if _is_device(c) and c.get_name() == plan["plc"]]
        if not found:
            raise Stop("no device named %s in the project (devices: %s)"
                       % (plan["plc"], ", ".join(c.get_name() for c in tops) or "none"))
        report.add("device", "%s (named in %s)" % (found[0].get_name(), plan_name))
        if active is not None and not _same(active, found[0]):
            report.add("warning", "the active application is on %s, so the build checks %s, not %s"
                       % (active.get_name(), active.get_name(), found[0].get_name()))
        return found[0]
    if active is not None:
        report.add("device", "%s (active application)" % active.get_name())
        return active
    if len(tops) == 1:
        report.add("device", "%s (only device)" % tops[0].get_name())
        return tops[0]
    if not tops:
        raise Stop("the project has no PLC device: add your PLC or display device first")
    raise Stop("the project has several devices (%s) and no active application: set one in CODESYS "
               "(Set Active Application on the device's application) or name the device with --codesys-plc NAME"
               % ", ".join(c.get_name() for c in tops))


def find_canbus(plc, net_id):
    buses = [c for c in _children(plc, True) if _is_device(c) and _type(c) == CANBUS_TYPE]
    for b in buses:
        p = _param(b, CANBUS_NET_ID)
        try:
            if p is not None and _number(p.value) == net_id:
                return b, buses
        except ValueError:
            pass
    return None, buses


CANOPEN_TYPES = (CANBUS_TYPE, MANAGER_TYPE, LOCAL_DEVICE_TYPE, 18)


def _path(plc, obj):
    names = []
    while obj is not None and not _same(obj, plc):
        names.append(obj.get_name())
        obj = _parent(obj)
    return "/".join([plc.get_name()] + names[::-1])


def _trailing_number(name):
    digits = ""
    for c in reversed(name):
        if not c.isdigit():
            break
        digits = c + digits
    return int(digits) if digits else None


def _looks_like_can(name):
    """CAN, CAN1, can_0, Port CAN 2, but not Scanner."""
    n = name.lower()
    i = n.find("can")
    while i >= 0:
        if (i == 0 or not n[i - 1].isalpha()) and (i + 3 == len(n) or not n[i + 3].isalpha()):
            return True
        i = n.find("can", i + 1)
    return False


def can_interface(plc, net, where):
    """Where a new CANbus goes: the object the plan names, else the
    device's only CAN interface object, else the one whose name ends in the
    network number, else the device itself."""
    objs = [c for c in _children(plc, True) if not _same(c, plc)]
    if net.get("interface"):
        found = [c for c in objs if c.get_name() == net["interface"]]
        if not found:
            raise Stop("%s: no object named %s in device %s (objects: %s)"
                       % (where, net["interface"], plc.get_name(), ", ".join(_path(plc, c) for c in objs) or "none"))
        return found[0]
    cands = [c for c in objs if _is_device(c) and _type(c) not in CANOPEN_TYPES
             and _looks_like_can(c.get_name()) and not any(_type(a) in CANOPEN_TYPES for a in _ancestors(plc, c))]
    if not cands:
        return plc
    if len(cands) == 1:
        return cands[0]
    match = [c for c in cands if _trailing_number(c.get_name()) == net["net_id"]]
    if len(match) == 1:
        return match[0]
    raise Stop("%s: device %s has several CAN interfaces (%s) and none ends in network number %d: name one with "
               "--codesys-can %s=OBJECT" % (where, plc.get_name(), ", ".join(_path(plc, c) for c in cands),
                                            net["net_id"], net["name"] or net["folder"]))


def _ancestors(plc, obj):
    out = []
    obj = _parent(obj)
    while obj is not None and not _same(obj, plc):
        out.append(obj)
        obj = _parent(obj)
    return out


def _refused(plc, host, where, *errors):
    others = [_path(plc, c) for c in _children(plc, True) if _is_device(c) and not _same(c, host)]
    return ("%s: CODESYS takes neither a CANbus nor a CANopen Manager under %s (device type %s): %s. "
            "Objects in the device: %s. Name the CAN interface with --codesys-can NETWORK=OBJECT"
            % (where, _path(plc, host), _type(host), "; ".join(str(e) for e in errors), ", ".join(others) or "none"))


def warn_other_devices(proj, plc, net, report):
    """A CANopen Manager on the same network number under another
    top-level device would drive the same bus from two controllers. One
    warning per network: projects that keep a device per hardware variant
    have many."""
    names = []
    for top in [c for c in _children(proj) if _is_device(c)]:
        if _same(top, plc) or any(_same(top, a) for a in _ancestors(proj, plc)):
            continue
        bus, _ = find_canbus(top, net["net_id"])
        if bus is not None and any(_type(c) == MANAGER_TYPE for c in _children(bus)):
            names.append(top.get_name())
    if not names:
        return
    where = net["name"] or net["folder"]
    if len(names) == 1:
        report.add("warning", "network %s: device %s also has a CANopen Manager on network number %d; "
                   "it was left as it is" % (where, names[0], net["net_id"]))
        return
    shown = ", ".join(names[:OTHER_DEVICES_SHOWN])
    if len(names) > OTHER_DEVICES_SHOWN:
        shown += " and %d more" % (len(names) - OTHER_DEVICES_SHOWN)
    report.add("warning", "network %s: %d other devices also have a CANopen Manager on network number %d and were "
               "left as they are: %s" % (where, len(names), net["net_id"], shown))


OTHER_DEVICES_SHOWN = 5


def _key(ident):
    return (ident.type, ident.id, ident.version) if ident is not None else None


def _top_device(proj, obj):
    above = _ancestors(proj, obj)
    return above[-1] if above else obj


def canbus_candidates(proj, host, repo):
    """The CANbus devices to try under `host`, as (identification, where
    it came from): the project's CANbus devices whose parent has the same
    identification as `host` (they fit by construction), the project's
    other CANbus devices, then the installed ones (highest version per id,
    CODESYS's standard CANbus first). A CAN interface often takes only its
    vendor's CANbus, and a refused add leaves nothing behind."""
    host_key = _key(_ident(host))
    same, other = [], []
    for c in _children(proj, True):
        if not _is_device(c) or _type(c) != CANBUS_TYPE:
            continue
        src = (_ident(c), "as on device %s" % _top_device(proj, c).get_name())
        (same if host_key is not None and _key(_ident(_parent(c))) == host_key else other).append(src)
    ids = sorted(set(d.device_id.id for d in repo.get_all_devices() if d.device_id.type == CANBUS_TYPE),
                 key=lambda i: (i != CANBUS_ID, i))
    installed = [(i, "installed") for i in (_highest(repo, CANBUS_TYPE, x) for x in ids) if i is not None]
    out, seen = [], set()
    for ident, why in _newest_first(same) + _newest_first(other) + installed:
        if (ident.id, ident.version) not in seen:
            seen.add((ident.id, ident.version))
            out.append((ident, why))
    return out


def _newest_first(found):
    return sorted(found, key=lambda s: _version_key(s[0].version), reverse=True)


def manager_like(proj, parent, repo):
    """The CANopen Manager to add under `parent`: the one the project has
    under an object with the same identification, else the version
    matching `parent`, else the highest installed."""
    key = _key(_ident(parent))
    for c in _children(proj, True):
        if _is_device(c) and _type(c) == MANAGER_TYPE and key is not None and _key(_ident(_parent(c))) == key:
            return _ident(c)
    ver = _ident(parent).version if _ident(parent) is not None else None
    same = [d.device_id for d in repo.get_all_devices()
            if d.device_id.type == MANAGER_TYPE and d.device_id.id == MANAGER_ID and d.device_id.version == ver]
    return same[0] if same else _highest(repo, MANAGER_TYPE, MANAGER_ID)


def _first_sentence(e):
    text = str(e).strip()
    for sep in ("; ", "\n"):
        text = text.split(sep)[0]
    return text


def _interface_number(bus, net, report, where):
    """A CAN interface that is the bus itself: set its network number when
    it has CODESYS's parameter for it, else say it keeps its own."""
    p = _param(bus, CANBUS_NET_ID)
    if p is None:
        report.add("not set", "%s: network number: CAN interface %s has no network number parameter, so it keeps "
                   "its own" % (where, bus.get_name()))
        return
    p.value = str(net["net_id"])
    report.add("set", "%s: CAN interface %s network number = %d" % (where, bus.get_name(), net["net_id"]))


def build_network(proj, plc, net, base, repo, guid, report):
    where = "network %s" % (net["name"] or net["folder"])
    bus, buses = find_canbus(plc, net["net_id"])
    mgr = None
    if bus is not None:
        report.add("reused", "%s: CANbus %s (network number %d)" % (where, bus.get_name(), net["net_id"]))
    else:
        host = can_interface(plc, net, where)
        if not _same(host, plc) and any(_type(c) == MANAGER_TYPE for c in _children(host)):
            # A CAN interface that is a bus itself and already holds the
            # manager from an earlier run.
            bus = host
            report.add("reused", "%s: CAN interface %s as the bus" % (where, _path(plc, host)))
            _interface_number(bus, net, report, where)
    if bus is None:
        cands = canbus_candidates(proj, host, repo)
        if not cands:
            raise Stop("%s: no CANbus device is installed in this CODESYS (CANopen support missing?)" % where)
        tried = []
        for like, why in cands:
            try:
                bus = _add(host, _unique_name(host, "CANbus"), like.type, like.id, like.version)
                break
            except Exception as e:
                tried.append("%s %s: %s" % (like.id, like.version, _first_sentence(e)))
        if bus is None:
            # The device's own CAN interface can be the bus itself and take
            # the manager directly.
            bus_refused = "CANbus tried: " + "; ".join(tried)
            mlike = manager_like(proj, host, repo)
            if _same(host, plc) or mlike is None:
                raise Stop(_refused(plc, host, where, bus_refused))
            try:
                mgr = _add(host, _unique_name(host, "CANopen_Manager"), mlike.type, mlike.id, mlike.version)
            except Exception as e:
                raise Stop(_refused(plc, host, where, bus_refused, "manager: %s" % _first_sentence(e)))
            bus = host
            report.add("created", "%s: CANopen Manager %s %s directly under the CAN interface %s"
                       % (where, mgr.get_name(), mlike.version, _path(plc, host)))
            _interface_number(bus, net, report, where)
        else:
            p = _param(bus, CANBUS_NET_ID)
            if p is None:
                raise Stop("%s: the new CANbus has no network number parameter" % where)
            p.value = str(net["net_id"])
            report.add("created", "%s: CANbus %s (%s %s, %s) under %s, network number %d"
                       % (where, bus.get_name(), like.id, like.version, why, _path(plc, host), net["net_id"]))
    apply_params(bus, net["canbus"], report, where + " CANbus")
    kids = [c for c in _children(bus) if _is_device(c)]
    if any(_type(c) == LOCAL_DEVICE_TYPE for c in kids):
        raise Stop("%s: CANbus %s holds a CANopen device (CODESYS as a slave), not a manager"
                   % (where, bus.get_name()))
    managers = [c for c in kids if _type(c) == MANAGER_TYPE]
    if mgr is not None:
        pass
    elif managers:
        mgr = managers[0]
        report.add("reused", "%s: CANopen Manager %s" % (where, mgr.get_name()))
    else:
        like = manager_like(proj, bus, repo)
        if like is None:
            raise Stop("%s: no CANopen Manager is installed in this CODESYS" % where)
        mgr = _add(bus, _unique_name(bus, "CANopen_Manager"), like.type, like.id, like.version)
        report.add("created", "%s: CANopen Manager %s %s" % (where, mgr.get_name(), like.version))
    apply_params(mgr, net["manager"], report, where + " manager")

    existing = {}
    for c in _children(mgr):
        p = _param(c, DEVICE_NODE_ID) if _is_device(c) else None
        try:
            if p is not None:
                existing[_number(p.value)] = c
        except ValueError:
            pass
    planned = set(n["node_id"] for n in net["nodes"])
    for nid in sorted(existing):
        if nid in planned:
            continue
        if nid in (net.get("remove") or []):
            name = existing[nid].get_name()
            existing[nid].remove()
            report.add("removed", "%s: %s (node %d) is no longer in the canworks config" % (where, name, nid))
        else:
            report.add("kept", "%s: %s (node %d) is not in the canworks config and stays as it is"
                       % (where, existing[nid].get_name(), nid))
    if net.get("time_producer"):
        time_producer(mgr, report, where + " manager")
    for node in net["nodes"]:
        nwhere = "%s node %d (%s)" % (where, node["node_id"], node["name"])
        old = existing.get(node["node_id"])
        if old is not None:
            why = structural_difference(old, node)
            if why is None:
                changed = update_device(old, node, report, nwhere) + set_checks(old, node.get("checks"), report, nwhere) \
                    if node.get("checks") is not None else update_device(old, node, report, nwhere)
                report.add("updated" if changed else "current", "%s: %s" % (
                    nwhere, "%d setting%s changed in place" % (len(changed), "" if len(changed) == 1 else "s")
                    if changed else "up to date"))
                read_back(old, node, report, nwhere)
                continue
            old_name = old.get_name()
            old.remove()
            report.add("replaced", "%s: %s; removed %s, added again from the DCF" % (nwhere, why, old_name))
        path = os.path.join(base, *node["dcf"].split("/"))
        try:
            did = repo.import_device(path, repo.sources[0], guid, True)
        except Exception as e:
            report.add("error", "%s: CODESYS did not install %s: %s" % (nwhere, node["dcf"], e))
            continue
        try:
            dev = _add(mgr, _unique_name(mgr, node["name"]), did.type, did.id, did.version)
        except Exception as e:
            report.add("error", "%s: cannot add the device: %s" % (nwhere, e))
            continue
        if old is None:
            report.add("created", "%s: device %s from %s" % (nwhere, dev.get_name(), node["dcf"]))
        update_device(dev, node, report, nwhere)
        if node.get("checks") is not None:
            set_checks(dev, node["checks"], report, nwhere)
        read_back(dev, node, report, nwhere)


def read_back(dev, node, report, where):
    """What CODESYS did not take: compares the device with the plan again."""
    for label in update_device(dev, node, report, where, write=False):
        report.add("warning", "%s: CODESYS did not take the value (read back after writing)" % label)


def build_project(proj, report):
    try:
        app = proj.active_application
    except Exception:
        app = None
    if app is None:
        report.add("warning", "the project has no active application, so it was not built")
        return
    try:
        app.build()
    except Exception as e:
        report.add("error", "the build did not run: %s" % e)
        return
    errors = warnings = 0
    for cat in system.get_message_categories():
        for m in system.get_message_objects(cat):
            sev = str(m.severity)
            if sev in ("Error", "FatalError"):
                errors += 1
                report.add("error", "build: %s" % m.text)
            elif sev == "Warning":
                warnings += 1
                report.add("warning", "build: %s" % m.text)
    report.add("built", "%d error%s, %d warning%s" % (errors, "" if errors == 1 else "s",
                                                      warnings, "" if warnings == 1 else "s"))


def open_project(plan, base, report):
    """(project, opened here)."""
    proj = projects.primary
    if proj is not None:
        report.add("project", "the project open in CODESYS (not saved by the script)")
        return proj, False
    if plan.get("project"):
        path = plan["project"]
        if not os.path.isabs(path):
            path = os.path.join(base, path)
        if not os.path.isfile(path):
            raise Stop("the project %s does not exist" % path)
        try:
            proj = projects.open(path)
        except Exception as e:
            if "in use" not in str(e):
                raise
            raise Stop("the project %s is open in CODESYS (%s); close it there first" % (path, str(e).strip()))
        report.add("project", "opened %s" % path)
        return proj, True
    create = plan.get("create")
    if create:
        path = create["path"]
        proj = projects.create(path, True)
        dev = create["device"]
        proj.add(create.get("name") or "PLC", dev["type"], dev["id"], dev["version"])
        report.add("project", "created %s with device %s %s %s" % (path, dev["type"], dev["id"], dev["version"]))
        return proj, True
    raise Stop("open a project in CODESYS first (or name one in %s)" % PLAN_NAME)


def run(base):
    report = Report()
    proj = None
    opened = False
    try:
        with io.open(os.path.join(base, PLAN_NAME), encoding="utf-8") as f:
            plan = json.load(f)
        if plan.get("format") != FORMAT:
            raise Stop("%s is format %s; this script reads format %d" % (PLAN_NAME, plan.get("format"), FORMAT))
        report.add("plan", "%s from %s (%s)" % (PLAN_NAME, plan.get("config"), plan.get("tool")))
        try:
            from System import Guid
            guid = Guid(EDS_CONVERTER)
        except ImportError:
            guid = EDS_CONVERTER
        proj, opened = open_project(plan, base, report)
        plc = choose_plc(proj, plan, report)
        for net in plan["networks"]:
            try:
                warn_other_devices(proj, plc, net, report)
                build_network(proj, plc, net, base, device_repository, guid, report)
            except Stop as e:
                report.add("error", str(e))
        for n in plan.get("notes") or []:
            report.add("not set", "%s: %s: %s" % (n["where"], n["setting"], n["note"]))
        build_project(proj, report)
        if opened:
            if report.errors:
                report.add("project", "not saved because of the errors above")
            else:
                proj.save()
                report.add("project", "saved")
    except Stop as e:
        report.add("error", str(e))
    except Exception:
        report.add("error", "unexpected: " + traceback.format_exc())
    text = report.text()
    try:
        with io.open(os.path.join(base, REPORT_NAME), "w", encoding="utf-8") as f:
            f.write(text if isinstance(text, type(u"")) else text.decode("utf-8"))
    except Exception as e:
        print("cannot write %s: %s" % (REPORT_NAME, e))
    for line in text.splitlines():
        print(line)
    if opened and proj is not None:
        try:
            proj.close()
        except Exception:
            pass
    return report


if "projects" in globals():
    run(os.path.dirname(os.path.abspath(__file__)))
