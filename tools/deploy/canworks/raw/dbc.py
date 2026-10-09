"""DBC files for raw messages (specs canopen-configurator "Import a DBC into
CAN messages" and canopen-dbc-export "Raw messages in the DBC"), with
cantools. Values stay raw in the config; scale, offset, unit and limits are
kept for tools and declarations."""

from .contract import hex_id, tx_dlc

PLC_NODE = "PLC"


def _cantools():
    import cantools  # noqa: PLC0415 - optional until a DBC is used
    return cantools


def _cycle(m, kind):
    """The DBC cycle time: a send message's period; for a receive message the
    sender's cycle that its timeout was made from (a third of it)."""
    if kind == "tx":
        return m.get("period_ms") or None
    return (m.get("timeout_ms") or 0) // 3 or None


def export_dbc(raw, network_name=None):
    """DBC text with every raw message of the `raw` object: receive messages
    with no sender, send messages sent by node PLC, and GenMsgCycleTime from
    the period (send) or a third of the timeout (receive)."""
    _cantools()
    from cantools.database.can import Database, Message, Node, Signal
    from cantools.database.conversion import BaseConversion

    messages = []
    for kind in ("rx", "tx"):
        for m in (raw or {}).get(kind) or []:
            signals = []
            for j, s in enumerate(m.get("signals") or []):
                big = s.get("byte_order") == "big"
                signals.append(Signal(
                    name=s.get("name") or "s%d" % j, start=s["start_bit"], length=s["length"],
                    byte_order="big_endian" if big else "little_endian", is_signed=bool(s.get("signed")),
                    conversion=BaseConversion.factory(scale=s.get("scale", 1), offset=s.get("offset", 0)),
                    minimum=s.get("minimum"), maximum=s.get("maximum"), unit=s.get("unit"),
                    comment=s.get("comment")))
            if kind == "rx":
                dlc = m.get("dlc", 8)
            else:
                dlc = tx_dlc(m)
            msg = Message(frame_id=m["id"], name=m.get("name") or "msg_%s" % hex_id(m["id"])[2:],
                          length=dlc, signals=signals, is_extended_frame=bool(m.get("extended")),
                          senders=[PLC_NODE] if kind == "tx" else [],
                          cycle_time=_cycle(m, kind), strict=False)
            messages.append(msg)
    db = Database(messages=messages, nodes=[Node(PLC_NODE)], strict=False)
    text = db.as_dbc_string()
    if network_name:
        text = "// raw messages of network %s\n%s" % (network_name, text)
    return text


def read_dbc(path_or_text):
    """The messages of a DBC file (a path, or the text itself) as
    [{name, id, extended, dlc, senders, cycle_ms, multiplexed, signals}]
    with signals in the config's form."""
    cantools = _cantools()
    if "\n" in path_or_text:
        db = cantools.database.load_string(path_or_text, database_format="dbc", strict=False)
    else:
        db = cantools.database.load_file(path_or_text, database_format="dbc", strict=False)
    out = []
    for msg in db.messages:
        signals, multiplexed = [], False
        for s in msg.signals:
            if s.multiplexer_ids is not None or s.is_multiplexer:
                multiplexed = True
                continue
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
            if s.minimum is not None:
                e["minimum"] = s.minimum
            if s.maximum is not None:
                e["maximum"] = s.maximum
            signals.append(e)
        out.append({"name": msg.name, "id": msg.frame_id, "extended": msg.is_extended_frame, "dlc": msg.length,
                     "senders": list(msg.senders or []), "cycle_ms": msg.cycle_time or 0,
                     "multiplexed": multiplexed, "signals": signals})
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
