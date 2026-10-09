"""The configurator's Simulation view on the server (canopen-configurator:
"Simulation view", "Scenarios in the configurator"; docs/simulator.md).

The simulation file (canworks/simulation.json): reading it with the project,
checking it against schema/canworks-sim.v1.schema.json (or v2, one section per
network) and writing it with the
configurator's save rules. The machine file a section names
(canworks/machine.json) is read for the Machine view and checked with the
simulation file's problems. The live requests go to the runtime's simulated
devices through the online access settings, or to a standalone simulator by
address; its address and token are kept on this PC (online.json), never in the
project.
"""

import hashlib
import json
import os

import jsonschema
from jsonschema.exceptions import best_match

from .. import contract, diag, machine, simclient

SIM_FILE = "simulation.json"
DEFAULT_ADDRESS = "127.0.0.1:%d" % simclient.SIM_PORT
SCHEMA_FILE = "canopen-sim.v%d.schema.json"
SUPPORTED_VERSION = 2
TARGETS = ("runtime", "simulator")
PINS_MAX = 64

# Requests the page may send through /api/sim/request.
OPS = ("sim_status", "sim_get", "sim_set", "sim_override", "sim_release", "sim_source", "sim_fault", "sim_clear",
       "sim_scenario_list", "sim_scenario_start", "sim_scenario_stop", "sim_check_expr", "sim_machine")

# Key order of a saved file; keys not listed keep their place after these.
ORDER = {
    "": ["schema_version", "tick_ms", "nodes", "extra_devices", "scenarios", "networks"],
    "section": ["machine", "nodes", "extra_devices", "scenarios"],
    "node": ["node", "name", "eds", "default_behaviour", "tick_ms", "identity", "device_type", "drive", "sources",
             "faults"],
    "scenario": ["description", "autostart", "test", "steps"],
}

_schemas = {}


def schema(version=1):
    if version not in _schemas:
        with open(os.path.join(os.path.dirname(contract.__file__), "schema", SCHEMA_FILE % version),
                  encoding="utf-8") as f:
            _schemas[version] = json.load(f)
    return _schemas[version]


def version(doc):
    v = doc.get("schema_version", 1) if isinstance(doc, dict) else 1
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 1 else 1


def bodies(doc):
    """The parts holding nodes, extra_devices and scenarios: the file (version
    1) or each network's section (version 2)."""
    if not isinstance(doc, dict):
        return []
    if version(doc) >= 2:
        nets = doc.get("networks")
        return [v for v in nets.values() if isinstance(v, dict)] if isinstance(nets, dict) else []
    return [doc]


def json_path(parts):
    out = ""
    for p in parts:
        out += "[%d]" % p if isinstance(p, int) else ("." if out else "") + str(p)
    return out


def check(doc):
    """Schema problems of a simulation file: [{"path", "message"}], one per
    problem, at its JSON path (scenarios.alarm.steps[2].wait)."""
    if not isinstance(doc, dict):
        return [{"path": "", "message": "the simulation file must be a JSON object"}]
    v = doc.get("schema_version", 1)
    if isinstance(v, int) and not isinstance(v, bool) and v > SUPPORTED_VERSION:
        return [{"path": "schema_version", "message": "schema_version %d is not supported; the highest supported "
                                                      "version is %d" % (v, SUPPORTED_VERSION)}]
    out = []
    validator = jsonschema.Draft202012Validator(schema(version(doc)))
    for e in sorted(validator.iter_errors(doc), key=lambda e: list(map(str, e.absolute_path))):
        while e.context:
            fitting = [c for c in e.context if c.validator != "type"]
            e = best_match(fitting or e.context)
        where = json_path(list(e.absolute_path))
        message = e.message
        if e.validator == "oneOf" and isinstance(e.instance, dict):
            message = "give exactly one of the alternatives (%s)" % ", ".join(sorted(e.instance)) \
                if e.instance else "is empty"
        elif e.validator == "additionalProperties":
            message = e.message.replace("Additional properties are not allowed", "unknown field")
        elif e.validator == "pattern" and "0x[0-9A-Fa-f]{4}" in str(e.validator_value):
            message = "%r is not an object: write it as 0xIIII:S, for example 0x6200:1" % (e.instance,)
        elif e.validator == "minProperties":
            message = "give at least one entry"
        elif e.validator == "propertyNames" and isinstance(e.instance, dict):
            message = "an object must be written as 0xIIII:S, for example 0x6200:1"
        out.append({"path": where, "message": message})
    return out


def machine_file(doc, network):
    """The machine file a version 2 file's section for `network` names, or
    None (a version 1 file, no such section, or no machine)."""
    if version(doc) < 2 or not isinstance(doc.get("networks"), dict):
        return None
    sec = doc["networks"].get(network or "")
    value = sec.get("machine") if isinstance(sec, dict) else None
    return value if isinstance(value, str) and value else None


def machine_problems(doc, sim_path, cfg, config_path, eds_paths, network=None):
    """The problems of the machine files a (schema-valid) simulation file
    names and of the scenario steps and conditions on them, in the shape of
    check(), with "level": the deploy tool's checks against the config. Only
    the section of `network` when given."""
    from .. import simfile
    if version(doc) < 2 or '"machine"' not in json.dumps(doc):
        return []  # nothing names a machine: spare the EDS reads on every check
    r = simfile.check(doc, sim_path, cfg if isinstance(cfg, dict) else None, config_path, eds_paths)
    out = []
    for item in r.items:
        paths = [p for p in item["paths"] if p == "machine" or p.endswith(".machine")]
        if not paths:
            continue
        if network is not None and not (paths[0] + ".").startswith("networks.%s." % network):
            continue
        msg = item["message"]
        prefix = "%s: %s: " % (sim_path, paths[0])
        if msg.startswith(prefix):
            msg = msg[len(prefix):]
        out.append({"path": paths[0], "message": msg, "level": item["level"]})
    return out


def read_machine(doc, sim_path, network):
    """{"network", "file", "machine"} of the machine file the section of
    `network` names: "machine" the parsed file, or None when there is none
    or it cannot be read; "error" then says why."""
    value = machine_file(doc, network)
    out = {"network": network, "file": value, "machine": None}
    if value is None:
        return out
    path = value if os.path.isabs(value) else os.path.join(os.path.dirname(os.path.abspath(sim_path)), value)
    try:
        m = machine.load(path)
        if isinstance(m, dict):
            out["machine"] = m
    except machine.MachineFileError as e:
        out["error"] = str(e)
    return out


def _ordered(obj, kind):
    if not isinstance(obj, dict):
        return obj
    keys = ORDER.get(kind, [])
    out = {k: obj[k] for k in keys if k in obj}
    out.update((k, v) for k, v in obj.items() if k not in out)
    return out


def canonical(doc):
    """The file with its keys in a fixed order (unknown keys kept), nodes by
    node ID; a version 2 file's empty sections left out."""
    doc = _ordered(doc, "")
    if version(doc) >= 2 and isinstance(doc.get("networks"), dict):
        doc["networks"] = {k: _canonical_body(_ordered(v, "section")) for k, v in doc["networks"].items()
                           if not (isinstance(v, dict) and not v)}
        return doc
    return _canonical_body(doc)


def _canonical_body(doc):
    if not isinstance(doc, dict):
        return doc
    if isinstance(doc.get("nodes"), dict):
        def key(k):
            return (0, int(k)) if str(k).isdigit() else (1, str(k))
        doc["nodes"] = {k: _ordered(doc["nodes"][k], "node") for k in sorted(doc["nodes"], key=key)}
    if isinstance(doc.get("extra_devices"), list):
        doc["extra_devices"] = [_ordered(d, "node") for d in doc["extra_devices"]]
    if isinstance(doc.get("scenarios"), dict):
        doc["scenarios"] = {k: _ordered(v, "scenario") for k, v in doc["scenarios"].items()}
    return doc


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def read(path):
    """{"path", "exists", "doc", "error", "sha256"} of a simulation file. A
    missing file reads as an empty one."""
    out = {"path": path, "exists": os.path.isfile(path), "doc": {"schema_version": 1}, "error": None,
           "sha256": None}
    if not out["exists"]:
        return out
    try:
        out["sha256"] = _sha(path)
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
        if not isinstance(doc, dict):
            raise ValueError("the top level is not a JSON object")
        out["doc"] = doc
    except (OSError, ValueError) as e:
        out["error"] = "%s cannot be read: %s" % (path, e)
    return out


def write(path, doc):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(canonical(doc), f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


def eds_files(canopen_dir):
    """EDS and DCF files an extra device can use: those in the config folder
    and in its eds/ subfolder, as paths relative to the simulation file."""
    out = []
    for sub in ("", "eds"):
        folder = os.path.join(canopen_dir, sub) if sub else canopen_dir
        if not os.path.isdir(folder):
            continue
        for name in sorted(os.listdir(folder), key=str.lower):
            if name.lower().endswith((".eds", ".dcf")) and os.path.isfile(os.path.join(folder, name)):
                out.append(sub + "/" + name if sub else name)
    return out


def extra_eds(doc):
    """The EDS values the extra devices of a simulation file name."""
    out = []
    for body in bodies(doc or {}):
        for d in body.get("extra_devices") or []:
            if isinstance(d, dict) and isinstance(d.get("eds"), str) and d["eds"]:
                out.append(d["eds"])
    return out


# ---------------------------------------------------------------------------
# Expressions


def parse_object(text):
    try:
        return simclient.parse_object(str(text))
    except ValueError:
        return None


def check_offline(expr, known_devices, has_object):
    """An expression checked on this PC with the simulation file checker
    (simfile), when that module is installed: {"checked": True, "ok": True},
    {"checked": True, "ok": False, "error", "position"}, or
    {"checked": False} without it."""
    try:
        from .. import simfile
    except ImportError:
        return {"checked": False}
    fn = getattr(simfile, "check_expression", None)
    if fn is None:
        return {"checked": False}
    try:
        problem = fn(expr, known_devices, has_object)
    except Exception as e:  # pragma: no cover - a checker bug is shown, not raised
        return {"checked": False, "note": "the expression checker failed: %s" % e}
    if not problem:
        return {"checked": True, "ok": True, "by": "configurator"}
    position, message = problem
    return {"checked": True, "ok": False, "position": position, "error": message, "by": "configurator"}


def remote_result(result, by):
    """A sim_check_expr answer in the page's form."""
    result = result if isinstance(result, dict) else {}
    if result.get("error"):
        return {"checked": True, "ok": False, "error": result["error"], "position": result.get("position"), "by": by}
    return {"checked": True, "ok": True, "by": by}


# ---------------------------------------------------------------------------
# Settings on this PC


def settings_view(proj):
    pins = proj.get("sim_pins")
    return {"target": proj.get("sim_target") if proj.get("sim_target") in TARGETS else "runtime",
            "address": proj.get("sim_address") or DEFAULT_ADDRESS,
            "token_set": bool(proj.get("sim_token")),
            "pins": pins if isinstance(pins, dict) else {}}


def clean_settings(body):
    """The settings in a POST /api/sim/settings body, checked: a dict for
    Settings.update_project (None removes a key)."""
    out = {}
    if "target" in body:
        if body["target"] not in TARGETS:
            raise ValueError("target must be runtime or simulator")
        out["sim_target"] = body["target"]
    if "address" in body:
        address = (body.get("address") or "").strip()
        if address:
            simclient.parse_sim(address)
        out["sim_address"] = address or None
    if "token" in body:
        out["sim_token"] = (body.get("token") or "").strip() or None
    if "pins" in body:
        pins = body["pins"]
        if not isinstance(pins, dict):
            raise ValueError("pins must be an object of device -> list of objects")
        clean = {}
        for dev, objs in pins.items():
            if not isinstance(objs, list) or len(objs) > PINS_MAX:
                raise ValueError("a device holds at most %d pinned objects" % PINS_MAX)
            keys = []
            for o in objs:
                p = parse_object(o)
                if p is None:
                    raise ValueError("pinned object %r: want 0xIIII:S" % (o,))
                k = simclient.object_key(*p)
                if k not in keys:
                    keys.append(k)
            if keys:
                clean[str(dev)] = keys
        out["sim_pins"] = clean or None
    return out


def target(proj, port=None):
    """(host, port, token, kind) of where the Simulation view connects, or
    raises LookupError with what is missing."""
    if proj.get("sim_target") == "simulator":
        host, p = simclient.parse_sim(proj.get("sim_address") or DEFAULT_ADDRESS)
        return host, p, proj.get("sim_token") or "", "simulator"
    host, token = proj.get("host"), proj.get("token")
    if not host:
        raise LookupError("host")
    if not token:
        raise LookupError("token")
    hostname, p = diag.parse_runtime(host)
    if ":" not in host.rsplit("]", 1)[-1] and isinstance(port, int) and not isinstance(port, bool):
        p = port
    return hostname, p, token, "runtime"
