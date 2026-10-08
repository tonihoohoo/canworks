"""The machine file (canopen/machine.json, docs/machine.md): loading, the JSON
Schema, and the checks the schema cannot express, given the network of the
simulation file section that names it.

The machine model itself runs in the simulator (plugin/sim/sim_machine.cpp);
messages here follow its wording, each naming the network and the element.
"""

import json
import math
import os

import jsonschema
from jsonschema.exceptions import best_match

from . import contract

SUPPORTED_VERSION = 1
FILE_NAME = "machine.json"
_SCHEMA_DIR = os.path.join(os.path.dirname(__file__), "schema")
_schemas = {}

# What a machine fault and a machine `clear` take (sim_machine.cpp).
FAULT_KINDS = ("jam", "stuck", "slip", "feeder", "misaligned_mm")
CLEAR_NAMES = ("jam", "stuck", "feeder", "misaligned_mm", "all")
COUNTERS = ("fed", "picked", "placed", "misplaced", "dropped", "pallets")
JOINTS = ("x", "y", "z")


def schema(version=SUPPORTED_VERSION):
    if version not in _schemas:
        with open(os.path.join(_SCHEMA_DIR, "canopen-machine.v%d.schema.json" % version), encoding="utf-8") as f:
            _schemas[version] = json.load(f)
    return _schemas[version]


def fault_problem(f):
    """None for a well-formed machine fault, else the simulator's message."""
    if not isinstance(f, dict) or len(f) != 1:
        return "a machine fault is an object with one of jam, stuck, slip, feeder, misaligned_mm"
    (k, v), = f.items()
    if k in ("jam", "slip"):
        return None if v is True else "\"%s\" must be true" % k
    if k == "stuck":
        return None if v in ("on", "off") else "\"stuck\" must be \"on\" or \"off\""
    if k == "feeder":
        return None if v in ("stop", "empty") else "\"feeder\" must be \"stop\" or \"empty\""
    if k == "misaligned_mm":
        ok = isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and abs(v) <= 1000
        return None if ok else "\"misaligned_mm\" must be a number -1000 to 1000"
    return "unknown machine fault \"%s\" (jam, stuck, slip, feeder, misaligned_mm)" % k


def elements(m):
    """{element name: kind} of a (schema-valid) machine file: joint, tool,
    conveyor (feeder: with a feed), sensor, fixture."""
    out = {}
    for j in (m.get("joints") or {}):
        out[j] = "joint"
    if isinstance(m.get("tool"), dict):
        out["tool"] = "tool"
    for c in m.get("conveyors") or []:
        out[c["name"]] = "feeder" if isinstance(c.get("feed"), dict) else "conveyor"
    for s in m.get("sensors") or []:
        out[s["name"]] = "sensor"
    for f in m.get("fixtures") or []:
        out[f["name"]] = "fixture"
    return out


def fault_element_problem(m, element, f):
    """None when the (well-formed) fault fits the element of machine file
    `m`, else the simulator's message."""
    els = elements(m)
    if element not in els:
        return "the machine has no element \"%s\"" % element
    k = next(iter(f))
    kind = els[element]
    want = {"jam": ("joint", "a joint"), "stuck": ("sensor", "a sensor"), "slip": ("tool", "the tool"),
            "feeder": ("feeder", "a conveyor with a feeder"),
            "misaligned_mm": ("feeder", "a conveyor with a feeder")}[k]
    if kind != want[0]:
        return "\"%s\" is a fault of %s, not of %s" % (k, want[1], element)
    return None


def clear_element_problem(m, element, name):
    if name not in CLEAR_NAMES:
        return "\"%s\" is not a machine fault (jam, stuck, feeder, misaligned_mm, all)" % name
    if element not in ("all", "") and element not in elements(m):
        return "the machine has no element \"%s\"" % element
    return None


def value_names(m):
    """The names a machine condition takes: counters, joints, sensors,
    fixtures (MachineModel::Names)."""
    return list(COUNTERS) + [j for j in JOINTS if j in (m.get("joints") or {})] + \
        [s["name"] for s in m.get("sensors") or []] + [f["name"] for f in m.get("fixtures") or []]


# ---------------------------------------------------------------------------
# Loading and the checks


class MachineFileError(Exception):
    pass


def load(path):
    """The parsed file; MachineFileError when it cannot be read or is not
    JSON."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except OSError as e:
        raise MachineFileError("cannot read %s: %s" % (path, e.strerror or e))
    except ValueError as e:
        raise MachineFileError("%s: not valid JSON (%s)" % (path, e))


def schema_problems(m):
    """[(JSON path, message)] of the schema check."""
    if not isinstance(m, dict):
        return [("", "top level must be a JSON object")]
    v = m.get("schema_version")
    if isinstance(v, int) and not isinstance(v, bool) and v > SUPPORTED_VERSION:
        return [("schema_version", "the file is version %d, this tool reads up to %d" % (v, SUPPORTED_VERSION))]
    out = []
    for e in sorted(jsonschema.Draft202012Validator(schema()).iter_errors(m),
                    key=lambda e: list(map(str, e.absolute_path))):
        while e.context:
            fitting = [c for c in e.context if c.validator != "type"]
            e = best_match(fitting or e.context)
        msg = e.message
        if e.validator == "additionalProperties" and isinstance(e.instance, dict):
            unknown = sorted(k for k in e.instance if k not in (e.schema.get("properties") or {}))
            msg = "unknown field%s %s" % ("s" if len(unknown) > 1 else "", ", ".join("'%s'" % k for k in unknown))
        out.append((contract.json_path(list(e.absolute_path)), msg))
    return out


def _fmt(v):
    return "%g" % v


def bit_text(b):
    """"node 10 0x6000:1 bit 3", as the simulator names a bound bit."""
    index, sub = _object(b["object"])
    return "node %d 0x%04X:%d bit %d" % (b["node"], index, sub, b["bit"])


def _object(text):
    idx, _, sub = text.partition(":")
    return int(idx, 16), (int(sub, 0) if sub else 0)


def outputs(m):
    """[(bit, element, JSON path)] of the bits the model reads: objects the
    master writes."""
    out = []
    t = m.get("tool")
    if isinstance(t, dict):
        out.append((t["close"], "tool.close", "tool.close"))
    for i, c in enumerate(m.get("conveyors") or []):
        out.append((c["run"], "conveyor %s run" % c["name"], "conveyors[%d].run" % i))
    for i, f in enumerate(m.get("fixtures") or []):
        if isinstance(f.get("change"), dict):
            out.append((f["change"]["request"], "fixture %s change request" % f["name"],
                        "fixtures[%d].change.request" % i))
    return out


def inputs(m):
    """[(bit, element, JSON path)] of the bits the model sets: objects the
    device sends."""
    out = []
    t = m.get("tool")
    if isinstance(t, dict) and isinstance(t.get("gripped"), dict):
        out.append((t["gripped"], "tool.gripped", "tool.gripped"))
    for i, s in enumerate(m.get("sensors") or []):
        out.append((s["output"], "sensor %s" % s["name"], "sensors[%d].output" % i))
    for i, f in enumerate(m.get("fixtures") or []):
        if isinstance(f.get("change"), dict):
            out.append((f["change"]["ready"], "fixture %s ready" % f["name"], "fixtures[%d].change.ready" % i))
    return out


def structure_problems(m):
    """[(JSON path, message)] of a schema-valid file's checks that need no
    config, in the simulator's words (parse_machine_file)."""
    out = []

    def pair_in_order(where, v):
        if v is not None and not v[0] < v[1]:
            out.append((where, "must be [low, high] with low < high"))
            return False
        return v is not None

    nodes = {}
    for name in JOINTS:
        j = (m.get("joints") or {}).get(name)
        if not isinstance(j, dict):
            continue
        at = "joints." + name
        travel_ok = pair_in_order(at + ".travel", j["travel"])
        limits_ok = pair_in_order(at + ".limits", j.get("limits"))
        stops_ok = pair_in_order(at + ".hard_stops", j.get("hard_stops"))
        lim, stops, travel = j.get("limits"), j.get("hard_stops"), j["travel"]
        if limits_ok and stops_ok and (stops[0] > lim[0] or stops[1] < lim[1]):
            out.append((at + ".hard_stops", "must lie outside the limit switches (%s, %s)"
                        % (_fmt(lim[0]), _fmt(lim[1]))))
        if stops_ok and travel_ok and (stops[0] > travel[0] or stops[1] < travel[1]):
            out.append((at + ".hard_stops", "must lie outside the travel (%s, %s)"
                        % (_fmt(travel[0]), _fmt(travel[1]))))
        if j["node"] in nodes:
            out.append((at, "node %d drives another joint too (joint %s)" % (j["node"], nodes[j["node"]])))
        else:
            nodes[j["node"]] = name
    t = m.get("tool")
    if isinstance(t, dict) and t.get("closed_mm", 0) >= t.get("open_mm", 96):
        out.append(("tool.closed_mm", "must be smaller than open_mm"))
    names = {n: "the joint" for n in JOINTS}
    names["tool"] = "the tool"
    kinds = m.get("parts") or {}
    for key in ("conveyors", "sensors", "fixtures"):
        for i, el in enumerate(m.get(key) or []):
            at = "%s[%d]" % (key, i)
            if el["name"] in names:
                out.append((at + ".name", "the name \"%s\" is used by another element (%s)"
                            % (el["name"], names[el["name"]])))
            else:
                names[el["name"]] = "%s %s" % (key[:-1], el["name"])
            if key != "conveyors":
                continue
            (fx, fy), (tx, ty) = el["from"], el["to"]
            if (abs(fy - ty) < 1e-6) == (abs(fx - tx) < 1e-6):
                out.append((at, "a conveyor runs along x or y: \"from\" and \"to\" share x or y, not both"))
            feed = el.get("feed")
            if isinstance(feed, dict):
                if feed["every_s"][0] > feed["every_s"][1]:
                    out.append((at + ".feed.every_s", "must be [shortest, longest]"))
                if feed["part"] not in kinds:
                    out.append((at + ".feed.part", "part kind \"%s\" is not defined in \"parts\"%s"
                                % (feed["part"], " (%s)" % ", ".join(sorted(kinds)) if kinds else "")))
    # No input bit bound twice, and no bit both read and written.
    seen = {}
    for b, element, at in inputs(m):
        key = bit_text(b)
        if key in seen:
            out.append((at, "%s is bound twice: %s and %s" % (key, seen[key], element)))
        else:
            seen[key] = element
    for b, element, at in outputs(m):
        key = bit_text(b)
        if key in seen:
            out.append((at, "%s is both an output (%s) and an input (%s)" % (key, element, seen[key])))
    return out


# Bits of the integer data types (CiA 301 codes); BOOLEAN holds bit 0 only.
_TYPE_BITS = {0x0001: 1, 0x0002: 8, 0x0003: 16, 0x0004: 32, 0x0005: 8, 0x0006: 16, 0x0007: 32, 0x0015: 64,
              0x001B: 64}


def config_problems(m, devices, simulated_network, simulated_nodes, network_label):
    """[(level, JSON path, message)] of the checks against the network: the
    joints' nodes simulated CiA 402 axes, the bound objects in the nodes'
    EDS with a type the bit fits, outputs written by the master in an RPDO
    and inputs not. devices: {node ID: simfile device} of the network's
    nodes and the section's extra devices."""
    out = []
    if not simulated_network:
        out.append(("warning", "", "%s is not used: a machine only runs on a simulated network (adapter.simulate)"
                    % network_label))

    def device(n, element, at):
        dev = devices.get(n)
        if dev is None:
            out.append(("error", at, "%s: node %d is neither a node of the network nor an extra device"
                        % (element, n)))
            return None
        if simulated_network and dev.extra is None and n not in simulated_nodes:
            out.append(("error", at, "%s: %s is not simulated (\"simulate\": false); every node the machine names "
                        "must be simulated" % (element, dev.label)))
            return None
        return dev

    for name in JOINTS:
        j = (m.get("joints") or {}).get(name)
        if not isinstance(j, dict):
            continue
        at = "joints.%s.node" % name
        dev = device(j["node"], "joint " + name, at)
        if dev is not None and not (isinstance(dev.cfg_node, dict) and isinstance(dev.cfg_node.get("axis"), dict)):
            out.append(("error", at, "joint %s: %s has no `axis`: a joint needs a CiA 402 axis node (\"axis\" in "
                        "the config)" % (name, dev.label)))

    def bit(b, element, at, is_input):
        dev = device(b["node"], element, at + ".node")
        if dev is None:
            return
        index, sub = _object(b["object"])
        obj = "0x%04X:%d" % (index, sub)
        if dev.eds is not None:
            o = dev.eds.find(index, sub)
            if o is None:
                out.append(("error", at + ".object", "%s: %s has no object %s in %s"
                            % (element, dev.label, obj, dev.eds_name)))
                return
            bits = _TYPE_BITS.get(o.data_type)
            if bits is None:
                out.append(("error", at + ".object", "%s: object %s of %s is not an integer object (data type "
                            "0x%04X); a bit needs an integer or BOOLEAN" % (element, obj, dev.label, o.data_type)))
                return
            if b["bit"] >= bits:
                out.append(("error", at + ".bit", "%s: bit %d does not fit object %s of %s (%d bit%s)"
                            % (element, b["bit"], obj, dev.label, bits, "" if bits == 1 else "s")))
        writer = dev.writers.get((index, sub))
        if is_input and writer:
            out.append(("error", at + ".object", "%s: the master writes %s of %s (%s); an input must be an object "
                        "the device sends" % (element, obj, dev.label, writer)))
        if not is_input and not (writer or "").startswith("RPDO"):
            out.append(("error", at + ".object", "%s: the master does not write %s of %s%s; an output must be an "
                        "object the master writes (an RPDO)"
                        % (element, obj, dev.label, " in a PDO (only by %s)" % writer if writer else "")))

    for b, element, at in inputs(m):
        bit(b, element, at, True)
    for b, element, at in outputs(m):
        bit(b, element, at, False)
    return out
