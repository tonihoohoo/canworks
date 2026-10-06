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

SUPPORTED_VERSION = 1
_SCHEMA_DIR = os.path.join(os.path.dirname(__file__), "schema")
_schemas = {}


def schema(version=SUPPORTED_VERSION):
    if version not in _schemas:
        with open(os.path.join(_SCHEMA_DIR, "canopen.v%d.schema.json" % version), encoding="utf-8") as f:
            _schemas[version] = json.load(f)
    return _schemas[version]


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
    for n in cfg.get("nodes", []):
        value = n.get("software_file") if isinstance(n, dict) else None
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
    or relative to `eds_dir`. Returns a Result.
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
    s = schema(version)
    validator = jsonschema.Draft202012Validator(s)
    for e in sorted(validator.iter_errors(cfg), key=lambda e: list(map(str, e.absolute_path))):
        while e.context:
            # Of the alternatives, the one for the value's own type says what
            # is wrong with it ("200 is greater than the maximum of 127").
            fitting = [c for c in e.context if c.validator != "type"]
            e = best_match(fitting or e.context)
        where = json_path(list(e.absolute_path))
        if where in ("", "adapter") and e.validator in ("oneOf", "not", "required", "enum") and (
                "adapter" in e.message or "interface" in e.message or "bitrate" in e.message
                or "device" in e.message or e.validator == "not" or "socketcan" in e.message):
            continue  # reported above, in the plugin's words
        if where == "adapter.device" and e.validator == "pattern":
            continue
        if (where == "master" and e.validator == "not") or where == "master.eds_lint":
            continue  # reported above
        if where == "master" and e.validator == "required" and "'diagnostics'" in e.message:
            # The schema's rule for an empty node list, in the plugin's words.
            err("", "field 'nodes' lists no slave nodes (an empty list needs master.diagnostics, for a "
                    "scan-only configuration)", ["nodes"])
            continue
        pdo_msg = _pdo_schema_message(cfg, list(e.absolute_path), e)
        if pdo_msg:
            err(pdo_msg[0], pdo_msg[1], [where])
            continue
        err(where, e.message)

    found = []
    unknown_fields(cfg, s, s, [], found)
    for where, key in found:
        parent = where[: -len(key)].rstrip(".")
        warn(parent, "unknown field '%s' (%s) ignored" % (key, where), [where])

    if r.errors:
        return r

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
    base = eds_dir if eds_dir is not None else os.path.dirname(os.path.abspath(path))
    sw_paths = software_paths if software_paths is not None else software_files(cfg, base)
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

    # CiA 402 axes: the standard objects the motion blocks' drive bridge needs.
    axis_mod.check(cfg, err, warn)

    if r.errors:
        return r

    # EDS checks, node by node. Their warnings (objects a device mapping
    # sends as 0) only matter for a config that is accepted.
    eds_warnings = []
    lint_mode = edslint.effective_mode(master)
    for i, node in enumerate(nodes):
        w = "nodes[%d]" % i
        file = (eds_paths or {}).get(node["eds"]) or os.path.join(base, node["eds"])
        if not os.path.isfile(file):
            r.add("error", "node %d: EDS file %s not found" % (node["node_id"], file), [w + ".eds"])
            continue
        # The plugin's EDS lint, on the prepared copy every later check reads.
        with open(file, "rb") as f:
            text, corrections, lint = edslint.check(f.read(), node["node_id"])
        label = "node %d" % node["node_id"] + (" (%s)" % node["name"] if node.get("name") else "")
        lint_error, lint_warning, _ = edslint.verdict(label, node["eds"], corrections, lint, lint_mode)
        if lint_error:
            r.add("error", lint_error, [w + ".eds"])
            continue
        if lint_warning:
            eds_warnings.append(("%s: %s" % (label, lint_warning), w + ".eds"))
        try:
            eds = eds_mod.Eds.read(file, text)
        except eds_mod.EdsError as e:
            r.add("error", "node %d: EDS file %s cannot be parsed: %s" % (node["node_id"], file, e), [w + ".eds"])
            continue
        messages, where, warnings = [], [], []
        eds_mod.check_node(node, eds, messages, where, warnings)
        profile = axis_mod.device_type_warning(cfg["nodes"][i], eds)
        if profile:
            warnings.append((profile, ".axis"))
        if "lss" in node:
            info = eds_mod.device_info(file) or {}
            node["lss"].update(vendor_id=info.get("vendor_id") or 0, product_code=info.get("product_code") or 0)
            if not info.get("lss_supported"):
                warnings.append(("%s: its EDS does not say LSS_Supported=1; LSS assignment may not work with this "
                                 "device" % label, ".lss.assign"))
        for msg, sub in zip(messages, where):
            r.add("error", msg, [w + sub])
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
            r.add("error", "%s and %s have the same LSS address (vendor ID 0x%08X, product code 0x%08X, serial "
                  "number 0x%08X)" % (labels[0], labels[1], p["vendor_id"], p["product_code"], p["serial_number"]),
                  ["nodes[%d].lss" % i, "nodes[%d].lss" % j])
    if not r.errors:
        for msg, at in eds_warnings:
            r.add("warning", msg, [at])
    return r
