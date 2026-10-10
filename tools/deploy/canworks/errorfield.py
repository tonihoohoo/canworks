"""A node's device error history, the pre-defined error field 0x1003 of
CiA 301, read and cleared with the manual SDO operations of a client:
diag.Client (a runtime) or localbus.LocalBus (a CAN adapter on this PC).
canworks-diag errors and the configurator's online node page use it.

Sub-index 0 holds the number of entries (UNSIGNED8), sub-indices 1 to that
number (at most 254) the entries (UNSIGNED32), sub-index 1 the newest. An
entry's low 16 bits are the error code, its high 16 bits the
manufacturer-specific information. Clearing writes 0 to sub-index 0 with the
manual write, so the plugin's guards apply: allow_changes, and force on an
OPERATIONAL node."""

from .diag import DiagError, abort_text, emcy_class, parse_hex, sdo_failure

INDEX = 0x1003
MAX_ENTRIES = 254
NO_OBJECT = 0x06020000
NO_HISTORY = "no error history (0x1003)"


def decode(subindex, value):
    """One entry: {subindex, value, code, class, info}."""
    code = value & 0xFFFF
    return {"subindex": subindex, "value": value, "code": code, "class": emcy_class(code), "info": value >> 16}


def _failure(sub, res):
    out = {"subindex": sub, "reason": sdo_failure(res)}
    if res.get("abort_code") is not None:
        out["abort_code"] = res["abort_code"]
        out["abort_text"] = abort_text(res["abort_code"])
    return out


def read(client, node, timeout_ms=1000):
    """The node's error history: {node, history, count, entries, failed}.
    history is False when the device has no 0x1003 (abort 0x06020000 on
    sub-index 0); count is None when sub-index 0 could not be read; failed
    is {subindex, reason[, abort_code, abort_text]} for the read that ended
    the list, else None. Refusals of the channel raise DiagError."""
    out = {"node": node, "history": True, "count": None, "entries": [], "failed": None}
    res = client.sdo_read(node, INDEX, 0, timeout_ms)
    if not res.get("success"):
        if res.get("abort_code") == NO_OBJECT:
            out["history"] = False
        else:
            out["failed"] = _failure(0, res)
        return out
    data = parse_hex(res.get("data") or "") if res.get("data") else b""
    if not data:
        out["failed"] = {"subindex": 0, "reason": "the device answered with no data"}
        return out
    out["count"] = data[0]
    for sub in range(1, min(out["count"], MAX_ENTRIES) + 1):
        res = client.sdo_read(node, INDEX, sub, timeout_ms)
        if not res.get("success"):
            out["failed"] = _failure(sub, res)
            break
        data = parse_hex(res.get("data") or "") if res.get("data") else b""
        out["entries"].append(decode(sub, int.from_bytes(data[:4], "little")))
    return out


def clear(client, node, force=None, timeout_ms=1000):
    """Writes UNSIGNED8 0 to 0x1003 sub-index 0. force: the caller's (None:
    the client's own). A refusal ("changes not allowed", "force needed")
    raises DiagError as the plugin gives it; a write the device aborts
    raises DiagError("refused") with the abort."""
    res = client.sdo_write(node, INDEX, 0, b"\x00", timeout_ms, force=force)
    if not res.get("success"):
        raise DiagError("refused", "node %d 0x1003:0: %s" % (node, sdo_failure(res)))
    return res


def lines(res):
    """The history as canworks-diag prints it, newest first."""
    node = res.get("node")
    if not res.get("history"):
        return ["node %s has %s" % (node, NO_HISTORY)]
    failed = res.get("failed")
    if res.get("count") is None:
        return ["node %s error history (0x1003): %s" % (node, failed["reason"] if failed else "not read")]
    out = ["node %s error history (0x1003): count %d%s" % (node, res["count"], ", newest first" if res["entries"] else "")]
    for e in res["entries"]:
        out.append("  sub %-3d  0x%04X  %-22s  information 0x%04X" % (e["subindex"], e["code"], e["class"], e["info"]))
    if failed:
        out.append("  sub %d: %s; the list ends here" % (failed["subindex"], failed["reason"]))
    elif res["count"] > MAX_ENTRIES:
        out.append("  count %d is above %d: only sub-indices 1-%d were read" % (res["count"], MAX_ENTRIES, MAX_ENTRIES))
    return out
