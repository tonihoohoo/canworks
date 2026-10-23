# -*- coding: utf-8 -*-
"""Connects a CODESYS project to canworks-bridge as a Modbus TCP client.

Run it in CODESYS on the open project (Tools > Scripting > Execute Script
File...). It reads canworks-codesys-modbus.json next to itself (written by
canworks-deploy --export-plcopen --for codesys or the configurator's For
another PLC (PLCopen XML)), and writes import_report.txt next to itself:

1. finds the PLC as import_canworks.py does (named in the plan, else the
   active application's device, else the only device);
2. imports canworks.xml (the canworks list, canworks_in, canworks_out and
   the library) into the PLC's application, replacing what an earlier run
   imported;
3. adds an Ethernet adapter, a Modbus TCP Master and under it a Modbus TCP
   Slave canworks_bridge with the bridge's address, port and unit ID,
   reusing ones an earlier run added;
4. lists the slave's channels (read input registers, write multiple
   registers) mapped onto canworks.in_w and canworks.out_w;
5. puts canworks_in first and canworks_out last in the task that runs the
   application's programs.

What the script engine cannot set here goes into the report as 'by hand'.
It changes the open project and does not save it. It runs on CODESYS's
IronPython 2.7 and on CPython 3 (tests); it loads import_canworks.py from
the same folder for the PLC lookup and the build.
"""
from __future__ import print_function

import io
import json
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import import_canworks as common  # noqa: E402

PLAN_NAME = "canworks-codesys-modbus.json"
REPORT_NAME = "import_report.txt"
FORMAT = 1
SLAVE_NAME = "canworks_bridge"
# Device catalogue names (DeviceInfo Name) of CODESYS's standard devices.
ETHERNET_NAMES = ("ethernet",)
MASTER_NAMES = ("modbus tcp master", "modbustcp master", "modbus_tcp_master")
SLAVE_NAMES = ("modbus tcp slave", "modbustcp slave", "modbus_tcp_slave")

Stop = common.Stop


def _norm(text):
    return (u"%s" % text).replace("_", " ").replace("-", " ").strip().lower()


def _device_name(desc):
    for path in (("device_info", "name"), ("name",)):
        obj = desc
        try:
            for attr in path:
                obj = getattr(obj, attr)
            if obj:
                return u"%s" % obj
        except Exception:
            pass
    return u""


def find_description(repo, names):
    """The newest installed device description whose catalogue name is one
    of `names`, as its device identification, or None."""
    best = None
    for d in repo.get_all_devices():
        if _norm(_device_name(d)) in [_norm(n) for n in names]:
            i = d.device_id
            if best is None or common._version_key(i.version) > common._version_key(best.version):
                best = i
    return best


def _kind(obj, repo_names, names):
    """Whether a device object is one of `names`: by its name in the
    project tree, or by its identification's catalogue name."""
    if _norm(obj.get_name()) in [_norm(n) for n in names]:
        return True
    ident = common._ident(obj)
    return ident is not None and repo_names.get((ident.type, ident.id)) in [_norm(n) for n in names]


def child_device(parent, repo, repo_names, names, add_name, report, where):
    """The child device of `parent` that is one of `names`, or a new one."""
    for c in common._children(parent):
        if common._is_device(c) and _kind(c, repo_names, names):
            report.add("kept", "%s: %s" % (where, c.get_name()))
            return c
    ident = find_description(repo, names)
    if ident is None:
        raise Stop("%s: this CODESYS has no %s device installed" % (where, names[0]))
    dev = common._add(parent, add_name, ident.type, ident.id, ident.version)
    report.add("added", "%s: %s (%s %s %s)" % (where, dev.get_name(), ident.type, ident.id, ident.version))
    return dev


def _set_by_name(dev, words, value, report, where, what):
    """Sets the device parameter whose name holds all of `words`."""
    for p in common._params(dev):
        name = _norm(getattr(p, "name", "") or getattr(p, "description", ""))
        if all(w in name for w in words):
            try:
                p.value = value
                report.add("set", "%s: %s = %s" % (where, what, value))
                return True
            except Exception as e:
                report.add("by hand", "%s: set %s to %s (%s)" % (where, what, value, common._first_sentence(e)))
                return False
    report.add("by hand", "%s: set %s to %s" % (where, what, value))
    return False


def _application(proj, plc):
    try:
        app = proj.active_application
    except Exception:
        app = None
    if app is not None and any(common._same(a, plc) for a in common._ancestors(proj, app) + [app]):
        return app
    for c in common._children(plc, True):
        try:
            if c.is_application:
                return c
        except Exception:
            pass
    return app


class _Reporter(object):
    """CODESYS's import reporter: replace what an earlier run imported."""

    def __init__(self, report):
        self.report = report
        self.count = 0

    def error(self, *args):
        self.report.add("error", "import: %s" % args[-1])

    def warning(self, *args):
        self.report.add("warning", "import: %s" % args[-1])

    def resolve_conflict(self, obj):
        try:
            return ConflictResolve.Replace  # noqa: F821 (CODESYS script engine)
        except NameError:
            return "replace"

    def added(self, obj):
        self.count += 1

    def replaced(self, obj):
        self.count += 1

    def skipped(self, obj):
        self.report.add("warning", "import: skipped %s" % obj)

    @property
    def aborting(self):
        return False


def import_xml(app, path, report):
    reporter = _Reporter(report)
    try:
        app.import_xml(reporter, path)
    except Exception as e:
        raise Stop("CODESYS could not import %s: %s" % (os.path.basename(path), common._first_sentence(e)))
    report.add("imported", "%s into %s (%d objects)" % (os.path.basename(path), app.get_name()
                                                         if hasattr(app, "get_name") else "the application",
                                                         reporter.count))


def connect(proj, plc, plan, repo, report):
    """Ethernet, Modbus TCP Master and the bridge's slave with its channels."""
    names = {}
    for d in repo.get_all_devices():
        names[(d.device_id.type, d.device_id.id)] = _norm(_device_name(d))
    eth = None
    if plan.get("ethernet"):
        found = [c for c in common._children(plc, True) if c.get_name() == plan["ethernet"]]
        if not found:
            raise Stop("no object named %s under %s" % (plan["ethernet"], plc.get_name()))
        eth = found[0]
        report.add("kept", "Ethernet: %s (named in %s)" % (eth.get_name(), PLAN_NAME))
    else:
        eth = child_device(plc, repo, names, ETHERNET_NAMES, "Ethernet", report, "Ethernet")
        report.add("by hand", "Ethernet: pick the PLC's network interface in %s's settings when it has none"
                   % eth.get_name())
    master = child_device(eth, repo, names, MASTER_NAMES, "Modbus_TCP_Master", report, "Modbus TCP Master")
    slave = None
    for c in common._children(master):
        if c.get_name() == SLAVE_NAME:
            slave = c
            report.add("kept", "Modbus TCP Slave: %s" % SLAVE_NAME)
    if slave is None:
        ident = find_description(repo, SLAVE_NAMES)
        if ident is None:
            raise Stop("Modbus TCP Slave: this CODESYS has no Modbus TCP Slave device installed")
        slave = common._add(master, SLAVE_NAME, ident.type, ident.id, ident.version)
        report.add("added", "Modbus TCP Slave: %s" % slave.get_name())
    b = plan["bridge"]
    where = "Modbus TCP Slave %s" % slave.get_name()
    _set_by_name(slave, ("ip",), b["host"], report, where, "IP address")
    _set_by_name(slave, ("port",), str(b["port"]), report, where, "port")
    _set_by_name(slave, ("unit",), str(b["unit_id"]), report, where, "unit ID")
    for ch in plan["channels"]:
        last = ch["start"] + ch["count"] - 1
        what = ("Read Input Registers (function 4)" if ch["function"] == 4 else
                "Write Multiple Registers (function 16)")
        report.add("by hand", "%s: channel %s, cyclic every %d ms, offset %d, length %d, mapped to %s[%d..%d]"
                   % (where, what, plan["cycle_ms"], ch["start"], ch["count"], ch["variable"], ch["start"], last))
    return slave


def _task_pous(task):
    try:
        return task.pous
    except Exception:
        return None


def order_tasks(proj, plc, plan, report):
    """canworks_in first and canworks_out last in the task with the
    application's programs (the only task, or the one calling PLC_PRG)."""
    first, last = plan["programs"]["first"], plan["programs"]["last"]
    tasks = []
    for c in common._children(plc, True):
        if _task_pous(c) is not None:
            tasks.append(c)
    if not tasks:
        report.add("by hand", "task: add %s as the first and %s as the last call of the task that runs your "
                   "program" % (first, last))
        return
    if len(tasks) > 1:
        main = [t for t in tasks if any(u"%s" % getattr(p, "name", p) == "PLC_PRG" for p in _task_pous(t))]
        if len(main) != 1:
            report.add("by hand", "task: %d tasks (%s): add %s as the first and %s as the last call of the one "
                       "that runs your program" % (len(tasks), ", ".join(t.get_name() for t in tasks), first, last))
            return
        tasks = main
    task = tasks[0]
    pous = _task_pous(task)
    try:
        names = [u"%s" % getattr(p, "name", p) for p in pous]
        for n in (first, last):
            if n in names:
                pous.remove(pous[names.index(n)])
                names.remove(n)
        pous.insert(0, first)
        pous.add(last)
        report.add("set", "task %s: %s" % (task.get_name(), ", ".join([first] + names + [last])))
    except Exception as e:
        report.add("by hand", "task %s: add %s as the first and %s as the last call (%s)"
                   % (task.get_name(), first, last, common._first_sentence(e)))


def run(base, engine):
    for name in ("projects", "device_repository", "system"):
        if name in engine:
            setattr(common, name, engine[name])
    report = common.Report()
    try:
        with io.open(os.path.join(base, PLAN_NAME), encoding="utf-8") as f:
            plan = json.load(f)
        if plan.get("format") != FORMAT:
            raise Stop("%s is format %s; this script reads format %d" % (PLAN_NAME, plan.get("format"), FORMAT))
        report.add("plan", "%s from %s (%s), map hash %s" % (PLAN_NAME, plan.get("config"), plan.get("tool"),
                                                             plan.get("map_hash")))
        proj = engine["projects"].primary
        if proj is None:
            raise Stop("open the PLC project in CODESYS first")
        plc = common.choose_plc(proj, plan, report, PLAN_NAME)
        app = _application(proj, plc)
        if app is None:
            raise Stop("device %s has no application to import into" % plc.get_name())
        import_xml(app, os.path.join(base, plan["xml"]), report)
        try:
            connect(proj, plc, plan, engine["device_repository"], report)
        except Stop as e:
            report.add("error", str(e))
        order_tasks(proj, plc, plan, report)
        common.build_project(proj, report)
        report.add("project", "the project open in CODESYS (not saved by the script)")
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
    return report


if "projects" in globals():
    run(HERE, globals())
