"""Writes the network documentation model (docexport.build) as one HTML file
(canopen-network-docs spec): inline styles, script and diagrams, every table
rendered here so the page reads without script, a print layout, light and
dark themes, and the model itself as JSON in the page."""

import html
import json

from .bustrace.explain import pdo_bit_text
from .docexport import hx

E = html.escape
# Categorical colours of the PDO layout bar (light, dark).
SEGMENT_COLOURS = 8


def _attr(value):
    return html.escape(str(value), quote=True)


def _cell(value):
    return "" if value is None else E(str(value))


def _vars(names):
    return "".join('<span class="var">%s</span>' % E(n) for n in names)


def _loc(text, names=()):
    if not text:
        return ""
    return '<code>%s</code>%s' % (E(text), (" " + _vars(names)) if names else "")


def _table(head, rows, cls="", numeric=(), empty="None."):
    """A table (rows of pre-escaped cell HTML) in a scroll wrapper."""
    if not rows:
        return '<p class="muted">%s</p>' % E(empty)
    out = ['<div class="tw"><table class="%s"><thead><tr>' % cls]
    for i, h in enumerate(head):
        out.append('<th scope="col"%s>%s</th>' % (' class="num"' if i in numeric else "", E(h)))
    out.append("</tr></thead><tbody>")
    for r in rows:
        out.append("<tr>" + "".join('<td%s>%s</td>' % (' class="num"' if i in numeric else "", c)
                                    for i, c in enumerate(r)) + "</tr>")
    out.append("</tbody></table></div>")
    return "".join(out)


def _kv(rows):
    out = ['<div class="tw"><table class="kv"><tbody>']
    for r in rows:
        obj = ' <span class="obj">%s</span>' % E(r["object"]) if r.get("object") else ""
        out.append("<tr><th scope=\"row\">%s%s</th><td>%s</td></tr>" % (E(r["label"]), obj, E(r["value"])))
    out.append("</tbody></table></div>")
    return "".join(out)


def _filter(target):
    return ('<label class="filter"><span class="sr">Filter</span><input type="search" placeholder="Filter…" '
            'data-filter="%s"></label>' % _attr(target))


def _pct(v):
    return "–" if v is None else "%.2f %%" % v


def _meter(v):
    if v is None:
        return ""
    cls = "bad" if v > 60 else ("warn" if v > 40 else "ok")
    return '<span class="meter %s" role="img" aria-label="%s"><span style="width:%.1f%%"></span></span>' % (
        cls, _attr(_pct(v)), min(v, 100.0))


def _device_title(n):
    """"Node 5 · name", or for the PLC's own device on a slave network
    "OpenPLC · node 10"."""
    nid = "node %d" % n["node_id"] if n["node_id"] is not None else "node ID from LSS"
    if n.get("role") == "slave":
        return "OpenPLC · " + nid
    return "Node %d%s" % (n["node_id"], (" · " + n["name"]) if n["name"] else "")


# -- sections ------------------------------------------------------------------

def _summary(model):
    tiles = []
    for net in model["networks"]:
        load = net["bus_load"]
        pdos = sum(len(n["pdos"]) for n in net["nodes"])
        stats = "<span><b>%d</b> PDOs</span>" % pdos
        if net["role"] == "j1939":
            rx = sum(1 for m in net["messages"] if m["direction"] == "rx")
            first = "<b>%d</b> received" % rx
            stats = "<span><b>%d</b> sent</span>" % (len(net["messages"]) - rx)
        elif net["role"] == "slave":
            dev = net["nodes"][0]
            first = "<b>slave</b> %s" % ("node %d" % dev["node_id"] if dev["node_id"] is not None else "LSS")
        else:
            first = "<b>%d</b> nodes" % len(net["nodes"])
        tiles.append(
            '<a class="tile" href="#%s"><span class="tile-title">%s</span>'
            '<span class="tile-sub">%s · %s · %s</span>'
            '<span class="stats"><span>%s</span>%s</span>'
            '<span class="loadrow"><span>Cyclic load</span><b>%s</b>%s</span>'
            '<span class="loadrow"><span>Worst case</span><b>%s</b>%s</span></a>' % (
                _attr(net["anchor"]), E(net["name"] or "Network"),
                "J1939" if net["protocol"] == "j1939" else "CANopen", E(net["interface"]),
                E("%d kbit/s" % (net["bitrate"] // 1000) if net["bitrate"] else "bitrate not set"),
                first, stats, _pct(load["cyclic"]), _meter(load["cyclic"]), _pct(load["worst"]),
                _meter(load["worst"])))
    warns = "".join("<li>%s</li>" % E(w) for w in model["warnings"])
    checks = ('<ul class="warnings">%s</ul>' % warns) if warns else '<p class="ok-text">No warnings.</p>'
    return ('<section id="summary"><h2>Summary</h2><div class="tiles">%s</div>'
            '<h3>Checks</h3>%s</section>' % ("".join(tiles), checks))


def _topology(net):
    nodes = net["nodes"]
    if net["role"] == "slave":
        dev = nodes[0]
        boxes = [("Upper master", "another device", "", True),
                 ("OpenPLC", "node %d" % dev["node_id"] if dev["node_id"] is not None else "LSS",
                  "#" + dev["anchor"], False)]
    else:
        boxes = [("Master", "node %d" % net["master_node_id"], "#" + net["anchor"] + "-settings", True)]
        boxes += [(n["name"] or "node %d" % n["node_id"], "node %d" % n["node_id"], "#" + n["anchor"], False)
                  for n in sorted(nodes, key=lambda n: n["node_id"])]
    per_row = 6
    rows = (len(boxes) + per_row - 1) // per_row
    bw, gap = 128, 22
    w = max(min(len(boxes), per_row) * (bw + gap) + 50, 360)
    h = rows * 130 + 20
    s = ['<svg class="topo" viewBox="0 0 %d %d" role="img" aria-label="Topology of %s">' % (
        w, h, _attr(net["name"] or "the network"))]
    for r in range(rows):
        y = 20 + r * 130
        line_y = y + 92
        s.append('<line class="bus" x1="12" y1="%d" x2="%d" y2="%d"/>' % (line_y, w - 12, line_y))
        if r < rows - 1:  # the bus snakes on to the next row
            x = w - 12 if r % 2 == 0 else 12
            s.append('<line class="bus" x1="%d" y1="%d" x2="%d" y2="%d"/>' % (x, line_y, x, line_y + 130))
        for i, (title, sub, href, is_master) in enumerate(boxes[r * per_row:(r + 1) * per_row]):
            x = 24 + i * (bw + gap)
            label = title if len(title) <= 15 else title[:14] + "\u2026"
            box = ('<g class="box%s"><title>%s</title><rect x="%d" y="%d" width="%d" height="58" rx="8"/>'
                   '<text x="%d" y="%d" class="t">%s</text><text x="%d" y="%d" class="s">%s</text></g>' % (
                       " master" if is_master else "", E("%s (%s)" % (title, sub)), x, y, bw,
                       x + bw // 2, y + 25, E(label), x + bw // 2, y + 45, E(sub)))
            s.append('<a href="%s">%s</a>' % (_attr(href), box) if href else box)
            s.append('<line class="drop" x1="%d" y1="%d" x2="%d" y2="%d"/>' % (
                x + bw // 2, y + 58, x + bw // 2, line_y))
    first_y = 20 + 92
    last_y = 20 + (rows - 1) * 130 + 92
    end_x = w - 14 if (rows - 1) % 2 == 0 else 4
    s.append('<rect class="term" x="4" y="%d" width="10" height="16" rx="2"><title>120 \u03a9 termination</title>'
             '</rect>' % (first_y - 8))
    s.append('<rect class="term" x="%d" y="%d" width="10" height="16" rx="2"><title>120 \u03a9 termination</title>'
             '</rect>' % (end_x, last_y - 8))
    s.append("</svg>")
    what = ("The upper master and OpenPLC as one of its devices" if net["role"] == "slave"
            else "Master and nodes")
    return ('<figure class="topology">%s<figcaption>%s on the bus line, terminated at both ends. '
            'Select a device to open its section.</figcaption></figure>' % ("".join(s), what))


def _frames(net):
    rows = []
    for f in net["frames"]:
        name = E(f["name"])
        if f["link"]:
            name = '<a href="#%s">%s</a>' % (_attr(f["link"]), name)
        if f["duplicate"]:
            name += ' <span class="badge bad">duplicate COB-ID</span>'
        rows.append([
            "<code>%s</code>" % hx(f["cob_id"], 3), name, '<span class="kind k-%s">%s</span>' % (
                _attr(f["kind"]), E(f["kind"].replace("_", " "))),
            E(f["producer"]), E(", ".join(f["consumers"])), str(f["dlc"]), E(f["trigger"]), str(f["bits"]),
            _pct(f["load_cyclic"]) if f["load_cyclic"] else "", _pct(f["load_worst"]) if f["load_worst"] else ""])
    target = net["anchor"] + "-frames"
    return ('<h3 id="%s">COB-ID map</h3><p class="muted">Every frame this network puts on the bus, sorted by COB-ID. '
            'Bits include worst-case bit stuffing and the interframe space.</p>%s<div id="%s-t">%s</div>' % (
                _attr(target), _filter(target + "-t"), _attr(target),
                _table(["COB-ID", "Frame", "Type", "Producer", "Consumers", "DLC", "Period / trigger", "Bits",
                        "Cyclic load", "Worst load"], rows, "sortable", numeric=(5, 7, 8, 9))))


def _bus_load(net):
    load = net["bus_load"]
    parts = ['<h3 id="%s-load">Bus load estimate</h3><div class="load-cards">' % _attr(net["anchor"])]
    for label, v, text in (("Cyclic", load["cyclic"], "SYNC, SYNC-driven PDOs, heartbeats, node guarding, TIME"),
                           ("Worst case", load["worst"], "cyclic plus event-driven PDOs at their fastest")):
        parts.append('<div class="load-card"><span class="tile-sub">%s</span><b>%s</b>%s<span class="muted">%s'
                     '</span></div>' % (E(label), _pct(v), _meter(v), E(text)))
    parts.append("</div>")
    notes = list(load["notes"]) + list(load["unbounded"])
    if notes:
        parts.append('<ul class="warnings">%s</ul>' % "".join("<li>%s</li>" % E(n) for n in notes))
    parts.append(
        '<p class="muted small">An estimate from the configuration, not a measurement: each frame counts '
        '47 + 8 × DLC bits plus worst-case stuff bits, times its rate, divided by the bitrate. Event-driven '
        'TPDOs count at their inhibit time, else their event timer; event-driven RPDOs at the SYNC rate, or at '
        'the master\'s 1 ms output check without SYNC. NMT, EMCY, SDO and LSS frames are not counted.</p>')
    return "".join(parts)


def _byte_bar(p):
    total = max(p["dlc"] * 8, p["bits"], 1)
    segs, colour = [], 0
    for e in p["entries"]:
        if e["dummy"]:
            cls, label = "seg dummy", "dummy"
        elif not e["used"]:
            cls, label = "seg unused", e["name"] or "%s:%d" % (hx(e["index"]), e["subindex"])
        else:
            cls, label = "seg c%d" % (colour % SEGMENT_COLOURS), e["name"] or hx(e["index"])
            colour += 1
        tip = "bits %d-%d: %s:%d %s" % (e["bit"], e["bit"] + e["length"] - 1, hx(e["index"]), e["subindex"], label)
        segs.append('<span class="%s" style="flex:%d" title="%s"><span>%s</span></span>' % (
            cls, e["length"], _attr(tip), E(label)))
    if p["bits"] < total:
        segs.append('<span class="seg pad" style="flex:%d"></span>' % (total - p["bits"]))
    ticks = "".join('<span>%d</span>' % b for b in range(p["dlc"] or 1))
    return ('<div class="bytebar" role="img" aria-label="%s">%s</div><div class="byteticks" style="--n:%d">%s</div>%s'
            % (_attr("Layout of %s %d, %d bytes" % (p["kind"], p["number"], p["dlc"])), "".join(segs),
               p["dlc"] or 1, ticks, _bit_grid(p)))


def _bit_grid(p):
    """Every bit of the PDO, most significant bit of each byte first; the
    explanation is each bit's title (shown by the script in a box too)."""
    if not p["dlc"]:
        return ""
    owner, colour = {}, 0
    for e in p["entries"]:
        cls = "dummy" if e["dummy"] else "unused" if not e["used"] else "c%d" % (colour % SEGMENT_COLOURS)
        if e["used"] and not e["dummy"]:
            colour += 1
        for b in range(e["bit"], e["bit"] + e["length"]):
            owner[b] = (e, cls)
    rows = []
    for by in range(p["dlc"]):
        cells = []
        for i in range(7, -1, -1):
            pb = by * 8 + i
            e, cls = owner.get(pb, (None, "pad"))
            cells.append('<span class="bit %s" tabindex="0" title="%s">%d</span>' % (
                cls, _attr(pdo_bit_text(pb, e, p["kind"])), pb))
        rows.append('<div class="bitrow"><span class="muted">byte %d</span>%s</div>' % (by, "".join(cells)))
    return ('<details class="bits"><summary>Every bit</summary><p class="muted">Point at or tab to a bit: the '
            'number is its CANopen bit number, most significant bit of each byte on the left.</p>%s'
            '<p class="bitex" aria-live="polite"></p></details>' % "".join(rows))


def _pdo(p):
    chips = ['<span class="chip">COB-ID <code>%s</code></span>' % hx(p["cob_id"], 3)]
    t = p["transmission"]
    chips.append('<span class="chip">Transmission %s%s%s</span>' % (
        "–" if t is None else t, (" · " + E(p["transmission_text"])) if p["transmission_text"] else "",
        " (from EDS)" if p["transmission_from_eds"] else ""))
    if p.get("inhibit_time_us"):
        chips.append('<span class="chip">Inhibit %g ms</span>' % (p["inhibit_time_us"] / 1000.0))
    if p.get("event_timer_ms"):
        chips.append('<span class="chip">%s %d ms</span>' % (
            "Event timer" if p["kind"] == "TPDO" else "Deadline", p["event_timer_ms"]))
    if p.get("sync_start") is not None:
        chips.append('<span class="chip">SYNC start %d</span>' % p["sync_start"])
    if p.get("timeout"):
        t = p["timeout"]
        chips.append('<span class="chip">Receive timeout %s%s, %s%s</span>' % (
            "?" if t["ms"] is None else "%d ms" % t["ms"], " (auto)" if t["auto"] else "", E(t["on_timeout"]),
            (", timeout bit " + _loc(t["location"], t["variables"])) if t["location"] else ""))
    chips.append('<span class="chip">%s</span>' % {
        "device": "Device mapping kept", "eds": "Mapping as the EDS gives it"}.get(p["mapping"],
                                                                               "Mapping written by the master"))
    if p.get("trigger"):
        chips.append('<span class="chip">%s</span>' % E(p["trigger"]))
    if p.get("gateway_rpdo"):
        chips.append('<span class="chip">CiA 309-3: r p %d</span>' % p["gateway_rpdo"])
    rows = []
    for e in p["entries"]:
        if e["dummy"]:
            what = '<span class="muted">dummy (gap)</span>'
        elif not e["used"]:
            what = '<span class="muted">%s</span>' % E(
                "not used by the PLC" + ("" if p["kind"] == "TPDO" else ", sent as 0"))
        else:
            what = _loc(e["location"], e["variables"])
        name = E(e["name"])
        if e.get("note"):
            name += '<div class="small muted">%s</div>' % E(e["note"])
        rows.append([str(e["bit"]), str(e["length"]), "<code>%s:%d</code>" % (hx(e["index"]), e["subindex"]),
                     name, E(e["type"]) + (" <span class=\"muted\">%s</span>" % E(e["unit"]) if e.get("unit") else ""),
                     what])
    direction = p.get("direction") or ("node → master" if p["kind"] == "TPDO" else "master → node")
    return ('<div class="pdo" id="%s"><h5>%s %d <span class="muted">%s · %d byte%s</span></h5>'
            '<div class="chips">%s</div>%s%s</div>' % (
                _attr(p["anchor"]), p["kind"], p["number"], direction, p["dlc"], "" if p["dlc"] == 1 else "s",
                "".join(chips), _byte_bar(p),
                _table(["Bit", "Bits", "Object", "Name", "Type", "PLC"], rows, numeric=(0, 1))))


def _identity(node):
    rows = []
    for i in node["identity"]:
        eds = hx(i["eds"], 8) if isinstance(i["eds"], int) else "–"
        exp = hx(i["expected"], 8) if isinstance(i["expected"], int) else "–"
        rows.append([E(i["field"]), "<code>%s</code>" % eds, "<code>%s</code>" % exp,
                     '<span class="badge %s">%s</span>' % ("ok" if i["checked"] else "", "checked" if i["checked"]
                                                           else "not checked")])
    return _table(["Identity (0x1018)", "EDS", "Expected at boot", "Check"], rows)


def _objects(node):
    rows = [["<code>%s:%d</code>" % (hx(o["index"]), o["subindex"]), E(o["name"]), E(o["type"]), E(o["access"]),
             E(o["direction"]), _loc(o["location"], o["variables"]), E(o["pdo"])] for o in node["objects"]]
    return ("<h5>Objects bound to the PLC</h5>" +
            _table(["Object", "Name", "Type", "Access", "Direction", "PLC", "Carried in"], rows, "sortable",
                   empty="No object is bound to a PLC address."))


def _node(node):
    eds = node["eds"]
    slave = node.get("role") == "slave"
    product = " ".join(x for x in (eds["vendor_name"], eds["product_name"]) if x)
    head = ('<section class="node" id="%s"><header class="node-head"><h4>%s</h4><p>%s</p></header>' % (
        _attr(node["anchor"]), E(_device_title(node)),
        E(product) or '<span class="muted">no product name in the EDS</span>'))
    eds_line = ('<p class="small">EDS <code>%s</code> · SHA-256 <code class="hash">%s</code>%s%s</p>' % (
        E(eds["file"]), E(eds["sha256"]), " · LSS supported" if eds["lss_supported"] else "",
        (' · <a download="%s" href="data:application/octet-stream;base64,%s">Save EDS file</a>' % (
            _attr(eds["file"].rsplit("/", 1)[-1]), eds["data"])) if eds.get("data") else ""))
    if slave:
        ident = _table(["Identity (0x1018)", "EDS"], [[E(i["field"]), "<code>%s</code>" % (
            hx(i["eds"], 8) if isinstance(i["eds"], int) else "–")] for i in node["identity"]])
        parts = [head, eds_line, ident, _objects(node)]
    else:
        parts = [head, eds_line, '<div class="cols"><div>', _identity(node), '</div><div>', _kv(node["settings"]),
                 '</div></div>']
    if node["locations"]:
        parts.append("<h5>%s in the PLC</h5>" % ("Own status and EMCY" if slave else "Status and control"))
        parts.append(_table(["PLC", "Holds"], [[_loc(l["location"], l["variables"]), E(l["what"])]
                                               for l in node["locations"]]))
    parts.append("<h5>PDOs</h5>")
    parts.append("".join(_pdo(p) for p in node["pdos"]) or '<p class="muted">No PDOs: every PDO of the %s is '
                                                            'switched off.</p>' % ("EDS" if slave else "node"))
    if node["boot"]:
        b = node["boot"]
        parts.append('<h5>Boot configuration <span class="muted">%d SDO writes, in order</span></h5>' %
                     len(b["writes"]))
        if b["before"]:
            parts.append('<p class="small">Before the writes: %s.</p>' % E("; ".join(b["before"])))
        rows = [[str(i + 1), "<code>%s:%d</code>" % (hx(w["index"]), w["subindex"]), E(w["name"]),
                 E(w.get("note", "")), "<code>%s</code>" % E(w["value"]), E(w["meaning"]), E(w["access"]),
                 "<code>%s</code>" % E(w["eds_default"]) if w["eds_default"] else "", E(w["source"])]
                for i, w in enumerate(b["writes"])]
        parts.append(_table(["#", "Object", "Name", "Note", "Value", "Meaning", "Access", "EDS default", "From"], rows,
                            "sortable", numeric=(0,), empty="Nothing is written: the node keeps its EDS values."))
        if b["after"]:
            parts.append('<p class="small">After the writes: %s.</p>' % E("; ".join(b["after"])))
    if node["sdo_variables"]:
        parts.append("<h5>SDO variables</h5>")
        rows = []
        for v in node["sdo_variables"]:
            extra = []
            for key, label in (("period_ms", "every %s ms"), ("timeout_ms", "timeout %s ms")):
                if v.get(key) is not None:
                    extra.append(label % v[key])
            for key, label in (("trigger_location", "trigger"), ("status_location", "status"),
                               ("abort_code_location", "abort code")):
                if v.get(key):
                    extra.append("%s %s" % (label, v[key]))
            rows.append([E(v["name"]), "<code>%s:%d</code>" % (hx(v["index"]), v["subindex"]), E(v["od_name"]),
                         E(v["type"]), E(v["direction"]), _loc(v["location"], v["variables"]), E(", ".join(extra))])
        parts.append(_table(["Name", "Object", "OD name", "Type", "Direction", "PLC", "Settings"], rows))
    target = node["anchor"] + "-od"
    parts.append('<details class="od"><summary>Object dictionary extract (%d entries)</summary>%s<div id="%s">%s</div>'
                 '</details>' % (len(node["od"]), _filter(target), _attr(target), _table(
                     ["Object", "Name", "Type", "Access", "Low", "High", "EDS default", "Configured"],
                     [["<code>%s:%d</code>" % (hx(o["index"]), o["subindex"]), E(o["name"]), E(o["type"]),
                       E(o["access"]), E(o["low"]), E(o["high"]), "<code>%s</code>" % E(o["default"])
                       if o["default"] else "", E(o["configured"])] for o in node["od"]], "sortable")))
    parts.append("</section>")
    return "".join(parts)


def _num(v):
    return "%g" % v if isinstance(v, float) else str(v)


def _j1939_message(m):
    chips = ['<span class="chip">ID <code>%08X</code></span>' % m["can_id"],
             '<span class="chip">%s %s → %s</span>' % ("From" if m["direction"] == "rx" else "Sent",
                                                       E(m["source"]), E(m["destination"])),
             '<span class="chip">%d byte%s</span>' % (m["length"], "" if m["length"] == 1 else "s")]
    if m["priority"] is not None:
        chips.append('<span class="chip">Priority %d</span>' % m["priority"])
    if m["timeout_ms"]:
        chips.append('<span class="chip">Receive timeout %d ms</span>' % m["timeout_ms"])
    if m["min_gap_ms"]:
        chips.append('<span class="chip">Minimum gap %d ms</span>' % m["min_gap_ms"])
    chips.append('<span class="chip">%s</span>' % E(m["trigger"]))
    if m["status"]:
        chips.append('<span class="chip">Status %s</span>' % _loc(m["status"]["location"], m["status"]["variables"]))
    rows = []
    for sg in m["signals"]:
        rows.append([E(sg["name"]), str(sg["start_bit"]), str(sg["length"]), E(sg["byte_order"]),
                     "yes" if sg["signed"] else "no", _num(sg["scale"]), _num(sg["offset"]), E(sg["unit"]),
                     _loc(sg["location"], sg["variables"]), _loc(sg["valid_location"], sg["valid_variables"]),
                     E(sg["comment"])])
    return ('<div class="pdo" id="%s"><h5>PGN %d %s <span class="muted">%s</span></h5>%s<div class="chips">%s</div>%s'
            '</div>' % (_attr(m["anchor"]), m["pgn"], E(m["name"]),
                        "received" if m["direction"] == "rx" else "sent by the PLC",
                        '<p class="small">%s</p>' % E(m["comment"]) if m["comment"] else "", "".join(chips),
                        _table(["Signal", "Start bit", "Bits", "Byte order", "Signed", "Scale", "Offset", "Unit",
                                "PLC", "Valid bit", "Comment"], rows, numeric=(1, 2))))


def _j1939_network(net):
    parts = ['<section class="network" id="%s"><h2>%s <span class="muted">J1939</span></h2>' % (
        _attr(net["anchor"]), E("Network " + net["name"] if net["name"] else "Network"))]
    parts.append('<h3 id="%s-settings">ECU and bus settings</h3>' % _attr(net["anchor"]))
    parts.append(_kv(net["settings"]))
    if net["locations"]:
        parts.append("<h4>ECU status in the PLC</h4>")
        parts.append(_table(["PLC", "Holds"], [[_loc(l["location"], l["variables"]), E(l["what"])]
                                               for l in net["locations"]]))
    target = net["anchor"] + "-frames"
    rows = []
    for f in net["frames"]:
        name = E(f["name"])
        if f["link"]:
            name = '<a href="#%s">%s</a>' % (_attr(f["link"]), name)
        rows.append(["<code>%08X</code>" % f["cob_id"], name, '<span class="kind k-%s">%s</span>' % (
            _attr(f["kind"]), E(f["kind"])), E(f["producer"]), E(", ".join(f["consumers"])), str(f["dlc"]),
            E(f["trigger"]), str(f["bits"]), _pct(f["load_cyclic"]) if f["load_cyclic"] else "",
            _pct(f["load_worst"]) if f["load_worst"] else ""])
    parts.append('<h3 id="%s">Frame map</h3><p class="muted">Every frame this ECU sends or takes, sorted by its 29-bit '
                 'identifier. Bits include worst-case bit stuffing and the interframe space; a message longer than '
                 '8 bytes counts all its transport protocol frames.</p>%s<div id="%s-t">%s</div>' % (
                     _attr(target), _filter(target + "-t"), _attr(target),
                     _table(["Identifier", "Frame", "Type", "Producer", "Consumers", "DLC", "Period / trigger",
                             "Bits", "Cyclic load", "Worst load"], rows, "sortable", numeric=(5, 7, 8, 9))))
    load = net["bus_load"]
    parts.append('<h3 id="%s-load">Bus load estimate</h3><div class="load-cards">' % _attr(net["anchor"]))
    for label, v, text in (("Cyclic", load["cyclic"], "periodic messages and requests"),
                           ("Worst case", load["worst"], "cyclic plus messages sent on change at their minimum gap")):
        parts.append('<div class="load-card"><span class="tile-sub">%s</span><b>%s</b>%s<span class="muted">%s'
                     '</span></div>' % (E(label), _pct(v), _meter(v), E(text)))
    parts.append("</div>")
    if load["notes"]:
        parts.append('<ul class="warnings">%s</ul>' % "".join("<li>%s</li>" % E(n) for n in load["notes"]))
    parts.append(
        '<p class="muted small">An estimate from the configuration, not a measurement: each frame counts '
        '67 + 8 × DLC bits plus worst-case stuff bits (29-bit identifier), times its rate, divided by the bitrate. '
        'Sent messages count at their period; received ones at the DBC cycle time, or at the period of the '
        'PLC\'s request for them. Address claims are not counted.</p>')
    for key, title in (("rx", "Received messages"), ("tx", "Sent messages")):
        msgs = [m for m in net["messages"] if m["direction"] == key]
        parts.append('<h3 id="%s-%s">%s</h3>' % (_attr(net["anchor"]), key, title))
        parts.append("".join(_j1939_message(m) for m in msgs) or '<p class="muted">None.</p>')
    parts.append('<h3 id="%s-requests">Periodic requests</h3>' % _attr(net["anchor"]))
    parts.append(_table(["PGN", "Destination", "Every", "Answered by"], [[
        str(r["pgn"]), E(r["destination"]), "%d ms" % r["period_ms"],
        '<a href="#%s">%s</a>' % (_attr(r["link"]), E(r["answer"])) if r["link"] else ""] for r in net["requests"]],
        numeric=(0,), empty="The PLC requests nothing periodically."))
    parts.append("</section>")
    return "".join(parts)


def _network(net):
    if net["role"] == "j1939":
        return _j1939_network(net)
    parts = ['<section class="network" id="%s"><h2>%s</h2>' % (_attr(net["anchor"]), E(
        "Network " + net["name"] if net["name"] else "Network"))]
    parts.append(_topology(net))
    slave = net["role"] == "slave"
    parts.append('<h3 id="%s-settings">%s</h3>' % (_attr(net["anchor"]), "Slave and bus settings" if slave
                                                   else "Master and bus settings"))
    parts.append(_kv(net["settings"]))
    if net["locations"]:
        parts.append("<h4>Master status in the PLC</h4>")
        parts.append(_table(["PLC", "Holds"], [[_loc(l["location"], l["variables"]), E(l["what"])]
                                               for l in net["locations"]]))
    parts.append(_frames(net))
    parts.append(_bus_load(net))
    parts.append('<h3>%s%s</h3>' % ("OpenPLC as a device" if slave else "Nodes",
                                     (" on network " if slave else " of network ") + E(net["name"])
                                     if net["name"] else ""))
    parts.append("".join(_node(n) for n in sorted(net["nodes"], key=lambda n: n["node_id"] or 0)) or
                 '<p class="muted">No nodes configured.</p>')
    parts.append("</section>")
    return "".join(parts)


def _gateway(model):
    g = model.get("gateway")
    if not g:
        return ""
    rows = []
    for r in g["routes"]:
        field = "%s node %d <code>%s:%d</code>" % (E(r["field_network"]), r["field_node"], hx(r["field_index"]),
                                                    r["field_subindex"])
        if r["field_link"]:
            field = '<a href="#%s">%s</a>' % (_attr(r["field_link"]), field)
        rows.append([E(r["name"]), "<code>%s:%d</code>" % (hx(r["slave_index"]), r["slave_subindex"]),
                     E(r["slave_name"]), E(r["type"]), E(r["direction"]), field])
    settings = [
        {"label": "Upper network (OpenPLC is a slave)", "value": g["upper"]},
        {"label": "Field node states", "value": "from %s (one ARRAY per master network)" % hx(g["status_index"])},
        {"label": "Field EMCYs forwarded upward", "value": "yes" if g["emcy_forward"] else "no"},
        {"label": "Routed values down when the upper master is lost", "value": {
            "zero": "sent as 0", "stop_nodes": "the field nodes that receive routes are stopped"}.get(
                g["on_upper_loss"], "keep their last values")},
        {"label": "SDO bridge", "value": ("at %s, %s" % (hx(g["sdo_bridge_index"]), "reads and writes" if
                                                         g["sdo_bridge_write"] else "reads only"))
         if g["sdo_bridge"] else "off"},
    ]
    return ('<section id="gateway"><h2>Gateway</h2><p class="muted">The plugin copies these values between the upper '
            'network and the master networks without the PLC program.</p>%s<h3>Routes</h3>%s</section>' % (
                _kv(settings), _table(["Route", "Slave object", "Name", "Type", "Direction", "Field node entry"],
                                      rows, "sortable", empty="No routes.")))


def _cia309(model):
    g = model.get("cia309")
    if not g:
        return ""
    settings = [
        {"label": "Plain port", "value": "%s:%d (loopback only)" % (g["bind"], g["port"]) if g["port"]
         else "none (sessions through the diagnostics channel only)"},
        {"label": "Sessions at once", "value": str(g["max_clients"])},
        {"label": "Changes (SDO downloads, NMT, LSS)", "value": "allowed" if g["allow_changes"] else "refused"},
        {"label": "Force on OPERATIONAL nodes", "value": "allowed" if g["allow_force"] else "refused"},
        {"label": "Default network", "value": str(g["default_net"]) if g["default_net"] else "–"},
    ]
    rows = [['<span class="num">%d</span>' % n["number"], E(n["name"] or "the network")] for n in g["nets"]]
    return ('<section id="cia309"><h2>CiA 309-3 gateway</h2><p class="muted">Standard CiA 309-3 text commands; other '
            'machines connect through canworks-diag gateway. A node\'s TPDO n (1-4) is read with r p (node - 1) × 4 + n, '
            'shown at each TPDO.</p>%s<h3>Network numbers</h3>%s</section>' % (
                _kv(settings), _table(["Number", "Network"], rows, empty="No networks.")))


FUNCTIONS = {4: "4 read input registers", 16: "16 write multiple registers"}


def _modbus(model):
    m = model.get("modbus")
    if not m:
        return ""
    loss = {"stop": "outputs stop (no RPDOs or transmit messages; SYNC and inputs go on)",
            "zero": "outputs are sent as 0 once, then stop", "hold": "outputs keep their last values"}
    settings = [
        {"label": "Listens on", "value": m["listen"]},
        {"label": "Unit ID", "value": str(m["unit_id"])},
        {"label": "32- and 64-bit values", "value": "high word first" if m["word_order"] == "high_first"
         else "low word first"},
        {"label": "Clients at once", "value": str(m["max_clients"])},
        {"label": "Watchdog", "value": "%d ms" % m["watchdog_ms"] if m["watchdog_ms"] else "off"},
        {"label": "When writes stop", "value": loss.get(m["on_client_loss"], m["on_client_loss"])},
        {"label": "Clients that may write", "value": ", ".join(m["writers"]) or "every client"},
        {"label": "Clients that may connect", "value": ", ".join(m["readers"]) or "every client"},
        {"label": "SDO writes through the registers", "value": "allowed" if m["sdo_bridge_write"] else "refused"},
        {"label": "Image", "value": "%d input bytes, %d output bytes" % (m["input_bytes"], m["output_bytes"])},
    ]
    rows = [[E(r["table"]), '<span class="num">%d</span>' % r["address"], '<span class="num">%d</span>' % r["count"],
             _loc(r["location"]), E(r["name"]), E(r["network"] or "–"), E(r["type"]),
             E(" ".join(str(x) for x in (r["scale"] and "× %s" % r["scale"], r["offset"] and "+ %s" % r["offset"],
                                         r["unit"]) if x))]
            for r in m["registers"]]
    channels = [[E(FUNCTIONS.get(c["function"], str(c["function"]))), str(c["start"]), str(c["count"]),
                 E(c["direction"])] for c in m["channels"]]
    return ('<section id="modbus"><h2>Modbus register map</h2><p class="muted">canworks-bridge serves this config as '
            'Modbus TCP registers: input byte n is input register n/2 (even byte the high byte), %%IXn.b discrete '
            'input n×8+b; outputs map to holding registers and coils the same way.</p>%s<h3>Registers</h3>%s'
            '<div id="modbus-t">%s</div><h3>Suggested client channels</h3>%s</section>' % (
                _kv(settings), _filter("modbus-t"),
                _table(["Table", "Address", "Registers", "PLC address", "Name", "Network", "Type", "Scaling"], rows,
                       "sortable", empty="No registers."),
                _table(["Function", "Start", "Count", "Direction"], channels, empty="No channels.")))


def _io(model):
    rows = [[_loc(r["location"]), E(r["network"]) or "–", E(r["who"]), _vars(r["variables"]),
             "<code>%s</code>" % E(r["path"])] for r in model["io"]]
    return ('<section id="io"><h2>PLC I/O cross-reference</h2><p class="muted">Every PLC address the configuration '
            'uses, sorted by address.</p>%s<div id="io-t">%s</div></section>' % (
                _filter("io-t"), _table(["PLC address", "Network", "Used by", "PLC variable", "Config field"], rows,
                                        "sortable", empty="The configuration uses no PLC address.")))


def _appendix(model):
    return ('<section id="config"><h2>Appendix: configuration file</h2><p class="small">%s · SHA-256 '
            '<code class="hash">%s</code> · schema version %s</p><details><summary>Show %s</summary><pre>%s</pre>'
            '</details></section>' % (E(model["config"]["file"]), E(model["config"]["sha256"]),
                                      model["config"]["schema_version"], E(model["config"]["file"]),
                                      E(model["config"]["text"])))


def _toc(model):
    items = ['<li><a href="#summary">Summary</a></li>']
    for net in model["networks"]:
        sub = "".join('<li><a href="#%s">%s</a></li>' % (_attr(n["anchor"]), E(_device_title(n)))
                      for n in sorted(net["nodes"], key=lambda n: n["node_id"] or 0))
        if net["role"] == "j1939":
            sub = "".join('<li><a href="#%s-%s">%s</a></li>' % (_attr(net["anchor"]), key, text) for key, text in (
                ("rx", "Received messages"), ("tx", "Sent messages"), ("requests", "Periodic requests")))
        items.append('<li><a href="#%s">%s</a><ul>%s</ul></li>' % (
            _attr(net["anchor"]), E("Network " + net["name"] if net["name"] else "Network"), sub))
    if model.get("gateway"):
        items.append('<li><a href="#gateway">Gateway</a></li>')
    if model.get("modbus"):
        items.append('<li><a href="#modbus">Modbus register map</a></li>')
    if model.get("cia309"):
        items.append('<li><a href="#cia309">CiA 309-3 gateway</a></li>')
    items.append('<li><a href="#io">PLC I/O</a></li><li><a href="#config">Configuration file</a></li>')
    return '<nav class="toc" aria-label="Contents"><p class="toc-title">Contents</p><ul>%s</ul></nav>' % "".join(items)


def write(model):
    """The document as HTML text."""
    data = json.dumps(model, sort_keys=True, ensure_ascii=False).replace("</", "<\\/")
    title = model["title"]
    head = ('<header class="top"><div><h1>%s</h1><p class="meta">%s · SHA-256 <code class="hash">%s</code> · '
            'generated %s by %s %s</p></div><div class="actions"><button type="button" data-theme-toggle>Theme'
            '</button><button type="button" data-print>Print</button></div></header>' % (
                E(title), E(model["config"]["file"]), E(model["config"]["sha256"][:16]), E(model["generated"]),
                E(model["tool"]["name"]), E(model["tool"]["version"])))
    body = [_summary(model)] + [_network(n) for n in model["networks"]] + [_gateway(model), _modbus(model), _cia309(model), _io(model),
                                                                          _appendix(model)]
    return ("<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            "<meta name=\"generator\" content=\"%s %s\"><title>%s</title><style>%s</style></head>"
            "<body><div class=\"layout\">%s<main>%s%s<footer class=\"foot\">%s · %s · generated %s</footer></main>"
            "</div><script type=\"application/json\" id=\"canworks-doc\">%s</script><script>%s</script></body></html>\n"
            % (E(model["tool"]["name"]), E(model["tool"]["version"]), E(title), CSS, _toc(model), head,
               "".join(body), E(title), E(model["config"]["file"]), E(model["generated"]), data, JS))


CSS = """
:root{color-scheme:light;--bg:#fbfbfc;--panel:#fff;--fg:#1c2128;--muted:#5d6672;--line:#dfe3e8;--head:#f2f4f7;
--acc:#1f5fbf;--acc-bg:#e7effb;--ok:#1d7a3a;--warn:#a15c00;--bad:#b42318;--code:#f4f5f7;
--c0:#3f7fd6;--c1:#d97f2b;--c2:#3a9b6a;--c3:#b45bb0;--c4:#c9a227;--c5:#2c9fa6;--c6:#d1576b;--c7:#7a6bd1}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;--bg:#111418;--panel:#181c21;
--fg:#e5e8ec;--muted:#9aa4b1;--line:#2b323a;--head:#1f252c;--acc:#7fb0ff;--acc-bg:#1d2a3d;--ok:#5cc983;
--warn:#f0ad4e;--bad:#ff7b72;--code:#20262d;--c0:#5b95e6;--c1:#e3934a;--c2:#4fb282;--c3:#c776c3;--c4:#d8b54a;
--c5:#45b6bd;--c6:#e0738a;--c7:#9586e3}}
:root[data-theme="dark"]{color-scheme:dark;--bg:#111418;--panel:#181c21;--fg:#e5e8ec;--muted:#9aa4b1;--line:#2b323a;
--head:#1f252c;--acc:#7fb0ff;--acc-bg:#1d2a3d;--ok:#5cc983;--warn:#f0ad4e;--bad:#ff7b72;--code:#20262d;
--c0:#5b95e6;--c1:#e3934a;--c2:#4fb282;--c3:#c776c3;--c4:#d8b54a;--c5:#45b6bd;--c6:#e0738a;--c7:#9586e3}
*{box-sizing:border-box}html{scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
.layout{display:grid;grid-template-columns:240px minmax(0,1fr);min-height:100vh}
.toc{position:sticky;top:0;align-self:start;max-height:100vh;overflow:auto;padding:20px 14px;border-right:1px solid var(--line);font-size:13px}
.toc ul{list-style:none;margin:0;padding:0 0 0 10px}.toc>ul{padding:0}.toc li{margin:3px 0}
.toc a{color:var(--fg);text-decoration:none}.toc a:hover{color:var(--acc)}.toc-title{font-weight:600;margin:0 0 8px}
main{padding:24px 32px 48px;max-width:1280px;min-width:0}
a{color:var(--acc)}h1{font-size:26px;margin:0}h2{font-size:21px;margin:40px 0 12px;padding-bottom:6px;border-bottom:2px solid var(--line)}
h3{font-size:17px;margin:28px 0 8px}h4{font-size:16px;margin:0}h5{font-size:14px;margin:20px 0 8px}
.top{display:flex;justify-content:space-between;gap:16px;align-items:flex-start;flex-wrap:wrap}
.meta,.muted,.small{color:var(--muted)}.small{font-size:12.5px}.meta{margin:6px 0 0;font-size:13px}
.actions{display:flex;gap:8px}button{font:inherit;padding:5px 12px;border:1px solid var(--line);border-radius:6px;background:var(--panel);color:var(--fg);cursor:pointer}
code{font:12.5px/1.4 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;background:var(--code);padding:1px 4px;border-radius:4px}
.hash{word-break:break-all}pre{background:var(--code);padding:12px;border-radius:8px;overflow:auto;font-size:12px}
.tiles{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:12px}
.tile{display:flex;flex-direction:column;gap:6px;padding:14px 16px;border:1px solid var(--line);border-radius:10px;background:var(--panel);color:var(--fg);text-decoration:none}
.tile:hover{border-color:var(--acc)}.tile-title{font-weight:600;font-size:16px}.tile-sub{color:var(--muted);font-size:12.5px}
.stats{display:flex;gap:16px}.loadrow{display:grid;grid-template-columns:90px 70px 1fr;align-items:center;gap:8px;font-size:13px}
.meter{display:inline-block;height:8px;border-radius:4px;background:var(--line);overflow:hidden;min-width:60px;width:100%}
.meter>span{display:block;height:100%;background:var(--ok)}.meter.warn>span{background:var(--warn)}.meter.bad>span{background:var(--bad)}
.load-cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:12px}
.load-card{display:flex;flex-direction:column;gap:6px;padding:12px 14px;border:1px solid var(--line);border-radius:10px;background:var(--panel)}
.load-card b{font-size:20px}
.warnings{margin:8px 0;padding-left:20px}.warnings li{color:var(--warn)}.ok-text{color:var(--ok)}
.tw{overflow-x:auto;margin:6px 0 14px;border:1px solid var(--line);border-radius:8px;background:var(--panel)}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{padding:5px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
tbody tr:last-child>*{border-bottom:0}thead th{background:var(--head);font-weight:600;white-space:nowrap;position:relative}
table.sortable thead th{cursor:pointer;user-select:none}table.sortable thead th[aria-sort]::after{content:" ▲";font-size:10px}
table.sortable thead th[aria-sort="descending"]::after{content:" ▼"}
.num{text-align:right;font-variant-numeric:tabular-nums}
table.kv th{width:40%;font-weight:500;background:transparent}.obj{color:var(--muted);font-size:11.5px;font-weight:400}
.filter{display:inline-block;margin:2px 0 4px}.filter input{font:inherit;padding:5px 10px;border:1px solid var(--line);border-radius:6px;background:var(--panel);color:var(--fg);width:260px;max-width:100%}
.sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)}
.topology{margin:8px 0 16px}.topo{width:100%;max-width:900px;height:auto}
.topo .bus{stroke:var(--fg);stroke-width:4}.topo .drop{stroke:var(--fg);stroke-width:2}.topo .term{fill:var(--muted)}
.topo .box rect{fill:var(--panel);stroke:var(--line);stroke-width:1.5}.topo .box.master rect{fill:var(--acc-bg);stroke:var(--acc)}
.topo a:hover rect{stroke:var(--acc)}.topo text{fill:var(--fg);text-anchor:middle}.topo .t{font-weight:600;font-size:14px}.topo .s{fill:var(--muted);font-size:12px}
figcaption{color:var(--muted);font-size:12.5px}
.node{border:1px solid var(--line);border-radius:12px;padding:4px 18px 10px;margin:18px 0;background:var(--panel)}
.node-head{display:flex;gap:12px;align-items:baseline;flex-wrap:wrap;padding-top:12px}.node-head p{margin:0;color:var(--muted)}
.cols{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(440px,100%),1fr));gap:14px}.cols>div{min-width:0}
.pdo{border-top:1px dashed var(--line);padding-top:4px}.pdo h5{margin:12px 0 6px}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px}.chip{font-size:12px;padding:2px 8px;border-radius:999px;background:var(--head);border:1px solid var(--line)}
.bytebar{display:flex;height:34px;border:1px solid var(--line);border-radius:6px;overflow:hidden;background:var(--head)}
.seg{display:flex;align-items:center;justify-content:center;min-width:0;border-right:2px solid var(--panel);color:#fff;font-size:11.5px;padding:0 4px}
.seg>span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.seg.c0{background:var(--c0)}.seg.c1{background:var(--c1)}.seg.c2{background:var(--c2)}.seg.c3{background:var(--c3)}
.seg.c4{background:var(--c4)}.seg.c5{background:var(--c5)}.seg.c6{background:var(--c6)}.seg.c7{background:var(--c7)}
.seg.unused{background:var(--line);color:var(--muted)}.seg.dummy{background:repeating-linear-gradient(45deg,var(--line) 0 4px,transparent 4px 8px);color:var(--muted)}
.seg.pad{background:transparent}
.bitrow{display:flex;gap:3px;align-items:center;margin:3px 0}.bitrow>.muted{width:52px;font-size:11.5px}
.bit{width:30px;height:24px;display:inline-grid;place-items:center;font-size:11px;border-radius:3px;color:#fff;cursor:help}
.bit.c0{background:var(--c0)}.bit.c1{background:var(--c1)}.bit.c2{background:var(--c2)}.bit.c3{background:var(--c3)}
.bit.c4{background:var(--c4)}.bit.c5{background:var(--c5)}.bit.c6{background:var(--c6)}.bit.c7{background:var(--c7)}
.bit.unused,.bit.pad{background:var(--line);color:var(--muted)}.bit.dummy{background:repeating-linear-gradient(45deg,var(--line) 0 4px,transparent 4px 8px);color:var(--muted)}
.bit:hover,.bit:focus,.bit.on{outline:2px solid var(--fg);outline-offset:1px}
.bitex{min-height:2.6em;font-size:13px}
.byteticks{display:grid;grid-template-columns:repeat(var(--n),1fr);font-size:11px;color:var(--muted);margin:2px 0 8px}
.byteticks span{border-left:1px solid var(--line);padding-left:4px}.byteticks span::before{content:"byte "}
.var{display:inline-block;font-size:12px;padding:0 6px;border-radius:4px;background:var(--acc-bg);color:var(--acc);margin:1px 2px}
.badge{font-size:11.5px;padding:1px 7px;border-radius:999px;border:1px solid var(--line);color:var(--muted);white-space:nowrap}
.badge.ok{color:var(--ok);border-color:currentColor}.badge.bad{color:var(--bad);border-color:currentColor}
.kind{font-size:12px;white-space:nowrap}
details{margin:8px 0}details>summary{cursor:pointer;color:var(--acc);font-weight:500}
.foot{margin-top:48px;padding-top:12px;border-top:1px solid var(--line);color:var(--muted);font-size:12px}
@media (max-width:860px){.layout{display:block}.toc{position:static;max-height:none;border-right:0;border-bottom:1px solid var(--line);padding:14px 16px}
main{padding:16px}.cols{grid-template-columns:1fr}}
@media print{:root{color-scheme:light}body{background:#fff;font-size:11.5px}.layout{display:block}
.toc,.actions,.filter{display:none}main{padding:0;max-width:none}
th,td{padding:3px 5px;overflow-wrap:anywhere}thead th,.kind,.badge{white-space:normal}code{font-size:10.5px}
td.num,td code{overflow-wrap:normal;white-space:nowrap}.topo{max-width:560px}
.network,.node{break-before:page}.node{border:0;padding:0;background:none}.tw{overflow:visible;border:0}
details>summary{display:none}details::details-content{display:contents;content-visibility:visible}
thead{display:table-header-group}tr,.bytebar,.chips,.tile,.load-card{break-inside:avoid}
a{color:inherit;text-decoration:none}h2,h3,h4,h5{break-after:avoid}.seg{-webkit-print-color-adjust:exact;print-color-adjust:exact}
.meter>span{-webkit-print-color-adjust:exact;print-color-adjust:exact}pre{white-space:pre-wrap}}
@page{size:A4;margin:14mm 12mm}
"""

JS = """
(function(){
var root=document.documentElement;
function store(v){try{if(v)localStorage.setItem('canworks-doc-theme',v);return localStorage.getItem('canworks-doc-theme')}catch(e){return null}}
var saved=store();if(saved)root.setAttribute('data-theme',saved);
var t=document.querySelector('[data-theme-toggle]');
if(t)t.addEventListener('click',function(){var dark=root.getAttribute('data-theme')?root.getAttribute('data-theme')==='dark':matchMedia('(prefers-color-scheme: dark)').matches;
var v=dark?'light':'dark';root.setAttribute('data-theme',v);store(v)});
document.querySelectorAll('details.bits').forEach(function(d){var ex=d.querySelector('.bitex');
d.querySelectorAll('.bit').forEach(function(b){function show(){d.querySelectorAll('.bit.on').forEach(function(o){o.classList.remove('on')});
b.classList.add('on');ex.textContent=b.getAttribute('title')}b.addEventListener('mouseenter',show);b.addEventListener('focus',show)})});
var p=document.querySelector('[data-print]');if(p)p.addEventListener('click',function(){window.print()});
window.addEventListener('beforeprint',function(){document.querySelectorAll('details').forEach(function(d){if(!d.open){d.open=true;d.dataset.closed='1'}})});
window.addEventListener('afterprint',function(){document.querySelectorAll('details[data-closed]').forEach(function(d){d.open=false;delete d.dataset.closed})});
function key(td){var s=td.textContent.trim();var m=s.match(/^-?(0x[0-9a-f]+|\\d+(\\.\\d+)?)/i);return m?[0,m[1].indexOf('0x')===0?parseInt(m[1],16):parseFloat(m[1]),s]:[1,0,s.toLowerCase()]}
document.querySelectorAll('table.sortable').forEach(function(tb){tb.querySelectorAll('thead th').forEach(function(th,i){
th.setAttribute('tabindex','0');function go(){var desc=th.getAttribute('aria-sort')==='ascending';
tb.querySelectorAll('thead th').forEach(function(o){o.removeAttribute('aria-sort')});th.setAttribute('aria-sort',desc?'descending':'ascending');
var body=tb.tBodies[0],rows=Array.prototype.slice.call(body.rows);rows.sort(function(a,b){var x=key(a.cells[i]),y=key(b.cells[i]);
var r=x[0]-y[0]||(x[0]?(x[2]<y[2]?-1:x[2]>y[2]?1:0):x[1]-y[1]||(x[2]<y[2]?-1:x[2]>y[2]?1:0));return desc?-r:r});rows.forEach(function(r){body.appendChild(r)})}
th.addEventListener('click',go);th.addEventListener('keydown',function(e){if(e.key==='Enter'||e.key===' '){e.preventDefault();go()}})})});
document.querySelectorAll('input[data-filter]').forEach(function(inp){inp.addEventListener('input',function(){var q=inp.value.toLowerCase();
var box=document.getElementById(inp.getAttribute('data-filter'));if(!box)return;box.querySelectorAll('tbody tr').forEach(function(r){r.hidden=q&&r.textContent.toLowerCase().indexOf(q)<0})})});
})();
"""
