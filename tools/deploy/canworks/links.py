"""PDO links (canopen-pdo-links) and the node-to-node heartbeat watch: the
rules the plugin applies at load, with its messages (plugin/src/can/config.cpp
parse_links, check_links, check_heartbeat_watch; plugin/src/canopen/
eds_check.cpp check_links, check_heartbeat_watch), and the writes it adds to
a consumer's configuration download (dcf_gen.cpp add_link_writes).

A link here is the normalized form of one `links` entry:
{"i": place, "label", "producer", "tpdo", "keep", "consumers": [{"j", "node",
"rpdo", "transmission", "event_timer_ms", "mapping", "entries": [{"index",
"subindex", "type"}]}]}; numbers are ints, absent fields None.
"""

from . import eds as eds_mod
from .eds import sync_needed_message, transmission_needs_sync
from .iec import CO_TYPES, CO_TYPE_BY_CODE


def _uint(value):
    from .contract import _uint as u
    return u(value)


def node_label(node_id, name=""):
    return "node %d" % node_id + (" (%s)" % name if name else "")


def link_label(link_json, i):
    """"link <name>", or "link <n>" (1-based) without a name."""
    name = link_json.get("name") if isinstance(link_json, dict) else None
    return "link %s" % name if isinstance(name, str) and name else "link %d" % (i + 1)


def raw_links(net_json):
    """The network's `links` list as written (empty when absent or not a list)."""
    links = net_json.get("links") if isinstance(net_json, dict) else None
    return links if isinstance(links, list) else []


def parse(net_json):
    """The network's links in normalized form (schema-valid input)."""
    out = []
    for i, lj in enumerate(raw_links(net_json)):
        if not isinstance(lj, dict) or not isinstance(lj.get("from"), dict):
            continue
        f = lj["from"]
        link = {"i": i, "label": link_label(lj, i), "producer": _uint(f.get("node")), "tpdo": _uint(f.get("tpdo")),
                "keep": lj.get("on_plc_stop") == "keep", "consumers": [], "name": lj.get("name")}
        for j, c in enumerate(lj.get("to") if isinstance(lj.get("to"), list) else []):
            if not isinstance(c, dict):
                continue
            link["consumers"].append({
                "j": j, "node": _uint(c.get("node")), "rpdo": _uint(c.get("rpdo")),
                "transmission": _uint(c["transmission"]) if "transmission" in c else None,
                "event_timer_ms": _uint(c["event_timer_ms"]) if "event_timer_ms" in c else None,
                "mapping": c.get("mapping"),
                "entries": [{"index": _uint(e.get("index")), "subindex": _uint(e.get("subindex", 0)) or 0,
                             "type": e.get("type")} for e in c.get("entries", []) if isinstance(e, dict)]})
        out.append(link)
    return out


def linked_tpdos(net_json):
    """{(producer node ID, TPDO number)} of the network's links."""
    return {(l["producer"], l["tpdo"]) for l in parse(net_json)}


def linked_rpdos(net_json):
    """{node ID: {RPDO numbers}} the network's links configure."""
    out = {}
    for l in parse(net_json):
        for c in l["consumers"]:
            if c["node"] != l["producer"]:
                out.setdefault(c["node"], set()).add(c["rpdo"])
    return out


def link_of_tpdo(links, node_id, tpdo):
    for l in links:
        if l["producer"] == node_id and l["tpdo"] == tpdo:
            return l
    return None


# -- the rules at load, without the EDS files --------------------------------

def check_rules(links, nodes, produces_sync, err):
    """config.cpp check_links. `nodes`: the contract's normalized nodes (node_id,
    name, tx_pdos and rx_pdos with number). err(where, msg, paths)."""
    by_id = {n["node_id"]: n for n in nodes}
    tpdo_owner, rpdo_owner = {}, {}
    for l in links:
        me = l["label"]
        lw = "links[%d]" % l["i"]
        p = by_id.get(l["producer"])
        if p is None:
            err(lw, "%s: node %d is not a configured node of this network" % (me, l["producer"]), [lw + ".from.node"])
        else:
            plabel = node_label(p["node_id"], p["name"])
            if not any(t["number"] == l["tpdo"] for t in p["tx_pdos"]):
                err(lw, "%s: %s has no TPDO %d in its tx_pdos (a link's 'from' names one of the producer's tx_pdos)"
                    % (me, plabel, l["tpdo"]), [lw + ".from.tpdo"])
            key = (l["producer"], l["tpdo"])
            if key in tpdo_owner:
                other = tpdo_owner[key]
                err(lw, "%s and %s both name %s TPDO %d in 'from'; list all consumers in one link"
                    % (other["label"], me, plabel, l["tpdo"]), [lw + ".from", "links[%d].from" % other["i"]])
            else:
                tpdo_owner[key] = l
        for c in l["consumers"]:
            cw = "%s: to[%d]" % (lw, c["j"])
            cp = "%s.to[%d]" % (lw, c["j"])
            n = by_id.get(c["node"])
            if n is None:
                err(cw, "%s: consumer node %d is not a configured node of this network" % (me, c["node"]),
                    [cp + ".node"])
                continue
            nlabel = node_label(n["node_id"], n["name"])
            if c["node"] == l["producer"]:
                err(cw, "%s: %s is the producer; a consumer must be another node" % (me, nlabel), [cp + ".node"])
                continue
            who = "%s RPDO %d" % (nlabel, c["rpdo"])
            if any(r["number"] == c["rpdo"] for r in n["rx_pdos"]):
                err(cw, "%s: %s is also in its rx_pdos; a link's consumer RPDO is fed by the producer, not the master "
                        "(use another RPDO number)" % (me, who), [cp + ".rpdo"])
            key = (c["node"], c["rpdo"])
            if key in rpdo_owner:
                err(cw, "%s: %s is already a consumer of %s" % (me, who, rpdo_owner[key]["label"]), [cp + ".rpdo"])
            else:
                rpdo_owner[key] = l
            t = c["transmission"]
            if t is not None and transmission_needs_sync(t) and not produces_sync:
                err(cw, "%s: %s: %s" % (me, who, sync_needed_message(t, False)),
                    [cp + ".transmission", "master.sync_period_us"])


def check_watch_rules(nodes_json, nodes, master_id, err):
    """config.cpp check_heartbeat_watch: the watched node on the network, not
    the node itself nor the master, sending a heartbeat, a timeout above its
    period."""
    by_id = {n["node_id"]: (k, n) for k, n in enumerate(nodes)}
    for i, (nj, node) in enumerate(zip(nodes_json, nodes)):
        w = "nodes[%d]" % i
        label = node_label(node["node_id"], node["name"])
        seen = set()
        for k, h in enumerate(nj.get("heartbeat_watch", []) or []):
            at = "%s.heartbeat_watch[%d]" % (w, k)
            head = "%s: heartbeat_watch[%d]: " % (label, k)
            wid = _uint(h.get("node"))
            if wid == node["node_id"]:
                err(w, head + "a node cannot watch its own heartbeat", [at + ".node"])
                continue
            if wid == master_id:
                err(w, head + "node %d is the master; use 'heartbeat_consumer' to watch the master's heartbeat" % wid,
                    [at + ".node"])
                continue
            if wid not in by_id:
                err(w, head + "node %d is not a configured node of this network" % wid, [at + ".node"])
                continue
            tk, t = by_id[wid]
            tj = nodes_json[tk]
            tlabel = node_label(t["node_id"], t["name"])
            if wid in seen:
                err(w, head + "%s is watched twice" % tlabel, [at + ".node"])
                continue
            seen.add(wid)
            if _uint(tj.get("guard_time_ms", 0)):
                err(w, head + "%s sends no heartbeat (it uses node guarding); a heartbeat watch needs the watched "
                              "node's heartbeat" % tlabel, [at + ".node"])
                continue
            hb = _uint(tj.get("heartbeat_ms", 0)) or 0
            if "heartbeat_ms" in tj and not hb:
                err(w, head + "%s sends no heartbeat (\"heartbeat_ms\": 0); a heartbeat watch needs the watched node's "
                              "heartbeat" % tlabel, [at + ".node"])
                continue
            if "timeout_ms" in h and hb and _uint(h["timeout_ms"]) <= hb:
                err(w, head + "timeout_ms %d must be above %s's heartbeat period of %d ms"
                    % (_uint(h["timeout_ms"]), tlabel, hb), [at + ".timeout_ms"])


# -- with the EDS files --------------------------------------------------------

def _unused(v):
    nid = (v >> 16) & 0xFF
    return (v & 0xFFFF) == 0 or nid == 0 or nid > 127


def resolve_watch(nodes_json, nodes, eds_by_id, master, add):
    """eds_check.cpp check_heartbeat_watch: default timeouts, the watched
    node's EDS heartbeat, the 0x1016 capacity and each entry's sub-index.
    Sets node["heartbeat_watch"] = [{"node", "timeout_ms", "subindex"}] on
    `nodes`. add(level, msg, paths)."""
    by_id = {n["node_id"]: (k, n) for k, n in enumerate(nodes)}
    master_id = _uint(master.get("node_id"))
    master_hb = _uint(master.get("heartbeat_ms", 0)) or 0
    for i, (nj, node) in enumerate(zip(nodes_json, nodes)):
        watches = nj.get("heartbeat_watch") or []
        if not watches:
            continue
        w = "nodes[%d]" % i
        eds = eds_by_id.get(node["node_id"])
        if eds is None:
            continue
        label = node_label(node["node_id"], node["name"])
        out = []
        usable = True
        for k, h in enumerate(watches):
            wid = _uint(h.get("node"))
            entry = {"position": k, "node": wid, "timeout_ms": _uint(h["timeout_ms"]) if "timeout_ms" in h else None,
                     "subindex": 0}
            out.append(entry)
            if wid not in by_id or wid == node["node_id"]:
                continue
            tk, t = by_id[wid]
            tj = nodes_json[tk]
            if _uint(tj.get("guard_time_ms", 0)):
                continue
            head = "%s: heartbeat_watch[%d]: " % (label, k)
            tlabel = node_label(t["node_id"], t["name"])
            if "heartbeat_ms" in tj:
                period = _uint(tj["heartbeat_ms"]) or 0
            else:
                teds = eds_by_id.get(wid)
                if teds is None:
                    continue
                sub = teds.find(0x1017, 0)
                period = sub.value(wid) if sub is not None else None
                if not period:
                    add("error", head + "%s sends no heartbeat (its EDS heartbeat 0x1017 defaults to 0 and it sets no "
                                        "heartbeat_ms); a heartbeat watch needs the watched node's heartbeat" % tlabel,
                        [w + ".heartbeat_watch[%d].node" % k])
                    usable = False
                    continue
            if not period:
                continue
            if entry["timeout_ms"] is None:
                if "heartbeat_ms" in tj:
                    entry["timeout_ms"] = (_uint(tj["heartbeat_timeout_ms"]) if "heartbeat_timeout_ms" in tj
                                           else min(period * 3, 0xFFFF))
                else:
                    entry["timeout_ms"] = min(3 * period, 0xFFFF)
            elif "heartbeat_ms" not in tj and entry["timeout_ms"] <= period:
                add("error", head + "timeout_ms %d must be above %s's heartbeat period of %d ms"
                    % (entry["timeout_ms"], tlabel, period), [w + ".heartbeat_watch[%d].timeout_ms" % k])
                usable = False
        node["heartbeat_watch"] = out
        if not usable:
            continue
        if not eds.has(0x1016):
            add("error", "%s: heartbeat_watch needs object 0x1016 (consumer heartbeat time), which %s does not define"
                % (label, node["eds"]), [w + ".heartbeat_watch"])
            continue
        entries = []
        for k in sorted(eds.objects[0x1016]):
            sub = eds.objects[0x1016][k]
            if k < 1 or not sub.writable or sub.data_type not in (0x0005, 0x0006, 0x0007):
                continue
            v = sub.value(node["node_id"])
            if v is not None:
                entries.append((k, v))
        master_entry = nj.get("heartbeat_consumer") is True and bool(master_hb)
        master_sub = 0
        if master_entry:
            master_sub = next((k for k, v in entries if (v >> 16) & 0xFF == master_id), 0) or \
                next((k for k, v in entries if _unused(v)), 0)
        need = len(watches) + (1 if master_entry else 0)
        if need > len(entries):
            why = ("1 for the master's heartbeat, %d for heartbeat_watch" % len(watches) if master_entry
                   else "%d for heartbeat_watch" % len(watches))
            add("error", "%s: heartbeat_watch: 0x1016 in %s has room for %d %s where %d %s needed (%s)"
                % (label, node["eds"], len(entries), "entry" if len(entries) == 1 else "entries", need,
                   "is" if need == 1 else "are", why), [w + ".heartbeat_watch"])
            continue
        taken = {master_sub} if master_sub else set()
        for entry in out:
            sub = next((k for k, v in entries if k not in taken and (v >> 16) & 0xFF == entry["node"]), 0) or \
                next((k for k, v in entries if k not in taken and _unused(v)), 0)
            if not sub:
                add("error", "%s: heartbeat_watch[%d]: no unused 0x1016 entry is left for node %d in %s"
                    % (label, entry["position"], entry["node"], node["eds"]),
                    [w + ".heartbeat_watch[%d]" % entry["position"]])
                continue
            entry["subindex"] = sub
            taken.add(sub)


def _layout_list(layout):
    return ", ".join("0x%04X:%d (%d bit)" % (p["index"], p["subindex"], p["bits"]) for p in layout)


def _eds_type(eds, index, sub):
    if 1 <= index <= 7:
        return None
    s = eds.find(index, sub)
    return s.data_type if s is not None else None


def default_layout(eds, info):
    return [{"index": v >> 16, "subindex": (v >> 8) & 0xFF, "bits": v & 0xFF,
             "type": _eds_type(eds, v >> 16, (v >> 8) & 0xFF)} for v in info["defaults"]]


def producer_layout(pdo, eds):
    """The producer TPDO's layout: its entries, or the EDS default mapping of
    a device-mapped TPDO; None when that has no default."""
    info = eds_mod.mapping_info(eds, 0x1A00 + pdo["number"] - 1)
    if eds_mod.uses_device_mapping(pdo, info):
        return default_layout(eds, info) if info["has_default"] else None
    return [{"index": e["index"], "subindex": e["subindex"], "bits": CO_TYPES[e["type"]][1],
             "type": CO_TYPES[e["type"]][0]} for e in pdo["entries"]]


def consumer_layout(c, eds):
    """(layout, device mapping?) of a consumer as the master sets it up."""
    info = eds_mod.mapping_info(eds, 0x1600 + c["rpdo"] - 1)
    device = c["mapping"] == "device" or (c["mapping"] is None and not info["writable"])
    if device:
        return (default_layout(eds, info) if info["has_default"] else []), True
    return [{"index": e["index"], "subindex": e["subindex"], "bits": CO_TYPES[e["type"]][1],
             "type": None if 1 <= e["index"] <= 7 else CO_TYPES[e["type"]][0]} for e in c["entries"]], False


def _effective_transmission(eds, node_id, comm, value):
    if value is not None:
        return value
    sub = eds.find(comm, 2)
    return sub.value(node_id) if sub is not None else None


def check_eds(links, nodes, eds_by_id, sync, add, warnings):
    """eds_check.cpp check_links: each link (with its resolved "cob_id")
    against both EDS files; sets each consumer's "device_mapping". `sync`:
    the master produces SYNC. add(level, msg, paths) for errors,
    warnings.append((msg, path)). `nodes` need node_id, name, eds,
    heartbeat_consumer and tx_pdos."""
    by_id = {n["node_id"]: n for n in nodes}
    for l in links:
        me = l["label"] + ": "
        lp = "links[%d]" % l["i"]
        p = by_id.get(l["producer"])
        tp = next((t for t in p["tx_pdos"] if t["number"] == l["tpdo"]), None) if p else None
        peds = eds_by_id.get(l["producer"])
        if tp is None or peds is None:
            continue
        prod_who = "%s TPDO %d" % (node_label(p["node_id"], p["name"]), tp["number"])
        prod = producer_layout(tp, peds)
        if prod is None:
            continue
        prod_bits = sum(x["bits"] for x in prod)
        ptt = _effective_transmission(peds, p["node_id"], 0x1800 + tp["number"] - 1, tp.get("transmission"))
        kept_sync = []
        if ptt is not None and transmission_needs_sync(ptt):
            kept_sync.append("%s is synchronous (transmission type %d)" % (prod_who, ptt))
        for c in l["consumers"]:
            n = by_id.get(c["node"])
            eds = eds_by_id.get(c["node"])
            if n is None or eds is None or c["node"] == l["producer"]:
                continue
            cp = "%s.to[%d]" % (lp, c["j"])
            who = "%s RPDO %d" % (node_label(n["node_id"], n["name"]), c["rpdo"])
            comm, mapi = 0x1400 + c["rpdo"] - 1, 0x1600 + c["rpdo"] - 1
            if not eds.has(comm) or not eds.has(mapi):
                add("error", "%s%s does not exist in %s (no object 0x%04X/0x%04X)" % (me, who, n["eds"], comm, mapi),
                    [cp + ".rpdo"])
                continue
            cob = eds.find(comm, 1)
            have = cob.value(n["node_id"]) if cob is not None and not cob.writable else None
            if have is not None and cob.data_type in (0x0005, 0x0006, 0x0007):
                if have & 0x80000000:
                    add("error", "%s%s: %s fixes its COB-ID with the PDO switched off (0x%04X subindex 1 is %s); it "
                                 "cannot receive the link" % (me, who, n["eds"], comm, cob.access), [cp + ".rpdo"])
                elif (have & 0x7FF) != l["cob_id"]:
                    add("error", "%s%s can only receive 0x%03X (%s makes 0x%04X subindex 1 %s); the producer %s needs "
                                 "\"cob_id\": \"0x%03X\"" % (me, who, have & 0x7FF, n["eds"], comm, cob.access,
                                                             prod_who, have & 0x7FF), [cp + ".rpdo", lp + ".from"])
            label = node_label(n["node_id"], n["name"])
            eds_mod._check_comm(label, "RPDO", eds, n["eds"], n["node_id"], comm,
                                {"number": c["rpdo"], "transmission": c["transmission"],
                                 "event_timer_ms": c["event_timer_ms"]},
                                lambda m, f, cp=cp: add("error", me + m, [cp + "." + f]))
            tt = _effective_transmission(eds, n["node_id"], comm, c["transmission"])
            cons_sync = tt is not None and transmission_needs_sync(tt)
            if cons_sync and c["transmission"] is None and not sync:
                add("error", "%s%s: %s" % (me, who, sync_needed_message(tt, True)), [cp + ".transmission"])
            if cons_sync:
                kept_sync.append("%s is synchronous (transmission type %d)" % (who, tt))
            info = eds_mod.mapping_info(eds, mapi)
            if c["mapping"] == "config" and not info["writable"]:
                add("error", "%s%s: 'mapping' is \"config\", but %s fixes the mapping (0x%04X subindex %d is %s); leave "
                             "'mapping' out or set it to \"device\"" % (me, who, n["eds"], mapi, info["fixed_sub"],
                                                                        info["fixed_access"]), [cp + ".mapping"])
                continue
            cons, device = consumer_layout(c, eds)
            c["device_mapping"] = device
            if device:
                if not info["has_default"]:
                    add("error", "%s%s uses the device mapping, but %s gives no default mapping (0x%04X subindex %d has "
                                 "no DefaultValue, or 0)" % (me, who, n["eds"], mapi, info["missing_sub"]), [cp])
                    continue
                same = len(c["entries"]) == len(cons) and all(
                    e["index"] == x["index"] and e["subindex"] == x["subindex"] for e, x in zip(c["entries"], cons))
                if c["entries"] and not same:
                    add("error", "%s%s uses the device mapping from %s (%s); its 'entries' must list those objects in "
                                 "that order, or be left out" % (me, who, n["eds"], _layout_list(cons)),
                        [cp + ".entries"])
                    continue
            else:
                for k, e in enumerate(c["entries"]):
                    at = "%s.entries[%d]" % (cp, k)
                    if 1 <= e["index"] <= 7:
                        head = "%s%s entries[%d]: dummy entry 0x%04X" % (me, who, k, e["index"])
                        if e["subindex"] != 0:
                            add("error", head + " takes subindex 0", [at + ".subindex"])
                        elif CO_TYPES[e["type"]][0] != e["index"]:
                            add("error", head + " is %s, not %s" % (CO_TYPE_BY_CODE[e["index"]], e["type"]),
                                [at + ".type"])
                        elif e["index"] not in eds.dummy:
                            add("error", head + " needs Dummy%04X=1 in [DummyUsage] of %s" % (e["index"], n["eds"]),
                                [at])
                        continue
                    where = me + "node %d, index 0x%04X, subindex %d" % (n["node_id"], e["index"], e["subindex"])
                    sub = eds.find(e["index"], e["subindex"])
                    if sub is None:
                        add("error", "%s: object is not defined in %s" % (where, n["eds"]), [at])
                    elif not sub.pdo_mapping:
                        add("error", "%s: object is not PDO-mappable in %s" % (where, n["eds"]), [at])
                    else:
                        if not eds_mod.ACCESS[sub.access][1]:
                            add("error", "%s: a link consumer entry needs an object the node can receive (AccessType "
                                         "wo, rw or rww), but its AccessType is %s" % (where, sub.access), [at])
                        if sub.data_type != CO_TYPES[e["type"]][0]:
                            add("error", "%s: configured type %s does not match the EDS data type %s"
                                % (where, e["type"], eds_mod.data_type_name(sub.data_type)), [at + ".type"])
            cons_bits = sum(x["bits"] for x in cons)
            match = len(cons) == len(prod) and all(a["bits"] == b["bits"] for a, b in zip(cons, prod))
            if not match and device:
                add("error", "%s%s uses the default mapping from %s (%s), which does not match %s (%s)"
                    % (me, who, n["eds"], _layout_list(cons), prod_who, _layout_list(prod)), [cp])
                continue
            if not match and (len(cons) != len(prod) or cons_bits != prod_bits):
                add("error", "%s%s maps %d bits in %d %s, but %s sends %d bits in %d %s; the consumer must map the same "
                             "positions with the same sizes (use dummy entries for values it does not need)"
                    % (me, who, cons_bits, len(cons), "position" if len(cons) == 1 else "positions", prod_who,
                       prod_bits, len(prod), "position" if len(prod) == 1 else "positions"), [cp + ".entries"])
                continue
            if not match:
                for k, (a, b) in enumerate(zip(cons, prod)):
                    if a["bits"] != b["bits"]:
                        add("error", "%s%s position %d: %s does not match %s of %s"
                            % (me, who, k + 1, _layout_list([a]), _layout_list([b]), prod_who),
                            [cp + ".entries[%d]" % k])
                continue
            for k, (a, b) in enumerate(zip(cons, prod)):
                if a["type"] is not None and b["type"] is not None and a["type"] != b["type"]:
                    warnings.append(("%sposition %d: %s sends 0x%04X:%d as %s and %s receives it in 0x%04X:%d as %s; "
                                     "the bits are copied unchanged"
                                     % (me, k + 1, prod_who, b["index"], b["subindex"],
                                        eds_mod.data_type_name(b["type"]), who, a["index"], a["subindex"],
                                        eds_mod.data_type_name(a["type"])), cp + ".entries[%d]" % k))
        if not l["keep"]:
            continue
        for s in kept_sync:
            warnings.append(("%s\"on_plc_stop\": \"keep\", but %s: the link stops when the PLC stops because SYNC stops"
                             % (me, s), lp + ".on_plc_stop"))
        for nid in [l["producer"]] + [c["node"] for c in l["consumers"]]:
            n = by_id.get(nid)
            if n is not None and n.get("heartbeat_consumer") is True:
                warnings.append(("%s\"on_plc_stop\": \"keep\", but %s watches the master's heartbeat "
                                 "(heartbeat_consumer), which stops when the PLC stops; the node reacts as its 0x1029 "
                                 "error behaviour says" % (me, node_label(n["node_id"], n["name"])),
                                 lp + ".on_plc_stop"))


# -- the configuration download -----------------------------------------------

def consumer_writes(link, consumer, ro):
    """The writes for one consumer RPDO (dcf_gen.cpp add_link_writes), as
    (index, sub-index, data); `ro`: the node's read-only PDO communication
    sub-indices."""
    out = []

    def push(index, sub, value, size):
        if (index, sub) not in ro:
            out.append((index, sub, value.to_bytes(size, "little")))

    comm, mapi = 0x1400 + consumer["rpdo"] - 1, 0x1600 + consumer["rpdo"] - 1
    push(comm, 1, link["cob_id"] | 0x80000000, 4)
    if consumer["transmission"] is not None:
        push(comm, 2, consumer["transmission"], 1)
    if consumer["event_timer_ms"] is not None:
        push(comm, 5, consumer["event_timer_ms"], 2)
    if not consumer.get("device_mapping"):
        push(mapi, 0, 0, 1)
        for k, e in enumerate(consumer["entries"]):
            push(mapi, k + 1, e["index"] << 16 | e["subindex"] << 8 | CO_TYPES[e["type"]][1], 4)
        push(mapi, 0, len(consumer["entries"]), 1)
    push(comm, 1, link["cob_id"], 4)
    return out


def watch_writes(watches, ro=()):
    """0x1016 writes of a node's resolved heartbeat_watch entries."""
    return [(0x1016, h["subindex"], ((h["node"] << 16) | (h["timeout_ms"] & 0xFFFF)).to_bytes(4, "little"))
            for h in watches if h.get("subindex")]
