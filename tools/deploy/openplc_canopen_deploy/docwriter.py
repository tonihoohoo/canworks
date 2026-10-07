"""Writes the network documentation model (docexport.build) as one HTML file
(canopen-network-docs spec): inline styles, script and diagrams, every table
rendered here so the page reads without script, a print layout, light and
dark themes, and the model itself as JSON in the page."""

import html
import json

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


# -- sections ------------------------------------------------------------------

def _summary(model):
    tiles = []
    for net in model["networks"]:
        load = net["bus_load"]
        pdos = sum(len(n["pdos"]) for n in net["nodes"])
        tiles.append(
            '<a class="tile" href="#%s"><span class="tile-title">%s</span>'
            '<span class="tile-sub">%s · %s</span>'
            '<span class="stats"><span><b>%d</b> nodes</span><span><b>%d</b> PDOs</span></span>'
            '<span class="loadrow"><span>Cyclic load</span><b>%s</b>%s</span>'
            '<span class="loadrow"><span>Worst case</span><b>%s</b>%s</span></a>' % (
                _attr(net["anchor"]), E(net["name"] or "Network"), E(net["interface"]),
                E("%d kbit/s" % (net["bitrate"] // 1000) if net["bitrate"] else "bitrate not set"),
                len(net["nodes"]), pdos, _pct(load["cyclic"]), _meter(load["cyclic"]), _pct(load["worst"]),
                _meter(load["worst"])))
    warns = "".join("<li>%s</li>" % E(w) for w in model["warnings"])
    checks = ('<ul class="warnings">%s</ul>' % warns) if warns else '<p class="ok-text">No warnings.</p>'
    return ('<section id="summary"><h2>Summary</h2><div class="tiles">%s</div>'
            '<h3>Checks</h3>%s</section>' % ("".join(tiles), checks))


def _topology(net):
    nodes = net["nodes"]
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
            s.append('<a href="%s"><g class="box%s"><title>%s</title>'
                     '<rect x="%d" y="%d" width="%d" height="58" rx="8"/>'
                     '<text x="%d" y="%d" class="t">%s</text><text x="%d" y="%d" class="s">%s</text></g></a>' % (
                         _attr(href), " master" if is_master else "", E("%s (%s)" % (title, sub)), x, y, bw,
                         x + bw // 2, y + 25, E(label), x + bw // 2, y + 45, E(sub)))
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
    return ('<figure class="topology">%s<figcaption>Master and nodes on the bus line, terminated at both ends. '
            'Select a device to open its section.</figcaption></figure>' % "".join(s))


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
    return ('<div class="bytebar" role="img" aria-label="%s">%s</div><div class="byteticks" style="--n:%d">%s</div>'
            % (_attr("Layout of %s %d, %d bytes" % (p["kind"], p["number"], p["dlc"])), "".join(segs),
               p["dlc"] or 1, ticks))


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
    chips.append('<span class="chip">%s</span>' % (
        "Device mapping kept" if p["mapping"] == "device" else "Mapping written by the master"))
    if p.get("trigger"):
        chips.append('<span class="chip">%s</span>' % E(p["trigger"]))
    rows = []
    for e in p["entries"]:
        if e["dummy"]:
            what = '<span class="muted">dummy (gap)</span>'
        elif not e["used"]:
            what = '<span class="muted">%s</span>' % E(
                "not used by the PLC" + ("" if p["kind"] == "TPDO" else ", sent as 0"))
        else:
            what = _loc(e["location"], e["variables"])
        rows.append([str(e["bit"]), str(e["length"]), "<code>%s:%d</code>" % (hx(e["index"]), e["subindex"]),
                     E(e["name"]), E(e["type"]), what])
    direction = "node → master" if p["kind"] == "TPDO" else "master → node"
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


def _node(node):
    eds = node["eds"]
    product = " ".join(x for x in (eds["vendor_name"], eds["product_name"]) if x)
    head = ('<section class="node" id="%s"><header class="node-head"><h4>Node %d%s</h4><p>%s</p></header>' % (
        _attr(node["anchor"]), node["node_id"], (" · " + E(node["name"])) if node["name"] else "",
        E(product) or '<span class="muted">no product name in the EDS</span>'))
    eds_line = ('<p class="small">EDS <code>%s</code> · SHA-256 <code class="hash">%s</code>%s%s</p>' % (
        E(eds["file"]), E(eds["sha256"]), " · LSS supported" if eds["lss_supported"] else "",
        (' · <a download="%s" href="data:application/octet-stream;base64,%s">Save EDS file</a>' % (
            _attr(eds["file"].rsplit("/", 1)[-1]), eds["data"])) if eds.get("data") else ""))
    parts = [head, eds_line, '<div class="cols"><div>', _identity(node), '</div><div>', _kv(node["settings"]),
             '</div></div>']
    if node["locations"]:
        parts.append("<h5>Status and control in the PLC</h5>")
        parts.append(_table(["PLC", "Holds"], [[_loc(l["location"], l["variables"]), E(l["what"])]
                                               for l in node["locations"]]))
    parts.append("<h5>PDOs</h5>")
    parts.append("".join(_pdo(p) for p in node["pdos"]) or '<p class="muted">No PDOs: every PDO of the node is '
                                                            'switched off.</p>')
    if node["boot"]:
        b = node["boot"]
        parts.append('<h5>Boot configuration <span class="muted">%d SDO writes, in order</span></h5>' %
                     len(b["writes"]))
        if b["before"]:
            parts.append('<p class="small">Before the writes: %s.</p>' % E("; ".join(b["before"])))
        rows = [[str(i + 1), "<code>%s:%d</code>" % (hx(w["index"]), w["subindex"]), E(w["name"]),
                 "<code>%s</code>" % E(w["value"]), E(w["meaning"]), E(w["access"]),
                 "<code>%s</code>" % E(w["eds_default"]) if w["eds_default"] else "", E(w["source"])]
                for i, w in enumerate(b["writes"])]
        parts.append(_table(["#", "Object", "Name", "Value", "Meaning", "Access", "EDS default", "From"], rows,
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


def _network(net):
    parts = ['<section class="network" id="%s"><h2>%s</h2>' % (_attr(net["anchor"]), E(
        "Network " + net["name"] if net["name"] else "Network"))]
    parts.append(_topology(net))
    parts.append('<h3 id="%s-settings">Master and bus settings</h3>' % _attr(net["anchor"]))
    parts.append(_kv(net["settings"]))
    if net["locations"]:
        parts.append("<h4>Master status in the PLC</h4>")
        parts.append(_table(["PLC", "Holds"], [[_loc(l["location"], l["variables"]), E(l["what"])]
                                               for l in net["locations"]]))
    parts.append(_frames(net))
    parts.append(_bus_load(net))
    parts.append('<h3>Nodes%s</h3>' % (" of network " + E(net["name"]) if net["name"] else ""))
    parts.append("".join(_node(n) for n in sorted(net["nodes"], key=lambda n: n["node_id"])) or
                 '<p class="muted">No nodes configured.</p>')
    parts.append("</section>")
    return "".join(parts)


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
        sub = "".join('<li><a href="#%s">%s</a></li>' % (_attr(n["anchor"]), E(
            "Node %d · %s" % (n["node_id"], n["name"]) if n["name"] else "Node %d" % n["node_id"]))
            for n in sorted(net["nodes"], key=lambda n: n["node_id"]))
        items.append('<li><a href="#%s">%s</a><ul>%s</ul></li>' % (
            _attr(net["anchor"]), E("Network " + net["name"] if net["name"] else "Network"), sub))
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
    body = [_summary(model)] + [_network(n) for n in model["networks"]] + [_io(model), _appendix(model)]
    return ("<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            "<meta name=\"generator\" content=\"%s %s\"><title>%s</title><style>%s</style></head>"
            "<body><div class=\"layout\">%s<main>%s%s<footer class=\"foot\">%s · %s · generated %s</footer></main>"
            "</div><script type=\"application/json\" id=\"canopen-doc\">%s</script><script>%s</script></body></html>\n"
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
function store(v){try{if(v)localStorage.setItem('canopen-doc-theme',v);return localStorage.getItem('canopen-doc-theme')}catch(e){return null}}
var saved=store();if(saved)root.setAttribute('data-theme',saved);
var t=document.querySelector('[data-theme-toggle]');
if(t)t.addEventListener('click',function(){var dark=root.getAttribute('data-theme')?root.getAttribute('data-theme')==='dark':matchMedia('(prefers-color-scheme: dark)').matches;
var v=dark?'light':'dark';root.setAttribute('data-theme',v);store(v)});
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
