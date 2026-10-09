"""What a network's protocol uses a CAN identifier for, in the plugin's words
(protocol_id_use in plugin/src/can/frame_tx.cpp): sent raw messages on such
an identifier need override_protocol (spec can-raw-messages)."""


def _uint(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != int(v) or v < 0:
        return None
    return int(v)


def _cob(v):
    if isinstance(v, str):
        try:
            return int(v, 0)
        except ValueError:
            return None
    return _uint(v)


def _node_label(n):
    s = "node %d" % n["node_id"]
    return s + " (%s)" % n["name"] if n.get("name") else s


def _canopen_use(net):
    """use(id, ext) for a CANopen network (networks() entry)."""
    from ..contract import auto_cob_ids

    js = net.get("json") or {}
    if net["role"] == "slave":
        slave = net.get("slave") or {}
        nid = _uint(slave.get("node_id"))
        master = js.get("master") if isinstance(js.get("master"), dict) else {}
        time_cob = _cob(master.get("time_cob_id", 0x100))
        time_cob = (time_cob if time_cob is not None else 0x100) & 0x1FFFFFFF

        def use_slave(ident, ext):
            if ext:
                return ""
            if ident in (0x000, 0x080):
                return "NMT" if ident == 0 else "SYNC"
            if ident in (0x7E4, 0x7E5):
                return "LSS"
            if ident == time_cob:
                return "TIME"
            if not nid:
                return ""
            who = " of the plugin's own slave (node %d)" % nid
            if ident == 0x80 + nid:
                return "EMCY" + who
            for k in range(4):
                if ident == 0x180 + 0x100 * k + nid:
                    return "TPDO%d%s" % (k + 1, who)
                if ident == 0x200 + 0x100 * k + nid:
                    return "RPDO%d%s" % (k + 1, who)
            if ident in (0x580 + nid, 0x600 + nid):
                return "the SDO channel" + who
            if ident == 0x700 + nid:
                return "the heartbeat" + who
            return ""

        return use_slave

    master = net.get("master") or {}
    mid = _uint(master.get("node_id", 1)) or 1
    time_cob = _cob(master.get("time_cob_id", 0x100))
    time_cob = (time_cob if time_cob is not None else 0x100) & 0x1FFFFFFF
    nodes = []
    for n in net.get("nodes") or []:
        if not isinstance(n, dict) or _uint(n.get("node_id")) is None:
            continue
        nodes.append({"node_id": _uint(n["node_id"]), "name": n.get("name") or "",
                      "tx_pdos": [p for p in n.get("tx_pdos") or [] if isinstance(p, dict) and _uint(p.get("number"))],
                      "rx_pdos": [p for p in n.get("rx_pdos") or [] if isinstance(p, dict) and _uint(p.get("number"))]})
    auto = auto_cob_ids(nodes)

    def pdo_cob(i, key, j, p, nid):
        if (i, key, j) in auto:
            return auto[(i, key, j)]
        cob = _cob(p.get("cob_id"))
        if cob:
            return cob
        return (0x80 if key == "tx_pdos" else 0x100) + 0x100 * int(p["number"]) + nid

    def use_master(ident, ext):
        if ext:
            return ""
        if ident == 0x000:
            return "NMT"
        if ident == 0x080:
            return "SYNC"
        if ident in (0x7E4, 0x7E5):
            return "LSS"
        if ident == time_cob:
            return "TIME"
        if ident == 0x700 + mid:
            return "the master's heartbeat"
        if ident == 0x80 + mid:
            return "the master's EMCY"
        for i, n in enumerate(nodes):
            nid = n["node_id"]
            who = " of " + _node_label(n)
            for key, kind in (("tx_pdos", "TPDO"), ("rx_pdos", "RPDO")):
                for j, p in enumerate(n[key]):
                    if pdo_cob(i, key, j, p, nid) == ident:
                        return "%s%d%s" % (kind, int(p["number"]), who)
            if ident == 0x80 + nid:
                return "EMCY" + who
            for k in range(4):
                if ident == 0x180 + 0x100 * k + nid:
                    return "TPDO%d%s (predefined)" % (k + 1, who)
                if ident == 0x200 + 0x100 * k + nid:
                    return "RPDO%d%s (predefined)" % (k + 1, who)
            if ident == 0x580 + nid:
                return "the SDO response channel" + who
            if ident == 0x600 + nid:
                return "the SDO request channel" + who
            if ident == 0x700 + nid:
                return "the heartbeat" + who
        return ""

    return use_master


def protocol_use(net):
    """use(id, extended) -> "" or what the protocol of `net` (a
    contract.networks() entry) uses the identifier for."""
    if net.get("protocol") == "none":
        return lambda ident, ext: ""
    if net.get("protocol") == "j1939":
        ecu = (net.get("j1939") or {}).get("ecu") or {}
        addr = _uint(ecu.get("address"))
        rng = ecu.get("address_range")
        lo = hi = None
        if isinstance(rng, list) and len(rng) == 2:
            lo, hi = _uint(rng[0]), _uint(rng[1])

        def use_j1939(ident, ext):
            if not ext:
                return ""
            sa = ident & 0xFF
            if sa == addr or (lo is not None and hi is not None and lo <= sa <= hi):
                return "a J1939 frame from the ECU's address %d" % sa
            return ""

        return use_j1939
    return _canopen_use(net)
