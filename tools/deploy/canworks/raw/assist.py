"""The configurator's help on the CAN messages page (spec
canopen-configurator, "CAN messages page"): free PLC addresses for a
message, DBC messages to import, and the "Copy as ST call" text."""

import re

from ..iec import element_str
from .contract import hex_id, size_for_bits, tx_dlc

DEFAULT_START = 300

# Locations a message gets from "Suggest addresses": (key, area, size).
_RX_EXTRA = (("status_location", "I", "X"),)
_TX_EXTRA = ()


def _free(area, size, used, start):
    element = start * 8 if size == "X" else start
    while (area, size, element) in used:
        element += 1
    used.add((area, size, element))
    return element_str(area, size, element)


def suggest_locations(entry, kind, used, start=DEFAULT_START):
    """Fills every signal without an `iec_location` (and, for `rx`, the
    status bit) with the lowest free location at or above `start`. `used` is a
    set of (area, size, element) keys and grows with what was given out.
    Returns the paths (relative to the entry) that were filled."""
    area = "I" if kind == "rx" else "Q"
    filled = []
    for key, a, size in _RX_EXTRA if kind == "rx" else _TX_EXTRA:
        if key not in entry:
            entry[key] = _free(a, size, used, start)
            filled.append(key)
    for j, s in enumerate(entry.get("signals") or []):
        if not s.get("iec_location"):
            s["iec_location"] = _free(area, size_for_bits(s.get("length", 1)), used, start)
            filled.append("signals[%d].iec_location" % j)
    return filled


def import_messages(messages, picks):
    """`raw` entries for DBC messages (from dbc.read_dbc()): `picks` maps a
    message name to "receive" or "send". Returns ({"rx": [...], "tx": [...]},
    notes) where notes say what was left out (multiplexed signals)."""
    from .dbc import to_entry
    out = {"rx": [], "tx": []}
    notes = []
    for m in messages:
        direction = picks.get(m["name"])
        if direction not in ("receive", "send"):
            continue
        if m.get("multiplexed"):
            notes.append("%s: multiplexed signals were left out" % m["name"])
        out["rx" if direction == "receive" else "tx"].append(to_entry(m, direction))
    return out, notes


def _ident(text):
    t = re.sub(r"[^A-Za-z0-9_]", "_", text or "")
    t = re.sub(r"_+", "_", t).strip("_")
    if not t or t[0].isdigit():
        t = "m_" + t
    return t


def _st_hex(value):
    return "16#%X" % value


def st_call(entry, kind, network=0):
    """A declaration and call of CAN_RECEIVE (rx) or CAN_SEND (tx) for one
    message, with a CAN_GET_BITS / CAN_SET_BITS line per signal."""
    name = _ident(entry.get("name") or "msg_%s" % hex_id(entry.get("id", 0))[2:])
    data = name + "_data"
    sigs = entry.get("signals") or []
    lines = ["VAR"]
    block = ("rx_" if kind == "rx" else "tx_") + name
    lines.append("  %s : %s;" % (block, "CAN_RECEIVE" if kind == "rx" else "CAN_SEND"))
    lines.append("  %s : ARRAY[0..7] OF BYTE;" % data)
    if kind == "tx":
        lines.append("  %s_go : BOOL;" % name)
        if sigs:
            lines.append("  %s_packed : BOOL;" % name)
    for j, s in enumerate(sigs):
        lines.append("  %s_%s : LINT;" % (name, _ident(s.get("name") or "s%d" % j)))
    lines.append("END_VAR")
    lines.append("")
    net = "" if not network else "NETWORK := %d, " % network
    ext = "EXTENDED := TRUE, " if entry.get("extended") else ""

    def bits(s):
        return "START_BIT := %d, BIT_LENGTH := %d, MOTOROLA := %s" % (
            s.get("start_bit", 0), s.get("length", 1), "TRUE" if s.get("byte_order") == "big" else "FALSE")

    if kind == "rx":
        mask = entry.get("mask")
        mask_pin = "MASK := %s, " % _st_hex(mask) if mask is not None else ""
        call = "%s(ENABLE := TRUE, %sID := %s, %s%sRX_DATA := %s);" % (block, net, _st_hex(entry.get("id", 0)),
                                                                     mask_pin, ext, data)
        lines.append(call)
        lines.append("WHILE %s.NEW DO" % block)
        for j, s in enumerate(sigs):
            lines.append("  %s_%s := CAN_GET_BITS(DATA := %s, %s, SIGNED := %s);" % (
                name, _ident(s.get("name") or "s%d" % j), data, bits(s), "TRUE" if s.get("signed") else "FALSE"))
        lines.append("  " + call)
        lines.append("END_WHILE;")
    else:
        for j, s in enumerate(sigs):
            lines.append("%s_packed := CAN_SET_BITS(DATA := %s, %s, VALUE := %s_%s);" % (
                name, data, bits(s), name, _ident(s.get("name") or "s%d" % j)))
        rtr = "RTR := TRUE, " if entry.get("rtr") else ""
        lines.append("%s(EXECUTE := %s_go, %sID := %s, %s%sDLC := %d, DATA := %s);" % (
            block, name, net, _st_hex(entry.get("id", 0)), ext, rtr, tx_dlc(entry), data))
        lines.append("IF %s.DONE OR %s.ERROR THEN %s_go := FALSE; END_IF;" % (block, block, name))
    return "\n".join(lines) + "\n"
