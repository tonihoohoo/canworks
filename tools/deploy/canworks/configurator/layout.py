"""Address suggestion, PDO packing, and the checks of CANopen locations
against the rest of an editor project."""

from .. import contract, modbusmap
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
# A slave network's status and EMCY locations: (key, area, size letter, name suffix, IEC type).
SLAVE_LOCATIONS = (
    ("state_location", "I", "B", "state", "USINT"),
    ("comm_ok_location", "I", "X", "comm_ok", "BOOL"),
    ("sync_count_location", "I", "W", "sync_count", "UINT"),
    ("emcy_code_location", "Q", "W", "emcy", "WORD"),
    ("error_register_location", "Q", "B", "errreg", "BYTE"),
)
# The IEC type of a location size when the object's type does not say it.
SIZE_TYPES = {"X": "BOOL", "B": "USINT", "W": "UINT", "D": "UDINT", "L": "ULINT"}


def area_size(direction, type_name):
    """("I"|"Q", size letter) for a PDO entry: inputs come from TPDOs."""
    return ("I" if direction == "input" else "Q"), _FITS[type_name]


def canopen_uses(cfg):
    """[(json path, Location)] for every iec_location, node diagnostic
    location, SDO variable location and master diagnostic location in a config,
    every slave binding and slave status location, and every J1939
    network's locations, over every network of
    a version 2 file (paths "networks[i]. ..."; unparseable values are left
    to the contract check)."""
    out = []
    if not isinstance(cfg, dict):
        return out
    for net in contract.networks(cfg):
        at = net["path"] + "." if net["path"] else ""
        if net["role"] == "j1939":
            # The ECU state and address, rx status, signal and valid locations.
            out += [(path, parse_location(text)) for _, _, path, text in contract.location_uses(net)]
            continue
        out += _network_uses(net["master"], net["nodes"], at)
        out += _slave_uses(net["slave"], at)
    return out


def _slave_uses(slave, at):
    out = []
    for key, _, _, _, _ in SLAVE_LOCATIONS:
        loc = parse_location(slave.get(key))
        if loc:
            out.append(("%sslave.%s" % (at, key), loc))
    objects = slave.get("objects")
    for j, o in enumerate(objects if isinstance(objects, list) else []):
        loc = parse_location(o.get("iec_location") if isinstance(o, dict) else None)
        if loc:
            out.append(("%sslave.objects[%d].iec_location" % (at, j), loc))
    return out


def _network_uses(master, nodes, at):
    out = []
    if isinstance(master, dict):
        for key in MASTER_LOCATION_KEYS:
            loc = parse_location(master.get(key))
            if loc:
                out.append(("%smaster.%s" % (at, key), loc))
    for i, n in enumerate(nodes if isinstance(nodes, list) else []):
        if not isinstance(n, dict):
            continue
        for key, _, _, _ in NODE_LOCATIONS:
            loc = parse_location(n.get(key))
            if loc:
                out.append(("%snodes[%d].%s" % (at, i, key), loc))
        for j, p in enumerate(n.get("tx_pdos") or []):
            loc = parse_location((p or {}).get("timeout_location"))
            if loc:
                out.append(("%snodes[%d].tx_pdos[%d].timeout_location" % (at, i, j), loc))
        for key in ("tx_pdos", "rx_pdos"):
            for j, p in enumerate(n.get(key) or []):
                for k, e in enumerate((p or {}).get("entries") or []):
                    loc = parse_location((e or {}).get("iec_location"))
                    if loc:
                        out.append(("%snodes[%d].%s[%d].entries[%d].iec_location" % (at, i, key, j, k), loc))
                    bits = (e or {}).get("bits")
                    for m, b in enumerate(bits if isinstance(bits, list) else []):
                        loc = parse_location(b.get("iec_location") if isinstance(b, dict) else None)
                        if loc:
                            out.append(("%snodes[%d].%s[%d].entries[%d].bits[%d].iec_location"
                                        % (at, i, key, j, k, m), loc))
        for j, v in enumerate(n.get("sdo_variables") or []):
            if not isinstance(v, dict):
                continue
            for key in ("iec_location",) + tuple(m[0] for m in SDO_VARIABLE_LOCATIONS):
                loc = parse_location(v.get(key))
                if loc:
                    out.append(("%snodes[%d].sdo_variables[%d].%s" % (at, i, j, key), loc))
    return out


def mark(used, loc, nbytes=None):
    """Takes the bytes of `loc` in the bridge's byte image: ("I"/"Q", "B",
    byte) for each byte a value holds (`nbytes`, else its size's), or
    ("I"/"Q", "X", bit) and ("I"/"Q", "b", byte) for a bit, which shares its
    byte with other bits only."""
    if loc.size == "X":
        used.add((loc.area, "X", loc.element))
        used.add((loc.area, "b", loc.index))
    else:
        for b in range(loc.index, loc.index + (nbytes or modbusmap.SIZE_BYTES[loc.size])):
            used.add((loc.area, "B", b))


def taken(cfg, project_uses):
    """The places of the bridge's byte image the config holds (see mark),
    the bridge blocks and the OpenPLC link's reserved bytes included. The
    editor project's own located variables are the PLC's, not the bridge's:
    `project_uses` take nothing."""
    used = set()
    if modbusmap.is_bridge_config(cfg):
        for it in modbusmap.collect(cfg):
            mark(used, it.loc, it.nbytes)
        if modbusmap.is_openplc(cfg):
            for area, first in modbusmap.OPENPLC_FIRST_FREE.items():
                for b in range(first):
                    used.add((area, "B", b))
    else:
        for _, loc in canopen_uses(cfg):
            mark(used, loc)
    return used


def is_free(used, area, size, element, count=1):
    """Whether `count` consecutive values of `size` from table element
    `element` fit in the free bytes (bits: free bits of bytes no value holds)."""
    if size == "X":
        return not any((area, "X", element + k) in used or (area, "B", (element + k) // 8) in used
                       for k in range(count))
    return not any((area, "B", b) in used or (area, "b", b) in used
                   for b in range(element, element + count * modbusmap.SIZE_BYTES[size]))


def suggest(area, size, used, start=DEFAULT_START, count=1):
    """The lowest free location at or above byte `start` for `count`
    consecutive values of `size`; word and larger values start at an even
    byte (whole Modbus registers)."""
    if size == "X":
        element = start * 8
        while not is_free(used, area, "X", element, count):
            element += 1
        return element_str(area, "X", element)
    step = 2 if modbusmap.SIZE_BYTES[size] >= 2 else 1
    element = start + start % step
    while not is_free(used, area, size, element, count):
        element += step
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


# The runtime declares every variable in C++ under its upper-case name, after
# the C library headers: a name that is one of their macros does not compile
# (a node named x gives x_ok, which is X_OK from unistd.h).
C_MACROS = frozenset("""
    F_OK R_OK W_OK X_OK EOF NULL BUFSIZ FILENAME_MAX SEEK_SET SEEK_CUR SEEK_END
    EXIT_SUCCESS EXIT_FAILURE RAND_MAX CHAR_BIT INT_MAX INT_MIN UINT_MAX
    STDIN_FILENO STDOUT_FILENO STDERR_FILENO TRUE FALSE ERANGE EDOM EINVAL
""".split())


def macro_problems(project_uses):
    """The project's located variables the runtime cannot compile: a name
    of a C library macro. Items as contract.Result.items."""
    return [{"level": "error", "message": "%s: the runtime cannot compile a variable named %s (a C library macro of that name); rename it"
             % (u.describe(), u.name), "paths": []}
            for u in project_uses if u.kind == "variable" and u.name and u.name.upper() in C_MACROS]
