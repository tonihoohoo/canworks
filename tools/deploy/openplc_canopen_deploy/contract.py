"""The CANopen config contract: schema_version, the published JSON Schema, and
the checks the plugin runs that the schema cannot express.

Messages that the plugin also produces use the plugin's wording (see
plugin/src/config.cpp); the shared fixtures in test/fixtures/config/ hold both
to it.
"""

import json
import math
import os
import re

import jsonschema
from jsonschema.exceptions import best_match

from . import axis as axis_mod
from . import eds as eds_mod
from . import edslint
from .eds import sync_needed_message, transmission_needs_sync
from .iec import CO_TYPES, parse_location, type_fits, SIZE_BITS

SUPPORTED_VERSION = 2
MAX_NETWORKS = 8
_SCHEMA_DIR = os.path.join(os.path.dirname(__file__), "schema")
_schemas = {}
_V1_REF = "canopen.v1.schema.json#"
NETWORK_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,15}$")


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
        with open(os.path.join(_SCHEMA_DIR, "canopen.v%d.schema.json" % version), encoding="utf-8") as f:
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
    network's fields, "" for version 1), `role` ("master" or "slave"),
    `adapter`, `master` and `nodes` (empty for a slave network) and `slave`
    (the slave object, empty for a master network). A version 2 network
    without a name is named after its interface."""
    if version_of(cfg) == 1 or not isinstance(cfg.get("networks"), list):
        adapter = cfg.get("adapter")
        if adapter is None and "interface" in cfg:
            adapter = {"type": "socketcan", "interface": cfg.get("interface"), "bitrate": cfg.get("bitrate")}
        return [{"name": "", "index": 0, "path": "", "role": "master", "adapter": adapter or {},
                 "master": cfg.get("master") or {}, "nodes": cfg.get("nodes") or [], "slave": {}, "json": cfg}]
    out = []
    for i, net in enumerate(cfg["networks"]):
        if not isinstance(net, dict):
            continue
        adapter = net.get("adapter") if isinstance(net.get("adapter"), dict) else {}
        name = net.get("name")
        if not isinstance(name, str) or not name:
            iface = adapter.get("interface")
            name = iface if isinstance(iface, str) and NETWORK_NAME.match(iface) else ""
        slave = net.get("role") == "slave"
        out.append({"name": name, "index": i, "path": "networks[%d]" % i, "role": "slave" if slave else "master",
                    "adapter": adapter, "master": {} if slave else net.get("master") or {},
                    "nodes": [] if slave else net.get("nodes") or [],
                    "slave": (net.get("slave") if isinstance(net.get("slave"), dict) else {}) if slave else {},
                    "json": net})
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


def _uint(value):
    """An unsigned integer given as a JSON number or a "0x.."/decimal string,
    as the plugin reads it; None if it is not one."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float):
        return int(value) if value >= 0 and value == math.floor(value) else None
    if isinstance(value, str) and re.match(r"^(0[xX][0-9a-fA-F]+|[0-9]+)$", value):
        return int(value, 16) if value[:2].lower() == "0x" else int(value, 0 if value == "0" else 10)
    return None


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
            props.update(_properties(sub, root))
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


def sdo_override(node, entry, data):
    """What a startup SDO overrides among the settings the plugin writes for
    the node (the same rule as the plugin's warning), or None."""
    index, sub = entry["index"], entry["subindex"]
    value = int.from_bytes(data or b"", "little")
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
    schema_errors = sorted(validator.iter_errors(cfg), key=lambda e: list(map(str, e.absolute_path)))
    found = []
    unknown_fields(cfg, s, s, [], found)
    base = eds_dir if eds_dir is not None else os.path.dirname(os.path.abspath(path))
    sw_paths = software_paths if software_paths is not None else software_files(cfg, base)
    args = dict(path=path, base=base, eds_paths=eds_paths, sw_paths=sw_paths)

    if version == 1:
        # Slave networks and the gateway exist only in version 2 (canopen-
        # config-contract: "Slave network role").
        for key in V2_ONLY_KEYS:
            if key in cfg:
                err("", "field '%s' needs schema_version 2: slave networks are entries of 'networks' with "
                        "\"role\": \"slave\"" % key, [key])
        found = [(where, key) for where, key in found if where not in V2_ONLY_KEYS]
        _check_network(r, cfg, "", 1, [(list(e.absolute_path), e) for e in schema_errors], **args)
    else:
        _check_v2(r, cfg, schema_errors, err, warn, args)
    for where, key in found:
        parent = where[: -len(key)].rstrip(".")
        warn(parent, "unknown field '%s' (%s) ignored" % (key, where), [where])
    return r


# Top-level keys a version 1 file may not have.
V2_ONLY_KEYS = ("role", "slave", "gateway")

MOVED_V1_KEYS = (("adapter", "networks[].adapter"), ("master", "networks[].master"), ("nodes", "networks[].nodes"),
                 ("interface", "networks[].adapter.interface"), ("bitrate", "networks[].adapter.bitrate"))


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
        where = json_path(p)
        if where == "" and e.validator in ("not", "required"):
            continue  # moved keys and a missing networks list, reported above
        if where == "networks" and e.validator in ("minItems", "maxItems", "type"):
            continue  # reported above
        if where == "schema_version":
            err("", "field 'schema_version' must be 2 in a file with 'networks'", ["schema_version"])
            continue
        err(where, e.message)
    diag = isinstance(cfg.get("diagnostics"), dict)
    routed = routed_entries(cfg)
    slaves = {}
    for i, net in enumerate(nets):
        prefix = "networks[%d]" % i
        if not isinstance(net, dict):
            err(prefix, "must be an object", [prefix])
            continue
        before = len(r.errors)
        role = "slave" if net.get("role") == "slave" else "master"
        if role == "slave":
            for key in ("master", "nodes"):
                if key in net:
                    err(prefix, "field '%s' belongs to a master network; a slave network (\"role\": \"slave\") has "
                                "'slave' instead" % key, [prefix + "." + key])
        elif "slave" in net:
            err(prefix, "field 'slave' belongs to a slave network: give the network \"role\": \"slave\" (a master "
                        "network has 'master' and 'nodes')", [prefix + ".slave"])
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
            (p == ["master"] and e.validator == "not"))]
        adapter = net.get("adapter") if isinstance(net.get("adapter"), dict) else {}
        name = net.get("name") if isinstance(net.get("name"), str) and net.get("name") else adapter.get("interface")
        _check_network(r, net, prefix, 2, errors, diag=diag, before=before, role=role, routed=routed,
                       net_name=name if isinstance(name, str) else "", slaves=slaves, net_index=i, **args)
        iface = adapter.get("interface")
        if "name" not in net and isinstance(iface, str) and iface and not NETWORK_NAME.match(iface):
            err(prefix, 'interface "%s" is not usable as a network name; give the network a \'name\'' % iface,
                [prefix + ".adapter.interface"])
    _check_across_networks(r, cfg, err)
    # The gateway's own checks read the section's fields, so they run only
    # once its shape is right (the schema errors above say what is not).
    if "gateway" in cfg and not any(list(e.absolute_path)[:1] == ["gateway"] for e in schema_errors):
        _check_gateway(cfg, err, warn, slaves)


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


def _check_across_networks(r, cfg, err):
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
            if kind == "slcan":
                if "device" not in a:
                    err("adapter", "missing required field 'device'", ["adapter.device"])
                elif isinstance(a["device"], str) and a["device"] and not a["device"].startswith("/"):
                    err("adapter", "field 'device' must be an absolute path such as /dev/ttyACM0", ["adapter.device"])
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
        if (where == "master" and e.validator == "not") or where == "master.eds_lint":
            continue  # reported above
        if where.endswith("diagnostics.token_sha256"):
            err(where, "the diagnostics channel is encrypted now and needs a 'token_verifier' instead: set the token "
                       "again (configurator: Online access, Upgrade or New token; or openplc-canopen-diag hash-token)")
            continue
        if where.endswith("diagnostics") and e.validator == "required" and "token_verifier" in e.message:
            d = cfg.get("diagnostics") if where == "diagnostics" else (cfg.get("master") or {}).get("diagnostics")
            if isinstance(d, dict) and "token_sha256" in d:
                continue  # reported as token_sha256
        if where.endswith("diagnostics.token_verifier") and e.validator == "pattern":
            err(where, "field 'token_verifier' must look like SCRAM-SHA-256$<iterations>:<salt>$<StoredKey>:"
                       "<ServerKey> (openplc-canopen-diag hash-token prints it)")
            continue
        if role == "slave" and where.split(".")[0].split("[")[0] in ("master", "nodes"):
            continue  # misplaced in a slave network, reported by _check_v2
        if (where == "master" and e.validator == "required" and "'diagnostics'" in e.message) or (
                version > 1 and where == "nodes" and e.validator == "minItems"):
            # The schema's rule for an empty node list, in the plugin's words.
            err("", "field 'nodes' lists no slave nodes (an empty list needs %s, for a scan-only configuration)"
                % ("master.diagnostics" if version == 1 else "a top-level 'diagnostics'"), ["nodes"])
            continue
        pdo_msg = _pdo_schema_message(cfg, list(rel), e)
        if pdo_msg:
            err(pdo_msg[0], pdo_msg[1], [where])
            continue
        err(where, e.message)

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
    _error_behavior(master, "master", err)
    if master.get("start") is False:
        warn("master", "'start' is false: the master stays PRE-OPERATIONAL and no PDOs are exchanged until it is "
                       "started", ["master.start"])
    master_hb = _uint(master.get("heartbeat_ms", 0)) or 0
    nodes = []
    seen = {}
    for i, n in enumerate(cfg["nodes"]):
        node = {"node_id": _uint(n["node_id"]), "name": n.get("name", ""), "eds": n["eds"],
                "tx_pdos": [], "rx_pdos": [], "sdo": [], "sdo_variables": [],
                "config_check": n.get("config_check") is True, "no_sync": not sync_period}
        label = "node %d" % node["node_id"] + (" (%s)" % node["name"] if node["name"] else "")
        w = "nodes[%d]" % i
        if n.get("heartbeat_consumer") is True and not master_hb:
            err(w, "'heartbeat_consumer' needs a master heartbeat (master 'heartbeat_ms' above 0)",
                [w + ".heartbeat_consumer"])
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
            err("nodes", "node ID %d is the master's node ID" % node["node_id"], ["master.node_id", w + ".node_id"])
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
                        if (net_name, node["node_id"], entry["index"], entry["subindex"]) not in routed:
                            err("%s: entries[%d]" % (pw, k),
                                "%s, object 0x%04X:%d: missing 'iec_location' (only an entry a gateway route uses "
                                "may leave it out)" % (label, entry["index"], entry["subindex"]),
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
            over = None if problem else sdo_override(n, entry, data)
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

    # "auto" COB-IDs, as the plugin resolves them.
    for (i, key, j), cob in auto_cob_ids(nodes).items():
        nodes[i][key][j]["cob_id"] = cob

    # CiA 402 axes: the standard objects the motion blocks' drive bridge needs.
    axis_mod.check(cfg, err, warn)

    if len(r.errors) > before:
        return

    # EDS checks, node by node. Their warnings (objects a device mapping
    # sends as 0) only matter for a config that is accepted.
    eds_warnings = []
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
        messages, where, warnings = [], [], []
        eds_mod.check_node(node, eds, messages, where, warnings)
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
            warn("gateway", "gateway status: only the first %d master networks are published; network \"%s\" is not"
                 % (MAX_STATUS_NETWORKS, masters[MAX_STATUS_NETWORKS]["name"]), ["gateway.status"])
        if eds is not None:
            base_index = _uint(g["status"].get("index", DEFAULT_STATUS_INDEX))
            for k, m in enumerate(masters[:MAX_STATUS_NETWORKS]):
                rec, bits = base_index + k, base_index + 0x10 + k
                # The first master network's records are required; a later
                # network whose records are both missing (an EDS generated
                # for fewer networks) is left out with a warning, as the
                # plugin does.
                if k > 0 and not eds.has(rec) and not eds.has(bits):
                    warn("gateway", "gateway status of network \"%s\" is not published: objects 0x%04X and 0x%04X are "
                                    "not in the EDS %s" % (m["name"], rec, bits, eds_name), ["gateway.status"])
                    continue
                for index in (rec, bits):
                    if not eds.has(index):
                        err("gateway", "gateway status of network \"%s\" needs object 0x%04X in the EDS %s (generate "
                                       "the slave EDS with the gateway section: openplc-canopen-deploy slave-eds "
                                       "--gateway)" % (m["name"], index, eds_name), ["gateway.status"])
    if g.get("sdo_bridge") is True and eds is not None:
        index = _uint(g.get("sdo_bridge_index", DEFAULT_BRIDGE_INDEX))
        if not eds.has(index) or eds.find(index, 9) is None:
            err("gateway", "'sdo_bridge' needs the SDO bridge record 0x%04X (sub-indices 1-9) in the slave's EDS %s; "
                           "generate the EDS with openplc-canopen-deploy slave-eds --gateway" % (index, eds_name),
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
