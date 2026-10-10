"""The config contract (CANopen and J1939 networks): schema_version, the published JSON Schema, and
the checks the plugin runs that the schema cannot express.

Messages that the plugin also produces use the plugin's wording (see
plugin/src/can/config.cpp); the shared fixtures in test/fixtures/config/ hold both
to it.
"""

import json
import math
import os
import re

import jsonschema
from jsonschema.exceptions import best_match

from . import axis as axis_mod
from . import bridgecheck
from . import eds as eds_mod
from . import edslint
from . import links as links_mod
from .eds import sync_needed_message, transmission_needs_sync
from .iec import CO_TYPES, parse_location, type_fits, SIZE_BITS
from .raw import contract as raw_contract
from .raw import mux as raw_mux
from .raw import ownership

SUPPORTED_VERSION = 2
MAX_NETWORKS = 8
_SCHEMA_DIR = os.path.join(os.path.dirname(__file__), "schema")
_schemas = {}
_V1_REF = "canworks.v1.schema.json#"
NETWORK_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,15}$")
# A Linux interface name the plugin can open or create (IFNAMSIZ - 1).
INTERFACE_NAME = re.compile(r"^[A-Za-z0-9_.:-]{1,15}$")
# Entries per table of the runtime's I/O image (the plugin's default
# buffer_size; a bridge config's image is bridgecheck.IMAGE_BYTES bytes).
IMAGE_ENTRIES = 1024
ON_PLC_STOP = ("preop", "stop", "keep")


def interface_message(name):
    """The plugin's refusal of an interface name, or None when it is fine."""
    if not isinstance(name, str) or not name or INTERFACE_NAME.match(name):
        return None
    return ("interface \"%s\" must be 1-15 characters of letters, digits, '_', '.', ':' and '-' (the 15-character "
            "limit of Linux interface names)" % name)


def supervision_message(label):
    """The plugin's refusal of a node without heartbeat or guarding whose EDS
    heartbeat default is 0 (canopen-node-supervision)."""
    return ("%s has no heartbeat or guarding (its EDS heartbeat 0x1017 defaults to 0): its loss would never be "
            "detected; set heartbeat_ms, or \"heartbeat_ms\": 0 to accept that" % label)


def _local_refs(node):
    """`node` with every reference into the version 1 schema made local."""
    if isinstance(node, dict):
        return {k: ("#" + v[len(_V1_REF):] if k == "$ref" and isinstance(v, str) and v.startswith(_V1_REF)
                    else _local_refs(v)) for k, v in node.items()}
    if isinstance(node, list):
        return [_local_refs(v) for v in node]
    return node


def schema(version=1):
    """The published schema of a version, ready to validate with. Version 2
    refers to version 1's definitions by file name; here they are copied in
    so the references resolve without loading anything else."""
    if version not in _schemas:
        with open(os.path.join(_SCHEMA_DIR, "canworks.v%d.schema.json" % version), encoding="utf-8") as f:
            doc = json.load(f)
        if version > 1:
            doc = _local_refs(doc)
            defs = dict(schema(1)["$defs"])
            defs.update(doc.get("$defs", {}))
            doc["$defs"] = defs
        _schemas[version] = doc
    return _schemas[version]


def version_of(cfg):
    """The config's schema_version as the plugin reads it (1 when left out),
    or None when it is not a version number."""
    if not isinstance(cfg, dict) or "schema_version" not in cfg:
        return 1
    v = _uint(cfg["schema_version"])
    return v if v else None


def networks(cfg):
    """The config's networks, for both versions: a list of dicts with `name`
    ("" for a version 1 file), `index`, `path` (the JSON path prefix of the
    network's fields, "" for version 1), `role` ("master", "slave" or, for a
    J1939 network, "j1939"), `protocol` ("canopen" or "j1939"), `adapter`,
    `master` and `nodes` (empty for a slave or J1939 network), `slave` (the
    slave object, empty for the others) and `j1939` (the j1939 object of a
    J1939 network, else empty). A version 2 network without a name is named
    after its interface."""
    if version_of(cfg) == 1 or not isinstance(cfg.get("networks"), list):
        adapter = cfg.get("adapter")
        if adapter is None and "interface" in cfg:
            adapter = {"type": "socketcan", "interface": cfg.get("interface"), "bitrate": cfg.get("bitrate")}
        return [{"name": "", "index": 0, "path": "", "role": "master", "protocol": "canopen", "adapter": adapter or {},
                 "master": cfg.get("master") or {}, "nodes": cfg.get("nodes") or [], "slave": {}, "j1939": {},
                 "json": cfg}]
    out = []
    for i, net in enumerate(cfg["networks"]):
        if not isinstance(net, dict):
            continue
        adapter = net.get("adapter") if isinstance(net.get("adapter"), dict) else {}
        name = net.get("name")
        if not isinstance(name, str) or not name:
            iface = adapter.get("interface")
            name = iface if isinstance(iface, str) and NETWORK_NAME.match(iface) else ""
        if net.get("protocol") == "none":
            out.append({"name": name, "index": i, "path": "networks[%d]" % i, "role": "plain", "protocol": "none",
                        "adapter": adapter, "master": {}, "nodes": [], "slave": {}, "j1939": {}, "json": net})
            continue
        if is_j1939(net):
            # Never a CANopen network: no master, nodes or slave, whatever the
            # entry holds (the checks report those keys).
            out.append({"name": name, "index": i, "path": "networks[%d]" % i, "role": "j1939", "protocol": "j1939",
                        "adapter": adapter, "master": {}, "nodes": [], "slave": {},
                        "j1939": net.get("j1939") if isinstance(net.get("j1939"), dict) else {}, "json": net})
            continue
        slave = net.get("role") == "slave"
        out.append({"name": name, "index": i, "path": "networks[%d]" % i, "role": "slave" if slave else "master",
                    "protocol": "canopen", "adapter": adapter, "master": {} if slave else net.get("master") or {},
                    "nodes": [] if slave else net.get("nodes") or [],
                    "slave": (net.get("slave") if isinstance(net.get("slave"), dict) else {}) if slave else {},
                    "j1939": {}, "json": net})
    return out


def all_nodes(cfg):
    """Every node entry of the config, network after network (the dicts
    themselves, so changes land in `cfg`)."""
    return [n for net in networks(cfg) for n in net["nodes"] if isinstance(n, dict)]


def slave_networks(cfg):
    """The slave networks of the config (networks() entries with role
    "slave"); none in a version 1 file."""
    return [n for n in networks(cfg) if n["role"] == "slave"] if isinstance(cfg, dict) else []


def eds_users(cfg):
    """Every object of the config that names an EDS file with `eds`: the
    nodes of every master network, then each slave network's slave object
    (the dicts themselves, so changes land in `cfg`)."""
    return all_nodes(cfg) + [n["slave"] for n in slave_networks(cfg) if n["slave"]]


def slave_direction(access):
    """Who writes an object of a slave's dictionary, from its EDS AccessType
    (canopen-slave-device D3): "input" for rww and rw (the master writes it,
    the PLC reads it from an %I location), "output" for ro and rwr (the PLC
    writes it from a %Q location, the master reads it), None for const and
    wo, which cannot be bound."""
    if access in ("rww", "rw"):
        return "input"
    if access in ("ro", "rwr"):
        return "output"
    return None


def network_config(cfg, name=None):
    """A version 1 style config (adapter, master, nodes) of one network, for
    the code that works on one network at a time. `name` picks the network;
    without it the config must have exactly one. Raises ValueError naming the
    networks otherwise. Version 2 diagnostics go into the master. A slave
    network comes back with an empty master and no nodes."""
    nets = networks(cfg)
    if name is None:
        if len(nets) != 1:
            raise ValueError("the config has %d networks (%s); name one"
                             % (len(nets), ", ".join(n["name"] for n in nets)))
        net = nets[0]
    else:
        found = [n for n in nets if n["name"] == name]
        if not found:
            raise ValueError("no network '%s' in the config (%s)"
                             % (name, ", ".join(n["name"] or "unnamed" for n in nets)))
        net = found[0]
    if not net["path"]:
        return cfg
    out = {"schema_version": 1, "adapter": net["adapter"], "master": dict(net["master"]), "nodes": net["nodes"]}
    if "links" in net["json"]:
        out["links"] = net["json"]["links"]
    if isinstance(cfg.get("diagnostics"), dict):
        out["master"]["diagnostics"] = cfg["diagnostics"]
    return out


class Result:
    """`errors` and `warnings` are the messages as the CLI prints them.
    `items` holds the same messages with the JSON paths of the fields they
    concern (`nodes[0].tx_pdos[1].entries[2].iec_location`), for a GUI:
    {"level": "error"|"warning", "message": str, "paths": [str]}."""

    def __init__(self):
        self.errors = []
        self.warnings = []
        self.items = []

    def add(self, level, message, paths):
        (self.errors if level == "error" else self.warnings).append(message)
        self.items.append({"level": level, "message": message, "paths": [p for p in paths if p is not None]})

    @property
    def ok(self):
        return not self.errors


def json_path(parts):
    out = ""
    for p in parts:
        out += "[%d]" % p if isinstance(p, int) else ("." if out else "") + str(p)
    return out


UINT_PATTERN = r"^(0[xX][0-9a-fA-F]+|[0-9]+)$"


def _uint(value):
    """An unsigned integer given as a JSON number or a "0x.."/decimal string,
    as the plugin reads it; None if it is not one. The one number parser:
    parse_numbers() runs it over every numeric field before the range checks."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float):
        return int(value) if value >= 0 and value == math.floor(value) else None
    if isinstance(value, str) and re.match(UINT_PATTERN, value):
        return int(value, 16) if value[:2].lower() == "0x" else int(value, 0 if value == "0" else 10)
    return None


def _alternatives(node, root):
    """The resolved alternatives a field's schema allows (itself when it has
    none), through anyOf, oneOf and allOf."""
    node = _resolve(node, root)
    out = []
    for key in ("anyOf", "oneOf", "allOf"):
        for sub in node.get(key, []):
            out += _alternatives(sub, root)
    return out or [node]


def _takes_number_string(node, root):
    """Whether a field takes both an integer and the same integer written as
    a string ("0x80", "128"): the schema's uint_string next to an integer."""
    alts = _alternatives(node, root)
    return any(a.get("pattern") == UINT_PATTERN for a in alts) and any(
        a.get("type") == "integer" or isinstance(a.get("const"), int) for a in alts)


def parse_numbers(value, node, root):
    """`value` with every number written as a string ("0x80", "128") where
    the schema takes it turned into the integer, so the schema's ranges
    check hex and decimal alike (the plugin parses before its range check)."""
    if isinstance(value, str):
        n = _uint(value)
        return n if n is not None and _takes_number_string(node, root) else value
    if isinstance(value, dict):
        props = _properties(node, root)
        return {k: parse_numbers(v, props[k], root) if k in props else v for k, v in value.items()}
    if isinstance(value, list):
        items = _items(node, root)
        return [parse_numbers(v, items, root) for v in value] if items is not None else value
    return value


# ---------------------------------------------------------------------------
# Schema errors in the user's words: the field's name and what it takes, not
# the rule or pattern (canopen-configurator: "The check refuses what the
# plugin refuses").

FIELD_NAMES = {
    "node_id": "node ID", "heartbeat_ms": "heartbeat period", "heartbeat_timeout_ms": "heartbeat timeout",
    "guard_time_ms": "guard time", "life_time_factor": "life time factor", "cob_id": "COB-ID",
    "time_cob_id": "TIME COB-ID", "vendor_id": "vendor ID", "product_code": "product code",
    "revision_number": "revision number", "serial_number": "serial number", "sync_period_us": "SYNC period",
    "sync_cycles": "SYNC every N PLC cycles", "sync_counter_overflow": "SYNC counter overflow",
    "sync_window_us": "SYNC window", "sync_source": "SYNC source", "index": "index", "subindex": "sub-index",
    "number": "PDO number", "transmission": "transmission type", "event_timer_ms": "event timer",
    "inhibit_time_us": "inhibit time", "sync_start": "SYNC start value", "timeout_ms": "timeout",
    "interface": "CAN interface", "bitrate": "bit rate", "device": "serial device", "serial_baudrate": "serial speed",
    "restart_ms": "restart time", "type": "type", "eds": "EDS file", "iec_location": "PLC location",
    "status_location": "status bit", "timeout_location": "timeout bit", "trigger_location": "trigger bit",
    "valid_location": "valid bit", "comm_ok_location": "communication OK bit", "port": "port", "bind": "address",
    "name": "name", "entries": "mapped objects", "nodes": "nodes", "networks": "networks",
    "scale_numerator": "scale numerator", "scale_denominator": "scale denominator", "scale_factor": "scale factor",
    "sdo_timeout_ms": "SDO timeout", "time_period_ms": "TIME period", "boot_time_ms": "boot time",
    "emcy_inhibit_time_us": "EMCY inhibit time", "nmt_inhibit_time_us": "NMT inhibit time",
    "heartbeat_multiplier": "heartbeat timeout factor", "period_ms": "read period", "value": "value",
    "direction": "direction", "pgn": "PGN", "address": "address", "upper": "upper network", "network": "network",
    "adapter": "CAN adapter", "master": "master section", "slave": "slave section", "j1939": "J1939 section",
}

# Fields whose numbers are written in hex in the page and the docs.
HEX_FIELDS = ("cob_id", "time_cob_id", "index", "vendor_id", "product_code", "revision_number", "serial_number",
              "pgn", "sdo_bridge_index", "status_index")

LOCATION_SIZES = {"X": ("bit", "X0.0"), "B": ("byte", "B0"), "W": ("word", "W0"), "D": ("double word", "D0"),
                  "L": ("long word", "L0")}


def field_name(key):
    """A config key in the page's words ("node_id" -> "node ID")."""
    return FIELD_NAMES.get(key) or str(key).replace("_", " ")


def _location_text(pattern):
    """What an IEC location pattern of the schema takes: "an input bit
    such as %IX0.0"."""
    m = re.match(r"^\^%\[(I?i?Q?q?)\](.*)$", pattern)
    if not m:
        return None
    area = {"Ii": "input", "Qq": "output"}.get(m.group(1), "input or output")
    letter = m.group(1)[0]
    sizes = [s for s in "XBWDL" if "[%s%s]" % (s, s.lower()) in m.group(2) or (s != "X" and "[BbWwDdLl]" in m.group(2))]
    if len(sizes) == 1:
        size, example = LOCATION_SIZES[sizes[0]]
        return "an %s %s such as %%%s%s" % (area, size, letter, example)
    return "an %s location such as %%%sX0.0 or %%%sW0" % (area, letter, letter)


def _number_text(n, hex_field):
    return "0x%X" % n if hex_field and n >= 16 else str(n)


def _range_text(alts, hex_field):
    """"1 to 127", "0 to 240 or 254 to 255", '128 to 2047 or "auto"'."""
    parts = []
    for a in alts:
        if a.get("type") == "integer" or "minimum" in a or "maximum" in a:
            lo, hi = a.get("minimum"), a.get("maximum")
            if lo is not None and hi is not None:
                parts.append("%s to %s" % (_number_text(lo, hex_field), _number_text(hi, hex_field)))
            elif lo is not None:
                parts.append("%s or more" % _number_text(lo, hex_field))
            elif hi is not None:
                parts.append("at most %s" % _number_text(hi, hex_field))
        elif "const" in a:
            parts.append(json.dumps(a["const"]))
        elif "enum" in a:
            parts += [json.dumps(v) for v in a["enum"]]
        elif a.get("type") == "null":
            parts.append("null")
    parts = list(dict.fromkeys(parts))
    return ", ".join(parts[:-1]) + " or " + parts[-1] if len(parts) > 2 else " or ".join(parts)


def plain_schema_message(e, root):
    """A jsonschema error (before best_match) of a field in the user's
    words: what the field takes, never the schema rule or its pattern."""
    path = list(e.absolute_path)
    keys = [p for p in path if isinstance(p, str)]
    key = keys[-1] if keys else ""
    name = field_name(key) if key else "the value"
    if path and isinstance(path[-1], int) and key:
        name = "each entry of " + name
    hex_field = key in HEX_FIELDS
    v = e.validator
    if v in ("anyOf", "oneOf") and not isinstance(e.instance, (dict, list)):
        alts = _alternatives(e.schema, root)
        numbers = [a for a in alts if a.get("type") in ("integer", "null") or "const" in a or "enum" in a]
        if isinstance(e.instance, str) and any(a.get("pattern") == UINT_PATTERN for a in alts) \
                and _uint(e.instance) is None and not any(a.get("type") == "string" and "pattern" not in a
                                                          for a in alts):
            words = _range_text(numbers, hex_field)
            return "%s must be a number (decimal or 0x hex)%s" % (name, ", " + words if words else "")
        def fits(a, x):
            if a.get("type") == "null":
                return False
            return a.get("minimum", x) <= x <= a.get("maximum", x) if "const" not in a and "enum" not in a \
                else x == a.get("const", x) and x in a.get("enum", [x])
        if numbers and isinstance(e.instance, (int, float)) and not isinstance(e.instance, bool) \
                and not any(fits(a, e.instance) for a in numbers):
            return "%s must be %s" % (name, _range_text(numbers, hex_field))
        if numbers and isinstance(e.instance, str) and not any(a.get("type") == "string" for a in alts):
            return "%s must be %s" % (name, _range_text(numbers, hex_field))
    while e.context:
        fitting = [c for c in e.context if c.validator != "type"]
        e = best_match(fitting or e.context)
        v = e.validator
    if v in ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum"):
        return "%s must be %s" % (name, _range_text([e.schema], hex_field))
    if v == "required":
        missing = [k for k in e.validator_value if isinstance(e.instance, dict) and k not in e.instance]
        return "the %s is missing" % field_name(missing[0] if missing else "")
    if v == "type":
        want = e.validator_value if isinstance(e.validator_value, list) else [e.validator_value]
        words = {"integer": "a whole number", "number": "a number", "string": "text", "boolean": "true or false",
                 "object": "a group of settings", "array": "a list", "null": "empty"}
        return "%s must be %s" % (name, " or ".join(words.get(w, w) for w in want))
    if v == "enum":
        return "%s must be %s" % (name, _range_text([{"enum": e.validator_value}], False))
    if v == "const":
        return "%s must be %s" % (name, json.dumps(e.validator_value))
    if v == "not" and isinstance(e.validator_value, dict) and "const" in e.validator_value:
        return "%s must not be %s" % (name, json.dumps(e.validator_value["const"]))
    if v == "pattern":
        loc = _location_text(e.validator_value)
        if loc:
            return "%s must be %s" % (name, loc)
        if e.validator_value == NETWORK_NAME.pattern:
            return "%s must start with a letter and hold only letters, digits and '_', at most 16 characters" % name
        if e.validator_value == UINT_PATTERN:
            return "%s must be a number (decimal or 0x hex)" % name
        return "%s %s is not valid here" % (name, json.dumps(e.instance))
    if v == "multipleOf":
        return "%s must be a multiple of %s" % (name, e.validator_value)
    if v == "minItems":
        return "%s: give at least %d" % (name, e.validator_value)
    if v == "maxItems":
        return "%s: give at most %d" % (name, e.validator_value)
    if v == "minLength":
        return "%s must not be empty" % name
    if v == "maxLength":
        return "%s must be at most %d characters" % (name, e.validator_value)
    if v == "dependentRequired":
        have = [k for k in e.validator_value if isinstance(e.instance, dict) and k in e.instance]
        need = [k for k in (e.validator_value.get(have[0]) if have else []) if k not in e.instance]
        if have and need:
            return "the %s needs the %s" % (field_name(have[0]), field_name(need[0]))
    if v == "additionalProperties" and isinstance(e.instance, dict):
        allowed = e.schema.get("properties") or {}
        return "unknown field%s %s" % ("" if len([k for k in e.instance if k not in allowed]) == 1 else "s",
                                      ", ".join("'%s'" % k for k in e.instance if k not in allowed))
    if v in ("oneOf", "anyOf"):
        return "%s does not fit any of the allowed forms" % name
    if v == "not":
        return "%s is not allowed here" % name
    return e.message


# ---------------------------------------------------------------------------
# Unknown fields: every key the schema does not name is ignored with a warning.

def _resolve(node, root):
    while "$ref" in node:
        ref = node["$ref"]
        target = root
        for part in ref.lstrip("#/").split("/"):
            target = target[part]
        rest = {k: v for k, v in node.items() if k != "$ref"}
        node = dict(target, **rest) if rest else target
    return node


def _properties(node, root):
    node = _resolve(node, root)
    props = dict(node.get("properties", {}))
    for key in ("allOf", "anyOf", "oneOf"):
        for sub in node.get(key, []):
            for name, child in _properties(sub, root).items():
                # A field described twice (a J1939 network's adapter rule)
                # has the fields of both descriptions.
                props[name] = {"allOf": [props[name], child]} if name in props else child
    if "then" in node:
        # A conditional only adds fields; it does not replace the schema of a
        # field already described (the empty-node-list rule names master).
        for key, sub in _properties(node["then"], root).items():
            props.setdefault(key, sub)
    return props


def _items(node, root):
    node = _resolve(node, root)
    items = node.get("items")
    if items is None:
        for key in ("allOf", "anyOf", "oneOf"):
            for sub in node.get(key, []):
                items = items or _items(sub, root)
    return items


def unknown_fields(value, node, root, path, out):
    """Appends (json path, field) for every object key the schema does not
    describe, walking objects and arrays the schema describes."""
    if isinstance(value, dict):
        if _resolve(node, root).get("additionalProperties") not in (None, False):
            return  # a map with free keys (error_behavior)
        props = _properties(node, root)
        for key, child in value.items():
            if key not in props:
                out.append((json_path(path + [key]), key))
            else:
                unknown_fields(child, props[key], root, path + [key], out)
    elif isinstance(value, list):
        items = _items(node, root)
        if items is not None:
            for i, child in enumerate(value):
                unknown_fields(child, items, root, path + [i], out)


# ---------------------------------------------------------------------------
# Startup SDO values (plugin: Parser::sdo_value)

def sdo_value(value, type_name):
    """Returns (data bytes or None, problem). Same rules as the plugin."""
    bits = CO_TYPES[type_name][1]
    nbytes = 1 if bits == 1 else bits // 8
    if type_name in ("REAL32", "REAL64"):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            return None, "must be a number"
        import struct
        if type_name == "REAL32":
            if abs(value) > 3.4028234663852886e38:
                return None, "does not fit REAL32"
            return struct.pack("<f", value), None
        return struct.pack("<d", value), None
    if isinstance(value, bool):
        n = int(value)
    elif isinstance(value, (int, float)):
        if isinstance(value, float) and (not math.isfinite(value) or value != math.floor(value)):
            return None, "is not an integer"
        n = int(value)
    elif isinstance(value, str) and value:
        neg = value.startswith("-")
        body = value[1:] if neg else value
        m = re.match(r"^(0[xX][0-9a-fA-F]+|0[0-7]*|[1-9][0-9]*)$", body)
        if not m:
            return None, "is not a valid integer"
        if body[:2].lower() == "0x":
            mag = int(body, 16)
        elif body.startswith("0"):
            mag = int(body, 8)  # strtoull base 0: a leading 0 is octal
        else:
            mag = int(body)
        if mag >= 1 << 64:
            return None, "is not a valid integer"
        n = -mag if neg else mag
    else:
        return None, "must be a number"
    if type_name == "BOOLEAN":
        fits = 0 <= n <= 1
    elif type_name.startswith("INTEGER"):
        fits = -(1 << (bits - 1)) <= n <= (1 << (bits - 1)) - 1
    else:
        fits = 0 <= n <= (1 << bits) - 1
    if not fits:
        return None, "does not fit " + type_name
    return (n & ((1 << (nbytes * 8)) - 1)).to_bytes(nbytes, "little"), None


def _value_text(value):
    if isinstance(value, str):
        return value
    return json.dumps(value)


# ---------------------------------------------------------------------------

def _pdo_schema_message(cfg, path, e):
    """The plugin's words for the PDO-only fields the schema rejects:
    (where, message), or None."""
    if len(path) < 4 or path[0] != "nodes" or path[2] not in ("tx_pdos", "rx_pdos"):
        return None
    i, key, j = path[1], path[2], path[3]
    try:
        p = cfg["nodes"][i][key][j]
        number = _uint(p.get("number", j + 1)) or j + 1
    except (KeyError, IndexError, TypeError, AttributeError):
        return None
    kind = "TPDO" if key == "tx_pdos" else "RPDO"
    where = "nodes[%d]: %s[%d]" % (i, key, j)
    if len(path) == 4 and e.validator == "not" and key == "rx_pdos":
        field = next(f for f in ("inhibit_time_us", "sync_start", "timeout_ms", "on_timeout", "timeout_location")
                     if f in p)
        return where, "%s %d: field '%s' is only for tx_pdos (PDOs the node sends)" % (kind, number, field)
    if len(path) == 4 and e.validator == "dependentRequired":
        field = next(f for f in ("on_timeout", "timeout_location") if f in p)
        return where, "%s %d: field '%s' needs 'timeout_ms'" % (kind, number, field)
    if len(path) == 5 and path[4] == "timeout_ms" and _uint(p["timeout_ms"]) == 0:
        return where, "%s %d: field 'timeout_ms' must be 1-65535 or \"auto\"; leave it out for no timeout" % (
            kind, number)
    if len(path) == 5 and path[4] == "on_timeout" and e.validator == "enum":
        return where, "%s %d: field 'on_timeout' must be \"hold\" or \"zero\", not \"%s\"" % (
            kind, number, p["on_timeout"])
    if len(path) == 5 and path[4] == "timeout_location" and e.validator == "pattern":
        loc = parse_location(p["timeout_location"])
        if loc is not None:
            return where, "%s %d: field 'timeout_location' must be an input bit (%%IX...), not %s" % (
                kind, number, loc)
    if len(path) == 5 and path[4] == "inhibit_time_us" and e.validator == "multipleOf":
        return where, "%s %d: field 'inhibit_time_us' must be a multiple of 100" % (kind, number)
    return None


# PDO COB-IDs (CiA 301): TPDO n of node id is 0x80 + 0x100*n + id, RPDO n
# 0x100 + 0x100*n + id, for n = 1-4.
def default_cob_id(node_id, number, is_tx):
    if number > 4:
        return None
    return (0x80 if is_tx else 0x100) + 0x100 * number + node_id


def auto_cob_ids(nodes):
    """{(node index, "tx_pdos"/"rx_pdos", pdo index): COB-ID} for every PDO
    whose cob_id is "auto", resolved like the plugin: the default for PDOs
    1-4; above, the highest COB-ID in 0x181-0x57F outside every node's
    predefined set and not used by another PDO, in config order. Nodes are
    dicts with integer node_id and PDO lists of dicts (number, cob_id)."""
    taken = set()
    for n in nodes:
        nid = n["node_id"]
        if not 1 <= nid <= 127:
            continue
        taken.update(base + nid for base in range(0x180, 0x501, 0x80))
        for key in ("tx_pdos", "rx_pdos"):
            for p in n.get(key, []):
                cob = p.get("cob_id")
                if cob == "auto" or cob is None:
                    cob = default_cob_id(nid, p["number"], key == "tx_pdos")
                if cob is not None:
                    taken.add(cob)
    out = {}
    for i, n in enumerate(nodes):
        for key in ("tx_pdos", "rx_pdos"):
            for j, p in enumerate(n.get(key, [])):
                if p.get("cob_id") != "auto":
                    continue
                cob = default_cob_id(n["node_id"], p["number"], key == "tx_pdos")
                if cob is None:
                    cob = 0x57F
                    while cob > 0x180 and cob in taken:
                        cob -= 1
                    if cob == 0x180:
                        continue
                    taken.add(cob)
                out[(i, key, j)] = cob
    return out


def sdo_override(node, entry, data, linked_rpdos=()):
    """What a startup SDO overrides among the settings the plugin writes for
    the node (the same rule as the plugin's warning), or None.
    `linked_rpdos`: the node's PDO link consumer RPDOs."""
    index, sub = entry["index"], entry["subindex"]
    value = int.from_bytes(data or b"", "little")
    if 0x1400 <= index <= 0x17FF and (index & 0x1FF) + 1 in linked_rpdos:
        return "the consumer RPDO of a PDO link ('links')"
    if 0x1400 <= index <= 0x1BFF:
        return "the PDO settings (the plugin sets up every PDO of the node)"
    if sub == 0 and index == 0x1017 and "heartbeat_ms" in node and value != _uint(node["heartbeat_ms"]):
        return "heartbeat_ms"
    guard = _uint(node.get("guard_time_ms", 0)) or 0
    if sub == 0 and index == 0x100C and guard and value != guard:
        return "guard_time_ms"
    if sub == 0 and index == 0x100D and guard and value != _uint(node.get("life_time_factor", 0)):
        return "life_time_factor"
    if sub == 0 and index == 0x1012 and "time_cob_id" in node and value != _uint(node["time_cob_id"]):
        return "time_cob_id"
    if index == 0x1016 and "heartbeat_consumer" in node:
        return "heartbeat_consumer"
    if index == 0x1016 and node.get("heartbeat_watch"):
        return "heartbeat_watch"
    if index == 0x1011 and "restore_configuration" in node and sub == _uint(node["restore_configuration"]):
        return "restore_configuration"
    if index == 0x1029 and isinstance(node.get("error_behavior"), dict):
        for key, v in node["error_behavior"].items():
            if _uint(key) == sub and _uint(v) != value:
                return "error_behavior"
    return None


def plugin_owned_object(index):
    """What the plugin itself configures in this object of a node, or None
    (plugin: plugin_owned_object in config.cpp)."""
    if 0x1400 <= index <= 0x1BFF:
        return "the PDO settings"
    return {
        0x1005: "the SYNC settings", 0x1006: "the SYNC settings", 0x1007: "the SYNC settings",
        0x100C: "node guarding", 0x100D: "node guarding",
        0x1014: "the EMCY settings", 0x1015: "the EMCY settings",
        0x1016: "the heartbeat consumer", 0x1017: "the node's heartbeat setting",
        0x1F80: "the NMT start-up settings",
    }.get(index)


SYNC_NEEDED = " needs 'sync_period_us' or \"sync_source\": \"plc_cycle\" (without them the master produces no SYNC)"


def produces_sync(master):
    """Whether the master sends SYNC: a timer period or PLC-cycle SYNC (plugin: MasterConfig::produces_sync)."""
    return bool(_uint(master.get("sync_period_us", 0)) or 0) or master.get("sync_source") == "plc_cycle"


def sdo_variable_label(entry, name=""):
    return "SDO variable 0x%04X:%d" % (entry["index"], entry["subindex"]) + (" (%s)" % name if name else "")


US100_FIELDS = ("emcy_inhibit_time_us", "nmt_inhibit_time_us")


def _error_behavior(obj, where, err):
    eb = obj.get("error_behavior")
    if not isinstance(eb, dict):
        return
    for key in eb:
        sub = _uint(key)
        if sub is None or not 1 <= sub <= 254:
            err(where + ": error_behavior", 'sub-index "%s" must be 1-254' % key,
                ["%s.error_behavior" % where])


def software_files(cfg, base):
    """{software_file value: absolute path on this PC} for every node that
    names one, relative values resolved against `base`."""
    out = {}
    for n in all_nodes(cfg):
        value = n.get("software_file")
        if isinstance(value, str) and value:
            out[value] = value if os.path.isabs(value) else os.path.join(base, value)
    return out


# Adapter types and the fields only that type takes (plugin: Parser::parse_adapter).
ADAPTER_TYPES = {"socketcan": ("configure_link", "restart_ms"), "slcan": ("device", "serial_baudrate")}


def check_config(cfg, path, eds_dir=None, eds_paths=None, software_paths=None):
    """Checks a parsed config the way the plugin does at load.

    `path` names the file in messages. EDS files are found through
    `eds_paths` ({eds value: file path}) or relative to `eds_dir`
    (default: the config's directory); messages name them by their `eds`
    value. Program files (`software_file`) likewise through `software_paths`
    or relative to `eds_dir`. A version 2 file is checked network by network
    (messages and paths start with `networks[i]`), then across networks.
    Returns a Result.
    """
    r = Result()

    def _paths(where, paths):
        return paths if paths is not None else [where.replace(": ", ".")]

    def err(where, msg, paths=None):
        r.add("error", "%s: %s%s" % (path, where + ": " if where else "", msg), _paths(where, paths))

    def warn(where, msg, paths=None):
        r.add("warning", "%s: %s%s" % (path, where + ": " if where else "", msg), _paths(where, paths))

    if not isinstance(cfg, dict):
        err("", "top level must be a JSON object")
        return r

    # schema_version first: a newer format is not guessed at.
    version = 1
    if "schema_version" in cfg:
        v = _uint(cfg["schema_version"])
        if v is None or v == 0:
            err("", "field 'schema_version' must be 1 or higher")
            return r
        if v > SUPPORTED_VERSION:
            err("", "schema_version %d is not supported; the highest supported version is %d"
                % (v, SUPPORTED_VERSION))
            return r
        version = v

    s = schema(version)
    validator = jsonschema.Draft202012Validator(s)
    # Numbers written as strings are parsed first, so "0x80" meets the same
    # range check as 128.
    schema_errors = sorted(validator.iter_errors(parse_numbers(cfg, s, s)),
                           key=lambda e: list(map(str, e.absolute_path)))
    found = []
    unknown_fields(cfg, s, s, [], found)
    base = eds_dir if eds_dir is not None else os.path.dirname(os.path.abspath(path))
    sw_paths = software_paths if software_paths is not None else software_files(cfg, base)
    args = dict(path=path, base=base, eds_paths=eds_paths, sw_paths=sw_paths)

    # The CiA 309-3 gateway's object: its own checks below, in the plugin's
    # words (an unknown field there is an error, not a warning).
    found = [(where, key) for where, key in found if not CIA309_PATH.match(where)]
    schema_errors = [e for e in schema_errors if not _cia309_error(e)]
    if version == 1:
        if "cia309" in cfg:
            err("", "field 'cia309' belongs in 'master' in schema_version 1 (master.cia309), or at the top level "
                    "in schema_version 2", ["cia309"])
        # Slave networks and the gateway exist only in version 2 (canopen-
        # config-contract: "Slave network role").
        for key in V2_ONLY_KEYS:
            if key in cfg:
                err("", "field '%s' needs schema_version 2: slave networks are entries of 'networks' with "
                        "\"role\": \"slave\"" % key, [key])
        for key in J1939_V2_KEYS + ("bridge",):
            if key in cfg:
                err("", "field '%s' needs schema_version 2" % key, [key])
        found = [(where, key) for where, key in found if where not in V2_ONLY_KEYS + J1939_V2_KEYS + ("bridge",)]
        _check_network(r, cfg, "", 1, [(list(e.absolute_path), e) for e in schema_errors], **args)
    else:
        _check_v2(r, cfg, schema_errors, err, warn, args)
    check_cia309(cfg, version, err)
    if r.ok:
        _check_image(cfg, err)
    for where, key in found:
        parent = where[: -len(key)].rstrip(".")
        warn(parent, "unknown field '%s' (%s) ignored" % (key, where), [where])
    return r


# The CiA 309-3 gateway (canopen-cia309-gateway, plugin/src/can/config.cpp
# parse_cia309 and resolve_cia309).
CIA309_PATH = re.compile(r"^(master\.|networks\[\d+\]\.master\.)?cia309(\.|$)")
CIA309_FIELDS = ("port", "bind", "max_clients", "allow_changes", "allow_force", "nets", "default_net")
CIA309_DEFAULT_PORT = 7533
CIA309_BIND_MESSAGE = ("the plain gateway port listens on loopback only (127.0.0.1 or ::1), not \"%s\": CiA 309-3 "
                       "has no login; remote clients use the diagnostics channel (canworks-diag gateway)")


def _cia309_error(e):
    p = [str(x) for x in e.absolute_path]
    return bool(p) and (p[0] == "cia309" or (len(p) > 1 and p[0] == "master" and p[1] == "cia309") or (
        len(p) > 3 and p[0] == "networks" and p[2] == "master" and p[3] == "cia309"))


def cia309_numbering(cfg):
    """The CiA 309-3 network numbers of a config: [(number, network name,
    network index)], `nets` when given, else 1..n in config order (as the
    plugin numbers them). [] without a cia309 object."""
    g = cia309_object(cfg)
    if g is None:
        return []
    index = {n["name"]: n["index"] for n in networks(cfg)}
    nets = g.get("nets") if isinstance(g, dict) else None
    if isinstance(nets, dict) and version_of(cfg) > 1:
        out = []
        for key, name in nets.items():
            if isinstance(key, str) and key.isdigit() and name in index:
                out.append((int(key), name, index[name]))
        return sorted(out)
    return [(i + 1, n["name"], n["index"]) for i, n in enumerate(networks(cfg))]


def cia309_object(cfg):
    """The cia309 object (top level in version 2, master.cia309 in version
    1), or None."""
    if not isinstance(cfg, dict):
        return None
    if version_of(cfg) > 1:
        return cfg.get("cia309")
    master = cfg.get("master")
    return master.get("cia309") if isinstance(master, dict) else None


def check_cia309(cfg, version, err):
    """The plugin's cia309 rules (canopen-cia309-gateway "CiA 309-3 gateway
    is opt-in")."""
    if version > 1:
        for i, net in enumerate(cfg.get("networks") or []):
            if isinstance(net, dict) and isinstance(net.get("master"), dict) and "cia309" in net["master"]:
                err("networks[%d]: master" % i, "field 'cia309' is a top-level object in schema_version 2, not part "
                                                "of a network's master", ["networks[%d].master.cia309" % i])
        g = cfg.get("cia309")
        w = "cia309"
    else:
        master = cfg.get("master")
        g = master.get("cia309") if isinstance(master, dict) else None
        w = "master.cia309"
    if g is None:
        return
    if not isinstance(g, dict):
        err(w.rpartition(".")[0], "field 'cia309' must be an object", [w])
        return
    for key in g:
        if key not in CIA309_FIELDS:
            err(w, "unknown field '%s'" % key, [w + "." + key])
    port = _uint(g.get("port", CIA309_DEFAULT_PORT))
    if "port" in g and (port is None or port > 65535 or (port != 0 and port < 1024)):
        err(w, "field 'port' must be 0 (no plain port) or 1024-65535", [w + ".port"])
    if "bind" in g:
        bind = g["bind"]
        if not isinstance(bind, str) or not bind:
            err(w, "field 'bind' must be a non-empty string", [w + ".bind"])
        elif bind not in ("127.0.0.1", "::1"):
            err(w + ".bind", CIA309_BIND_MESSAGE % bind, [w + ".bind"])
    if "max_clients" in g:
        v = _uint(g["max_clients"])
        if v is None or not 1 <= v <= 16:
            err(w, "field 'max_clients' must be 1-16", [w + ".max_clients"])
    for key in ("allow_changes", "allow_force"):
        if key in g and not isinstance(g[key], bool):
            err(w, "field '%s' must be true or false" % key, [w + "." + key])
    names = [n["name"] for n in networks(cfg)]
    numbers = {}
    nets = g.get("nets")
    if "nets" in g:
        if version == 1:
            err(w, "field 'nets' needs schema_version 2 (a version 1 file has one network, number 1)", [w + ".nets"])
        elif not isinstance(nets, dict):
            err(w, "field 'nets' must be an object of network numbers and names, like {\"1\": \"io\"}", [w + ".nets"])
        else:
            seen = {}
            for key, name in nets.items():
                if not isinstance(name, str) or not name:
                    err(w + ".nets", "network %s must name a network" % key, [w + ".nets." + key])
                    continue
                if not (key.isdigit() and key[0] != "0" and len(key) <= 3 and 1 <= int(key) <= 127):
                    err(w + ".nets", "\"%s\" is not a network number 1-127" % key, [w + ".nets." + key])
                    continue
                if name not in names:
                    err(w + ".nets", "network %s names \"%s\", which is not a network of this file" % (key, name),
                        [w + ".nets." + key])
                    continue
                if name in seen:
                    err(w + ".nets", "network \"%s\" has two numbers (%s and %s)" % (name, seen[name], key),
                        [w + ".nets." + key])
                    continue
                seen[name] = key
                numbers[int(key)] = name
    if not ("nets" in g and isinstance(nets, dict) and version > 1):
        numbers = {i + 1: n for i, n in enumerate(names)}
    if "default_net" in g:
        v = _uint(g["default_net"])
        if v is None or not 1 <= v <= 127:
            err(w, "field 'default_net' must be 1-127", [w + ".default_net"])
        elif v not in numbers:
            listed = ", ".join("%d = %s" % (k, numbers[k] or "the network") for k in sorted(numbers)) or "none"
            err(w, "field 'default_net' is %d, which is not a gateway network number (%s)" % (v, listed),
                [w + ".default_net"])
    d = cfg.get("diagnostics") if version > 1 else (cfg.get("master") or {}).get("diagnostics")
    if isinstance(d, dict) and port and _uint(d.get("port", 7531)) == port:
        err(w, "field 'port' %d is the diagnostics channel's port; give the gateway another one (default 7533)" % port,
            [w + ".port"])


# Top-level keys a version 1 file may not have.
V2_ONLY_KEYS = ("role", "slave", "gateway")
J1939_V2_KEYS = ("protocol", "j1939", "raw")

MOVED_V1_KEYS = (("adapter", "networks[].adapter"), ("master", "networks[].master"), ("nodes", "networks[].nodes"),
                 ("interface", "networks[].adapter.interface"), ("bitrate", "networks[].adapter.bitrate"))


def _check_image(cfg, err):
    """Every location inside the runtime's I/O image, as the plugin checks
    it (Parser::get_location): index below IMAGE_ENTRIES, or in a bridge
    config, all its bytes below bridgecheck.IMAGE_BYTES."""
    byte_mode = "bridge" in cfg
    limit = bridgecheck.IMAGE_BYTES if byte_mode else IMAGE_ENTRIES
    for net in networks(cfg):
        for _, _, at, text in location_uses(net):
            loc = parse_location(text)
            if loc is None:
                continue
            if byte_mode and loc.index + bridgecheck.SIZE_BYTES[loc.size] <= limit:
                continue
            if not byte_mode and loc.index < limit:
                continue
            err("", "%s: %s lies outside the runtime I/O image (index must be below %d)" % (at, loc, limit), [at])


def _check_v2(r, cfg, schema_errors, err, warn, args):
    """A version 2 file: the top level, each network (master or slave), then
    the checks across networks (canopen-networks spec) and the gateway
    (canopen-gateway spec)."""
    for key, where in MOVED_V1_KEYS:
        if key in cfg:
            err("", "field '%s' belongs in %s in schema_version 2" % (key, where), [key])
    nets = cfg.get("networks")
    if not isinstance(nets, list):
        err("", "missing required field 'networks' (an array)", ["networks"])
        return
    if not nets:
        err("", "field 'networks' lists no networks", ["networks"])
    if len(nets) > MAX_NETWORKS:
        err("", "field 'networks' lists %d networks; at most %d are supported" % (len(nets), MAX_NETWORKS),
            ["networks"])
    by_net = {}
    for e in schema_errors:
        p = list(e.absolute_path)
        if len(p) >= 2 and p[0] == "networks" and isinstance(p[1], int):
            by_net.setdefault(p[1], []).append((p[2:], e))
            continue
        if p[:1] == ["bridge"]:
            continue  # the bridge checks below give the plugin's words
        where = json_path(p)
        if where == "" and e.validator in ("not", "required"):
            continue  # moved keys and a missing networks list, reported above
        if where == "networks" and e.validator in ("minItems", "maxItems", "type"):
            continue  # reported above
        if where == "schema_version":
            err("", "field 'schema_version' must be 2 in a file with 'networks'", ["schema_version"])
            continue
        err(where, plain_schema_message(e, schema(2)))
    diag = isinstance(cfg.get("diagnostics"), dict)
    routed = routed_entries(cfg)
    slaves = {}
    for i, net in enumerate(nets):
        prefix = "networks[%d]" % i
        if not isinstance(net, dict):
            err(prefix, "must be an object", [prefix])
            continue
        before = len(r.errors)
        j1939 = is_j1939(net)
        plain = net.get("protocol") == "none"
        if "protocol" in net and net["protocol"] not in ("canopen", "j1939", "none"):
            err(prefix, 'field \'protocol\' must be "canopen", "j1939" or "none"', [prefix + ".protocol"])
        role = "j1939" if j1939 else "plain" if plain else "slave" if net.get("role") == "slave" else "master"
        if plain:
            for key in CANOPEN_KEYS + ("j1939",):
                if key in net:
                    err(prefix, "field '%s' does not belong to a plain CAN network (\"protocol\": \"none\"), which "
                                "has only 'adapter' and 'raw'" % key, [prefix + "." + key])
        elif j1939:
            for key in CANOPEN_KEYS:
                if key in net:
                    err(prefix, "field '%s' belongs to a CANopen network; a J1939 network has 'j1939'" % key,
                        [prefix + "." + key])
        elif "j1939" in net:
            err(prefix, 'field \'j1939\' belongs to a J1939 network ("protocol": "j1939")', [prefix + ".j1939"])
        if j1939 or plain:
            pass
        elif role == "slave":
            for key in ("master", "nodes"):
                if key in net:
                    err(prefix, "field '%s' belongs to a master network; a slave network (\"role\": \"slave\") has "
                                "'slave' instead" % key, [prefix + "." + key])
        elif "slave" in net:
            err(prefix, "field 'slave' belongs to a slave network: give the network \"role\": \"slave\" (a master "
                        "network has 'master' and 'nodes')", [prefix + ".slave"])
        if "links" in net and role != "master":
            err(prefix, "field 'links' needs a CANopen master network; this is a %s network"
                % {"j1939": "J1939", "plain": "plain CAN", "slave": "slave"}[role], [prefix + ".links"])
        for key in ("interface", "bitrate"):
            if key in net:
                err(prefix, "field '%s' belongs in 'adapter' in schema_version 2" % key, [prefix + "." + key])
        name = net.get("name")
        if "name" in net and not (isinstance(name, str) and NETWORK_NAME.match(name)):
            err(prefix, 'network name "%s" must start with a letter and hold only letters, digits and \'_\', at '
                        "most 16 characters" % name, [prefix + ".name"])
        master = net.get("master")
        if isinstance(master, dict) and "diagnostics" in master:
            err(prefix + ": master", "field 'diagnostics' is a top-level object in schema_version 2, not part of a "
                                     "network's master", [prefix + ".master.diagnostics"])
        errors = [(p, e) for p, e in by_net.get(i, []) if not (
            (p == ["name"] and e.validator == "pattern") or
            (p == [] and e.validator == "not") or
            (p == ["master"] and e.validator == "not") or
            p[:1] == ["protocol"] or
            # The raw object's own checks give the plugin's words.
            p[:1] == ["raw"] or
            (p == ["adapter"] and e.validator == "not") or
            (plain and (not p or p[0] in ("j1939",) + CANOPEN_KEYS)) or
            # A J1939 network's own checks below give the plugin's words for
            # everything but its adapter; a CANopen network's j1939 object is
            # reported above.
            (j1939 and (not p or p[0] in ("j1939",) + CANOPEN_KEYS)) or
            (not j1939 and p[:1] == ["j1939"]))]
        adapter = net.get("adapter") if isinstance(net.get("adapter"), dict) else {}
        name = net.get("name") if isinstance(net.get("name"), str) and net.get("name") else adapter.get("interface")
        _check_network(r, net, prefix, 2, errors, diag=diag, before=before, role=role, routed=routed,
                       net_name=name if isinstance(name, str) else "", slaves=slaves, net_index=i, **args)
        raw_errors, raw_warnings, _ = raw_contract.check_raw(net.get("raw"), prefix + ".raw",
                                                             adapter.get("listen_only") is True)
        for m in raw_errors:
            r.add("error", "%s: %s" % (args["path"], m), [_raw_path(m)])
        for m in raw_warnings:
            r.add("warning", "%s: %s" % (args["path"], m), [_raw_path(m)])
        iface = adapter.get("interface")
        if "name" not in net and isinstance(iface, str) and iface and not NETWORK_NAME.match(iface):
            err(prefix, 'interface "%s" is not usable as a network name; give the network a \'name\'' % iface,
                [prefix + ".adapter.interface"])
    bridge_uses = bridgecheck.check_bridge(cfg, networks(cfg), err, warn) if "bridge" in cfg else None
    _check_across_networks(r, cfg, err, bridge_uses)
    # Sent raw messages on identifiers the protocol uses (after the checks
    # across networks, as in the plugin).
    for n in networks(cfg):
        raw = n["json"].get("raw")
        if not isinstance(raw, dict) or not raw.get("tx"):
            continue
        listen = n["adapter"].get("listen_only") is True
        e1, _, _ = raw_contract.check_raw(raw, n["path"] + ".raw", listen)
        if e1:
            continue  # reported above
        errs, _, _ = raw_contract.check_raw(raw, n["path"] + ".raw", listen, ownership.protocol_use(n))
        for m in errs:
            r.add("error", "%s: %s" % (args["path"], m), [_raw_path(m)])
    # The gateway's own checks read the section's fields, so they run only
    # once its shape is right (the schema errors above say what is not).
    if "gateway" in cfg and not any(list(e.absolute_path)[:1] == ["gateway"] for e in schema_errors):
        _check_gateway(cfg, err, warn, slaves)


def _raw_path(message):
    """The JSON path a raw check message starts with."""
    return message.split(":", 1)[0]


def routed_entries(cfg):
    """{(network name, node ID, index, subindex)} of every field PDO entry a
    gateway route names: only these may leave out iec_location."""
    out = set()
    g = cfg.get("gateway") if isinstance(cfg, dict) else None
    for rt in (g.get("routes") if isinstance(g, dict) and isinstance(g.get("routes"), list) else []):
        f = rt.get("field") if isinstance(rt, dict) else None
        if isinstance(f, dict):
            out.add((f.get("network"), _uint(f.get("node")), _uint(f.get("index")), _uint(f.get("subindex", 0))))
    return out


def _check_across_networks(r, cfg, err, bridge_uses=None):
    nets = networks(cfg)
    names, ifaces, devices, simulated = {}, {}, {}, {}
    label = {n["index"]: "networks[%d]" % n["index"] + (" (%s)" % n["name"] if n["name"] else "") for n in nets}
    for n in nets:
        me = "networks[%d]" % n["index"]
        if n["name"]:
            key = n["name"].lower()
            if key in names:
                err("networks", 'networks[%d] and %s are both named "%s" (names must differ, ignoring case)'
                    % (names[key], me, n["name"]), ["networks[%d].name" % names[key], me + ".name"])
            else:
                names[key] = n["index"]
        a = n["adapter"]
        iface = a.get("interface")
        if isinstance(iface, str) and iface and a.get("simulate") is True:
            # Simulated networks with one interface name share one in-process
            # bus: one master network and one slave network at most.
            bus = simulated.setdefault(iface, {})
            if n["role"] in bus:
                err("networks", "%s and %s are both %s networks on simulated bus %s (a simulated bus takes one master "
                                "network and one slave network)"
                    % (label[bus[n["role"]]], label[n["index"]], n["role"], iface),
                    ["networks[%d].adapter.interface" % bus[n["role"]], me + ".adapter.interface"])
            else:
                bus[n["role"]] = n["index"]
        elif isinstance(iface, str) and iface:
            if iface in ifaces:
                err("networks", "%s and %s both use interface %s" % (label[ifaces[iface]], label[n["index"]], iface),
                    ["networks[%d].adapter.interface" % ifaces[iface], me + ".adapter.interface"])
            else:
                ifaces[iface] = n["index"]
        dev = a.get("device")
        if a.get("type") == "slcan" and isinstance(dev, str) and dev:
            if dev in devices:
                err("networks", "%s and %s both use serial device %s" % (label[devices[dev]], label[n["index"]], dev),
                    ["networks[%d].adapter.device" % devices[dev], me + ".adapter.device"])
            else:
                devices[dev] = n["index"]
    # On a shared simulated bus the master's node for the slave network is the
    # plugin's own slave: a simulated device with that node ID would answer
    # next to it.
    for sl in nets:
        sa, ss = sl["adapter"], sl["slave"]
        iface = sa.get("interface")
        nid = ss.get("node_id")
        if sl["role"] != "slave" or sa.get("simulate") is not True or not isinstance(iface, str) or not iface \
                or isinstance(nid, bool) or not isinstance(nid, int):
            continue
        for m in nets:
            ma = m["adapter"]
            if m["role"] != "master" or ma.get("simulate") is not True or ma.get("interface") != iface:
                continue
            for j, node in enumerate(m["nodes"]):
                if not isinstance(node, dict) or _uint(node.get("node_id")) != nid:
                    continue
                if node.get("simulate", True) is not False:
                    err("networks", '%s node %d is %s on simulated bus %s; set "simulate": false on the node, or the '
                                    'simulator answers in its place' % (label[m["index"]], nid, label[sl["index"]], iface),
                        ["networks[%d].nodes[%d].simulate" % (m["index"], j)])
    uses = []
    for n in nets:
        who = "networks[%d]" % n["index"] + (" (%s)" % n["name"] if n["name"] else "")
        uses += location_uses(n, who + " ")
    if bridge_uses is not None:
        # A bridge config is byte-addressed (modbus-bridge).
        located = [(parse_location(text), who, at, None) for _, who, at, text in uses] + bridge_uses
        bridgecheck.report_byte_overlaps(located, "networks", err)
        return
    for i, a in enumerate(uses):
        for b in uses[i + 1:]:
            if a[0] == b[0]:
                err("networks", "%s and %s both map to %s" % (a[1], b[1], a[3]), [a[2], b[2]])


def location_uses(net, prefix=""):
    """Every IEC location of one network as (key, who, JSON path, text), named
    as the plugin names them; key compares equal for the same variable."""
    out = []
    base = net["path"] + "." if net["path"] else ""

    def add(text, who, at):
        loc = parse_location(text)
        if loc is not None:
            out.append(((loc.area, loc.size, loc.element), prefix + who, base + at, str(loc)))

    # Raw messages first, named by their place in the file as the plugin does.
    raw = (net.get("json") or {}).get("raw")
    if net["path"] and isinstance(raw, dict):
        for text, at in raw_contract.locations(raw, net["path"] + ".raw"):
            loc = parse_location(text)
            if loc is not None:
                out.append(((loc.area, loc.size, loc.element), at, at, str(loc)))
    if net.get("role") == "plain":
        return out
    if net.get("role") == "j1939":
        _j1939_location_uses(net.get("j1939") or {}, add)
        return out
    s = net.get("slave") or {}
    for key in SLAVE_LOCATION_KEYS:
        if key in s:
            add(s[key], "slave " + key, "slave." + key)
    for j, o in enumerate(s.get("objects") if isinstance(s.get("objects"), list) else []):
        if isinstance(o, dict):
            add(o.get("iec_location"), "slave object %s" % object_text(_uint(o.get("index")) or 0,
                                                                     _uint(o.get("subindex")) or 0)
                + (" (%s)" % o["name"] if o.get("name") else ""), "slave.objects[%d].iec_location" % j)
    m = net["master"]
    for key in ("bus_state_location", "tx_error_count_location", "rx_error_count_location", "bus_off_count_location",
                "state_location"):
        if key in m:
            add(m[key], "master " + key, "master." + key)
    for i, n in enumerate(net["nodes"]):
        if not isinstance(n, dict):
            continue
        nid = _uint(n.get("node_id"))
        label = "node %s" % nid + (" (%s)" % n["name"] if n.get("name") else "")
        w = "nodes[%d]" % i
        for key in ("status_location", "state_location", "boot_error_location", "emcy_code_location",
                    "error_register_location", "nmt_command_location"):
            if key in n:
                add(n[key], label + " " + key, w + "." + key)
        for j, v in enumerate(n.get("sdo_variables", [])):
            entry = {"index": _uint(v.get("index")) or 0, "subindex": _uint(v.get("subindex", 0)) or 0}
            who = label + " " + sdo_variable_label(entry, v.get("name", ""))
            vw = "%s.sdo_variables[%d]" % (w, j)
            add(v.get("iec_location"), who, vw + ".iec_location")
            for key in ("trigger_location", "status_location", "abort_code_location"):
                if key in v:
                    add(v[key], who + " " + key, vw + "." + key)
        for j, p in enumerate(n.get("tx_pdos", [])):
            if "timeout_location" in p:
                add(p["timeout_location"], "%s TPDO %s timeout_location" % (label, _uint(p.get("number", j + 1))),
                    "%s.tx_pdos[%d].timeout_location" % (w, j))
        for key, kind in (("tx_pdos", "TPDO"), ("rx_pdos", "RPDO")):
            for j, p in enumerate(n.get(key, [])):
                number = _uint(p.get("number", j + 1))
                for k, e in enumerate(p.get("entries", [])):
                    add(e.get("iec_location"), "%s %s %s object 0x%04X:%d" % (
                        label, kind, number, _uint(e.get("index")) or 0, _uint(e.get("subindex", 0)) or 0),
                        "%s.%s[%d].entries[%d].iec_location" % (w, key, j, k))
    return out


def _j1939_location_uses(j, add):
    """location_uses() of a J1939 network, in the plugin's order and words."""
    ecu = j.get("ecu") if isinstance(j.get("ecu"), dict) else {}
    for key, who in (("state_location", "ECU state"), ("address_location", "ECU address")):
        if key in ecu:
            add(ecu[key], who, "j1939.ecu." + key)
    for key in ("rx", "tx"):
        for i, m in enumerate(j.get(key) if isinstance(j.get(key), list) else []):
            if not isinstance(m, dict):
                continue
            pgn = _uint(m.get("pgn"))
            who, at = "PGN %s" % pgn, "j1939.%s[%d]" % (key, i)
            if key == "rx" and "status_location" in m:
                add(m["status_location"], who + " status_location", at + ".status_location")
            for k, s in enumerate(m.get("signals") if isinstance(m.get("signals"), list) else []):
                if not isinstance(s, dict):
                    continue
                sig = "%s signal %s" % (who, s.get("name"))
                add(s.get("iec_location"), sig, "%s.signals[%d].iec_location" % (at, k))
                if key == "rx" and "valid_location" in s:
                    add(s["valid_location"], sig + " valid_location", "%s.signals[%d].valid_location" % (at, k))
    d = j.get("diagnostics") if isinstance(j.get("diagnostics"), dict) else {}
    for i, m in enumerate(d.get("rx") if isinstance(d.get("rx"), list) else []):
        if not isinstance(m, dict):
            continue
        who, at = "diagnostics rx[%d]" % i, "j1939.diagnostics.rx[%d]" % i
        for key in ("status_location", "lamps_location", "flash_location", "count_location"):
            if key in m:
                add(m[key], who + " " + key, at + "." + key)
        n = _uint(m.get("dtcs"))
        loc = parse_location(m["dtcs_location"]) if isinstance(m.get("dtcs_location"), str) else None
        if loc is not None and loc.size == "D" and n:
            for k in range(min(n, J1939_MAX_DM_RX_CODES)):
                add("%%%sD%d" % (loc.area, loc.index + k), "%s code %d" % (who, k), at + ".dtcs_location")
    for i, c in enumerate(d.get("dtcs") if isinstance(d.get("dtcs"), list) else []):
        if isinstance(c, dict) and "active_location" in c:
            add(c["active_location"], "diagnostics SPN %s FMI %s active_location" % (_uint(c.get("spn")),
                                                                                    _uint(c.get("fmi"))),
                "j1939.diagnostics.dtcs[%d].active_location" % i)
    for key in ("lamps_location", "clear_location"):
        if key in d:
            add(d[key], "diagnostics " + key, "j1939.diagnostics." + key)


def _check_network(r, cfg, prefix, version, schema_errors, path, base, eds_paths, sw_paths, diag=False, before=None,
                   role="master", routed=(), net_name="", slaves=None, net_index=0):
    """One network: the version 1 top level, or one networks[] entry of a
    version 2 file (`prefix` "networks[i]", in front of every message's
    place and every path). `schema_errors`: (path inside the network,
    error). A slave network (`role` "slave") gets the slave checks, and its
    EDS and bindings go into `slaves` under `net_index` for the gateway
    check. `routed` holds the field entries gateway routes name
    (routed_entries()), which may leave out iec_location."""
    if before is None:
        before = len(r.errors)

    def full(where):
        if not prefix:
            return where
        return prefix + (": " + where if where else "")

    def _paths(where, paths):
        ps = paths if paths is not None else [where.replace(": ", ".")]
        if not prefix:
            return ps
        return [prefix + ("." + p if p else "") for p in ps if p is not None]

    def err(where, msg, paths=None):
        w = full(where)
        r.add("error", "%s: %s%s" % (path, w + ": " if w else "", msg), _paths(where, paths))

    def warn(where, msg, paths=None):
        w = full(where)
        r.add("warning", "%s: %s%s" % (path, w + ": " if w else "", msg), _paths(where, paths))

    def add(level, msg, paths):
        r.add(level, (prefix + ": " if prefix else "") + msg, _paths("", paths))

    if not isinstance(cfg, dict):
        return
    # Adapter and the pre-contract keys.
    has_adapter = "adapter" in cfg
    old_iface, old_rate = "interface" in cfg, "bitrate" in cfg
    if has_adapter and (old_iface or old_rate):
        err("", "give either 'adapter' or the deprecated top-level '%s', not both"
            % ("interface" if old_iface else "bitrate"))
    elif has_adapter:
        a = cfg["adapter"]
        kind = a.get("type") if isinstance(a, dict) else None
        if isinstance(kind, str) and kind and kind not in ADAPTER_TYPES:
            err("adapter", 'adapter type "%s" is not supported (supported: %s)' % (kind, ", ".join(ADAPTER_TYPES)))
        elif kind in ADAPTER_TYPES:
            for other, fields in ADAPTER_TYPES.items():
                for f in fields if other != kind else ():
                    if f in a:
                        err("adapter", "field '%s' does not apply to adapter type %s" % (f, kind), ["adapter." + f])
            for f in ("interface", "bitrate") + (("device",) if kind == "slcan" else ()):
                if f not in a or a[f] == "":
                    err("adapter", "the %s is missing" % field_name(f), ["adapter." + f])
            if kind == "slcan":
                if isinstance(a.get("device"), str) and a["device"] and not a["device"].startswith("/"):
                    err("adapter", "field 'device' must be an absolute path such as /dev/ttyACM0", ["adapter.device"])
    iface_msg = interface_message((cfg["adapter"] if has_adapter and isinstance(cfg["adapter"], dict) else
                                   {} if has_adapter else cfg).get("interface"))
    if iface_msg:
        err("adapter" if has_adapter else "", iface_msg, ["adapter.interface" if has_adapter else "interface"])
    if has_adapter and isinstance(cfg["adapter"], dict) and cfg["adapter"].get("listen_only") is True \
            and role != "plain":
        err("adapter", "field 'listen_only' needs a plain CAN network (\"protocol\": \"none\"): a %s network must "
                       "send" % ("J1939" if role == "j1939" else "CANopen"), ["adapter.listen_only"])
    if has_adapter:
        pass
    elif old_iface or old_rate:
        warn("", "top-level 'interface' and 'bitrate' are deprecated; move them into "
                 '"adapter": {"type": "socketcan", ...}')
    else:
        err("", "missing required field 'adapter'")

    # The EDS lint setting and its pre-contract alias, in the plugin's words.
    master_in = cfg.get("master")
    if isinstance(master_in, dict):
        if "eds_lint" in master_in and "strict_eds" in master_in:
            err("master", "give either 'eds_lint' or the deprecated 'strict_eds', not both",
                ["master.eds_lint", "master.strict_eds"])
        if "eds_lint" in master_in and master_in["eds_lint"] not in edslint.MODES:
            err("master", "field 'eds_lint' must be \"communication\", \"all\" or \"off\"", ["master.eds_lint"])

    # The schema, with one message per problem at its JSON path.
    for rel, e in schema_errors:
        first = e
        while e.context:
            # Of the alternatives, the one for the value's own type says what
            # is wrong with it ("200 is greater than the maximum of 127").
            fitting = [c for c in e.context if c.validator != "type"]
            e = best_match(fitting or e.context)
        where = json_path(rel)
        if where in ("", "adapter") and e.validator in ("oneOf", "not", "required", "enum") and (
                "adapter" in e.message or "interface" in e.message or "bitrate" in e.message
                or "device" in e.message or e.validator == "not" or "socketcan" in e.message):
            continue  # reported above, in the plugin's words
        if where == "adapter.device" and e.validator == "pattern":
            continue
        if where in ("adapter.interface", "adapter.device") and e.validator == "minLength":
            continue  # reported above as missing
        if where in ("adapter.interface", "interface") and e.validator in ("pattern", "maxLength"):
            continue  # reported above, in the plugin's words
        if where in ("master.on_plc_stop", "master.scan_watchdog_ms"):
            continue  # reported below, in the plugin's words
        if (where == "master" and e.validator == "not") or where == "master.eds_lint":
            continue  # reported above
        if where.endswith("diagnostics.token_sha256"):
            err(where, "the diagnostics channel is encrypted now and needs a 'token_verifier' instead: set the token "
                       "again (configurator: Online access, Upgrade or New token; or canworks-diag hash-token)")
            continue
        if where.endswith("diagnostics") and e.validator == "required" and "token_verifier" in e.message:
            d = cfg.get("diagnostics") if where == "diagnostics" else (cfg.get("master") or {}).get("diagnostics")
            if isinstance(d, dict) and "token_sha256" in d:
                continue  # reported as token_sha256
        if where.endswith("diagnostics.token_verifier") and e.validator == "pattern":
            err(where, "field 'token_verifier' must look like SCRAM-SHA-256$<iterations>:<salt>$<StoredKey>:"
                       "<ServerKey> (canworks-diag hash-token prints it)")
            continue
        if ".remote_link.relays[" in where and e.validator == "pattern":
            err(where, "relay URLs must use https, like https://relay.example.com")
            continue
        if role == "slave" and where.split(".")[0].split("[")[0] in ("master", "nodes"):
            continue  # misplaced in a slave network, reported by _check_v2
        if (where == "master" and e.validator == "required" and "'diagnostics'" in e.message) or (
                version > 1 and where == "nodes" and e.validator == "minItems"):
            # The schema's rule for an empty node list, in the plugin's words.
            err("", "field 'nodes' lists no slave nodes (an empty list needs %s, for a scan-only configuration)"
                % ("master.diagnostics" if version == 1 else "a top-level 'diagnostics'"), ["nodes"])
            continue
        if re.match(r"^links\[\d+\]\.to\[\d+\]\.entries\[\d+\]$", where) and e.validator == "not":
            full_path = (prefix + "." if prefix else "") + where + ".iec_location"
            err(where.replace(".", ": "), "field 'iec_location' (%s) does not belong to a link consumer's entry: the "
                                          "consumer receives the value from the producer, not from the PLC"
                % full_path, [where + ".iec_location"])
            continue
        pdo_msg = _pdo_schema_message(cfg, list(rel), e)
        if pdo_msg:
            err(pdo_msg[0], pdo_msg[1], [where])
            continue
        err(where, plain_schema_message(first, schema(version)))

    if role == "plain":
        return

    if role == "j1939":
        a = cfg.get("adapter")
        if isinstance(a, dict) and a.get("simulate") is True:
            err("", J1939_SIMULATE, ["adapter.simulate"])
        check_j1939(cfg, err, warn)
        return

    # The verifier's numbers, which the schema's pattern does not check.
    d = cfg.get("diagnostics") if version > 1 else (cfg.get("master") or {}).get("diagnostics")
    if isinstance(d, dict) and isinstance(d.get("token_verifier"), str) and re.match(
            r"^SCRAM-SHA-256\$[0-9]{1,7}:", d["token_verifier"]):
        from . import diag
        if diag.parse_verifier(d["token_verifier"]) is None:
            where = "diagnostics" if version > 1 else "master.diagnostics"
            err(where, "field 'token_verifier' needs iterations 4096-1000000 and a salt of at least 16 bytes",
                [where + ".token_verifier"])

    if len(r.errors) > before:
        return

    if role == "slave":
        got = _check_slave(cfg["slave"], err, add, base, eds_paths)
        if got is not None and len(r.errors) == before and slaves is not None:
            slaves[net_index] = got
        return

    # Schema-valid from here on: normalise numbers and run the plugin's
    # cross-field checks.
    master = cfg["master"]
    master_id = _uint(master["node_id"])
    for f in US100_FIELDS:
        v = _uint(master.get(f, 0))
        if v % 100:
            err("master", "field '%s' must be a multiple of 100: %d" % (f, v), ["master." + f])
    if _uint(master.get("sync_counter_overflow", 0)) == 1 or (_uint(master.get("sync_counter_overflow", 0)) or 0) > 240:
        err("master", "field 'sync_counter_overflow' must be 0 (no counter) or 2-240", ["master.sync_counter_overflow"])
    plc_cycle = master.get("sync_source") == "plc_cycle"
    if "sync_cycles" in master and not plc_cycle:
        err("master", "field 'sync_cycles' needs \"sync_source\": \"plc_cycle\"", ["master.sync_cycles"])
    if plc_cycle and (_uint(master.get("sync_period_us", 0)) or 0):
        err("master", "field 'sync_period_us' cannot be used with \"sync_source\": \"plc_cycle\": the SYNC period "
                      "comes from the PLC cycle", ["master.sync_period_us", "master.sync_source"])
    if plc_cycle and "sync_cycles" in master and not 1 <= (_uint(master["sync_cycles"]) or 0) <= 1000:
        err("master", "field 'sync_cycles' must be 1-1000", ["master.sync_cycles"])
    # Neither a timer period nor PLC-cycle SYNC: the master produces no SYNC.
    sync_period = produces_sync(master)
    if not sync_period:
        for f in ("sync_window_us", "sync_counter_overflow"):
            if f in master:
                err("master", "field '%s'%s" % (f, SYNC_NEEDED), ["master." + f, "master.sync_period_us"])
    sdo_timeout = _uint(master.get("sdo_timeout_ms", 1000))
    if sdo_timeout is not None and not 10 <= sdo_timeout <= 60000:
        err("master", "field 'sdo_timeout_ms' must be 10-60000: %d" % sdo_timeout, ["master.sdo_timeout_ms"])
    if "time_period_ms" in master:
        time_period = _uint(master["time_period_ms"])
        if time_period is not None and not 100 <= time_period <= 3600000:
            err("master", "field 'time_period_ms' must be 100-3600000: %d" % time_period, ["master.time_period_ms"])
        elif not any((_uint(n.get("time_cob_id", 0)) or 0) & 0x80000000 for n in cfg.get("nodes", [])):
            warn("master", "the master produces TIME, but no configured node is set to consume it (time_cob_id "
                           "with bit 31)", ["master.time_period_ms"])
    if "on_plc_stop" in master and master["on_plc_stop"] not in ON_PLC_STOP:
        err("master", "field 'on_plc_stop' must be \"preop\", \"stop\" or \"keep\"", ["master.on_plc_stop"])
    if "scan_watchdog_ms" in master:
        watchdog = _uint(master["scan_watchdog_ms"])
        if watchdog is None:
            err("master", "field 'scan_watchdog_ms' must be a non-negative integer", ["master.scan_watchdog_ms"])
        elif watchdog and not 10 <= watchdog <= 60000:
            err("master", "field 'scan_watchdog_ms' must be 0 or 10-60000: %d" % watchdog, ["master.scan_watchdog_ms"])
    _error_behavior(master, "master", err)
    if master.get("start") is False:
        warn("master", "'start' is false: the master stays PRE-OPERATIONAL and no PDOs are exchanged until it is "
                       "started", ["master.start"])
    master_hb = _uint(master.get("heartbeat_ms", 0)) or 0
    links = links_mod.parse(cfg)
    linked_tx = {(l["producer"], l["tpdo"]) for l in links}
    linked_rx = links_mod.linked_rpdos(cfg)
    nodes = []
    seen = {}
    for i, n in enumerate(cfg["nodes"]):
        node = {"node_id": _uint(n["node_id"]), "name": n.get("name", ""), "eds": n["eds"],
                "tx_pdos": [], "rx_pdos": [], "sdo": [], "sdo_variables": [],
                "heartbeat_consumer": n.get("heartbeat_consumer") is True,
                "config_check": n.get("config_check") is True, "no_sync": not sync_period}
        label = "node %d" % node["node_id"] + (" (%s)" % node["name"] if node["name"] else "")
        w = "nodes[%d]" % i
        if "heartbeat_ms" in n and _uint(n["heartbeat_ms"]) == 0 and not _uint(n.get("guard_time_ms", 0)):
            warn(w, "%s: \"heartbeat_ms\": 0 and no guarding: its loss is not detected" % label, [w + ".heartbeat_ms"])
        if n.get("heartbeat_consumer") is True and not master_hb:
            err(w, "'heartbeat_consumer' needs a master heartbeat (master 'heartbeat_ms' above 0)",
                [w + ".heartbeat_consumer"])
        if "heartbeat_timeout_ms" in n:
            hb, timeout = _uint(n.get("heartbeat_ms", 0)) or 0, _uint(n["heartbeat_timeout_ms"])
            if not hb:
                err(w, "the heartbeat timeout needs a heartbeat period", [w + ".heartbeat_timeout_ms"])
            elif timeout < hb:
                err(w, "the heartbeat timeout (%d ms) must not be shorter than the heartbeat period (%d ms)"
                    % (timeout, hb),
                    [w + ".heartbeat_timeout_ms", w + ".heartbeat_ms"])
        _error_behavior(n, w, err)
        sw = n.get("software_file")
        if sw:
            file = sw_paths.get(sw) or os.path.join(base, sw)
            if not os.path.isfile(file):
                err(w, '%s: software_file "%s" not found (looked at %s)' % (label, sw, file), [w + ".software_file"])
            if "software_version" not in n:
                warn(w, "%s: 'software_file' without 'software_version': the master never downloads it" % label,
                     [w + ".software_file"])
        elif "software_version" in n:
            err(w, "%s: 'software_version' needs 'software_file'" % label, [w + ".software_version"])
        if "store_configuration" in n:
            store = _uint(n["store_configuration"])
            if store is None or not 1 <= store <= 127:
                err(w, "%s: field 'store_configuration' must be a 0x1010 sub-index 1-127: %s"
                    % (label, n["store_configuration"]), [w + ".store_configuration"])
            elif n.get("config_check") is not True:
                err(w, "%s: 'store_configuration' needs 'config_check', so the node saves only after a download"
                    % label, [w + ".store_configuration"])
            else:
                node["store_configuration"] = store
        lss = n.get("lss") or {}
        if lss.get("store") is True and lss.get("assign") is not True:
            err(w, "%s: 'lss.store' needs 'lss.assign'" % label, [w + ".lss.store"])
        if lss.get("assign") is True:
            if "serial_number" not in n:
                err(w, "%s: LSS assignment ('lss.assign') needs 'serial_number'" % label,
                    [w + ".lss.assign", w + ".serial_number"])
            if n.get("reset_communication") is False:
                err(w, "%s: 'lss.assign' needs 'reset_communication' true: a node ID set by LSS becomes active only "
                       "on a communication reset" % label, [w + ".lss.assign", w + ".reset_communication"])
            node["lss"] = {"serial_number": _uint(n.get("serial_number", 0)),
                           "revision_number": _uint(n.get("revision_number", 0)) or 0}
        if node["node_id"] == master_id:
            err("nodes", "node ID %d is the master's node ID" % node["node_id"], [w + ".node_id", "master.node_id"])
        seen.setdefault(node["node_id"], []).append(i)
        if len(seen[node["node_id"]]) == 2:
            err("nodes", "node ID %d is used by more than one slave" % node["node_id"],
                ["nodes[%d].node_id" % k for k in range(len(cfg["nodes"]))
                 if _uint(cfg["nodes"][k]["node_id"]) == node["node_id"]])
        for key in ("tx_pdos", "rx_pdos"):
            for j, p in enumerate(n.get(key, [])):
                pdo = {"number": _uint(p.get("number", j + 1)), "entries": []}
                pw = "%s: %s[%d]" % (w, key, j)
                kind = "TPDO" if key == "tx_pdos" else "RPDO"
                for f in ("transmission", "inhibit_time_us", "event_timer_ms", "sync_start"):
                    if f in p:
                        pdo[f] = _uint(p[f])
                if "timeout_ms" in p:
                    pdo["timeout_ms"] = "auto" if p["timeout_ms"] == "auto" else _uint(p["timeout_ms"])
                if "cob_id" in p:
                    pdo["cob_id"] = "auto" if p["cob_id"] == "auto" else _uint(p["cob_id"])
                pdo["default_cob_id"] = default_cob_id(node["node_id"], pdo["number"], key == "tx_pdos")
                if pdo["default_cob_id"] is None and "cob_id" not in p:
                    err(pw, "%s %d has no default COB-ID; set 'cob_id' (or \"auto\")" % (kind, pdo["number"]),
                        ["%s.%s[%d].cob_id" % (w, key, j)])
                if "mapping" in p:
                    pdo["mapping"] = p["mapping"]
                if pdo.get("sync_start") is not None and pdo.get("transmission") is not None \
                        and not 1 <= pdo["transmission"] <= 240:
                    err(pw, "%s %d: field 'sync_start' needs a synchronous transmission type (1-240), not %d"
                        % (kind, pdo["number"], pdo["transmission"]), ["%s.%s[%d].sync_start" % (w, key, j)])
                if not sync_period:
                    what = "%s %s %d" % (label, kind, pdo["number"])
                    if pdo.get("transmission") is not None and transmission_needs_sync(pdo["transmission"]):
                        err(pw, "%s: %s" % (what, sync_needed_message(pdo["transmission"], False)),
                            ["%s.%s[%d].transmission" % (w, key, j), "master.sync_period_us"])
                    if pdo.get("sync_start") is not None:
                        err(pw, "%s: field 'sync_start'%s" % (what, SYNC_NEEDED),
                            ["%s.%s[%d].sync_start" % (w, key, j), "master.sync_period_us"])
                bits = 0
                for k, e in enumerate(p["entries"]):
                    entry = {"index": _uint(e["index"]), "subindex": _uint(e.get("subindex", 0)), "type": e["type"]}
                    loc = parse_location(e.get("iec_location"))
                    if loc is None:
                        if (net_name, node["node_id"], entry["index"], entry["subindex"]) not in routed and not (
                                key == "tx_pdos" and (node["node_id"], pdo["number"]) in linked_tx):
                            err("%s: entries[%d]" % (pw, k),
                                "%s, object 0x%04X:%d: missing 'iec_location' (only an entry a gateway route or a PDO "
                                "link uses may leave it out)" % (label, entry["index"], entry["subindex"]),
                                ["%s.%s[%d].entries[%d]" % (w, key, j, k)])
                    elif not type_fits(e["type"], loc.size):
                        err("%s: entries[%d]" % (pw, k),
                            "%s, object 0x%04X:%d: type %s (%d bit) does not fit location %s (%d bit)"
                            % (label, entry["index"], entry["subindex"], e["type"], CO_TYPES[e["type"]][1],
                               loc, SIZE_BITS[loc.size]),
                            ["%s.%s[%d].entries[%d].iec_location" % (w, key, j, k)])
                    bits += CO_TYPES[e["type"]][1]
                    pdo["entries"].append(entry)
                if bits > 64:
                    err(pw, "mapped objects total %d bits; a PDO carries at most 64" % bits, ["%s.%s[%d]" % (w, key, j)])
                node[key].append(pdo)
        for j, sdo in enumerate(n.get("sdo", [])):
            entry = {"index": _uint(sdo["index"]), "subindex": _uint(sdo.get("subindex", 0)), "type": sdo["type"]}
            data, problem = sdo_value(sdo["value"], sdo["type"])
            if problem:
                err("%s: sdo[%d]" % (w, j), "node %d, index 0x%04X, subindex %d: value %s %s"
                    % (node["node_id"], entry["index"], entry["subindex"], _value_text(sdo["value"]), problem),
                    ["%s.sdo[%d].value" % (w, j)])
            entry["value"] = data
            node["sdo"].append(entry)
            over = None if problem else sdo_override(n, entry, data, linked_rx.get(node["node_id"], ()))
            if over:
                warn(label, "startup SDO to 0x%04X subindex %d runs last and overrides %s"
                     % (entry["index"], entry["subindex"], over), ["%s.sdo[%d]" % (w, j)])
        for j, v in enumerate(n.get("sdo_variables", [])):
            entry = {"index": _uint(v["index"]), "subindex": _uint(v.get("subindex", 0)), "type": v["type"],
                     "direction": v["direction"]}
            vlabel = sdo_variable_label(entry, v.get("name", ""))
            loc = parse_location(v["iec_location"])
            if not type_fits(v["type"], loc.size):
                err("%s: sdo_variables[%d]" % (w, j), "%s, %s: type %s (%d bit) does not fit location %s (%d bit)"
                    % (label, vlabel, v["type"], CO_TYPES[v["type"]][1], loc, SIZE_BITS[loc.size]),
                    ["%s.sdo_variables[%d].iec_location" % (w, j)])
            what = plugin_owned_object(entry["index"]) if entry["direction"] == "write" else None
            if what:
                warn(label, "%s writes an object the plugin configures itself; the program can override %s"
                     % (vlabel, what), ["%s.sdo_variables[%d]" % (w, j)])
            node["sdo_variables"].append(entry)
        nodes.append(node)

    # PDO links and heartbeat watch: the rules between nodes (plugin:
    # check_links, check_heartbeat_watch).
    links_mod.check_rules(links, nodes, sync_period, err)
    links_mod.check_watch_rules(cfg["nodes"], nodes, master_id, err)

    # "auto" COB-IDs, as the plugin resolves them.
    for (i, key, j), cob in auto_cob_ids(nodes).items():
        nodes[i][key][j]["cob_id"] = cob
    for l in links:
        p = next((n for n in nodes if n["node_id"] == l["producer"]), None)
        t = next((t for t in p["tx_pdos"] if t["number"] == l["tpdo"]), None) if p else None
        if t is not None:
            l["cob_id"] = t["cob_id"] if isinstance(t.get("cob_id"), int) else t["default_cob_id"]

    # Two PDOs on one COB-ID collide on the bus (plugin: add_cob), whether
    # the COB-ID is set, "auto" or the default.
    cobs = {}
    for i, node in enumerate(nodes):
        label = "node %d" % node["node_id"] + (" (%s)" % node["name"] if node["name"] else "")
        for key, kind in (("tx_pdos", "TPDO"), ("rx_pdos", "RPDO")):
            for j, pdo in enumerate(node[key]):
                cob = pdo.get("cob_id")
                cob = cob if isinstance(cob, int) else pdo["default_cob_id"]
                if cob is None:
                    continue
                who, at = "%s %s %d" % (label, kind, pdo["number"]), "nodes[%d].%s[%d].cob_id" % (i, key, j)
                if key == "tx_pdos":
                    who += "".join(" (%s)" % l["label"] for l in links
                                   if l["producer"] == node["node_id"] and l["tpdo"] == pdo["number"])
                if cob in cobs:
                    err("nodes", "%s and %s both use COB-ID 0x%03X" % (who, cobs[cob][0], cob), [at, cobs[cob][1]])
                else:
                    cobs[cob] = (who, at)

    # CiA 402 axes: the standard objects the motion blocks' drive bridge needs.
    axis_mod.check(cfg, err, warn)

    if len(r.errors) > before:
        return

    # EDS checks, node by node. Their warnings (objects a device mapping
    # sends as 0) only matter for a config that is accepted.
    eds_warnings = []
    eds_by_id = {}
    lint_mode = edslint.effective_mode(master)
    for i, node in enumerate(nodes):
        w = "nodes[%d]" % i
        file = (eds_paths or {}).get(node["eds"]) or os.path.join(base, node["eds"])
        if not os.path.isfile(file):
            add("error", "node %d: EDS file %s not found" % (node["node_id"], file), [w + ".eds"])
            continue
        # The plugin's EDS lint, on the prepared copy every later check reads.
        with open(file, "rb") as f:
            text, corrections, lint = edslint.check(f.read(), node["node_id"])
        label = "node %d" % node["node_id"] + (" (%s)" % node["name"] if node.get("name") else "")
        lint_error, lint_warning, _ = edslint.verdict(label, node["eds"], corrections, lint, lint_mode)
        if lint_error:
            add("error", lint_error, [w + ".eds"])
            continue
        if lint_warning:
            eds_warnings.append(("%s: %s" % (label, lint_warning), w + ".eds"))
        try:
            eds = eds_mod.Eds.read(file, text)
        except eds_mod.EdsError as e:
            add("error", "node %d: EDS file %s cannot be parsed: %s" % (node["node_id"], file, e), [w + ".eds"])
            continue
        eds_by_id.setdefault(node["node_id"], eds)
        messages, where, warnings = [], [], []
        eds_mod.check_node(node, eds, messages, where, warnings)
        src = cfg["nodes"][i]
        if "heartbeat_ms" not in src and not _uint(src.get("guard_time_ms", 0)):
            hb = eds.find(0x1017, 0)
            try:
                period = hb.value(node["node_id"]) if hb is not None else 0
            except (ValueError, eds_mod.EdsError):
                period = 0
            if not period:
                messages.append(supervision_message(label))
                where.append(".heartbeat_ms")
        profile = axis_mod.device_type_warning(cfg["nodes"][i], eds)
        if profile:
            warnings.append((profile, ".axis"))
        cyc_errors, cyc_warnings = axis_mod.cyclic_eds_check(cfg["nodes"][i], node, eds)
        messages += [m for m, _ in cyc_errors]
        where += [sub for _, sub in cyc_errors]
        warnings += cyc_warnings
        if "lss" in node:
            info = eds_mod.device_info(file) or {}
            node["lss"].update(vendor_id=info.get("vendor_id") or 0, product_code=info.get("product_code") or 0)
            if not info.get("lss_supported"):
                warnings.append(("%s: its EDS does not say LSS_Supported=1; LSS assignment may not work with this "
                                 "device" % label, ".lss.assign"))
        for msg, sub in zip(messages, where):
            add("error", msg, [w + sub])
        eds_warnings += [(msg, w + sub) for msg, sub in warnings]
    # Two nodes with lss.assign must not name the same device.
    lss_nodes = [(i, n) for i, n in enumerate(nodes) if "vendor_id" in n.get("lss", {})]
    for a in range(len(lss_nodes)):
        for b in range(a + 1, len(lss_nodes)):
            (i, x), (j, y) = lss_nodes[a], lss_nodes[b]
            p, q = x["lss"], y["lss"]
            if (p["vendor_id"], p["product_code"], p["serial_number"]) != \
                    (q["vendor_id"], q["product_code"], q["serial_number"]):
                continue
            if p["revision_number"] and q["revision_number"] and p["revision_number"] != q["revision_number"]:
                continue
            labels = ["node %d" % n["node_id"] + (" (%s)" % n["name"] if n.get("name") else "") for n in (x, y)]
            add("error", "%s and %s have the same LSS address (vendor ID 0x%08X, product code 0x%08X, serial "
                  "number 0x%08X)" % (labels[0], labels[1], p["vendor_id"], p["product_code"], p["serial_number"]),
                  ["nodes[%d].lss" % i, "nodes[%d].lss" % j])
    # Heartbeat watch and PDO links against the EDS files (plugin: eds_check.cpp).
    links_mod.resolve_watch(cfg["nodes"], nodes, eds_by_id, master, add)
    links_mod.check_eds([l for l in links if "cob_id" in l], nodes, eds_by_id, sync_period, add, eds_warnings)
    if len(r.errors) == before:
        for msg, at in eds_warnings:
            add("warning", msg, [at])


# ---------------------------------------------------------------------------
# Slave networks (canopen-slave-device) and the gateway (canopen-gateway)

# A slave's status and EMCY locations: (key, area, size letter).
SLAVE_LOCATIONS = (("state_location", "I", "B"), ("comm_ok_location", "I", "X"), ("sync_count_location", "I", "W"),
                   ("emcy_code_location", "Q", "W"), ("error_register_location", "Q", "B"))
SLAVE_LOCATION_KEYS = tuple(k for k, _, _ in SLAVE_LOCATIONS)
DEFAULT_STATUS_INDEX = 0x5E00
DEFAULT_BRIDGE_INDEX = 0x5F00
MAX_STATUS_NETWORKS = 4


def object_text(index, sub):
    return "0x%04X:%d" % (index, sub)


def _check_slave(s, err, add, base, eds_paths):
    """The plugin's checks of one schema-valid slave object: node ID, the
    EDS (found, lint, readable) and every binding against it. Returns
    (Eds, eds value, {(index, subindex): (objects position, location)}), or
    None when the EDS cannot be used."""
    nid = s.get("node_id")
    node_id = None
    if nid is not None:
        node_id = _uint(nid)
        if node_id is None or not 1 <= node_id <= 127:
            err("slave", "field 'node_id' must be 1-127, or null for LSS: %s" % _value_text(nid), ["slave.node_id"])
            node_id = None
    value = s["eds"]
    file = (eds_paths or {}).get(value) or os.path.join(base, value)
    if not os.path.isfile(file):
        add("error", "slave: EDS file %s not found" % file, ["slave.eds"])
        return None
    with open(file, "rb") as f:
        text, corrections, lint = edslint.check(f.read(), node_id or 1)
    mode = s.get("eds_lint") if s.get("eds_lint") in edslint.MODES else edslint.DEFAULT_MODE
    lint_error, lint_warning, _ = edslint.verdict("slave", value, corrections, lint, mode)
    if lint_error:
        add("error", lint_error, ["slave.eds"])
        return None
    try:
        eds = eds_mod.Eds.read(file, text)
    except eds_mod.EdsError as e:
        add("error", "slave: EDS file %s cannot be parsed: %s" % (file, e), ["slave.eds"])
        return None
    if lint_warning:
        add("warning", "slave: " + lint_warning, ["slave.eds"])
    bound = {}
    for j, o in enumerate(s.get("objects", [])):
        index, sub = _uint(o["index"]), _uint(o["subindex"])
        at = "slave: objects[%d]" % j
        if index > 0xFFFF or sub > 0xFF:
            err(at, "object index must be 0x0000-0xFFFF and subindex 0-255", ["slave.objects[%d]" % j])
            continue
        what = "slave object %s" % object_text(index, sub) + (" (%s)" % o["name"] if o.get("name") else "")
        loc = parse_location(o["iec_location"])
        if (index, sub) in bound:
            err(at, "%s is bound twice (objects[%d] and objects[%d])" % (what, bound[(index, sub)][0], j),
                ["slave.objects[%d]" % bound[(index, sub)][0], "slave.objects[%d]" % j])
            continue
        bound[(index, sub)] = (j, str(loc))
        so = eds.find(index, sub)
        if so is None:
            err(at, "%s is not defined in %s" % (what, value), ["slave.objects[%d]" % j])
            continue
        direction = slave_direction(so.access)
        if direction is None:
            err(at, "%s has AccessType %s in %s and cannot be bound: the PLC binds objects the master writes (rww, "
                    "rw) to inputs and objects the master reads (ro, rwr) to outputs" % (what, so.access, value),
                ["slave.objects[%d]" % j])
            continue
        if not so.type_name:
            err(at, "%s has data type %s, which no PLC location holds (supported: %s)"
                % (what, eds_mod.data_type_name(so.data_type), ", ".join(CO_TYPES)), ["slave.objects[%d]" % j])
            continue
        want = "I" if direction == "input" else "Q"
        if loc.area != want:
            if direction == "input":
                msg = "the master writes %s (AccessType %s), so it needs an %%I location, not %s" % (
                    object_text(index, sub), so.access, loc)
                if so.access == "rw":
                    msg += "; an object the PLC writes needs AccessType ro or rwr in the EDS"
            else:
                msg = "the master reads %s (AccessType %s), so it needs a %%Q location, not %s" % (
                    object_text(index, sub), so.access, loc)
            err(at, msg, ["slave.objects[%d].iec_location" % j])
        elif not type_fits(so.type_name, loc.size):
            err(at, "%s: type %s (%d bit) does not fit location %s (%d bit)"
                % (what, so.type_name, CO_TYPES[so.type_name][1], loc, SIZE_BITS[loc.size]),
                ["slave.objects[%d].iec_location" % j])
    return eds, value, bound


def upper_master_stand_in(cfg):
    """The name of the master network that shares the gateway's upper
    network's simulated bus (it stands in for the upper master and is not a
    field network), or None."""
    g = cfg.get("gateway") if isinstance(cfg, dict) else None
    if not isinstance(g, dict):
        return None
    nets = networks(cfg)
    upper = next((n for n in nets if n["name"] and n["name"] == g.get("upper") and n["role"] == "slave"), None)
    if upper is None or upper["adapter"].get("simulate") is not True:
        return None
    for n in nets:
        if n["role"] == "master" and n["adapter"].get("simulate") is True \
                and n["adapter"].get("interface") == upper["adapter"].get("interface"):
            return n["name"]
    return None


def field_networks(cfg):
    """The gateway's field networks: the master networks except the upper
    master's stand-in."""
    stand_in = upper_master_stand_in(cfg)
    return [n for n in networks(cfg) if n["role"] == "master" and not (stand_in and n["name"] == stand_in)]


def _net_phrase(net):
    """'network "io"', or 'network 4' for one without a name yet."""
    return 'network "%s"' % net["name"] if net["name"] else "network %d" % (net["index"] + 1)


def _check_gateway(cfg, err, warn, slaves):
    """The plugin's checks of the gateway section (canopen-gateway): the
    upper network, the field networks, and each route's two ends, their
    direction, type and single writer. `slaves`: what _check_slave()
    returned per network index, for the slave networks that passed."""
    g = cfg["gateway"]
    if not isinstance(g, dict):
        return
    nets = networks(cfg)
    by_name = {n["name"]: n for n in nets if n["name"]}
    upper_name = g.get("upper")
    upper = by_name.get(upper_name)
    if upper is None:
        err("gateway", "upper network '%s' is not in the config (networks: %s)"
            % (upper_name, ", ".join(n["name"] or "unnamed" for n in nets)), ["gateway.upper"])
    elif upper["role"] == "j1939":
        # The plugin's words (parse_gateway).
        err("gateway", 'upper network "%s" must be a slave network ("role": "slave"); it is a J1939 network'
            % upper_name, ["gateway.upper"])
    elif upper["role"] != "slave":
        err("gateway", "the upper network '%s' must be a slave network (\"role\": \"slave\"), not a master network"
            % upper_name, ["gateway.upper"])
    stand_in = upper_master_stand_in(cfg)
    masters = field_networks(cfg)
    if not masters:
        err("gateway", "a gateway needs at least one master network (a field network) besides the slave network"
            + (" and the upper master's stand-in '%s'" % stand_in if stand_in else ""), ["gateway"])
    slave = slaves.get(upper["index"]) if upper is not None and upper["role"] == "slave" else None
    eds, eds_name, bound = slave if slave else (None, None, {})
    if isinstance(g.get("status"), dict):
        if len(masters) > MAX_STATUS_NETWORKS:
            warn("gateway", "gateway status: only the first %d master networks are published; %s is not"
                 % (MAX_STATUS_NETWORKS, _net_phrase(masters[MAX_STATUS_NETWORKS])), ["gateway.status"])
        if eds is not None:
            base_index = _uint(g["status"].get("index", DEFAULT_STATUS_INDEX))
            for k, m in enumerate(masters[:MAX_STATUS_NETWORKS]):
                rec, bits = base_index + k, base_index + 0x10 + k
                # The first master network's records are required; a later
                # network whose records are both missing (an EDS generated
                # for fewer networks) is left out with a warning, as the
                # plugin does.
                if k > 0 and not eds.has(rec) and not eds.has(bits):
                    warn("gateway", "gateway status of %s is not published: objects 0x%04X and 0x%04X are "
                                    "not in the EDS %s" % (_net_phrase(m), rec, bits, eds_name), ["gateway.status"])
                    continue
                for index in (rec, bits):
                    if not eds.has(index):
                        err("gateway", "gateway status of %s needs object 0x%04X in the EDS %s (generate "
                                       "the slave EDS with the gateway section: canworks-deploy slave-eds "
                                       "--gateway)" % (_net_phrase(m), index, eds_name), ["gateway.status"])
    if g.get("sdo_bridge") is True and eds is not None:
        index = _uint(g.get("sdo_bridge_index", DEFAULT_BRIDGE_INDEX))
        if not eds.has(index) or eds.find(index, 9) is None:
            err("gateway", "'sdo_bridge' needs the SDO bridge record 0x%04X (sub-indices 1-9) in the slave's EDS %s; "
                           "generate the EDS with canworks-deploy slave-eds --gateway" % (index, eds_name),
                ["gateway.sdo_bridge"])
    if g.get("sdo_bridge_write") is True and g.get("sdo_bridge") is not True:
        warn("gateway", "'sdo_bridge_write' has no effect without 'sdo_bridge'", ["gateway.sdo_bridge_write"])
    writers = {}
    for j, rt in enumerate(g.get("routes") or []):
        at = "gateway: routes[%d]" % j
        pj = "gateway.routes[%d]" % j
        f = rt["field"]
        fnet = by_name.get(f["network"])
        node_id = _uint(f["node"])
        index, sub = _uint(f["index"]), _uint(f.get("subindex", 0))
        s_index, s_sub = _uint(rt["slave"]["index"]), _uint(rt["slave"].get("subindex", 0))
        if fnet is None:
            err(at, "field network '%s' is not in the config" % f["network"], [pj + ".field.network"])
            continue
        if fnet["role"] == "j1939":
            err(at + ": field", 'network "%s" is a J1939 network; a route\'s field end is on a CANopen master network'
                % f["network"], [pj + ".field.network"])
            continue
        if fnet["role"] != "master":
            err(at, "field network '%s' is a slave network; a route's field end is a PDO entry of a node on a master "
                    "network" % f["network"], [pj + ".field.network"])
            continue
        if stand_in and fnet["name"] == stand_in:
            err(at, "field network '%s' shares the upper network's simulated bus: it stands in for the upper master "
                    "and is not a field network" % f["network"], [pj + ".field.network"])
            continue
        node_i = next((i for i, n in enumerate(fnet["nodes"])
                       if isinstance(n, dict) and _uint(n.get("node_id")) == node_id), None)
        field_text = "network %s node %d %s" % (f["network"], node_id, object_text(index, sub))
        if node_i is None:
            err(at, "network %s has no node %d" % (f["network"], node_id), [pj + ".field.node"])
            continue
        found = {}
        for key in ("tx_pdos", "rx_pdos"):
            for pi, p in enumerate(fnet["nodes"][node_i].get(key) or []):
                for k, e in enumerate(p.get("entries") or []):
                    if _uint(e.get("index")) == index and _uint(e.get("subindex", 0)) == sub:
                        found.setdefault(key, ("%s.nodes[%d].%s[%d].entries[%d]" % (fnet["path"], node_i, key, pi, k),
                                               e))
        if not found:
            err(at, "%s is not an entry of the node's tx_pdos or rx_pdos; a route's field end is a PDO entry"
                % field_text, [pj + ".field"])
            continue
        if eds is None:
            continue  # the slave network's own errors say why
        slave_text = "slave object %s" % object_text(s_index, s_sub)
        so = eds.find(s_index, s_sub)
        if so is None:
            err(at, "%s is not defined in %s" % (slave_text, eds_name), [pj + ".slave"])
            continue
        direction = slave_direction(so.access)
        if direction is None:
            err(at, "%s has AccessType %s and cannot be routed: a route up needs ro or rwr, a route down rww or rw"
                % (slave_text, so.access), [pj + ".slave"])
            continue
        up = direction == "output"
        key = "tx_pdos" if up else "rx_pdos"
        if key not in found:
            other = found["rx_pdos" if up else "tx_pdos"][0]
            if up:
                err(at, "the upper master cannot write %s (AccessType %s), so it cannot feed the RPDO entry %s; route "
                        "an rww or rw object down" % (slave_text, so.access, field_text), [pj + ".slave", other])
            else:
                err(at, "the upper master writes %s (AccessType %s), so the TPDO entry %s cannot write it; route an "
                        "ro or rwr object up" % (slave_text, so.access, field_text), [pj + ".slave", other])
            continue
        entry_path, entry = found[key]
        if entry.get("type") != so.type_name:
            err(at, "%s (%s) and %s (%s) need the same data type" % (
                field_text, entry.get("type"), slave_text, so.type_name or eds_mod.data_type_name(so.data_type)),
                [pj, entry_path + ".type"])
            continue
        # One writer per target: the route, not the PLC or another route.
        if up:
            target, target_text = ("slave", s_index, s_sub), slave_text
            plc = bound.get((s_index, s_sub))
            plc_loc = plc[1] if plc else None
            plc_path = "%s.slave.objects[%d].iec_location" % (upper["path"], plc[0]) if plc else None
        else:
            target, target_text = (f["network"], node_id, index, sub), "the RPDO entry " + field_text
            plc_loc, plc_path = entry.get("iec_location"), entry_path + ".iec_location"
        if plc_loc:
            err(at, "%s is written by routes[%d] and by %s; give it one writer (leave out its location)"
                % (target_text, j, plc_loc), [pj, plc_path])
        if target in writers:
            err(at, "%s is written by routes[%d] and routes[%d]; give it one writer"
                % (target_text, writers[target], j), ["gateway.routes[%d]" % writers[target], pj])
        else:
            writers[target] = j


# ---------------------------------------------------------------------------
# J1939 networks (j1939-config spec; plugin: parse_j1939_network in
# plugin/src/can/config.cpp and check_j1939 in plugin/src/j1939/j1939_config.cpp)

J1939_MAX_PGN = 0x3FFFF
J1939_MAX_ADDRESS = 253  # 254 is the null address, 255 global
J1939_NULL_ADDRESS = 254
J1939_GLOBAL = 255
J1939_MAX_LENGTH = 1785  # bytes, the transport protocol's limit
J1939_MAX_PERIOD_MS = 600000
J1939_MIN_REQUEST_PERIOD_MS = 100
J1939_DEFAULT_PRIORITY = 6
J1939_MAX_SPN = 0x7FFFF  # 19 bits
J1939_MAX_DM_RX_CODES = 32
J1939_DEFAULT_DM_TIMEOUT_MS = 3000
J1939_LAMPS = ("mil", "red", "amber", "protect")
# The NAME fields and their highest values, in the order of the NAME's bits.
J1939_NAME_FIELDS = (("identity_number", 0x1FFFFF), ("manufacturer_code", 2047), ("ecu_instance", 7),
                     ("function_instance", 31), ("function", 255), ("vehicle_system", 127),
                     ("vehicle_system_instance", 15), ("industry_group", 7))
# Keys of a CANopen network that a J1939 network may not have.
CANOPEN_KEYS = ("role", "master", "nodes", "slave")
J1939_SIMULATE = ("J1939 networks run on SocketCAN or slcan interfaces; use a vcan interface for simulation, not "
                  "adapter.simulate")


def is_j1939(net):
    """Whether a networks[] entry is a J1939 network."""
    return isinstance(net, dict) and net.get("protocol") == "j1939"


def has_j1939(cfg):
    """Whether any network of the config is a J1939 network (writers then
    write schema_version 2)."""
    return isinstance(cfg, dict) and isinstance(cfg.get("networks"), list) and any(
        is_j1939(n) for n in cfg["networks"])


def j1939_pdu1(pgn):
    """PDU1 (PF below 240): the PGN's low byte is the destination."""
    return ((pgn >> 8) & 0xFF) < 240


def j1939_pgn_text(pgn):
    return "%d (0x%X)" % (pgn, pgn)


def j1939_name_value(name):
    """The 64-bit NAME of a j1939.ecu.name object (missing fields 0)."""
    name = name if isinstance(name, dict) else {}
    shifts = (0, 21, 32, 35, 40, 49, 56, 60)
    value = 0
    for (key, top), shift in zip(J1939_NAME_FIELDS, shifts):
        v = name.get(key, 0)
        value |= (v & top if isinstance(v, int) and not isinstance(v, bool) else 0) << shift
    return value | (1 << 63 if name.get("arbitrary_address_capable") is True else 0)


def j1939_signal_bits(start_bit, length, big_endian=False):
    """The message bits a signal covers, least significant first (plugin:
    j1939_signal_bits). DBC big byte order: the start bit is the most
    significant bit; the next lower bit is the next lower bit of the same
    byte, or bit 7 of the next byte."""
    if not big_endian:
        return list(range(start_bit, start_bit + length))
    bits, pos = [], start_bit
    for _ in range(length):
        bits.append(pos)
        pos = pos + 15 if pos % 8 == 0 else pos - 1
    return bits[::-1]


def j1939_bytes_needed(signals):
    """The bytes a message needs to hold `signals` (parse_j1939() signals)."""
    top = 0
    for s in signals:
        for b in j1939_signal_bits(s["start_bit"], s["length"], s["big_endian"]):
            top = max(top, b // 8 + 1)
    return top


def _mux_def(sj, path):
    """A J1939 signal object in the form mux.Layout reads, whatever its
    other fields' errors."""
    def whole(key, default):
        v = sj.get(key)
        return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v == int(v) and v >= 0 else default
    return {"path": path, "name": sj.get("name") if isinstance(sj.get("name"), str) else "",
            "start_bit": whole("start_bit", 0), "length": whole("length", 1) or 1,
            "byte_order": sj.get("byte_order"), "signed": sj.get("signed") is True}


class _J1939Parser:
    """Reads one networks[] entry's j1939 object the way the plugin does,
    reporting through err(where, message, paths) with the plugin's places
    and words. The result (parse()) is the object with defaults filled in
    and locations parsed; entries and signals the plugin would drop are left
    out."""

    def __init__(self, err, warn=None):
        self.err = err
        self.warn = warn or (lambda *a: None)

    # The plugin's field readers (j_uint, j_range, j_uint64, get_string, ...).
    def uint(self, obj, key, where, path):
        if key not in obj:
            return None
        v = obj[key]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or (isinstance(v, float) and (
                not math.isfinite(v) or v != math.floor(v))) or v < 0:
            self.err(where, "field '%s' must be a non-negative integer" % key, [path + "." + key])
            return None
        return int(v)

    def range(self, obj, key, where, path, lo, hi, extra=""):
        v = self.uint(obj, key, where, path)
        if v is None:
            return None
        if not lo <= v <= hi:
            self.err(where, "%s %d is out of range %d..%d%s" % (key, v, lo, hi, extra), [path + "." + key])
            return None
        return v

    def uint64(self, obj, key, where, path):
        if key not in obj:
            return None
        v = obj[key]
        if isinstance(v, str) and v and not v.startswith("-"):
            text = v.strip()
            try:
                if re.match(r"^0[xX][0-9a-fA-F]+$", text):
                    n = int(text, 16)
                elif re.match(r"^0[0-7]*$", text):
                    n = int(text, 8)
                elif re.match(r"^[1-9][0-9]*$", text):
                    n = int(text)
                else:
                    n = None
            except ValueError:
                n = None
            if n is not None and n < 1 << 64:
                return n
        elif isinstance(v, (int, float)) and not isinstance(v, bool):
            return self.uint(obj, key, where, path)
        self.err(where, "field '%s' must be a 64-bit unsigned integer, decimal or 0x hex" % key, [path + "." + key])
        return None

    def string(self, obj, key, where, path, required=False):
        if key not in obj:
            if required:
                self.err(where, "missing required field '%s'" % key, [path + "." + key])
            return None
        v = obj[key]
        if not isinstance(v, str) or not v:
            self.err(where, "field '%s' must be a non-empty string" % key, [path + "." + key])
            return None
        return v

    def boolean(self, obj, key, where, path):
        if key not in obj:
            return None
        if not isinstance(obj[key], bool):
            self.err(where, "field '%s' must be true or false" % key, [path + "." + key])
            return None
        return obj[key]

    def number(self, obj, key, where, path):
        if key not in obj:
            return None
        v = obj[key]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            self.err(where, "field '%s' must be a number" % key, [path + "." + key])
            return None
        return v

    def location(self, obj, key, where, path):
        text = self.string(obj, key, where, path)
        if text is None:
            return None
        loc = parse_location(text)
        if loc is None or loc.area == "M":
            self.err(where, 'invalid %s "%s": %s' % (
                key, text, "only input (%I) and output (%Q) locations are supported" if loc is not None
                else "expected a location like %IX0.0 or %QW10"), [path + "." + key])
            return None
        return loc

    def fixed_location(self, obj, key, where, path, area, size, what):
        """A status location of one area and size ("a byte input (%IB)")."""
        if key not in obj:
            return None
        loc = self.location(obj, key, where, path)
        if loc is None:
            return None
        if loc.area != area or loc.size != size:
            self.err(where, "%s %s must be %s" % (key, loc, what), [path + "." + key])
            return None
        return loc

    def pgn(self, obj, where, path):
        if "pgn" not in obj:
            self.err(where, "field 'pgn' is missing", [path])
            return None
        v = self.range(obj, "pgn", where, path, 0, J1939_MAX_PGN, " (0x3FFFF)")
        if v is not None and j1939_pdu1(v) and v & 0xFF:
            self.err(where, "PGN %s is a PDU1 PGN: its low byte must be 0 (the destination is given separately)"
                     % j1939_pgn_text(v), [path + ".pgn"])
        return v

    def destination(self, obj, where, path):
        v = self.uint(obj, "destination", where, path)
        if v is not None and v > J1939_MAX_ADDRESS and v != J1939_GLOBAL:
            self.err(where, "destination %d is out of range 0..253 or 255 (global)" % v, [path + ".destination"])
            return None
        return v

    # The j1939 object.
    def parse(self, j):
        out = {"ecu": None, "dbc": None, "rx": [], "tx": [], "requests": [], "diagnostics": None}
        out["ecu"] = self.ecu(j)
        out["dbc"] = self.string(j, "dbc", "j1939", "j1939")
        for key in ("rx", "tx", "requests"):
            arr = j.get(key)
            if key in j and not isinstance(arr, list):
                self.err("j1939", "field '%s' must be an array" % key, ["j1939." + key])
                continue
            for i, m in enumerate(arr or []):
                w, p = "j1939: %s[%d]" % (key, i), "j1939.%s[%d]" % (key, i)
                if not isinstance(m, dict):
                    self.err(w, "must be an object", [p])
                    continue
                out[key].append(getattr(self, key)(m, w, p))
        out["diagnostics"] = self.diagnostics(j)
        self.check(out)
        return out

    # The diagnostics object (j1939-diagnostics "Diagnostics config").
    def diagnostics(self, j):
        if "diagnostics" not in j:
            return None
        o = j["diagnostics"]
        w, p = "j1939: diagnostics", "j1939.diagnostics"
        if not isinstance(o, dict):
            self.err("j1939", "field 'diagnostics' must be an object", [p])
            return None
        d = {"rx": [], "dtcs": [], "lamps_location": None, "clear_location": None, "accept_clear": True,
             "dm13": True}
        arr = o.get("rx")
        if "rx" in o and not isinstance(arr, list):
            self.err(w, "field 'rx' must be an array", [p + ".rx"])
            arr = []
        for i, m in enumerate(arr or []):
            mw, mp = "%s: rx[%d]" % (w, i), "%s.rx[%d]" % (p, i)
            if not isinstance(m, dict):
                self.err(mw, "must be an object", [mp])
                continue
            r = {"source": None, "source_name": None, "source_name_mask": None,
                 "timeout_ms": J1939_DEFAULT_DM_TIMEOUT_MS, "dtcs": 0, "path": mp}
            if "source" in m and "source_name" in m:
                self.err(mw, "give 'source' or 'source_name', not both", [mp + ".source", mp + ".source_name"])
            elif "source" in m:
                r["source"] = self.range(m, "source", mw, mp, 0, J1939_MAX_ADDRESS)
            elif "source_name" in m:
                r["source_name"] = self.uint64(m, "source_name", mw, mp)
            else:
                self.err(mw, "give 'source' or 'source_name': the ECU whose DM1 the program sees", [mp])
            if "source_name_mask" in m:
                if "source_name" not in m:
                    self.err(mw, "field 'source_name_mask' needs 'source_name'", [mp + ".source_name_mask"])
                else:
                    r["source_name_mask"] = self.uint64(m, "source_name_mask", mw, mp)
            v = self.range(m, "timeout_ms", mw, mp, 0, J1939_MAX_PERIOD_MS)
            if v is not None:
                r["timeout_ms"] = v
            r["status_location"] = self.fixed_location(m, "status_location", mw, mp, "I", "X", "a bit input (%IX)")
            for key in ("lamps_location", "flash_location", "count_location"):
                r[key] = self.fixed_location(m, key, mw, mp, "I", "B", "a byte input (%IB)")
            r["dtcs_location"] = self.fixed_location(m, "dtcs_location", mw, mp, "I", "D",
                                                     "a double word input (%ID)")
            if "dtcs" in m:
                v = self.range(m, "dtcs", mw, mp, 1, J1939_MAX_DM_RX_CODES)
                if v is not None:
                    r["dtcs"] = v
            if "dtcs_location" in m and "dtcs" not in m:
                self.err(mw, "field 'dtcs' is missing: the number of codes at dtcs_location (1..32)",
                         [mp + ".dtcs"])
            if "dtcs" in m and "dtcs_location" not in m:
                self.err(mw, "field 'dtcs' needs 'dtcs_location'", [mp + ".dtcs"])
            if not any(key in m for key in ("status_location", "lamps_location", "flash_location", "count_location",
                                            "dtcs_location")):
                self.err(mw, "needs at least one of status_location, lamps_location, flash_location, "
                         "count_location and dtcs_location", [mp])
            d["rx"].append(r)
        arr = o.get("dtcs")
        if "dtcs" in o and not isinstance(arr, list):
            self.err(w, "field 'dtcs' must be an array", [p + ".dtcs"])
            arr = []
        for i, m in enumerate(arr or []):
            mw, mp = "%s: dtcs[%d]" % (w, i), "%s.dtcs[%d]" % (p, i)
            if not isinstance(m, dict):
                self.err(mw, "must be an object", [mp])
                continue
            c = {"spn": None, "fmi": None, "active_location": None, "lamps": [], "flash": None, "path": mp}
            ok = True
            for key, top in (("spn", J1939_MAX_SPN), ("fmi", 31)):
                if key not in m:
                    self.err(mw, "field '%s' is missing" % key, [mp + "." + key])
                    ok = False
                    continue
                c[key] = self.range(m, key, mw, mp, 0, top)
                ok = ok and c[key] is not None
            if "active_location" not in m:
                self.err(mw, "field 'active_location' is missing", [mp + ".active_location"])
                ok = False
            else:
                c["active_location"] = self.fixed_location(m, "active_location", mw, mp, "Q", "X",
                                                           "a bit output (%QX)")
                ok = ok and c["active_location"] is not None
            if "lamps" in m:
                lamps = m["lamps"]
                if not isinstance(lamps, list) or any(x not in J1939_LAMPS for x in lamps):
                    self.err(mw, 'field \'lamps\' must be a list of "mil", "red", "amber" and "protect"',
                             [mp + ".lamps"])
                else:
                    c["lamps"] = list(lamps)
            if "flash" in m:
                if m["flash"] not in ("slow", "fast"):
                    self.err(mw, 'field \'flash\' must be "slow" or "fast"', [mp + ".flash"])
                else:
                    c["flash"] = m["flash"]
            if ok:
                d["dtcs"].append(c)
        d["lamps_location"] = self.fixed_location(o, "lamps_location", w, p, "Q", "B", "a byte output (%QB)")
        d["clear_location"] = self.fixed_location(o, "clear_location", w, p, "I", "B", "a byte input (%IB)")
        for key in ("accept_clear", "dm13"):
            v = self.boolean(o, key, w, p)
            if v is not None:
                d[key] = v
        return d

    def ecu(self, j):
        w, p = "j1939: ecu", "j1939.ecu"
        if "ecu" not in j:
            self.err("j1939", "field 'ecu' is missing", ["j1939.ecu"])
            return None
        e = j["ecu"]
        if not isinstance(e, dict):
            self.err("j1939", "field 'ecu' must be an object", ["j1939.ecu"])
            return None
        ecu = {"name": {key: 0 for key, _ in J1939_NAME_FIELDS}, "address": None, "address_range": None,
               "state_location": None, "address_location": None}
        ecu["name"]["arbitrary_address_capable"] = False
        n = e.get("name")
        if "name" not in e:
            self.err(w, "field 'name' is missing", [p + ".name"])
        elif not isinstance(n, dict):
            self.err(w, "field 'name' must be an object of NAME fields", [p + ".name"])
        else:
            for key, top in J1939_NAME_FIELDS:
                v = self.range(n, key, w + ": name", p + ".name", 0, top)
                if v is not None:
                    ecu["name"][key] = v
            aac = self.boolean(n, "arbitrary_address_capable", w + ": name", p + ".name")
            if aac is not None:
                ecu["name"]["arbitrary_address_capable"] = aac
        if "address" not in e:
            self.err(w, "field 'address' is missing", [p + ".address"])
        else:
            ecu["address"] = self.range(e, "address", w, p, 0, J1939_MAX_ADDRESS)
        if "address_range" in e:
            r = e["address_range"]

            def addr(x):
                return not isinstance(x, bool) and isinstance(x, (int, float)) and 0 <= x <= 253 and x == int(x)

            def plain(x):
                return int(x) if isinstance(x, float) and x == math.floor(x) else x

            shown = json.dumps([plain(x) for x in r] if isinstance(r, list) else r, separators=(", ", ":"))
            if not isinstance(r, list) or len(r) != 2 or not addr(r[0]) or not addr(r[1]) or r[0] > r[1]:
                self.err(w, "address_range %s must be [low, high] within 0..253" % shown, [p + ".address_range"])
            else:
                ecu["address_range"] = [int(r[0]), int(r[1])]
                if not ecu["name"]["arbitrary_address_capable"]:
                    self.err(w, "address_range needs a NAME with arbitrary_address_capable true",
                             [p + ".address_range", p + ".name.arbitrary_address_capable"])
        for key in ("state_location", "address_location"):
            ecu[key] = self.fixed_location(e, key, w, p, "I", "B", "a byte input (%IB)")
        return ecu

    def rx(self, m, w, p):
        r = {"pgn": self.pgn(m, w, p), "name": self.string(m, "name", w, p), "source": None, "source_name": None,
             "source_name_mask": None, "timeout_ms": 0, "status_location": None}
        if "source" in m and "source_name" in m:
            self.err(w, "give 'source' or 'source_name', not both", [p + ".source", p + ".source_name"])
        elif "source" in m:
            r["source"] = self.range(m, "source", w, p, 0, J1939_MAX_ADDRESS)
        elif "source_name" in m:
            r["source_name"] = self.uint64(m, "source_name", w, p)
        if "source_name_mask" in m:
            if "source_name" not in m:
                self.err(w, "field 'source_name_mask' needs 'source_name'", [p + ".source_name_mask"])
            else:
                r["source_name_mask"] = self.uint64(m, "source_name_mask", w, p)
        v = self.range(m, "timeout_ms", w, p, 0, J1939_MAX_PERIOD_MS)
        if v is not None:
            r["timeout_ms"] = v
        r["status_location"] = self.fixed_location(m, "status_location", w, p, "I", "X", "a bit input (%IX)")
        r["signals"], r["layout"] = self.signals(m, w, p, True)
        return r

    def tx(self, m, w, p):
        t = {"pgn": self.pgn(m, w, p), "name": self.string(m, "name", w, p), "priority": J1939_DEFAULT_PRIORITY,
             "destination": J1939_GLOBAL, "length": None, "period_ms": 0, "min_gap_ms": 0}
        v = self.range(m, "priority", w, p, 0, 7)
        if v is not None:
            t["priority"] = v
        v = self.destination(m, w, p)
        if v is not None:
            t["destination"] = v
            if t["pgn"] is not None and not j1939_pdu1(t["pgn"]):
                self.err(w, "PGN %s is a PDU2 PGN and always broadcast; remove 'destination'"
                         % j1939_pgn_text(t["pgn"]), [p + ".destination"])
        t["length"] = self.range(m, "length", w, p, 1, J1939_MAX_LENGTH)
        for key in ("period_ms", "min_gap_ms"):
            v = self.range(m, key, w, p, 0, J1939_MAX_PERIOD_MS)
            if v is not None:
                t[key] = v
        t["pages"] = "program"
        mode = None
        if "pages" in m:
            v = m["pages"]
            if v not in raw_mux.PAGES:
                self.err(w, 'pages: must be "program", "all" or "rotate"', [p + ".pages"])
                mode = ""
            else:
                t["pages"] = v
                mode = None if v == "program" else v
        t["signals"], t["layout"] = self.signals(m, w, p, False, mode)
        if "pages" in m and not any(s["is_switch"] for s in t["signals"]):
            self.err(w, "pages: only for a message with a switch (multiplexer: true)", [p + ".pages"])
        if mode and t["layout"].multiplexed:
            n = t["layout"].page_count()
            if n > raw_mux.MAX_PAGES:
                self.err(w, '%d pages; pages "all" and "rotate" send at most %d (use pages "program")'
                         % (n, raw_mux.MAX_PAGES), [p])
        return t

    def requests(self, m, w, p):
        q = {"pgn": self.pgn(m, w, p), "destination": J1939_GLOBAL, "period_ms": None}
        v = self.destination(m, w, p)
        if v is not None:
            q["destination"] = v
        if "period_ms" not in m:
            self.err(w, "field 'period_ms' is missing", [p + ".period_ms"])
        else:
            q["period_ms"] = self.range(m, "period_ms", w, p, J1939_MIN_REQUEST_PERIOD_MS, J1939_MAX_PERIOD_MS)
        return q

    def signals(self, msg, where, path, rx, switch_mode=None):
        """(signals, mux.Layout): the signals the plugin keeps (each with
        "index", its place in the message's list) and the multiplexing of
        the message's signals. `switch_mode`: "all" or "rotate" for a tx
        entry whose switches the plugin sets ("" when `pages` was wrong)."""
        out = []
        if "signals" not in msg:
            self.err(where, "field 'signals' is missing", [path + ".signals"])
            return out, raw_mux.Layout([])
        arr = msg["signals"]
        if not isinstance(arr, list):
            self.err(where, "field 'signals' must be an array", [path + ".signals"])
            return out, raw_mux.Layout([])
        defs, specs = [], []
        for i, sj in enumerate(arr):
            sw, sp = "%s: signals[%d]" % (where, i), "%s.signals[%d]" % (path, i)
            if not isinstance(sj, dict):
                self.err(sw, "must be an object", [sp])
                continue
            # Multiplexing, named by the signal's place ("signals[1].mux.on: ...").
            shape = []
            is_switch, spec = raw_mux.parse_fields(sj, "signals[%d]" % i, shape)
            for e in shape:
                self.err(where, e, [sp])
            specs.append((is_switch, spec, bool(shape)))
            defs.append(_mux_def(sj, "signals[%d]" % i))
            name = self.string(sj, "name", sw, sp, required=True)
            if name is None:
                continue
            me = "signal " + name
            mw = where + ": " + me
            s = {"name": name, "start_bit": None, "length": None, "big_endian": False, "signed": False,
                 "scale": 1, "offset": 0, "unit": "", "location": None, "valid_location": None, "path": sp,
                 "index": len(defs) - 1, "is_switch": is_switch, "multiplexer": sj.get("multiplexer"),
                 "mux": sj.get("mux")}
            ok = True
            for key, lo, hi in (("start_bit", 0, J1939_MAX_LENGTH * 8 - 1), ("length", 1, 64)):
                if key not in sj:
                    self.err(where, "%s: field '%s' is missing" % (me, key), [sp + "." + key])
                    ok = False
                    continue
                s[key] = self.range(sj, key, mw, sp, lo, hi)
                ok = ok and s[key] is not None
            order = self.string(sj, "byte_order", sw, sp)
            if order == "big":
                s["big_endian"] = True
            elif order is not None and order != "little":
                self.err(where, '%s: field \'byte_order\' must be "little" or "big", not "%s"' % (me, order),
                         [sp + ".byte_order"])
            s["signed"] = self.boolean(sj, "signed", sw, sp) or False
            for key, default in (("scale", 1), ("offset", 0)):
                v = self.number(sj, key, sw, sp)
                s[key] = default if v is None else v
            s["unit"] = self.string(sj, "unit", sw, sp) or ""
            if is_switch and switch_mode is not None:
                # The plugin sets the switch; an empty mode was reported at `pages`.
                if "iec_location" in sj and switch_mode:
                    self.err(where, 'signals[%d].iec_location: the plugin sets switch %s when pages is "%s"; '
                             'leave it out' % (i, name, switch_mode), [sp + ".iec_location"])
            elif "iec_location" not in sj:
                self.err(where, "%s: field 'iec_location' is missing" % me, [sp + ".iec_location"])
                ok = False
            else:
                loc = self.location(sj, "iec_location", mw, sp)
                at = [sp + ".iec_location"]
                if loc is None:
                    ok = False
                elif rx and loc.area != "I":
                    self.err(where, "%s: location %s must be an input (%%I)" % (me, loc), at)
                    ok = False
                elif not rx and loc.area != "Q":
                    self.err(where, "%s: location %s must be an output (%%Q)" % (me, loc), at)
                    ok = False
                elif ok and (s["length"] != 1 if loc.size == "X" else s["length"] > SIZE_BITS[loc.size]):
                    self.err(where, "%s (%d bit%s) does not fit location %s (%d bit)" % (
                        me, s["length"], "" if s["length"] == 1 else "s", loc, SIZE_BITS[loc.size]), at)
                    ok = False
                s["location"] = loc
            if "valid_location" in sj:
                if not rx:
                    self.err(where, "%s: field 'valid_location' is only for received signals (rx)" % me,
                             [sp + ".valid_location"])
                else:
                    s["valid_location"] = self.fixed_location(sj, "valid_location", mw, sp, "I", "X",
                                                              "a bit input (%IX)")
            if ok:
                out.append(s)
        errors, warnings = [], []
        layout = raw_mux.Layout.build(defs, errors, warnings, specs)
        for e in errors:
            self.err(where, e, [path + ".signals"])
        for e in warnings:
            self.warn(where, e, [path + ".signals"])
        return out, layout

    # check_j1939: signal fit and overlap, duplicate PGNs, default TX length.
    def check_signals(self, signals, length, where, path, layout=None):
        """Fit and overlap; signals on different pages of `layout` (a
        mux.Layout) may share bits."""
        owner = {}
        reported = set()
        for i, s in enumerate(signals):
            fits = True
            for b in j1939_signal_bits(s["start_bit"], s["length"], s["big_endian"]):
                if b >= length * 8:
                    fits = False
                    continue
                # The latest earlier signal on this bit that can share a frame.
                o = next((o for o in reversed(owner.get(b, ())) if layout is None or layout.can_share(
                    signals[o]["index"], s["index"])), None)
                if o is not None and (o, i) not in reported:
                    reported.add((o, i))
                    self.err(where, "signals %s and %s overlap" % (signals[o]["name"], s["name"]),
                             [signals[o]["path"], s["path"]])
                owner.setdefault(b, []).append(i)
            if not fits:
                self.err(where, "signal %s (start bit %d, %d bits) does not fit in %d bytes"
                         % (s["name"], s["start_bit"], s["length"], length), [s["path"]])

    def check(self, j):
        def same_filter(a, b):
            if (a["source"] is None) != (b["source"] is None) or \
                    (a["source_name"] is None) != (b["source_name"] is None):
                return False
            if a["source"] is not None:
                return a["source"] == b["source"]
            if a["source_name"] is not None:
                return a["source_name"] == b["source_name"] and a["source_name_mask"] == b["source_name_mask"]
            return True

        for i, r in enumerate(j["rx"]):
            # A received message is as long as its sender makes it; the
            # signals only have to fit what the transport protocol carries.
            self.check_signals(r["signals"], J1939_MAX_LENGTH, "j1939: rx[%d]" % i, "j1939.rx[%d]" % i, r["layout"])
            for k in range(i):
                if r["pgn"] is not None and j["rx"][k]["pgn"] == r["pgn"] and same_filter(j["rx"][k], r):
                    self.err("j1939", "rx[%d] and rx[%d] both receive PGN %s with the same source filter"
                             % (k, i, j1939_pgn_text(r["pgn"])), ["j1939.rx[%d]" % k, "j1939.rx[%d]" % i])
        for i, t in enumerate(j["tx"]):
            w = "j1939: tx[%d]" % i
            if t["length"] is None:
                t["length"] = max(8, j1939_bytes_needed(t["signals"]))
                if t["length"] > J1939_MAX_LENGTH:
                    self.err(w, "the signals need %d bytes; a message carries at most %d"
                             % (t["length"], J1939_MAX_LENGTH), ["j1939.tx[%d]" % i])
                    t["length"] = J1939_MAX_LENGTH
            self.check_signals(t["signals"], t["length"], w, "j1939.tx[%d]" % i, t["layout"])
            for k in range(i):
                if t["pgn"] is not None and j["tx"][k]["pgn"] == t["pgn"]:
                    self.err("j1939", "tx[%d] and tx[%d] both send PGN %s" % (k, i, j1939_pgn_text(t["pgn"])),
                             ["j1939.tx[%d]" % k, "j1939.tx[%d]" % i])
        d = j["diagnostics"] or {"rx": [], "dtcs": []}
        for i, r in enumerate(d["rx"]):
            for k in range(i):
                if same_filter(d["rx"][k], r):
                    self.err("j1939: diagnostics", "rx[%d] and rx[%d] have the same source filter" % (k, i),
                             [d["rx"][k]["path"], r["path"]])
        for i, c in enumerate(d["dtcs"]):
            for k in range(i):
                o = d["dtcs"][k]
                if (o["spn"], o["fmi"]) == (c["spn"], c["fmi"]):
                    self.err("j1939: diagnostics", "dtcs[%d] and dtcs[%d] both report SPN %d FMI %d"
                             % (k, i, c["spn"], c["fmi"]), [o["path"], c["path"]])


def check_j1939(net, err, warn=None):
    """The plugin's checks of one J1939 network's j1939 object (the network's
    adapter and keys are checked by the caller). `err(where, message,
    paths)` (and `warn`, the same for warnings) gets places and paths
    relative to the network. Returns the parsed object (parse_j1939()) or
    None when there is none."""
    j = net.get("j1939")
    if "j1939" not in net:
        err("", "a J1939 network needs a 'j1939' object", ["j1939"])
        return None
    if not isinstance(j, dict):
        err("", "field 'j1939' must be an object", ["j1939"])
        return None
    return _J1939Parser(err, warn).parse(j)


def parse_j1939(net):
    """A J1939 network's j1939 object as the plugin reads it: {"ecu": {"name":
    {field: value}, "address", "address_range", "state_location",
    "address_location"}, "dbc", "rx": [...], "tx": [...], "requests": [...]}
    with defaults filled in (tx length, priority, destination) and locations
    as iec.Location; signals {"name", "start_bit", "length", "big_endian",
    "signed", "scale", "offset", "unit", "location", "valid_location",
    "path"}. Meant for a config that passed check_config."""
    return check_j1939(net, lambda *a: None) or {"ecu": None, "dbc": None, "rx": [], "tx": [], "requests": []}
