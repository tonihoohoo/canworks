"""Copy as ST call for a J1939 network's rx and tx entries (spec
j1939-pc-tools, "Copy as ST call for J1939 PGNs"): Structured Text that
uses the canworks library's J1939 message blocks (docs/j1939.md) for the
entry's PGN, with a J1939_GET_BITS or J1939_SET_BITS line per signal."""

import re

from ..contract import j1939_bytes_needed

GLOBAL = 255


def _ident(text):
    t = re.sub(r"[^A-Za-z0-9_]", "_", text or "")
    t = re.sub(r"_+", "_", t).strip("_")
    if not t or t[0].isdigit():
        t = "m_" + t
    return t


def _int(value, default=None):
    if value in (None, ""):
        return default
    if isinstance(value, str):
        return int(value, 0)
    return int(value)


def _scaling(s):
    scale, offset, unit = s.get("scale"), s.get("offset"), s.get("unit")
    parts = []
    if scale not in (None, 1, 1.0):
        parts.append("x %s" % scale)
    if offset not in (None, 0, 0.0):
        parts.append("%+g" % float(offset))
    if unit:
        parts.append(str(unit))
    return " (* raw %s *)" % " ".join(parts) if parts else ""


def _big(s):
    return s.get("byte_order") == "big"


def _big_note(s, op):
    return "(* %s is big-endian; J1939_%s_BITS is little-endian only, so this call leaves it out. *)" % (
        s.get("name") or "a signal", op)


def st_call(entry, kind, network=0, net_name=None):
    """The declarations and calls for one rx (J1939_RECEIVE and
    J1939_REQUEST) or tx (J1939_SEND) entry of network number `network`."""
    pgn = _int(entry.get("pgn"), 0)
    name = _ident(entry.get("name") or "pgn%d" % pgn)
    prefix = _ident(net_name) + "_" + name if net_name else name
    data = prefix + "_data"
    sigs = [s for s in entry.get("signals") or [] if isinstance(s, dict)]
    # J1939_GET_BITS and J1939_SET_BITS work in little-endian (J1939) order:
    # a big-endian signal gets a note instead of a call that decodes it wrong.
    big = [s for s in sigs if _big(s)]
    sigs = [s for s in sigs if not _big(s)]
    net = "NETWORK := %d%s" % (network, " (* %s *)" % net_name if net_name else "")
    var = ["VAR"]
    body = []

    def sig_var(j, s):
        return "%s_%s" % (prefix, _ident(s.get("name") or "s%d" % j))

    def bits(s):
        return "START_BIT := %d, BIT_LENGTH := %d" % (_int(s.get("start_bit"), 0), _int(s.get("length"), 1))

    if kind == "rx":
        rx, rq = "rx_" + prefix, "rq_" + prefix
        source = _int(entry.get("source"))
        answer = prefix + "_answer"
        var += ["  %s : J1939_RECEIVE;" % rx, "  %s : J1939_REQUEST;" % rq,
                "  %s : ARRAY[0..1784] OF BYTE;" % data, "  %s : ARRAY[0..1784] OF BYTE;" % answer,
                "  %s_ask : BOOL;" % prefix]
        var += ["  %s : LINT;" % sig_var(j, s) for j, s in enumerate(sigs)]
        body.append("(* Every PGN %d message%s, oldest first; the config's %%I locations get it too. *)"
                    % (pgn, " from address %d" % source if source is not None else ""))
        if entry.get("source_name") not in (None, "") and source is None:
            body.append("(* The config takes it from the ECU with NAME %s: J1939_FIND_ECU gives its address for "
                        "SOURCE. *)" % entry.get("source_name"))
        src = "SOURCE := %d, FILTER_SOURCE := TRUE, " % source if source is not None else ""
        call = "%s(ENABLE := TRUE, %s, PGN := %d, %sRX_DATA := %s, LINK := canworks.link);" % (rx, net, pgn, src, data)
        body.append(call)
        body.append("WHILE %s.RECEIVED DO" % rx)
        for j, s in enumerate(sigs):
            body.append("  %s := J1939_GET_BITS(DATA := %s, %s, SIGNED := %s);%s" % (
                sig_var(j, s), data, bits(s), "TRUE" if s.get("signed") else "FALSE", _scaling(s)))
        body += ["  " + _big_note(s, "GET") for s in big]
        body.append("  " + call)
        body.append("END_WHILE;")
        body.append("")
        dest = source if source is not None else GLOBAL
        body.append("(* A rising edge of %s_ask requests PGN %d from %s; the answer also reaches %s. *)"
                    % (prefix, pgn, "address %d" % dest if dest != GLOBAL else "every ECU", rx))
        body.append("%s(EXECUTE := %s_ask, %s, PGN := %d, DESTINATION := %d, DATA := %s, LINK := canworks.link);"
                    % (rq, prefix, net, pgn, dest, answer))
        body.append("IF %s.DONE OR %s.ERROR THEN %s_ask := FALSE; END_IF;" % (rq, rq, prefix))
    else:
        tx = "tx_" + prefix
        length = _int(entry.get("length"))
        if length is None:
            try:
                need = j1939_bytes_needed([{"start_bit": _int(s.get("start_bit"), 0), "length": _int(s.get("length"), 1),
                                            "big_endian": _big(s)} for s in sigs + big])
            except (TypeError, ValueError):
                need = 0
            length = max(8, need)
        dest = _int(entry.get("destination"), GLOBAL) if (pgn >> 8) & 0xFF < 0xF0 else GLOBAL
        var += ["  %s : J1939_SEND;" % tx, "  %s : ARRAY[0..1784] OF BYTE;" % data, "  %s_go : BOOL;" % prefix]
        if sigs:
            var.append("  %s_packed : BOOL;" % prefix)
        var += ["  %s : LINT;" % sig_var(j, s) for j, s in enumerate(sigs)]
        body.append("(* The config sends PGN %d itself: remove this tx entry, or set raw.program_override_protocol, "
                    "before the program sends it (else error 4). *)" % pgn)
        for j, s in enumerate(sigs):
            body.append("%s_packed := J1939_SET_BITS(DATA := %s, %s, VALUE := %s);%s" % (
                prefix, data, bits(s), sig_var(j, s), _scaling(s)))
        body += [_big_note(s, "SET") for s in big]
        body.append("(* A rising edge of %s_go sends it. *)" % prefix)
        body.append("%s(EXECUTE := %s_go, %s, PGN := %d, DESTINATION := %d, PRIORITY := %d, LENGTH := %d, DATA := %s, "
                    "LINK := canworks.link);"
                    % (tx, prefix, net, pgn, dest, _int(entry.get("priority"), 6), length, data))
        body.append("IF %s.DONE OR %s.ERROR THEN %s_go := FALSE; END_IF;" % (tx, tx, prefix))
    var.append("END_VAR")
    return "\n".join(var + [""] + body) + "\n"
