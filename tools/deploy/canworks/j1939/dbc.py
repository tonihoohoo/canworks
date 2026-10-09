"""J1939 DBC files: import (j1939-pc-tools "DBC import", "Config from
imported messages") and export of a J1939 network ("J1939 DBC export").

The import reads the 29-bit identifier, GenMsgCycleTime and VFrameFormat of
each message and its signals' layout; everything it does not use (11-bit
messages, multiplexed messages, float signals, signals over 64 bits, other
attributes) is named in a problem list, not guessed.

    imported = load("machine.dbc")
    entry = config_entry(imported.messages[0], "rx", layout.taken(cfg, []))

The export writes the network's rx and tx messages with the writer of the
CANopen export (canworks/dbcexport.py), so both look alike:

    text = dbcexport.write(build(contract.networks(cfg)[i], "canworks.json"))
"""

import os

from .. import __version__, contract
from .. import dbcexport
from ..configurator import layout
from ..iec import element_str

# The node name of the PLC's own ECU in an exported DBC.
PLC = "PLC"
# Attributes the import reads; any other attribute is reported once.
USED_ATTRIBUTES = ("GenMsgCycleTime", "VFrameFormat", "ProtocolType")
VFRAME_J1939 = "J1939PG"
VFRAME_FORMATS = ("StandardCAN", "ExtendedCAN", "reserved", "J1939PG")
# The location size of a signal of up to 1, 8, 16, 32 and 64 bits.
SIZES = ((1, "X"), (8, "B"), (16, "W"), (32, "D"), (64, "L"))


class ImportFailed(Exception):
    """The file is not a DBC file cantools can read."""


class Imported:
    """`messages`: the J1939 messages, each a dict {"name", "frame_id" (29
    bits), "pgn", "priority", "source", "destination" (PDU1: the DBC ID's
    destination byte, else None), "length", "cycle_ms" (None when the DBC
    gives none), "sender" (or None), "comment", "signals": [{"name",
    "start_bit" (as in the DBC), "length", "byte_order" ("little"|"big"),
    "signed", "scale", "offset", "unit", "minimum", "maximum",
    "comment"}]}. `problems`: what was left out, one message per line,
    naming the message."""

    def __init__(self, messages, problems):
        self.messages, self.problems = messages, problems

    def find(self, pgn):
        return [m for m in self.messages if m["pgn"] == pgn]


def split_id(frame_id):
    """(priority, PGN, destination or None, source) of a 29-bit identifier.
    A PDU1 PGN (PF below 240) has its destination byte cleared."""
    priority = (frame_id >> 26) & 7
    pgn = (frame_id >> 8) & 0x3FFFF
    destination = None
    if contract.j1939_pdu1(pgn):
        destination = pgn & 0xFF
        pgn &= 0x3FF00
    return priority, pgn, destination, frame_id & 0xFF


def join_id(priority, pgn, source, destination=None):
    """The 29-bit identifier of a parameter group (PDU1: `destination` in
    the PGN's low byte, default global)."""
    if contract.j1939_pdu1(pgn):
        pgn = (pgn & 0x3FF00) | (contract.J1939_GLOBAL if destination is None else destination)
    return (priority & 7) << 26 | (pgn & 0x3FFFF) << 8 | (source & 0xFF)


def _attribute(obj, name):
    attrs = getattr(getattr(obj, "dbc", None), "attributes", None) or {}
    a = attrs.get(name)
    return a.value if a is not None else None


def _frame_format(db, msg):
    """The message's VFrameFormat as text, or None when the DBC has none."""
    value = _attribute(msg, "VFrameFormat")
    if value is None:
        d = (getattr(db.dbc, "attribute_definitions", None) or {}).get("VFrameFormat")
        value = d.default_value if d is not None else None
    if isinstance(value, int) and 0 <= value < len(VFRAME_FORMATS):
        d = (getattr(db.dbc, "attribute_definitions", None) or {}).get("VFrameFormat")
        choices = getattr(d, "choices", None) or VFRAME_FORMATS
        return choices[value] if value < len(choices) else str(value)
    return value if value is None else str(value)


def _num(v):
    """An int when the value is integral (scale 1, not 1.0)."""
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v


def load(path=None, text=None):
    """Imports a DBC file (or its `text`). Loads in cantools' strict mode
    first; a file that loads only without it is imported with a problem
    saying so. Raises ImportFailed when it does not load at all."""
    import cantools
    problems = []

    def read(strict):
        if text is not None:
            return cantools.database.load_string(text, "dbc", strict=strict)
        return cantools.database.load_file(path, database_format="dbc", strict=strict)

    try:
        db = read(True)
    except Exception as strict_error:  # cantools raises several types
        try:
            db = read(False)
        except Exception as e:
            raise ImportFailed("not a readable DBC file: %s" % e)
        problems.append("the DBC does not load in strict mode (%s); check the imported layouts" % strict_error)
    defs = getattr(db.dbc, "attribute_definitions", None) or {} if db.dbc else {}
    for name in defs:
        if name not in USED_ATTRIBUTES:
            problems.append("attribute %s is not used by the import" % name)
    messages = []
    for m in db.messages:
        what = "message %s (ID 0x%X)" % (m.name, m.frame_id)
        if not m.is_extended_frame:
            problems.append("%s has an 11-bit identifier; J1939 messages have 29-bit identifiers" % what)
            continue
        fmt = _frame_format(db, m)
        if fmt not in (None, VFRAME_J1939):
            problems.append("%s has VFrameFormat %s, not %s; imported as J1939 by its 29-bit identifier"
                            % (what, fmt, VFRAME_J1939))
        if m.is_multiplexed():
            problems.append("%s is multiplexed; multiplexed messages are not supported" % what)
            continue
        priority, pgn, destination, source = split_id(m.frame_id)
        signals = []
        for s in m.signals:
            if s.is_float:
                problems.append("%s: signal %s is a float signal; only integer signals are supported" % (what, s.name))
                continue
            if s.length > 64:
                problems.append("%s: signal %s has %d bits; at most 64 are supported" % (what, s.name, s.length))
                continue
            signals.append({"name": s.name, "start_bit": s.start, "length": s.length,
                            "byte_order": "big" if s.byte_order == "big_endian" else "little",
                            "signed": bool(s.is_signed), "scale": _num(s.scale), "offset": _num(s.offset),
                            "unit": s.unit or "", "minimum": s.minimum, "maximum": s.maximum,
                            "comment": s.comment or ""})
        cycle = m.cycle_time if m.cycle_time is not None else _attribute(m, "GenMsgCycleTime")
        messages.append({"name": m.name, "frame_id": m.frame_id, "pgn": pgn, "priority": priority,
                         "source": source, "destination": destination, "length": m.length,
                         "cycle_ms": cycle or None, "sender": m.senders[0] if m.senders else None,
                         "comment": m.comment or "", "signals": signals})
    return Imported(messages, problems)


def location_size(length):
    """The IEC size letter that holds a signal of `length` bits."""
    return next(size for bits, size in SIZES if length <= bits)


def free_locations(cfg, project_uses=()):
    """The locations already used: the config's (every network, J1939 too)
    and an editor project's (configurator/scan.py uses), for
    config_entry()."""
    return layout.taken(cfg, project_uses)


def config_entry(message, direction, used, start=layout.DEFAULT_START):
    """An rx or tx entry (`direction` "rx" or "tx") of an imported message,
    with the DBC's names and layout and a free location of the right size
    for each signal, %I for rx and %Q for tx, from `used` (a set of
    (area, size, element) as free_locations() gives; the new locations are
    added to it).

    rx: timeout_ms is three times the cycle time (none without one); the
    source is not set, so any sender's message is taken. tx: priority from
    the identifier, period_ms the cycle time (0: on change and request
    only), the destination of a PDU1 PGN, and length when the DBC's
    differs from the default (at least 8 bytes, enough for every signal)."""
    if direction not in ("rx", "tx"):
        raise ValueError('direction must be "rx" or "tx"')
    area = "I" if direction == "rx" else "Q"
    entry = {"pgn": message["pgn"], "name": message["name"]}
    if direction == "rx":
        if message.get("cycle_ms"):
            entry["timeout_ms"] = min(3 * message["cycle_ms"], contract.J1939_MAX_PERIOD_MS)
    else:
        entry["priority"] = message["priority"]
        if message.get("destination") is not None:
            entry["destination"] = message["destination"]
        entry["period_ms"] = min(message.get("cycle_ms") or 0, contract.J1939_MAX_PERIOD_MS)
        default = max(8, contract.j1939_bytes_needed([
            {"start_bit": s["start_bit"], "length": s["length"], "big_endian": s["byte_order"] == "big"}
            for s in message["signals"]]))
        if message.get("length") and message["length"] != default:
            entry["length"] = message["length"]
    signals = []
    for s in message["signals"]:
        size = location_size(s["length"])
        element = start * 8 if size == "X" else start
        while (area, size, element) in used:
            element += 1
        used.add((area, size, element))
        sig = {"name": s["name"], "start_bit": s["start_bit"], "length": s["length"]}
        if s["byte_order"] == "big":
            sig["byte_order"] = "big"
        if s["signed"]:
            sig["signed"] = True
        if s["scale"] != 1:
            sig["scale"] = s["scale"]
        if s["offset"] != 0:
            sig["offset"] = s["offset"]
        if s["unit"]:
            sig["unit"] = s["unit"]
        sig["iec_location"] = element_str(area, size, element)
        signals.append(sig)
    entry["signals"] = signals
    return entry


# -- export -------------------------------------------------------------------

def _ecu_node(address):
    return "ECU%d" % address


def build(net, config_path, names=None):
    """The DBC model (dbcexport.Model) of one J1939 network (a
    contract.networks() entry of a config that passed the checks).

    rx messages carry the source filter's address in their identifier, or
    254 (the null address) without one, and come from node ECU<address>
    (no sender without a filter); a PDU1 rx PGN is addressed to the ECU's
    configured address. Their cycle time is a third of timeout_ms (the
    import's rule backwards). tx messages carry the ECU's configured address
    and come from node PLC. `names`: plc_names() of an editor project, for
    the signal comments."""
    j = contract.parse_j1939(net["json"])
    ecu = j["ecu"] or {}
    own = ecu.get("address")
    own = contract.J1939_NULL_ADDRESS if own is None else own
    nodes = dbcexport._Names([PLC])
    node_list = [PLC]
    taken = dbcexport._Names()
    messages = []
    for key in ("rx", "tx"):
        for m in j[key]:
            rx = key == "rx"
            pgn = m["pgn"]
            if rx:
                source = m["source"] if m["source"] is not None else contract.J1939_NULL_ADDRESS
                frame_id = join_id(contract.J1939_DEFAULT_PRIORITY, pgn, source, own)
                sender = dbcexport.NO_RECEIVER
                if m["source"] is not None:
                    sender = _ecu_node(m["source"])
                    if sender.lower() not in nodes.taken:
                        node_list.append(nodes.add(sender, ""))
                length = max(8, contract.j1939_bytes_needed(m["signals"]))
                cycle = m["timeout_ms"] // 3 if m["timeout_ms"] else None
                text = "PGN %s received" % contract.j1939_pgn_text(pgn)
                if m["source"] is not None:
                    text += " from address %d" % m["source"]
                elif m["source_name"] is not None:
                    text += " from NAME 0x%016X" % m["source_name"]
                else:
                    text += " from any address"
                if m["timeout_ms"]:
                    text += ", timeout %d ms" % m["timeout_ms"]
            else:
                frame_id = join_id(m["priority"], pgn, own, m["destination"])
                sender, length, cycle = PLC, m["length"], m["period_ms"] or None
                text = "PGN %s sent by the PLC (address %d), priority %d, %s" % (
                    contract.j1939_pgn_text(pgn), own, m["priority"],
                    "every %d ms" % m["period_ms"] if m["period_ms"] else "on change and on request")
            name = taken.add(dbcexport.identifier(m["name"] or "") or "PGN%d" % pgn, "%s_%d" % (key, pgn))
            msg = dbcexport.Message(frame_id, name, length, sender, text, cycle, j1939=True)
            signal_names = dbcexport._Names()
            for s in m["signals"]:
                _, loc_text = dbcexport._location_label(str(s["location"]), names)
                msg.signals.append(dbcexport.Signal(
                    signal_names.add(dbcexport.identifier(s["name"]) or "signal", str(s["start_bit"])),
                    s["start_bit"], s["length"], s["signed"], receivers=[PLC] if rx else [],
                    comment=("-> " if rx else "<- ") + loc_text, scale=s["scale"], offset=s["offset"],
                    unit=s["unit"], big_endian=s["big_endian"]))
            messages.append(msg)
    comment = "J1939 network %s of %s, exported by canworks-deploy %s" % (
        net["name"], os.path.basename(config_path), __version__)
    return dbcexport.Model(node_list, messages, comment, [], protocol="J1939")


def export(net, config_path, names=None):
    """The DBC text of one J1939 network (see build())."""
    return dbcexport.write(build(net, config_path, names))
