"""canworks-diag sim: live control of simulated devices
(docs/simulator.md, "Control subcommands"), in the plugin with --runtime or
in a standalone canworks-sim with --sim HOST[:PORT] (default: the
local simulator, 127.0.0.1:7532).

  canworks-diag sim status --runtime plc.local
  canworks-diag sim fault 5 emcy 0x5000 --register 1 --runtime plc.local
  canworks-diag sim test --sim 127.0.0.1 --scenario alarm --junit results.xml
"""

import argparse
import json
import re
import time
import xml.etree.ElementTree as ET

from . import diag, simclient
from .diag import DiagError

SCENARIO_DONE = ("passed", "failed", "stopped")
POLL_S = 0.2
CLEAR_KINDS = ("all", "emcy", "heartbeat", "power", "sdo-abort", "sdo-delay", "refuse-write-operational",
               "tpdo-stop", "identity", "device-type", "drive-input")
DRIVE_INPUTS = ("blocked", "positive_limit", "negative_limit", "home_switch")
IDENTITY_KEYS = ("vendor_id", "product_code", "revision_number", "serial_number")


# ---------------------------------------------------------------------------
# Argument types


def device(text):
    """A node ID (1-127) or an extra device's name."""
    t = str(text).strip()
    if re.match(r"^[0-9]+$", t) or t.lower().startswith("0x"):
        try:
            v = int(t, 0)
        except ValueError:
            raise argparse.ArgumentTypeError("node %r is not a number" % text)
        if not 1 <= v <= 127:
            raise argparse.ArgumentTypeError("node ID must be 1-127")
        return v
    if re.match(r"^[A-Za-z][A-Za-z0-9_-]{0,31}$", t):
        return t
    raise argparse.ArgumentTypeError("%r is not a node ID or a device name" % text)


def obj(text):
    """An object as the protocol writes it, "0xIIII:S"."""
    try:
        return simclient.object_key(*simclient.parse_object(text))
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e))


def value(text):
    """A number (decimal, 0x hex, float; true/false as 1/0), else the text."""
    t = str(text).strip()
    if t.lower() in ("true", "false"):
        return 1 if t.lower() == "true" else 0
    try:
        return int(t, 0)
    except ValueError:
        pass
    if re.match(r"^[+-]?[0-9]+$", t):
        return int(t, 10)  # "010": int(t, 0) refuses leading zeros
    try:
        return float(t)
    except ValueError:
        return text


def _u32(what):
    def parse(text):
        try:
            v = int(str(text), 0)
        except ValueError:
            raise argparse.ArgumentTypeError("%s %r is not a number" % (what, text))
        if not 0 <= v <= 0xFFFFFFFF:
            raise argparse.ArgumentTypeError("%s %r is out of range" % (what, text))
        return v
    return parse


def _positive(what, top):
    def parse(text):
        try:
            v = int(str(text), 0)
        except ValueError:
            raise argparse.ArgumentTypeError("%s %r is not a number" % (what, text))
        if not 1 <= v <= top:
            raise argparse.ArgumentTypeError("%s must be 1-%d" % (what, top))
        return v
    return parse


def _msef(text):
    t = "".join(str(text).split())
    if t.lower().startswith("0x"):
        t = t[2:]
    if not re.match(r"^[0-9A-Fa-f]{10}$", t):
        raise argparse.ArgumentTypeError("--msef %r: give 5 bytes as 10 hex digits, e.g. 0100000000" % text)
    return t.upper()


def _source(text):
    if text.strip().lower() in ("none", "null"):
        return None
    try:
        v = json.loads(text)
    except ValueError as e:
        raise argparse.ArgumentTypeError("source %r is not JSON: %s" % (text, e))
    if not isinstance(v, dict):
        raise argparse.ArgumentTypeError("a source is a JSON object such as '{\"sine\": {...}}', or none")
    return v


def _json_object(text):
    try:
        v = json.loads(text)
    except ValueError as e:
        raise argparse.ArgumentTypeError("%r is not JSON: %s" % (text, e))
    if not isinstance(v, dict):
        raise argparse.ArgumentTypeError("a fault is a JSON object with one key, such as '{\"heartbeat\": \"stop\"}'")
    return v


# ---------------------------------------------------------------------------
# Parser


def _common():
    """Connection options that may also come after the subcommand; they keep
    what the main parser read when left out here."""
    c = argparse.ArgumentParser(add_help=False)
    s = argparse.SUPPRESS
    c.add_argument("--runtime", default=s, metavar="HOST[:PORT]", help="the plugin's simulated devices")
    c.add_argument("--sim", dest="sim_addr", default=s, metavar="HOST[:PORT]",
                   help="a standalone simulator (default 127.0.0.1:%d)" % simclient.SIM_PORT)
    c.add_argument("--network", default=s, metavar="NAME",
                   help="with --runtime: the network whose simulated devices to talk to (needed when the "
                        "runtime runs several)")
    c.add_argument("--token", default=s, help="access token")
    c.add_argument("--token-file", default=s, metavar="FILE", help="read the access token from this file")
    c.add_argument("--json", action="store_true", default=s, help="print the answer as JSON")
    return c


def _bool_flags(p, names):
    """--NAME and --no-NAME for each boolean drive input."""
    for name in names:
        flag = name.replace("_", "-")
        p.add_argument("--" + flag, dest=name, action="store_const", const=True, default=None,
                       help="set %s" % flag)
        p.add_argument("--no-" + flag, dest=name, action="store_const", const=False, help="clear %s" % flag)


def add_parser(sub):
    common = _common()
    s = sub.add_parser("sim", parents=[common], help="control simulated devices (see docs/simulator.md)",
                       description="Live control of simulated devices: the plugin's (--runtime HOST) or a "
                                   "standalone canworks-sim's (--sim HOST[:PORT], default 127.0.0.1:%d)."
                                   % simclient.SIM_PORT)
    ss = s.add_subparsers(dest="sim_command", metavar="SIMCOMMAND")
    ss.required = True

    def add(name, help_text, **kw):
        return ss.add_parser(name, parents=[common], help=help_text, **kw)

    add("status", "the simulated devices and scenarios")
    g = add("get", "read objects of a simulated device")
    g.add_argument("node", type=device)
    g.add_argument("objects", nargs="*", type=obj, metavar="OBJ", help="0xIIII:S")
    g.add_argument("--pdo", action="store_true", help="every object in the device's active PDOs")
    for name, text in (("set", "set a value once (a value source moves it again)"),
                       ("override", "hold a value until it is released")):
        q = add(name, text)
        q.add_argument("node", type=device)
        q.add_argument("object", type=obj, metavar="OBJ")
        q.add_argument("value", type=value)
    r = add("release", "end overrides (all of the device's without OBJ)")
    r.add_argument("node", type=device)
    r.add_argument("objects", nargs="*", type=obj, metavar="OBJ")
    so = add("source", "give an object a value source, or remove it with none")
    so.add_argument("node", type=device)
    so.add_argument("object", type=obj, metavar="OBJ")
    so.add_argument("source", type=_source, metavar="JSON|none")

    f = add("fault", "inject a fault")
    f.add_argument("node", type=device)
    fk = f.add_subparsers(dest="fault_kind", metavar="KIND")
    fk.required = True

    def kind(name, text):
        return fk.add_parser(name, parents=[common], help=text)

    k = kind("emcy", "send an EMCY (again every --period-ms)")
    k.add_argument("code", type=_u32("EMCY code"))
    k.add_argument("--register", type=_u32("error register"), help="error register (default 0)")
    k.add_argument("--msef", type=_msef, help="manufacturer-specific bytes, 5 bytes as hex")
    k.add_argument("--period-ms", type=_positive("--period-ms", 3600000), help="send it again every N ms")
    kind("heartbeat-stop", "stop the heartbeat (the device goes on working)")
    k = kind("power", "power the device off, on, or off and on again")
    k.add_argument("state", choices=("off", "on", "cycle"))
    k.add_argument("--off-ms", type=_positive("--off-ms", 3600000), help="cycle: how long it stays off")
    k = kind("reset", "the device resets itself")
    k.add_argument("what", choices=("node", "comm"))
    k = kind("nmt", "the device changes its NMT state by itself")
    k.add_argument("state", choices=("stopped", "preop", "operational"))
    k = kind("sdo-abort", "abort SDO transfers of an object")
    k.add_argument("object", type=obj, metavar="OBJ")
    k.add_argument("code", type=_u32("abort code"))
    k.add_argument("--on", choices=("read", "write", "both"), help="which transfers (default both)")
    k.add_argument("--count", type=_positive("--count", 0x7FFFFFFF), help="only the next N (default: until cleared)")
    k = kind("sdo-delay", "answer SDO requests later")
    k.add_argument("ms", type=_positive("delay", 60000))
    k.add_argument("--object", type=obj, metavar="OBJ", help="only this object")
    kind("refuse-write-operational", "abort writes while OPERATIONAL")
    k = kind("tpdo-stop", "stop sending a TPDO")
    k.add_argument("number", type=_positive("TPDO number", 512))
    k = kind("identity", "0x1018 reads these values")
    for key in IDENTITY_KEYS:
        k.add_argument("--" + key.replace("_", "-"), dest=key, type=_u32(key.replace("_", " ")))
    k = kind("device-type", "0x1000 reads this value")
    k.add_argument("value", type=_u32("device type"))
    kind("forget-node-id", "the device loses its node ID and waits for LSS")
    k = kind("drive-input", "inputs of the CiA 402 drive model")
    _bool_flags(k, DRIVE_INPUTS)
    k = kind("json", "a fault in its JSON form")
    k.add_argument("fault", type=_json_object, metavar="JSON")

    c = add("clear", "clear a fault (all: every fault, and power on)")
    c.add_argument("node", type=device)
    c.add_argument("kind", choices=CLEAR_KINDS + tuple(k.replace("-", "_") for k in CLEAR_KINDS if "-" in k),
                   metavar="KIND", help=", ".join(CLEAR_KINDS))
    c.add_argument("--object", type=obj, metavar="OBJ", help="sdo-abort: only this object's rule")
    c.add_argument("--tpdo", type=_positive("TPDO number", 512), help="tpdo-stop: only this TPDO")

    sc = add("scenario", "list, start or stop scenarios")
    sca = sc.add_subparsers(dest="scenario_command", metavar="list|start|stop")
    sca.required = True
    sca.add_parser("list", parents=[common], help="the scenarios and their state")
    for name in ("start", "stop"):
        q = sca.add_parser(name, parents=[common], help="%s a scenario" % name)
        q.add_argument("name")

    t = add("test", "run scenarios as tests and report the result",
            description="Starts the scenarios one after another (--parallel: together), waits until each "
                        "passed or failed, prints one line per scenario and exits 0 when all passed, 1 when one "
                        "failed, 2 on a usage or connection error.")
    t.add_argument("--scenario", action="append", default=[], metavar="NAME", help="a scenario to run (repeatable)")
    t.add_argument("--all", action="store_true", help="every scenario the simulation has")
    t.add_argument("--parallel", action="store_true", help="run the scenarios at the same time")
    t.add_argument("--timeout", dest="test_timeout", type=float, default=300.0, metavar="S",
                   help="stop after S seconds in all (default %(default)s)")
    t.add_argument("--junit", metavar="FILE", help="write a JUnit XML report")
    return s


# ---------------------------------------------------------------------------
# Faults


def fault_object(args):
    """The JSON fault of `fault NODE KIND ...` (docs/simulator.md, Faults)."""
    k = args.fault_kind
    if k == "emcy":
        f = {"code": args.code}
        if args.register is not None:
            if args.register > 0xFF:
                raise DiagError("usage", "--register must be 0-255")
            f["register"] = args.register
        if args.msef is not None:
            f["msef"] = args.msef
        if args.period_ms is not None:
            if args.period_ms < 10:
                raise DiagError("usage", "--period-ms must be at least 10")
            f["period_ms"] = args.period_ms
        return {"emcy": f}
    if k == "heartbeat-stop":
        return {"heartbeat": "stop"}
    if k == "power":
        f = {"power": args.state}
        if args.off_ms is not None:
            if args.state != "cycle":
                raise DiagError("usage", "--off-ms goes with power cycle")
            f["off_ms"] = args.off_ms
        return f
    if k == "reset":
        return {"reset": args.what}
    if k == "nmt":
        return {"nmt_state": args.state}
    if k == "sdo-abort":
        f = {"object": args.object, "code": args.code}
        if args.on:
            f["on"] = args.on
        if args.count is not None:
            f["count"] = args.count
        return {"sdo_abort": f}
    if k == "sdo-delay":
        f = {"ms": args.ms}
        if args.object:
            f["object"] = args.object
        return {"sdo_delay": f}
    if k == "refuse-write-operational":
        return {"refuse_write_operational": True}
    if k == "tpdo-stop":
        return {"tpdo_stop": args.number}
    if k == "identity":
        f = {key: getattr(args, key) for key in IDENTITY_KEYS if getattr(args, key) is not None}
        if not f:
            raise DiagError("usage", "identity: give at least one of --vendor-id, --product-code, "
                                     "--revision-number, --serial-number")
        return {"identity": f}
    if k == "device-type":
        return {"device_type": args.value}
    if k == "forget-node-id":
        return {"forget_node_id": True}
    if k == "drive-input":
        f = {key: getattr(args, key) for key in DRIVE_INPUTS if getattr(args, key) is not None}
        if not f:
            raise DiagError("usage", "drive-input: give at least one of --blocked, --positive-limit, "
                                     "--negative-limit, --home-switch (or their --no- forms)")
        return {"drive_input": f}
    return args.fault  # json


def fault_text(f):
    """A fault object in one line, the way the command line writes it."""
    if not isinstance(f, dict) or len(f) == 0:
        return str(f)
    key = next(k for k in f if k != "off_ms")
    v = f[key]
    name = key.replace("_", "-")
    if key == "emcy" and isinstance(v, dict):
        code = v.get("code")
        text = "emcy %s" % ("0x%04X" % code if isinstance(code, int) else code)
        for k2 in ("register", "msef", "period_ms"):
            if k2 in v:
                text += " %s %s" % (k2.replace("_", "-"), v[k2])
        return text
    if key == "power":
        return "power %s" % v + (" off-ms %s" % f["off_ms"] if "off_ms" in f else "")
    if key == "heartbeat":
        return "heartbeat-stop"
    if v is True:
        return name
    if isinstance(v, dict):
        return "%s %s" % (name, " ".join("%s=%s" % (a, b) for a, b in v.items()))
    return "%s %s" % (name, v)


# ---------------------------------------------------------------------------
# Output


def _names(v):
    """Faults/sources/overrides as the protocol gives them (list or object) in
    one short text."""
    if not v:
        return "-"
    if isinstance(v, dict):
        return ", ".join("%s=%s" % (k, x) if not isinstance(x, (dict, list)) else
                         "%s %s" % (k, next(iter(x), "") if isinstance(x, dict) else "")
                         for k, x in v.items())
    if isinstance(v, list):
        out = []
        for x in v:
            if isinstance(x, dict) and "object" in x and len(x) <= 3:
                out.append(str(x["object"]))
            elif isinstance(x, dict):
                out.append(fault_text(x))
            else:
                out.append(str(x))
        return ", ".join(out)
    return str(v)


def print_status(st, out):
    if st.get("simulated_network"):
        out.write("simulated network: no CAN interface is used\n")
    elif st.get("interface"):
        out.write("interface %s\n" % st["interface"])
    rows = [("NODE", "NAME", "PROFILE", "POWER", "NMT", "FAULTS", "SOURCES", "OVERRIDES")]
    for d in st.get("devices") or []:
        node = d.get("node")
        rows.append((str(node if node else "-"), d.get("name") or "", str(d.get("profile") or "-"),
                     str(d.get("power") or "-"),
                     "conflict: %s" % d["conflict"] if d.get("conflict") else str(d.get("nmt") or "-"),
                     _names(d.get("faults")), _names(d.get("sources")), _names(d.get("overrides"))))
    if len(rows) == 1:
        out.write("no simulated devices\n")
    else:
        widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]) - 1)]
        for r in rows:
            out.write("  ".join(c.ljust(w) for c, w in zip(r, widths)) + "  " + r[-1] + "\n")
    print_scenarios(st.get("scenarios") or [], out, header=True)


def scenario_line(s):
    line = "%-24s %s" % (s.get("name"), s.get("state"))
    if s.get("state") == "running" and s.get("step") is not None:
        line += ", step %s" % s.get("step")
    if s.get("message"):
        line += ": %s" % s["message"]
    return line


def print_scenarios(scenarios, out, header=False):
    if header and scenarios:
        out.write("scenarios:\n")
    for s in scenarios:
        out.write(("  " if header else "") + scenario_line(s) + "\n")
    if not scenarios and not header:
        out.write("the simulation has no scenarios\n")


def _value_text(v):
    if isinstance(v, float) and v.is_integer():
        return repr(v)
    return json.dumps(v) if isinstance(v, str) else str(v)


def print_values(values, out):
    for v in values:
        where = "node %s %s" % (v.get("node"), v.get("object"))
        if "error" in v:
            out.write("%s: %s\n" % (where, v["error"]))
        else:
            out.write("%s = %s%s\n" % (where, _value_text(v.get("value")),
                                       " (%s)" % v["type"] if v.get("type") else ""))


# ---------------------------------------------------------------------------
# Running


def connect(args):
    """A connected SimClient for --runtime or --sim (default: the local
    standalone simulator)."""
    runtime = getattr(args, "runtime", None)
    sim_addr = getattr(args, "sim_addr", None)
    if runtime and sim_addr:
        raise DiagError("usage", "give --runtime or --sim, not both")
    timeout = getattr(args, "timeout", 5.0)
    try:
        if runtime:
            host, port = diag.parse_runtime(runtime)
            return simclient.SimClient.for_runtime(host, port, diag._token(args), timeout,
                                                   network=getattr(args, "network", None))
        host, port = simclient.parse_sim(sim_addr) if sim_addr else ("127.0.0.1", simclient.SIM_PORT)
    except ValueError as e:
        raise DiagError("usage", str(e))
    token = getattr(args, "token", None) or diag._token_file(args) or ""
    try:
        return simclient.SimClient.for_simulator(host, port, token, timeout)
    except DiagError as e:
        if e.kind == "closed":
            raise DiagError("closed", "no simulator listens on %s:%d (start canworks-sim, or give --sim "
                                      "HOST[:PORT] or --runtime HOST)" % (host, port))
        raise


def run(args, out):
    client = connect(args)
    try:
        return _run(client, args, out)
    finally:
        client.close()


def _done(args, out, res, text):
    if args.json:
        out.write(json.dumps(res, indent=2) + "\n")
    else:
        out.write(text + "\n")


def _run(client, args, out):
    cmd = args.sim_command
    node = getattr(args, "node", None)
    if cmd == "status":
        res = client.status()
        if args.json:
            out.write(json.dumps(res, indent=2) + "\n")
        else:
            print_status(res, out)
        return 0
    if cmd == "get":
        if args.pdo and args.objects:
            raise DiagError("usage", "give objects or --pdo, not both")
        if not args.pdo and not args.objects:
            raise DiagError("usage", "give the objects to read (0xIIII:S), or --pdo")
        values = client.get_pdo(node) if args.pdo else client.get([(node, o) for o in args.objects])
        if args.json:
            out.write(json.dumps({"values": values}, indent=2) + "\n")
        else:
            print_values(values, out)
        failed = [v for v in values if "error" in v]
        if failed and len(failed) == len(values):
            raise DiagError("refused", "no object could be read")
        return 0
    if cmd in ("set", "override"):
        res = (client.set if cmd == "set" else client.override)(node, {args.object: args.value})
        _done(args, out, res, "node %s %s %s %s" % (node, args.object, "set to" if cmd == "set" else "held at",
                                                    _value_text(args.value)))
        return 0
    if cmd == "release":
        objects = args.objects or "all"
        res = client.release(node, objects)
        _done(args, out, res, "node %s: %s released" % (node, "all overrides" if objects == "all"
                                                         else ", ".join(objects)))
        return 0
    if cmd == "source":
        res = client.source(node, args.object, args.source)
        _done(args, out, res, "node %s %s: %s" % (node, args.object, "value source removed" if args.source is None
                                                  else "value source " + json.dumps(args.source)))
        return 0
    if cmd == "fault":
        f = fault_object(args)
        res = client.fault(node, f)
        _done(args, out, res, "node %s: fault %s" % (node, fault_text(f)))
        return 0
    if cmd == "clear":
        kind = args.kind.replace("-", "_")
        if args.object and kind != "sdo_abort" and kind != "sdo_delay":
            raise DiagError("usage", "--object goes with sdo-abort")
        if args.tpdo is not None and kind != "tpdo_stop":
            raise DiagError("usage", "--tpdo goes with tpdo-stop")
        res = client.clear(node, kind, args.object, args.tpdo)
        what = args.kind.replace("_", "-")
        if args.object:
            what += " " + args.object
        if args.tpdo is not None:
            what += " %d" % args.tpdo
        _done(args, out, res, "node %s: %s cleared" % (node, "every fault" if kind == "all" else what))
        return 0
    if cmd == "scenario":
        sub = args.scenario_command
        if sub == "list":
            scenarios = client.scenarios()
            if args.json:
                out.write(json.dumps({"scenarios": scenarios}, indent=2) + "\n")
            else:
                print_scenarios(scenarios, out)
            return 0
        res = client.start_scenario(args.name) if sub == "start" else client.stop_scenario(args.name)
        _done(args, out, res, "scenario %s %s" % (args.name, "started" if sub == "start" else "stopped"))
        return 0
    if cmd == "test":
        return run_tests(client, args, out)
    raise DiagError("usage", "unknown sim command %s" % cmd)


class TestResult:
    def __init__(self, name):
        self.name = name
        self.state = "not run"
        self.message = ""
        self.seconds = 0.0

    @property
    def passed(self):
        return self.state == "passed"

    def to_json(self):
        return {"name": self.name, "state": self.state, "message": self.message, "seconds": round(self.seconds, 3)}


def run_tests(client, args, out, poll_s=None, clock=time.monotonic, sleep=time.sleep):
    """`sim test`: 0 every scenario passed, 1 one did not (a DiagError for
    usage and connection problems)."""
    poll_s = POLL_S if poll_s is None else poll_s
    listed = client.scenarios()
    names = [s.get("name") for s in listed]
    if args.all and args.scenario:
        raise DiagError("usage", "give --scenario NAME or --all, not both")
    if args.all:
        wanted = names
    else:
        wanted = list(dict.fromkeys(args.scenario))
    if not wanted:
        raise DiagError("usage", "give the scenarios to run with --scenario NAME (repeatable), or --all"
                        if names or not args.all else "the simulation has no scenarios")
    unknown = [n for n in wanted if n not in names]
    if unknown:
        raise DiagError("usage", "no scenario %s; the simulation has: %s" % (
            ", ".join(unknown), ", ".join(names) or "none"))
    results = [TestResult(n) for n in wanted]
    deadline = clock() + args.test_timeout
    groups = [results] if args.parallel else [[r] for r in results]
    timed_out = False
    for group in groups:
        if timed_out:
            break
        started = clock()
        for r in group:
            client.start_scenario(r.name)
            r.state = "running"
        pending = list(group)
        while pending:
            by_name = {s.get("name"): s for s in client.scenarios()}
            now = clock()
            for r in list(pending):
                s = by_name.get(r.name) or {}
                if s.get("state") in SCENARIO_DONE:
                    r.state, r.message, r.seconds = s["state"], s.get("message") or "", now - started
                    pending.remove(r)
                    if not args.json:
                        out.write(_test_line(r) + "\n")
            if not pending:
                break
            if now >= deadline:
                for r in pending:
                    try:
                        client.stop_scenario(r.name)
                    except DiagError:
                        pass
                    r.state, r.seconds = "timeout", now - started
                    r.message = "still running after --timeout %g s" % args.test_timeout
                    if not args.json:
                        out.write(_test_line(r) + "\n")
                timed_out = True
                break
            sleep(poll_s)
    for r in results:
        if r.state == "not run" and not args.json:
            out.write(_test_line(r) + "\n")
    passed = sum(1 for r in results if r.passed)
    if args.json:
        out.write(json.dumps({"passed": passed, "total": len(results),
                              "scenarios": [r.to_json() for r in results]}, indent=2) + "\n")
    else:
        out.write("%d of %d scenario%s passed\n" % (passed, len(results), "" if len(results) == 1 else "s"))
    if args.junit:
        write_junit(results, args.junit)
    return 0 if passed == len(results) else 1


def _test_line(r):
    word = {"passed": "PASS", "failed": "FAIL", "stopped": "STOPPED", "timeout": "TIMEOUT"}.get(r.state, "NOT RUN")
    line = "%-7s %s" % (word, r.name)
    if r.state != "not run":
        line += " (%.1f s)" % r.seconds
    if r.message:
        line += ": " + r.message
    elif r.state == "not run":
        line += ": not started before --timeout"
    return line


def write_junit(results, path, suite="canworks-sim"):
    """A JUnit XML report: one testcase per scenario; failed, stopped and
    timed out ones have a <failure>, ones not run are <skipped>."""
    failures = sum(1 for r in results if r.state in ("failed", "stopped", "timeout"))
    skipped = sum(1 for r in results if r.state == "not run")
    total = sum(r.seconds for r in results)
    root = ET.Element("testsuites", tests=str(len(results)), failures=str(failures), errors="0",
                      time="%.3f" % total)
    ts = ET.SubElement(root, "testsuite", name=suite, tests=str(len(results)), failures=str(failures),
                       errors="0", skipped=str(skipped), time="%.3f" % total)
    for r in results:
        tc = ET.SubElement(ts, "testcase", classname="scenarios", name=r.name, time="%.3f" % r.seconds)
        if r.state in ("failed", "stopped", "timeout"):
            f = ET.SubElement(tc, "failure", message=r.message or r.state, type=r.state)
            f.text = r.message or r.state
        elif r.state == "not run":
            ET.SubElement(tc, "skipped", message="not started before the timeout")
    data = ET.tostring(root, encoding="utf-8")
    try:
        with open(path, "wb") as f:
            f.write(b'<?xml version="1.0" encoding="UTF-8"?>\n' + data + b"\n")
    except OSError as e:
        raise DiagError("usage", "cannot write %s: %s" % (path, e.strerror or e))
    return path
