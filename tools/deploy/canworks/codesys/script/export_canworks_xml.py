# -*- coding: utf-8 -*-
"""Exports a CODESYS project's CANopen networks as PLCopenXML for canworks'
Import from CODESYS (codesys-import spec).

Headless:

  CODESYS.exe --profile="<profile>" --noUI --runscript="<folder>\\export_canworks_xml.py"

It reads canworks-export.json next to itself ({"project": path, "device":
name or null}), opens the project, writes devices.json (every device that
has a CANopen Manager, with its buses and node count, and which one holds
the active application) and, when the device is named or is the only one,
exports it to canworks-export.xml. It never saves the project. It writes
export_report.txt next to itself.

It runs on CODESYS's IronPython 2.7 and on CPython 3 (tests).
"""
from __future__ import print_function

import io
import json
import os
import traceback

JOB_NAME = "canworks-export.json"
DEVICES_NAME = "devices.json"
XML_NAME = "canworks-export.xml"
REPORT_NAME = "export_report.txt"
CANBUS_TYPE, MANAGER_TYPE, REMOTE_TYPE = 15, 16, 18


def _children(obj, recursive=False):
    try:
        return list(obj.get_children(recursive))
    except TypeError:
        return list(obj.get_children())


def _type(obj):
    try:
        return obj.get_device_identification().type
    except Exception:
        return None


def _is_device(obj):
    try:
        return bool(obj.is_device)
    except Exception:
        return False


def _parent(obj):
    try:
        return obj.parent
    except Exception:
        return None


def _same(a, b):
    try:
        return a.guid == b.guid
    except Exception:
        return a is b


def active_top(proj):
    """The top-level device holding the active application, or None."""
    try:
        obj = proj.active_application
    except Exception:
        return None
    last = None
    seen = 0
    while obj is not None and not _same(obj, proj) and seen < 64:
        last = obj
        obj = _parent(obj)
        seen += 1
    return last if last is not None and _is_device(last) else None


def devices(proj):
    """[(top-level device, [CANbus names], node count)] of the devices that
    have a CANopen Manager."""
    out = []
    for top in [c for c in _children(proj) if _is_device(c)]:
        buses, nodes = [], 0
        for c in _children(top, True):
            if _type(c) == MANAGER_TYPE:
                bus = _parent(c)
                buses.append(bus.get_name() if bus is not None else c.get_name())
                nodes += len([n for n in _children(c) if _type(n) == REMOTE_TYPE])
        if buses:
            out.append((top, buses, nodes))
    return out


def run(base):
    lines = []
    ok = False
    proj = None
    opened = False
    try:
        with io.open(os.path.join(base, JOB_NAME), encoding="utf-8") as f:
            job = json.load(f)
        proj = projects.primary
        if proj is None:
            try:
                proj = projects.open(job["project"])
                opened = True
            except Exception as e:
                if "in use" in str(e):
                    raise Exception("in use: %s" % str(e).strip())
                raise
        found = devices(proj)
        active = active_top(proj)
        listing = [{"name": d.get_name(), "buses": b, "nodes": n,
                    "active": active is not None and _same(d, active)} for d, b, n in found]
        with io.open(os.path.join(base, DEVICES_NAME), "w", encoding="utf-8") as f:
            f.write(u"%s" % json.dumps(listing, indent=1))
        chosen = None
        if job.get("device"):
            chosen = [d for d, _, _ in found if d.get_name() == job["device"]]
            if not chosen:
                raise Exception("no device %s with a CANopen Manager in the project (devices: %s)"
                                % (job["device"], ", ".join(x["name"] for x in listing) or "none"))
            chosen = chosen[0]
        elif len(found) == 1:
            chosen = found[0][0]
        if chosen is not None:
            proj.export_xml([chosen], os.path.join(base, XML_NAME), True)
            lines.append("exported %s" % chosen.get_name())
        else:
            lines.append("devices listed: %d" % len(found))
        ok = True
    except Exception as e:
        lines.append("error: %s" % (e if "in use" in str(e) or "no device" in str(e) else traceback.format_exc()))
    if opened and proj is not None:
        try:
            proj.close()
        except Exception:
            pass
    text = u"\n".join([u"result: %s" % ("ok" if ok else "error")] + [u"%s" % x for x in lines]) + u"\n"
    with io.open(os.path.join(base, REPORT_NAME), "w", encoding="utf-8") as f:
        f.write(text)
    print(text)


if "projects" in globals():
    run(os.path.dirname(os.path.abspath(__file__)))
