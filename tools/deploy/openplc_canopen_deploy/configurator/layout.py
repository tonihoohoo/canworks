"""Address suggestion, PDO packing, and the checks of CANopen locations
against the rest of an editor project."""

from ..iec import CO_TYPES, parse_location, element_str, _FITS

DEFAULT_START = 100
MAX_ENTRIES = 8
MAX_BITS = 64
# The master's bus diagnostic inputs: (key, size letter, declared name, IEC type).
MASTER_LOCATIONS = (
    ("bus_state_location", "B", "can_bus_state", "USINT"),
    ("tx_error_count_location", "B", "can_tx_errors", "USINT"),
    ("rx_error_count_location", "B", "can_rx_errors", "USINT"),
    ("bus_off_count_location", "W", "can_bus_offs", "UINT"),
    ("state_location", "B", "can_master_state", "USINT"),
)
# A node's diagnostic inputs: (key, size letter, name suffix, IEC type).
NODE_LOCATIONS = (
    ("status_location", "X", "ok", "BOOL"),
    ("state_location", "B", "state", "USINT"),
    ("boot_error_location", "B", "boot_err", "USINT"),
    ("emcy_code_location", "W", "emcy", "WORD"),
    ("error_register_location", "B", "errreg", "BYTE"),
    ("nmt_command_location", "B", "nmt", "USINT"),
)
# An SDO variable's extra locations: (key, area, size letter, name suffix, IEC type).
SDO_VARIABLE_LOCATIONS = (
    ("trigger_location", "Q", "X", "trig", "BOOL"),
    ("status_location", "I", "B", "status", "USINT"),
    ("abort_code_location", "I", "D", "abort", "UDINT"),
)
MASTER_LOCATION_KEYS = tuple(m[0] for m in MASTER_LOCATIONS)


def area_size(direction, type_name):
    """("I"|"Q", size letter) for a PDO entry: inputs come from TPDOs."""
    return ("I" if direction == "input" else "Q"), _FITS[type_name]


def canopen_uses(cfg):
    """[(json path, Location)] for every iec_location, node diagnostic
    location, SDO variable location and master diagnostic location in a config
    (unparseable values are left to the contract check)."""
    out = []
    master = cfg.get("master") if isinstance(cfg, dict) else None
    if isinstance(master, dict):
        for key in MASTER_LOCATION_KEYS:
            loc = parse_location(master.get(key))
            if loc:
                out.append(("master.%s" % key, loc))
    for i, n in enumerate(cfg.get("nodes", []) if isinstance(cfg, dict) else []):
        if not isinstance(n, dict):
            continue
        for key, _, _, _ in NODE_LOCATIONS:
            loc = parse_location(n.get(key))
            if loc:
                out.append(("nodes[%d].%s" % (i, key), loc))
        for key in ("tx_pdos", "rx_pdos"):
            for j, p in enumerate(n.get(key) or []):
                for k, e in enumerate((p or {}).get("entries") or []):
                    loc = parse_location((e or {}).get("iec_location"))
                    if loc:
                        out.append(("nodes[%d].%s[%d].entries[%d].iec_location" % (i, key, j, k), loc))
        for j, v in enumerate(n.get("sdo_variables") or []):
            if not isinstance(v, dict):
                continue
            for key in ("iec_location",) + tuple(m[0] for m in SDO_VARIABLE_LOCATIONS):
                loc = parse_location(v.get(key))
                if loc:
                    out.append(("nodes[%d].sdo_variables[%d].%s" % (i, j, key), loc))
    return out


def taken(cfg, project_uses):
    keys = {(l.area, l.size, l.element) for _, l in canopen_uses(cfg)}
    keys.update(u.key() for u in project_uses)
    return keys


def suggest(area, size, used, start=DEFAULT_START):
    """The lowest free location of the table at or above byte/word `start`."""
    element = start * 8 if size == "X" else start
    while (area, size, element) in used:
        element += 1
    return element_str(area, size, element)


def pack(pdos, type_name, pdo_count):
    """Where a new entry of `type_name` goes in a node's PDO list of one
    direction: (index of the PDO, or len(pdos) for a new one; None and the
    reason when the node has no room)."""
    bits = CO_TYPES[type_name][1]
    if pdos:
        last = pdos[-1].get("entries") or []
        used = sum(CO_TYPES.get(e.get("type"), (0, 0))[1] for e in last)
        if len(last) < MAX_ENTRIES and used + bits <= MAX_BITS:
            return len(pdos) - 1, None
    if len(pdos) < pdo_count:
        return len(pdos), None
    if pdo_count == 0:
        return None, "the EDS defines no PDO in this direction"
    return None, "all %d PDOs of this direction are full (8 entries or 64 bits each)" % pdo_count


def project_checks(cfg, project_uses, allow_overlap=False):
    """Checks every CANopen location against the project's devices. Returns
    (items, declared): items as contract.Result.items, declared
    {json path: variable name} for locations a located variable declares."""
    by_key = {}
    for u in project_uses:
        by_key.setdefault(u.key(), []).append(u)
    items, declared = [], {}
    for path, loc in canopen_uses(cfg):
        for u in by_key.get((loc.area, loc.size, loc.element), []):
            if u.kind == "variable":
                declared.setdefault(path, u.name)
                continue
            msg = "%s is also used by %s" % (loc, u.describe())
            if allow_overlap:
                items.append({"level": "warning", "message": msg + " (overlap allowed)", "paths": [path], "overlap_allowed": True})
            else:
                items.append({"level": "error", "message": msg, "paths": [path], "overlap": True})
    return items, declared
