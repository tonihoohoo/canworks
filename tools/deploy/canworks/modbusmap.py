"""Modbus register map of a bridge config (modbus-bridge-map).

A bridge config (a version 2 config with a top-level `bridge` object) is
byte-addressed: %IWn is input bytes n..n+1, %IXn.b is bit b of input byte n,
the same for %Q. canworks-bridge serves input byte n in input register n // 2
(even n the high byte), %IXn.b as discrete input n * 8 + b, output byte n in
holding register n // 2 and %QXn.b as coil n * 8 + b. This module computes
that map from the config alone, writes it as CSV, JSON or an ST variable
list, suggests client channels, and repacks a config densely ("Pack for
Modbus"). It mirrors plugin/src/bridge/byte_image.h.
"""

import copy
import csv
import io
import json

from .iec import parse_location

# Bytes per location size letter.
SIZE_BYTES = {"X": 1, "B": 1, "W": 2, "D": 4, "L": 8}
IEC_TYPES = {"X": "BOOL", "B": "BYTE", "W": "WORD", "D": "DWORD", "L": "LWORD"}
# CANopen types as the matching IEC elementary type, for the ST list.
CO_TO_IEC = {
    "BOOLEAN": "BOOL", "INTEGER8": "SINT", "UNSIGNED8": "USINT",
    "INTEGER16": "INT", "UNSIGNED16": "UINT", "INTEGER32": "DINT",
    "UNSIGNED32": "UDINT", "REAL32": "REAL", "INTEGER64": "LINT",
    "UNSIGNED64": "ULINT", "REAL64": "LREAL",
}

# The bridge's own blocks: config path, direction, size in bytes.
BRIDGE_BLOCKS = {
    "status_location": ("I", 8),
    "control_location": ("Q", 6),
}
LIVE_LIST_BYTES = 16
SDO_BRIDGE_BYTES = 14

MAX_READ_REGISTERS = 125
MAX_WRITE_REGISTERS = 123
WORD_ORDERS = ("high_first", "low_first")


class MapError(ValueError):
    """The config is not a bridge config, or its locations break the byte rules."""


def is_bridge_config(cfg):
    return isinstance(cfg, dict) and isinstance(cfg.get("bridge"), dict)


class Item:
    """One located value of the config.

    `kind` orders packing: "data" (PDO entries, signals, SDO variable values),
    "status" (every other *_location), "bridge" (the bridge's own blocks).
    `nbytes` is the block length for the bridge blocks, else the location
    size. `holder`/`key` point at the dict entry that holds the location text,
    so packing can rewrite it."""

    def __init__(self, holder, key, text, loc, kind, name, network, source, obj,
                 co_type=None, nbytes=None, extra=None):
        self.holder = holder
        self.key = key
        self.text = text
        self.loc = loc
        self.kind = kind
        self.name = name
        self.network = network
        self.source = source
        self.obj = obj
        self.co_type = co_type
        self.nbytes = nbytes if nbytes is not None else SIZE_BYTES[loc.size]
        self.extra = extra or {}

    @property
    def direction(self):
        return "input" if self.loc.area == "I" else "output"

    @property
    def start_byte(self):
        return self.loc.index

    def byte_range(self):
        return range(self.loc.index, self.loc.index + self.nbytes)


def _hex(value):
    if isinstance(value, int):
        return "0x%04X" % value
    return str(value)


def _object_text(entry):
    if "index" in entry:
        sub = entry.get("subindex", 0)
        return "%s:%s" % (_hex(entry["index"]), sub)
    if "pgn" in entry:
        return "PGN %s" % entry["pgn"]
    if "id" in entry:
        return "ID %s" % _hex(entry["id"])
    return ""


def _walk(value, ctx, out):
    """Collects every location string below `value`. `ctx` carries the
    network, node or source and the nearest object description."""
    if isinstance(value, dict):
        ctx = dict(ctx)
        if "node_id" in value and ("eds" in value or "tx_pdos" in value or "rx_pdos" in value):
            ctx["source"] = value.get("name") or "node %s" % value["node_id"]
        if "number" in value and "entries" in value:
            ctx["pdo"] = "%s%s" % ("RPDO" if ctx.get("parent_key") == "rx_pdos" else "TPDO", value["number"])
        obj = _object_text(value)
        if obj:
            ctx["object"] = obj
        if "name" in value and isinstance(value.get("name"), str):
            ctx["label"] = value["name"]
        for key, sub in value.items():
            if isinstance(sub, str) and (key == "iec_location" or key.endswith("_location")):
                loc = parse_location(sub)
                if loc is None or loc.area == "M":
                    continue
                kind = "data" if key == "iec_location" else "status"
                if key == "iec_location":
                    label = ctx.get("label")
                    if label in (ctx.get("source"), ctx.get("network")):
                        label = None
                    name = label or ctx.get("object") or key
                    if ctx.get("source"):
                        name = "%s.%s" % (ctx["source"], name)
                else:
                    name = key[: -len("_location")]
                    if "pdo" in ctx and "entries" in value:
                        name = "%s.%s" % (ctx["pdo"], name)
                    base = ctx.get("label") or ctx.get("source") or ctx.get("network")
                    if base:
                        name = "%s.%s" % (base, name)
                out.append(Item(value, key, sub, loc, kind, name, ctx.get("network"),
                                ctx.get("source"), ctx.get("object", ""),
                                co_type=value.get("type") if key == "iec_location" else None,
                                extra={k: value[k] for k in ("scale", "offset", "unit") if k in value}))
            elif isinstance(sub, (dict, list)):
                _walk(sub, dict(ctx, parent_key=key), out)
    elif isinstance(value, list):
        for sub in value:
            _walk(sub, ctx, out)


def _bridge_items(bridge):
    out = []
    for key, (area, nbytes) in BRIDGE_BLOCKS.items():
        text = bridge.get(key)
        if text is None:
            continue
        out.append(_block_item(bridge, key, text, area, nbytes, "bridge." + key[: -len("_location")]))
    for i, entry in enumerate(bridge.get("live_lists") or []):
        if isinstance(entry, dict) and "location" in entry:
            out.append(_block_item(entry, "location", entry["location"], "I", LIVE_LIST_BYTES,
                                   "bridge.live_list.%s" % entry.get("network", i),
                                   network=entry.get("network")))
    sdo = bridge.get("sdo_bridge_location")
    if isinstance(sdo, dict):
        for key, area in (("request", "Q"), ("response", "I")):
            if key in sdo:
                out.append(_block_item(sdo, key, sdo[key], area, SDO_BRIDGE_BYTES,
                                       "bridge.sdo_bridge.%s" % key))
    return out


def _block_item(holder, key, text, area, nbytes, name, network=None):
    loc = parse_location(text)
    if loc is None or loc.size != "B" or loc.area != area:
        raise MapError("%s: %r must be a byte location in %%%s (a %d-byte block starts there)"
                       % (name, text, area, nbytes))
    return Item(holder, key, text, loc, "bridge", name, network, None, "", nbytes=nbytes)


def collect(cfg):
    """Every located value of a bridge config, in config order, bridge blocks last."""
    if not is_bridge_config(cfg):
        raise MapError("not a bridge config: it has no top-level \"bridge\" object")
    items = []
    for net in cfg.get("networks") or []:
        _walk(net, {"network": net.get("name")}, items)
    rest = {k: v for k, v in cfg.items() if k not in ("networks", "bridge", "diagnostics")}
    _walk(rest, {}, items)
    items.extend(_bridge_items(cfg["bridge"]))
    return items


def check(items):
    """Byte rules of a bridge config: word and larger locations start at an
    even byte, and no two locations share a byte (bits may share a byte with
    other bits only). Returns a list of problem strings."""
    problems = []
    for it in items:
        if it.loc.size in "WDL" and it.loc.index % 2:
            problems.append("%s: %s must start at an even byte (word locations are whole registers)"
                            % (it.name, it.text))
    for area in "IQ":
        owners = {}
        for it in items:
            if it.loc.area != area:
                continue
            for b in it.byte_range():
                owners.setdefault(b, []).append(it)
        reported = set()
        for b in sorted(owners):
            users = owners[b]
            if len(users) < 2:
                continue
            bits = [u for u in users if u.loc.size == "X"]
            if len(bits) == len(users):
                seen = {}
                for u in bits:
                    if u.loc.bit in seen and (id(seen[u.loc.bit]), id(u)) not in reported:
                        reported.add((id(seen[u.loc.bit]), id(u)))
                        problems.append("%s (%s) and %s (%s) use the same bit"
                                        % (seen[u.loc.bit].name, seen[u.loc.bit].text, u.name, u.text))
                    seen.setdefault(u.loc.bit, u)
                continue
            for i in range(len(users)):
                for j in range(i + 1, len(users)):
                    a, c = users[i], users[j]
                    if a.loc.size == "X" and c.loc.size == "X":
                        continue
                    pair = (id(a), id(c))
                    if pair in reported:
                        continue
                    reported.add(pair)
                    shared = sorted(set(a.byte_range()) & set(c.byte_range()))
                    problems.append("%s (%s) and %s (%s) overlap in %s byte%s %s"
                                    % (a.name, a.text, c.name, c.text,
                                       "input" if area == "I" else "output",
                                       "s" if len(shared) > 1 else "",
                                       " and ".join(str(x) for x in shared)))
    return problems


def _row(it, word_order):
    loc = it.loc
    if loc.size == "X":
        table = "discrete input" if loc.area == "I" else "coil"
        address = loc.index * 8 + loc.bit
        count = 1
    else:
        table = "input register" if loc.area == "I" else "holding register"
        address = loc.index // 2
        count = max(1, (it.nbytes + 1) // 2)
    row = {
        "name": it.name,
        "network": it.network or "",
        "source": it.source or "",
        "object": it.obj,
        "direction": it.direction,
        "location": it.text,
        "table": table,
        "address": address,
        "count": count,
        "byte": loc.index,
        "type": it.co_type or ("BLOCK" if it.kind == "bridge" else IEC_TYPES[loc.size]),
        "word_order": word_order if it.nbytes >= 4 and it.kind != "bridge" else "",
        "scale": it.extra.get("scale", ""),
        "offset": it.extra.get("offset", ""),
        "unit": it.extra.get("unit", ""),
    }
    if loc.size == "B" and it.kind != "bridge":
        row["byte_in_register"] = "high" if loc.index % 2 == 0 else "low"
    return row


def register_map(cfg):
    """The register map rows of a bridge config, sorted by table and address.
    Raises MapError when the config breaks the byte rules."""
    items = collect(cfg)
    problems = check(items)
    if problems:
        raise MapError("; ".join(problems))
    word_order = cfg["bridge"].get("word_order", "high_first")
    if word_order not in WORD_ORDERS:
        raise MapError("bridge.word_order must be high_first or low_first, not %r" % word_order)
    order = {"input register": 0, "discrete input": 1, "holding register": 2, "coil": 3}
    rows = [_row(it, word_order) for it in items]
    rows.sort(key=lambda r: (order[r["table"]], r["address"], r["name"]))
    return rows


def image_sizes(rows):
    """(input bytes, output bytes) the bridge serves, each rounded up to even."""
    sizes = {"input": 0, "output": 0}
    for r in rows:
        if r["table"] in ("discrete input", "coil"):
            end = r["byte"] + 1
        else:
            end = (r["address"] + r["count"]) * 2
        sizes[r["direction"]] = max(sizes[r["direction"]], end)
    return tuple(n + (n % 2) for n in (sizes["input"], sizes["output"]))


def suggest_channels(rows):
    """Client channels that cover the used register ranges in as few requests
    as the Modbus limits allow: [(function, start, count, direction)].
    Bits are covered by the registers they live in."""
    used = {"input": set(), "output": set()}
    for r in rows:
        if r["table"] in ("discrete input", "coil"):
            used[r["direction"]].add(r["byte"] // 2)
        else:
            used[r["direction"]].update(range(r["address"], r["address"] + r["count"]))
    channels = []
    for direction, function, limit in (("input", 4, MAX_READ_REGISTERS),
                                       ("output", 16, MAX_WRITE_REGISTERS)):
        regs = sorted(used[direction])
        i = 0
        while i < len(regs):
            start = regs[i]
            j = i
            # Extend while the next used register still fits in this request.
            while j + 1 < len(regs) and regs[j + 1] - start < limit:
                j += 1
            channels.append((function, start, regs[j] - start + 1, direction))
            i = j + 1
    return channels


# -- writers ---------------------------------------------------------------

CSV_FIELDS = ("name", "network", "source", "object", "direction", "location", "table",
              "address", "count", "type", "word_order", "scale", "offset", "unit")


def to_csv(rows):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=CSV_FIELDS, extrasaction="ignore", lineterminator="\n")
    w.writeheader()
    for r in rows:
        w.writerow(r)
    return buf.getvalue()


def to_json(cfg, rows):
    b = cfg["bridge"]
    inputs, outputs = image_sizes(rows)
    doc = {
        "listen": b.get("listen", ""),
        "unit_id": b.get("unit_id", 1),
        "word_order": b.get("word_order", "high_first"),
        "input_bytes": inputs,
        "output_bytes": outputs,
        "registers": rows,
        "channels": [{"function": f, "start": s, "count": c, "direction": d}
                     for f, s, c, d in suggest_channels(rows)],
    }
    return json.dumps(doc, indent=2) + "\n"


def _st_name(name):
    out = []
    for ch in name:
        out.append(ch if ch.isalnum() else "_")
    text = "".join(out).strip("_") or "value"
    while "__" in text:
        text = text.replace("__", "_")
    if text[0].isdigit():
        text = "v_" + text
    return text


def to_st(cfg, rows):
    """A VAR_GLOBAL list for a PLC that reads the bridge as a Modbus client,
    plus a comment table of suggested client channels."""
    lines = ["(* Modbus register map of the canworks bridge at %s, unit %s, word order %s. *)"
             % (cfg["bridge"].get("listen", "?"), cfg["bridge"].get("unit_id", 1),
                cfg["bridge"].get("word_order", "high_first")),
             "VAR_GLOBAL"]
    taken = set()
    for r in rows:
        if r["type"] == "BLOCK":
            iec = "ARRAY[0..%d] OF WORD" % (r["count"] - 1)
        else:
            iec = CO_TO_IEC.get(r["type"], r["type"])
        name = _st_name(r["name"])
        base, n = name, 2
        while name.lower() in taken:
            name = "%s_%d" % (base, n)
            n += 1
        taken.add(name.lower())
        where = "%s %d" % (r["table"], r["address"])
        if r["count"] > 1:
            where += "..%d" % (r["address"] + r["count"] - 1)
        if r.get("byte_in_register"):
            where += " (%s byte)" % r["byte_in_register"]
        notes = [where]
        src = " ".join(x for x in (r["network"], r["source"], r["object"]) if x)
        if src:
            notes.append(src)
        if r["unit"]:
            notes.append(str(r["unit"]))
        if r["scale"] != "":
            notes.append("scale %s" % r["scale"])
        lines.append("    %s : %s; (* %s *)" % (name, iec, ", ".join(notes)))
    lines.append("END_VAR")
    lines.append("")
    lines.append("(* Suggested client channels:")
    lines.append("   function  start  count  direction")
    for f, s, c, d in suggest_channels(rows):
        lines.append("   %-8d  %-5d  %-5d  %s" % (f, s, c, "read input registers" if d == "input"
                                                    else "write holding registers"))
    lines.append("*)")
    return "\n".join(lines) + "\n"


def export(cfg, path):
    """Writes the map of `cfg` to `path` in the format of its extension."""
    rows = register_map(cfg)
    lower = path.lower()
    if lower.endswith(".csv"):
        text = to_csv(rows)
    elif lower.endswith(".json"):
        text = to_json(cfg, rows)
    elif lower.endswith(".st"):
        text = to_st(cfg, rows)
    else:
        raise MapError("unknown map format for %s: use .csv, .json or .st" % path)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return rows


# -- Pack for Modbus ---------------------------------------------------------

def _fmt(area, size, index, bit=None):
    if size == "X":
        return "%%%sX%d.%d" % (area, index, bit)
    return "%%%s%s%d" % (area, size, index)


def pack(cfg):
    """A copy of `cfg` with every location reassigned densely: per direction,
    data from byte 0 in config order, then status locations, then the bridge
    blocks; word and larger values word-aligned; bits share bytes."""
    if not is_bridge_config(cfg):
        raise MapError("not a bridge config: it has no top-level \"bridge\" object")
    out = copy.deepcopy(cfg)
    items = collect(out)
    for area in "IQ":
        pos = 0
        bit_byte = None
        bit_next = 8
        for kind in ("data", "status", "bridge"):
            for it in (x for x in items if x.loc.area == area and x.kind == kind):
                if it.loc.size == "X":
                    if bit_next > 7:
                        bit_byte, bit_next = pos, 0
                        pos += 1
                    it.holder[it.key] = _fmt(area, "X", bit_byte, bit_next)
                    bit_next += 1
                    continue
                if it.nbytes >= 2 or it.kind == "bridge":
                    pos += pos % 2
                it.holder[it.key] = _fmt(area, it.loc.size, pos)
                pos += it.nbytes
            # The next class starts on its own byte.
            bit_next = 8
    return out
