"""DBC files for raw messages (specs canopen-configurator "Import a DBC into
CAN messages" and canopen-dbc-export "Raw messages in the DBC"), with
cantools. Values stay raw in the config; scale, offset, unit and limits are
kept for tools and declarations."""

import math

PLC_NODE = "PLC"


def _cantools():
    import cantools  # noqa: PLC0415 - optional until a DBC is used
    return cantools


def export_dbc(raw, network_name=None):
    """DBC text with every raw message of the `raw` object: receive messages
    with no sender, send messages sent by node PLC, GenMsgCycleTime from the
    period (send) or a third of the timeout (receive), and the signals'
    multiplexing. Written by the DBC export's writer (dbcexport.write), as
    the configurator's export of a plain network."""
    from .. import dbcexport
    comment = "raw messages of network %s" % network_name if network_name else "raw messages"
    return dbcexport.write(dbcexport.Model([PLC_NODE], dbcexport.raw_messages(raw, PLC_NODE), comment, []))


# What the import says about a message whose multiplexing cantools cannot
# read: several switches (M) and no SG_MUL_VAL_ saying which is which.
MUX_PROBLEM = "several switches but no SG_MUL_VAL_; multiplexing left out"


def fold_ids(ids):
    """Switch values as the config writes them: [1, 2, 3, 5] -> [[1, 3], 5]."""
    runs = []
    for v in sorted(set(ids)):
        if runs and v == runs[-1][1] + 1:
            runs[-1][1] = v
        else:
            runs.append([v, v])
    return [lo if lo == hi else [lo, hi] for lo, hi in runs]


def mux_fields(msg):
    """({signal name: {"multiplexer": True, "mux": {...}}}, problem) of a
    cantools message: the config's multiplexing fields of its signals
    (`mux.on` only when the message has several switches), and True when
    it has several switches whose dependents cantools could not place (no
    SG_MUL_VAL_), which is then left out."""
    switches = [s for s in msg.signals if s.is_multiplexer]
    if not switches:
        return {}, False
    if len(switches) > 1 and all(s.multiplexer_ids is None for s in msg.signals):
        return {}, True
    out = {}
    for s in msg.signals:
        f = {}
        if s.is_multiplexer:
            f["multiplexer"] = True
        if s.multiplexer_ids and s.multiplexer_signal:
            m = {"on": s.multiplexer_signal} if len(switches) > 1 else {}
            m["values"] = fold_ids(s.multiplexer_ids)
            f["mux"] = m
        if f:
            out[s.name] = f
    return out, False


def _full_range(s):
    """True when a cantools signal's limits are its raw range in physical
    units, which the DBC export writes for a signal without limits."""
    if s.minimum is None or s.maximum is None:
        return False
    lo, hi = (-(1 << (s.length - 1)), (1 << (s.length - 1)) - 1) if s.is_signed else (0, (1 << s.length) - 1)
    lo, hi = sorted((lo * s.scale + s.offset, hi * s.scale + s.offset))
    return math.isclose(s.minimum, lo, rel_tol=1e-12, abs_tol=1e-9) and \
        math.isclose(s.maximum, hi, rel_tol=1e-12, abs_tol=1e-9)


def read_dbc(path_or_text):
    """The messages of a DBC file (a path, or the text itself) as
    [{name, id, extended, dlc, senders, cycle_ms, multiplexed, signals}]
    with signals in the config's form, multiplexing included (`multiplexed`:
    the message has a switch). A message whose multiplexing cannot be read
    (MUX_PROBLEM) also has "mux_problem" and its signals come without it."""
    cantools = _cantools()
    if "\n" in path_or_text:
        db = cantools.database.load_string(path_or_text, database_format="dbc", strict=False)
    else:
        db = cantools.database.load_file(path_or_text, database_format="dbc", strict=False)
    out = []
    for msg in db.messages:
        signals = []
        fields, problem = mux_fields(msg)
        for s in msg.signals:
            e = {"name": s.name, "start_bit": s.start, "length": s.length,
                 "byte_order": "big" if s.byte_order == "big_endian" else "little"}
            if s.is_signed:
                e["signed"] = True
            if s.scale != 1:
                e["scale"] = s.scale
            if s.offset != 0:
                e["offset"] = s.offset
            if s.unit:
                e["unit"] = s.unit
            if not _full_range(s):
                if s.minimum is not None:
                    e["minimum"] = s.minimum
                if s.maximum is not None:
                    e["maximum"] = s.maximum
            e.update(fields.get(s.name, {}))
            signals.append(e)
        m = {"name": msg.name, "id": msg.frame_id, "extended": msg.is_extended_frame, "dlc": msg.length,
             "senders": list(msg.senders or []), "cycle_ms": msg.cycle_time or 0,
             "multiplexed": bool(fields), "signals": signals}
        if problem:
            m["mux_problem"] = MUX_PROBLEM
        out.append(m)
    return out


def to_entry(message, direction):
    """A `raw.rx` ("receive") or `raw.tx` ("send") entry for a message from
    read_dbc(), without PLC locations: receive gets three cycle times as
    timeout_ms, send gets the cycle as period_ms (on change when the DBC has
    none)."""
    e = {"name": message["name"], "id": message["id"]}
    if message["extended"]:
        e["extended"] = True
    e["dlc"] = message["dlc"]
    if direction == "receive":
        if message["cycle_ms"]:
            e["timeout_ms"] = 3 * message["cycle_ms"]
    else:
        if message["cycle_ms"]:
            e["period_ms"] = message["cycle_ms"]
        else:
            e["on_change"] = True
    e["signals"] = [dict(s) for s in message["signals"]]
    return e
