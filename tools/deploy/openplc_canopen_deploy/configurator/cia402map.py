"""The configurator's "Map CiA 402 objects": puts the standard objects of
a CiA 402 axis (axis.OBJECTS) that the node's EDS has into its PDOs, with
suggested locations.

An object goes into the PDO whose EDS default mapping carries it when that
PDO keeps the device's mapping or is not in the config yet, so a drive's own
layout is kept where it has one. Otherwise it is packed into a PDO written
from the config (8 entries, 64 bits each), a new one if needed. Transmission
types and timers are left out: they stay at the EDS values.
"""

import copy

from .. import axis
from ..iec import CO_TYPES, parse_location
from . import layout


def _int(value):
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    try:
        return int(str(value), 0)
    except ValueError:
        return None


def _number(p, j):
    return _int(p.get("number")) or j + 1


def map_objects(node, info, used, start=layout.DEFAULT_START):
    """(new node, mapped, missing) for node dict `node` and its EDS summary
    `info` (server.eds_summary). `used` is the set of taken location keys
    (layout.taken); it is updated. mapped: [{index, name, pdo, location}];
    missing: [{index, name, reason}]."""
    node = copy.deepcopy(node)
    objects = {(_int(o["index"]), o["subindex"]): o for o in info.get("objects", [])}
    maps = info.get("pdo_maps", {})
    counts = info.get("pdo_count", {})
    have = axis.mapped(node, 0)
    mapped, missing = [], []
    made = []  # PDOs this run added, by identity

    def pdo_map(direction, number):
        return maps.get(direction, {}).get(str(number))

    def keeps_device(p, m):
        return p.get("mapping") == "device" or (p.get("mapping") is None and m is not None and not m["writable"])

    def default_has(m, index):
        return bool(m and m["has_default"]) and any(_int(d["index"]) == index and d["subindex"] == 0
                                                     for d in m["defaults"])

    def room(p, bits):
        entries = p.get("entries") or []
        return len(entries) < layout.MAX_ENTRIES and \
            sum(CO_TYPES.get(e.get("type"), (0, 0))[1] for e in entries) + bits <= layout.MAX_BITS

    def find(key, direction, index, bits):
        pdos = node.setdefault(key, [])
        numbers = {_number(p, j): p for j, p in enumerate(pdos)}
        count = counts.get(direction, 0)
        # 1. a PDO whose default mapping has it: in the config with the
        # device mapping, or not in the config yet.
        for number in range(1, count + 1):
            m = pdo_map(direction, number)
            if not default_has(m, index):
                continue
            p = numbers.get(number)
            if p is not None and (keeps_device(p, m) or (any(p is q for q in made) and room(p, bits))):
                return p, None
            if p is None:
                p = {"number": number, "entries": []}
                pdos.append(p)
                made.append(p)
                return p, None
        # 2. a PDO written from the config with room.
        for number in sorted(numbers):
            p = numbers[number]
            m = pdo_map(direction, number)
            if m is not None and m["writable"] and not keeps_device(p, m) and room(p, bits):
                return p, None
        # 3. a free PDO the master can write.
        for number in range(1, count + 1):
            m = pdo_map(direction, number)
            if number not in numbers and m is not None and m["writable"]:
                p = {"number": number, "entries": []}
                pdos.append(p)
                made.append(p)
                return p, None
        kind = "TPDO" if direction == "input" else "RPDO"
        if count == 0:
            return None, "the EDS has no %s" % kind
        if not any((pdo_map(direction, k) or {}).get("writable") for k in range(1, count + 1)):
            return None, "no %s's fixed mapping has it" % kind
        return None, "no free %s (the others keep the device's mapping or are full)" % kind

    for index in axis.PIN_ORDER:
        _, key, co_type, _, name = axis.OBJECTS[index]
        if index in have:
            continue
        o = objects.get((index, 0))
        direction = "input" if key == "tx_pdos" else "output"
        if o is None:
            missing.append({"index": "0x%04X" % index, "name": name, "reason": "not in the EDS"})
            continue
        if direction not in (o.get("directions") or []) or o.get("type") != co_type:
            why = "the EDS does not let it be mapped in a%s" % (" TPDO" if direction == "input" else "n RPDO") \
                if direction not in (o.get("directions") or []) else "the EDS gives it type %s, not %s" % (
                    o.get("type"), co_type)
            missing.append({"index": "0x%04X" % index, "name": name, "reason": why})
            continue
        p, reason = find(key, direction, index, CO_TYPES[co_type][1])
        if p is None:
            missing.append({"index": "0x%04X" % index, "name": name, "reason": reason})
            continue
        area, size = layout.area_size(direction, co_type)
        loc = layout.suggest(area, size, used, start)
        used.add((area, size, _element(loc)))
        p.setdefault("entries", []).append({"index": "0x%04X" % index, "subindex": 0, "type": co_type,
                                            "iec_location": loc})
        number = _number(p, node[key].index(p))
        mapped.append({"index": "0x%04X" % index, "name": name,
                       "pdo": "%s%d" % ("TPDO" if direction == "input" else "RPDO", number), "location": loc})
    for key in ("tx_pdos", "rx_pdos"):
        if key in node and not node[key]:
            del node[key]
        elif key in node and all(_int(p.get("number")) for p in node[key]):
            node[key].sort(key=lambda p: _int(p["number"]))
    if not node.get("status_location"):
        loc = layout.suggest("I", "X", used, start)
        used.add(("I", "X", _element(loc)))
        node["status_location"] = loc
        mapped.append({"index": None, "name": "status bit", "pdo": None, "location": loc})
    return node, mapped, missing


def _element(loc):
    return parse_location(loc).element
