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
    network's fields, "" for version 1), `adapter`, `master` and `nodes`.
    A version 2 network without a name is named after its interface."""
    if version_of(cfg) == 1 or not isinstance(cfg.get("networks"), list):
        adapter = cfg.get("adapter")
        if adapter is None and "interface" in cfg:
            adapter = {"type": "socketcan", "interface": cfg.get("interface"), "bitrate": cfg.get("bitrate")}
        return [{"name": "", "index": 0, "path": "", "adapter": adapter or {}, "master": cfg.get("master") or {},
                 "nodes": cfg.get("nodes") or [], "json": cfg}]
    out = []
    for i, net in enumerate(cfg["networks"]):
        if not isinstance(net, dict):
            continue
        adapter = net.get("adapter") if isinstance(net.get("adapter"), dict) else {}
        name = net.get("name")
        if not isinstance(name, str) or not name:
            iface = adapter.get("interface")
            name = iface if isinstance(iface, str) and NETWORK_NAME.match(iface) else ""
        out.append({"name": name, "index": i, "path": "networks[%d]" % i, "adapter": adapter,
                    "master": net.get("master") or {}, "nodes": net.get("nodes") or [], "json": net})
    return out


def all_nodes(cfg):
    """Every node entry of the config, network after network (the dicts
    themselves, so changes land in `cfg`)."""
    return [n for net in networks(cfg) for n in net["nodes"] if isinstance(n, dict)]


def network_config(cfg, name=None):
    """A version 1 style config (adapter, master, nodes) of one network, for
    the code that works on one network at a time. `name` picks the network;
    without it the config must have exactly one. Raises ValueError naming the
    networks otherwise. Version 2 diagnostics go into the master."""
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
        field = "inhibit_time_us" if "inhibit_time_us" in p else "sync_start"
        return where, "%s %d: field '%s' is only for tx_pdos (PDOs the node sends)" % (kind, number, field)
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


SYNC_NEEDED = " needs 'sync_period_us' (without it the master produces no SYNC)"


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
        _check_network(r, cfg, "", 1, [(list(e.absolute_path), e) for e in schema_errors], **args)
    else:
        _check_v2(r, cfg, schema_errors, err, args)
    for where, key in found:
        parent = where[: -len(key)].rstrip(".")
        warn(parent, "unknown field '%s' (%s) ignored" % (key, where), [where])
    return r


MOVED_V1_KEYS = (("adapter", "networks[].adapter"), ("master", "networks[].master"), ("nodes", "networks[].nodes"),
                 ("interface", "networks[].adapter.interface"), ("bitrate", "networks[].adapter.bitrate"))


def _check_v2(r, cfg, schema_errors, err, args):
    """A version 2 file: the top level, each network, then the checks across
    networks (canopen-networks spec)."""
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
    for i, net in enumerate(nets):
        prefix = "networks[%d]" % i
        if not isinstance(net, dict):
            err(prefix, "must be an object", [prefix])
            continue
        before = len(r.errors)
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
        _check_network(r, net, prefix, 2, errors, diag=diag, before=before, **args)
        adapter = net.get("adapter") if isinstance(net.get("adapter"), dict) else {}
        iface = adapter.get("interface")
        if "name" not in net and isinstance(iface, str) and iface and not NETWORK_NAME.match(iface):
            err(prefix, 'interface "%s" is not usable as a network name; give the network a \'name\'' % iface,
                [prefix + ".adapter.interface"])
    _check_across_networks(r, cfg, err)


def _check_across_networks(r, cfg, err):
    nets = networks(cfg)
    names, ifaces, devices = {}, {}, {}
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
        if isinstance(iface, str) and iface:
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
        for key, kind in (("tx_pdos", "TPDO"), ("rx_pdos", "RPDO")):
            for j, p in enumerate(n.get(key, [])):
                number = _uint(p.get("number", j + 1))
                for k, e in enumerate(p.get("entries", [])):
                    add(e.get("iec_location"), "%s %s %s object 0x%04X:%d" % (
                        label, kind, number, _uint(e.get("index")) or 0, _uint(e.get("subindex", 0)) or 0),
                        "%s.%s[%d].entries[%d].iec_location" % (w, key, j, k))
    return out


def _check_network(r, cfg, prefix, version, schema_errors, path, base, eds_paths, sw_paths, diag=False, before=None):
    """One network: the version 1 top level, or one networks[] entry of a
    version 2 file (`prefix` "networks[i]", in front of every message's
    place and every path). `schema_errors`: (path inside the network,
    error)."""
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


    if len(r.errors) > before:
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
    # Left out or 0: the master produces no SYNC.
    sync_period = _uint(master.get("sync_period_us", 0)) or 0
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
                    loc = parse_location(e["iec_location"])
                    if not type_fits(e["type"], loc.size):
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
