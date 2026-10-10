// PDO links page (canopen-pdo-links, canopen-configurator "Links table"): one
// node's TPDO received directly by other nodes' RPDOs, the master configuring
// both ends at boot. The checks are the plugin's, from /api/check; this page
// builds the links, shows both layouts side by side and edits the consumers'
// heartbeat watch. Loaded after app.js, whose helpers it uses.
"use strict";

// Dummy entries by data type (CiA 301: the index is the type's code).
const LINK_DUMMY = { BOOLEAN: 1, INTEGER8: 2, INTEGER16: 3, INTEGER32: 4, UNSIGNED8: 5, UNSIGNED16: 6, UNSIGNED32: 7 };
const LINK_DUMMY_BY_BITS = { 1: "BOOLEAN", 8: "UNSIGNED8", 16: "UNSIGNED16", 32: "UNSIGNED32" };

function linksNetwork(net) { return !!net && !isSlave(net) && !isJ1939(net) && !isPlain(net); }
function linkList() { return (S.config && S.config.links) || []; }
function linkName(l, i) { return l.name ? `link ${l.name}` : `link ${i + 1}`; }
function linkNode(id) { return (S.config.nodes || []).find((n) => num(n.node_id) === num(id)) || null; }
function nodeIndexOf(id) { return (S.config.nodes || []).findIndex((n) => num(n.node_id) === num(id)); }
function typeBits(t) { return (S.state.type_bits || {})[t] || 0; }
function nodeText(n) { return n ? `node ${n.node_id ?? "?"}${n.name ? " " + n.name : ""}` : "?"; }

// The TPDOs of a node as the config numbers them: [{ number, pdo, j }].
function nodeTpdos(n) { return (n.tx_pdos || []).map((p, j) => ({ number: num(p.number) || j + 1, pdo: p, j })); }

// The producer layout: [{ index, subindex, bits, type }] in frame order,
// the TPDO's entries or the device mapping of a device-mapped TPDO.
function producerLayout(l) {
  const n = linkNode((l.from || {}).node);
  if (!n) return [];
  const t = nodeTpdos(n).find((x) => x.number === num((l.from || {}).tpdo));
  if (!t) return [];
  const m = pdoMap(edsFor(n), "input", t.number);
  if (usesDeviceMapping(t.pdo, m)) {
    return m && m.has_default ? m.defaults.map((d) => {
      const o = objectInfo(edsFor(n), d.index, d.subindex);
      return { index: d.index, subindex: d.subindex, bits: d.bits, type: o ? o.type : "" };
    }) : [];
  }
  return (t.pdo.entries || []).map((e) => ({ index: e.index, subindex: num(e.subindex || 0), bits: typeBits(e.type), type: e.type }));
}

// The consumer's mapping object, and whether it keeps the device mapping.
function consumerMap(c) {
  const n = linkNode(c.node);
  const m = n ? pdoMap(edsFor(n), "output", num(c.rpdo)) : null;
  return { m, device: c.mapping === "device" || (c.mapping === undefined && !!m && !m.writable) };
}

function consumerLayout(c) {
  const { m, device } = consumerMap(c);
  if (device) return m && m.has_default ? m.defaults.map((d) => ({ index: d.index, subindex: d.subindex, bits: d.bits })) : [];
  return (c.entries || []).map((e) => ({ index: e.index, subindex: num(e.subindex || 0), bits: typeBits(e.type), type: e.type }));
}

// The producer's COB-ID as the plugin resolves it.
function linkCobId(l) {
  const n = linkNode((l.from || {}).node);
  if (!n) return null;
  const t = nodeTpdos(n).find((x) => x.number === num((l.from || {}).tpdo));
  if (!t) return null;
  if (t.pdo.cob_id === "auto") {
    const c = autoCobIds()[`nodes[${nodeIndexOf(n.node_id)}].tx_pdos[${t.j}]`];
    return c === undefined ? null : c;
  }
  if (t.pdo.cob_id !== undefined) return num(t.pdo.cob_id);
  return t.number <= 4 && num(n.node_id) >= 1 ? 0x80 + 0x100 * t.number + num(n.node_id) : null;
}

// RPDO numbers a consumer node may use: in its EDS, not in its rx_pdos, not
// in another link (the current one stays).
function freeRpdos(node, keep) {
  const count = (edsFor(node) || { pdo_count: {} }).pdo_count.output || 0;
  const used = new Set((node.rx_pdos || []).map((p, j) => num(p.number) || j + 1));
  for (const l of linkList()) for (const c of l.to || []) if (num(c.node) === num(node.node_id) && num(c.rpdo) !== keep) used.add(num(c.rpdo));
  const out = [];
  for (let k = 1; k <= count; k++) if (!used.has(k) || k === keep) out.push(k);
  return out;
}

// Objects of a consumer it can receive in an RPDO, of a given size.
function receivable(node, bits) {
  const eds = edsFor(node);
  if (!eds || !eds.objects) return [];
  return eds.objects.filter((o) => (o.directions || []).includes("output") && typeBits(o.type) === bits);
}

// The dummy entry for a producer position on this consumer, or null when its
// EDS allows none of that size.
function dummyFor(node, pos) {
  const allowed = new Set(((edsFor(node) || {}).dummy) || []);
  for (const t of [pos.type, LINK_DUMMY_BY_BITS[pos.bits]]) if (t && LINK_DUMMY[t] && allowed.has(LINK_DUMMY[t]) && typeBits(t) === pos.bits) return { index: hex4(LINK_DUMMY[t]), subindex: 0, type: t };
  return null;
}

// The consumer's entries filled from the producer layout: per position the
// first receivable object of that size not used yet, else a dummy.
function fillEntries(node, layout) {
  const taken = new Set();
  return layout.map((pos) => {
    const o = receivable(node, pos.bits).find((x) => !taken.has(`${x.index}:${x.subindex}`));
    if (o) { taken.add(`${o.index}:${o.subindex}`); return { index: o.index, subindex: o.subindex, type: o.type }; }
    return dummyFor(node, pos) || { index: "0x0005", subindex: 0, type: "UNSIGNED8" };
  });
}

function hasHeartbeat(n) { return !!n && (num(n.heartbeat_ms) > 0 || (n.heartbeat_ms === undefined && n.guard_time_ms === undefined && edsDefault(edsFor(n), 0x1017, 0) > 0)); }

function watches(node, id) { return (node.heartbeat_watch || []).some((h) => num(h.node) === num(id)); }

function setWatch(node, id, on) {
  const list = (node.heartbeat_watch || []).filter((h) => num(h.node) !== num(id));
  if (on) list.push({ node: num(id) });
  if (list.length) node.heartbeat_watch = list; else delete node.heartbeat_watch;
}

function addLink() {
  const prod = (S.config.nodes || []).find((n) => (n.tx_pdos || []).length);
  if (!prod) { banner("Give a node a TPDO first: a link starts from one of its tx_pdos.", true); return; }
  const used = new Set(linkList().map((l) => `${num((l.from || {}).node)}/${num((l.from || {}).tpdo)}`));
  const t = nodeTpdos(prod).find((x) => !used.has(`${num(prod.node_id)}/${x.number}`)) || nodeTpdos(prod)[0];
  S.config.links = linkList().concat([{ from: { node: num(prod.node_id), tpdo: t.number }, to: [] }]);
  changed(true);
}

async function removeLink(i) {
  const v = await modal(`Remove ${linkName(linkList()[i], i)}? Its consumers' RPDOs are no longer configured.`,
    [["cancel", "Keep the link"], ["remove", "Remove link", { danger: true }]]);
  if (v !== "remove") return;
  S.config.links.splice(i, 1);
  if (!S.config.links.length) delete S.config.links;
  changed(true);
  removedBanner("the link");
}

function addConsumer(i, id) {
  const l = linkList()[i];
  const node = linkNode(id);
  const rpdo = freeRpdos(node)[0];
  if (!rpdo) { banner(`${nodeText(node)} has no free RPDO in its EDS.`, true); return; }
  const c = { node: num(id), rpdo };
  const { device } = consumerMap(c);
  if (device) c.mapping = "device"; else c.entries = fillEntries(node, producerLayout(l));
  l.to = (l.to || []).concat([c]);
  // "watch producer", ticked by default when the producer has a heartbeat.
  if (hasHeartbeat(linkNode(l.from.node)) && !watches(node, l.from.node)) setWatch(node, l.from.node, true);
  changed(true);
}

function removeConsumer(i, k) {
  const l = linkList()[i];
  const [c] = l.to.splice(k, 1);
  const node = linkNode(c.node);
  if (node && !linkList().some((x) => num((x.from || {}).node) === num(l.from.node) && (x.to || []).some((y) => num(y.node) === num(c.node))))
    setWatch(node, l.from.node, false);
  changed(true);
}

// Before a TPDO goes: the links it feeds go too, when the user says so
// (default: keep both). False when the user cancelled.
async function dropLinksOf(n, number) {
  const feeds = linkList().map((l, i) => [l, i]).filter(([l]) => num((l.from || {}).node) === num(n.node_id) && num((l.from || {}).tpdo) === number);
  if (!feeds.length) return true;
  const v = await modal(`TPDO ${number} of ${nodeText(n)} feeds ${feeds.map(([l, i]) => linkName(l, i)).join(", ")}. Remove the link too?`,
    [["cancel", "Cancel"], ["remove", "Remove TPDO and link", { danger: true }]]);
  if (v !== "remove") return false;
  for (const [, i] of feeds.reverse()) S.config.links.splice(i, 1);
  if (!S.config.links.length) delete S.config.links;
  return true;
}

// The node page: which link a TPDO feeds (its entries need no PLC address).
function linkTag(n, number) {
  const names = linkList().map((l, i) => [l, i]).filter(([l]) => num((l.from || {}).node) === num(n.node_id) && num((l.from || {}).tpdo) === number)
    .map(([l, i]) => linkName(l, i));
  if (!names.length) return null;
  return el("button", { type: "button", class: "small tag", dataset: { linkTag: String(number) }, title: "Its entries may leave the PLC location empty: the consumers get the value anyway.",
    onclick: () => showView("links") }, `feeds ${names.join(", ")}`);
}

// The node page's heartbeat watch list (canopen-configurator "Heartbeat watch setting").
function heartbeatWatchFields(i) {
  const n = S.config.nodes[i];
  const base = `nodes[${i}].heartbeat_watch`;
  const others = (S.config.nodes || []).filter((x) => x !== n);
  const rows = (n.heartbeat_watch || []).map((h, k) => {
    const hp = `${base}[${k}]`;
    const target = linkNode(h.node);
    const period = target ? (num(target.heartbeat_ms) > 0 ? num(target.heartbeat_ms) : edsDefault(edsFor(target), 0x1017, 0)) : null;
    const timeout = target && num(target.heartbeat_timeout_ms) > 0 ? num(target.heartbeat_timeout_ms) : period > 0 ? Math.min(3 * period, 65535) : null;
    const sel = el("select", { dataset: { path: hp + ".node" }, "aria-label": "Watched node" },
      others.map((x) => el("option", { value: String(x.node_id) }, nodeText(x))));
    sel.value = String(h.node);
    sel.addEventListener("change", () => { setPath(hp + ".node", Number(sel.value)); render(); });
    const t = el("input", { type: "text", dataset: { path: hp + ".timeout_ms" }, "aria-label": "Watch timeout (ms)",
      placeholder: timeout ? `default (${timeout} ms)` : "default" });
    t.value = h.timeout_ms === undefined ? "" : String(h.timeout_ms);
    t.addEventListener("input", () => { const v = t.value.trim(); setPath(hp + ".timeout_ms", v === "" ? undefined : /^[0-9]+$/.test(v) ? parseInt(v, 10) : v); });
    return el("li", { dataset: { path: hp } }, sel, " timeout ", t, " ms ",
      el("button", { type: "button", class: "small", "aria-label": `Stop watching node ${h.node}`,
        onclick: () => { n.heartbeat_watch.splice(k, 1); if (!n.heartbeat_watch.length) delete n.heartbeat_watch; changed(true); } }, "✕"),
      el("span", { class: "field-msg", dataset: { for: hp } }), el("span", { class: "field-msg", dataset: { for: hp + ".node" } }),
      el("span", { class: "field-msg", dataset: { for: hp + ".timeout_ms" } }));
  });
  const free = others.filter((x) => !watches(n, x.node_id));
  const add = el("select", { "aria-label": "Watch another node's heartbeat" }, el("option", { value: "" }, "Watch a node…"),
    free.map((x) => el("option", { value: String(x.node_id) }, nodeText(x))));
  add.addEventListener("change", () => { if (add.value) { setWatch(n, add.value, true); changed(true); } });
  return el("div", { class: "wide heartbeat-watch", dataset: { path: base } },
    el("span", { class: "row-head" }, "Heartbeat watch"),
    hint("Nodes whose heartbeat this node watches itself (its 0x1016): it reacts per its error behaviour (0x1029), usually with EMCY 0x8130, without the master. Empty timeout: the watched node's heartbeat timeout."),
    el("ul", { class: "plain" }, rows), free.length ? add : null,
    el("span", { class: "field-msg", dataset: { for: base } }));
}

// A layout as a row of position cells (each as wide as its bits).
function layoutGrid(layout, other, label, path) {
  return el("div", { class: "link-grid", "aria-label": label },
    el("span", { class: "row-head" }, label),
    layout.map((p, k) => {
      const o = other[k];
      const bad = !o || o.bits !== p.bits;
      return el("span", { class: "link-pos" + (bad ? " bad" : "") + (num(p.index) < 8 ? " dummy" : ""),
        style: `flex:${Math.max(p.bits, 4)}`, dataset: path ? { path: `${path}[${k}]`, linkPos: String(k) } : { linkPos: String(k) },
        title: `position ${k + 1}: ${p.index}:${p.subindex} (${p.bits} bit)${bad ? (o ? `, the other side has ${o.bits} bit` : ", nothing on the other side") : ""}` },
      `${num(p.index) < 8 ? "dummy" : p.index + ":" + p.subindex} · ${p.bits}`);
    }));
}

function consumerBox(i, k, l, prod) {
  const c = l.to[k];
  const cp = `links[${i}].to[${k}]`;
  const node = linkNode(c.node);
  const { m, device } = consumerMap(c);
  const cons = consumerLayout(c);
  const nodeSel = el("select", { dataset: { path: cp + ".node" }, "aria-label": "Consumer node" },
    (S.config.nodes || []).filter((x) => num(x.node_id) !== num(l.from.node)).map((x) => el("option", { value: String(x.node_id) }, nodeText(x))));
  nodeSel.value = String(c.node);
  nodeSel.addEventListener("change", () => {
    const nn = linkNode(nodeSel.value);
    c.node = Number(nodeSel.value);
    c.rpdo = freeRpdos(nn)[0] || 1;
    delete c.mapping;
    const map = consumerMap(c);
    if (map.device) { c.mapping = "device"; delete c.entries; } else c.entries = fillEntries(nn, prod);
    changed(true);
  });
  const rpdos = node ? freeRpdos(node, num(c.rpdo)) : [];
  const rpdoSel = el("select", { dataset: { path: cp + ".rpdo" }, "aria-label": "Consumer RPDO" },
    (rpdos.includes(num(c.rpdo)) ? rpdos : rpdos.concat([num(c.rpdo)])).map((r) => el("option", { value: String(r) }, `RPDO ${r}`)));
  rpdoSel.value = String(c.rpdo);
  rpdoSel.addEventListener("change", () => { setPath(cp + ".rpdo", Number(rpdoSel.value)); render(); });
  const parts = [el("div", { class: "pdo-grid" },
    el("label", null, "Node", nodeSel, el("span", { class: "field-msg", dataset: { for: cp + ".node" } })),
    el("label", null, "RPDO", rpdoSel, hint("RPDOs of its EDS that are not in its rx_pdos or another link."),
      el("span", { class: "field-msg", dataset: { for: cp + ".rpdo" } })),
    pdoField("Transmission", cp + ".transmission", "EDS value", "255 or 254: applied on arrival; 0-240: at the next SYNC."),
    pdoField("Deadline (ms)", cp + ".event_timer_ms", "EDS value", "Sub-index 5: the consumer reacts when no PDO came for this long."))];
  if (device) {
    parts.push(el("div", { class: "fixed-field" }, el("output", { dataset: { linkMapping: cp } }, m && !m.writable ? "Mapping fixed by the device" : "Device mapping"),
      hint("The consumer keeps its EDS default mapping; it must match the producer position by position.")));
  } else if (node) {
    const rows = prod.map((pos, e) => {
      const ep = `${cp}.entries[${e}]`;
      const cur = (c.entries || [])[e];
      const opts = receivable(node, pos.bits).map((o) => [`${o.index}:${o.subindex}`, `${o.index}:${o.subindex} ${o.name} (${o.type})`, o]);
      const dummy = dummyFor(node, pos);
      if (dummy) opts.push([`${dummy.index}:0`, `dummy (skip, ${dummy.type})`, dummy]);
      if (cur && !opts.some(([key]) => key === `${cur.index}:${num(cur.subindex || 0)}`))
        opts.push([`${cur.index}:${num(cur.subindex || 0)}`, `${cur.index}:${cur.subindex ?? 0} (${cur.type}, ${typeBits(cur.type)} bit)`, cur]);
      const sel = el("select", { dataset: { path: ep }, "aria-label": `Consumer object for position ${e + 1}` },
        el("option", { value: "" }, "—"), opts.map(([key, text]) => el("option", { value: key }, text)));
      sel.value = cur ? `${cur.index}:${num(cur.subindex || 0)}` : "";
      sel.addEventListener("change", () => {
        const hit = opts.find(([key]) => key === sel.value);
        c.entries = c.entries || [];
        if (hit) c.entries[e] = { index: hit[2].index, subindex: num(hit[2].subindex || 0), type: hit[2].type };
        changed(true);
      });
      const size = cur ? typeBits(cur.type) : 0;
      return el("tr", { class: size && size !== pos.bits ? "bad" : null },
        el("td", null, String(e + 1)), el("td", null, `${pos.index}:${pos.subindex} ${pos.type || ""} (${pos.bits} bit)`),
        el("td", null, sel, el("span", { class: "field-msg", dataset: { for: ep } }), el("span", { class: "field-msg", dataset: { for: ep + ".type" } })));
    });
    // Positions the consumer maps beyond the producer's.
    for (let e = prod.length; e < (c.entries || []).length; e++) {
      const x = c.entries[e];
      rows.push(el("tr", { class: "bad" }, el("td", null, String(e + 1)), el("td", null, "—"),
        el("td", null, `${x.index}:${x.subindex ?? 0} (${x.type}) `, el("button", { type: "button", class: "small",
          onclick: () => { c.entries.splice(e, 1); changed(true); } }, "✕"))));
    }
    parts.push(el("table", { class: "link-entries" }, el("thead", null, el("tr", null, thCells(["Position", "Producer object", "Consumer object"]))),
      el("tbody", null, rows)));
  }
  parts.push(layoutGrid(cons, prod, "Consumer layout", device ? null : cp + ".entries"));
  const prodNode = linkNode(l.from.node);
  const watch = el("input", { type: "checkbox", dataset: { linkWatch: cp } });
  watch.checked = !!node && watches(node, l.from.node);
  watch.addEventListener("change", () => { setWatch(node, l.from.node, watch.checked); changed(true); });
  parts.push(el("div", { class: "check-field" }, el("label", { class: "check" }, watch, ` watch producer (${nodeText(prodNode)}) heartbeat`),
    hint("Adds the producer to this node's heartbeat watch (0x1016): the consumer itself notices when the producer is gone.")));
  parts.push(el("span", { class: "field-msg", dataset: { for: cp } }), el("span", { class: "field-msg", dataset: { for: cp + ".entries" } }));
  return el("div", { class: "pdo link-consumer", dataset: { path: cp } },
    el("div", { class: "pdo-title" }, el("strong", null, `${nodeText(node)} RPDO ${c.rpdo}`), linkLiveCell(c.node),
      el("button", { type: "button", class: "small", "aria-label": `Remove consumer ${nodeText(node)}`, onclick: () => removeConsumer(i, k) }, "Remove consumer")),
    ...parts);
}

// The NMT state of a node from the Online view's last status, when there is one.
function linkLiveState(id) {
  const st = S.onlineLast && S.onlineLast.status;
  if (!st || !Array.isArray(st.nodes)) return null;
  const n = st.nodes.find((x) => x.node_id === num(id));
  return n ? n.state : 0;
}

function linkLiveCell(id) {
  const s = linkLiveState(id);
  if (s === null) return null;
  return el("span", { class: "tag " + (s === 5 ? "ok" : "bad"), dataset: { linkState: String(id) } }, s ? stateName(s) : "no contact");
}

function linkBox(l, i) {
  const lp = `links[${i}]`;
  const prodNode = linkNode((l.from || {}).node);
  const prodSel = el("select", { dataset: { path: lp + ".from.node" }, "aria-label": "Producer node" },
    (S.config.nodes || []).filter((n) => (n.tx_pdos || []).length).map((n) => el("option", { value: String(n.node_id) }, nodeText(n))));
  prodSel.value = String((l.from || {}).node);
  prodSel.addEventListener("change", () => {
    const n = linkNode(prodSel.value);
    l.from = { node: Number(prodSel.value), tpdo: nodeTpdos(n)[0].number };
    l.to = (l.to || []).filter((c) => num(c.node) !== num(prodSel.value));
    changed(true);
  });
  const tpdoSel = el("select", { dataset: { path: lp + ".from.tpdo" }, "aria-label": "Producer TPDO" },
    (prodNode ? nodeTpdos(prodNode) : []).map((t) => el("option", { value: String(t.number) }, `TPDO ${t.number}`)));
  tpdoSel.value = String((l.from || {}).tpdo);
  tpdoSel.addEventListener("change", () => { setPath(lp + ".from.tpdo", Number(tpdoSel.value)); render(); });
  const cob = linkCobId(l);
  const prod = producerLayout(l);
  const consumers = (l.to || []).map((c, k) => consumerBox(i, k, l, prod));
  const candidates = (S.config.nodes || []).filter((n) => num(n.node_id) !== num((l.from || {}).node) && freeRpdos(n).length);
  const add = el("select", { "aria-label": "Add a consumer", dataset: { linkAdd: String(i) } }, el("option", { value: "" }, "Add consumer…"),
    candidates.map((n) => el("option", { value: String(n.node_id) }, nodeText(n))));
  add.addEventListener("change", () => { if (add.value) addConsumer(i, add.value); });
  const down = [l.from && l.from.node].concat((l.to || []).map((c) => c.node)).filter((id) => { const s = linkLiveState(id); return s !== null && s !== 5; });
  return el("fieldset", { class: "link" + (down.length ? " link-down" : ""), dataset: { path: lp, link: String(i) } },
    el("legend", null, linkName(l, i)),
    el("div", { class: "pdo-grid" },
      field("Name", lp + ".name", "text", { placeholder: `link ${i + 1}` }),
      el("label", null, "Producer", prodSel, el("span", { class: "field-msg", dataset: { for: lp + ".from.node" } })),
      el("label", null, "TPDO", tpdoSel, el("span", { class: "field-msg", dataset: { for: lp + ".from.tpdo" } })),
      el("label", null, "COB-ID", el("output", { dataset: { linkCob: String(i) } }, cob === null ? "?" : "0x" + cob.toString(16).toUpperCase()),
        hint("The producer TPDO's; set it on the producer.")),
      choice("On PLC stop", lp + ".on_plc_stop", [
        { value: undefined, label: "Follow the master", help: "The link's nodes get the master's on_plc_stop command like every node." },
        { value: "keep", label: "Keep running", help: "The master sends the link's nodes no NMT command on PLC stop, so the link runs on (event-driven types only: SYNC stops)." },
      ])),
    el("div", { class: "pdo-row" }, el("span", { class: "row-head" }, "Producer"), linkLiveCell((l.from || {}).node),
      el("span", { class: "muted" }, prodNode ? `${nodeText(prodNode)} TPDO ${(l.from || {}).tpdo}: ${prod.length} position${prod.length === 1 ? "" : "s"}, ${prod.reduce((s, p) => s + p.bits, 0)} bit` : "")),
    layoutGrid(prod, prod, "Producer layout", null),
    el("span", { class: "field-msg", dataset: { for: lp } }), el("span", { class: "field-msg", dataset: { for: lp + ".from" } }),
    el("span", { class: "field-msg", dataset: { for: lp + ".on_plc_stop" } }),
    ...consumers,
    el("div", { class: "toolbar" }, candidates.length ? add : el("span", { class: "muted" }, "No other node has a free RPDO."),
      el("button", { type: "button", class: "small danger", dataset: { linkRemove: String(i) }, onclick: () => removeLink(i) }, "Remove link")));
}

function renderLinks(view) {
  view.append(el("h2", null, "PDO links"),
    el("p", { class: "muted" }, "A link sends one node's TPDO straight to RPDOs of other nodes (CiA 301 producer/consumer): " +
      "the data no longer passes through the PLC scan, and with \"Keep running\" it moves on while the PLC is stopped. " +
      "The master configures both ends at boot and keeps receiving the TPDO, so the PLC can still read it. See docs/config.md, PDO links."));
  if (S.onlineLast && S.onlineLast.status) view.append(el("p", { class: "muted small" }, "States from the Online view's last status."));
  view.append(...linkList().map((l, i) => linkBox(l, i)));
  if (!linkList().length) view.append(el("p", { class: "muted" }, "No links yet."));
  view.append(el("button", { type: "button", dataset: { linkNew: "1" }, onclick: addLink }, "Add link"));
}

// Where a check path in links[] is, for the Problems pane: ["PDO links", "link x", "node 20 RPDO 2"].
function linkPlace(net, path) {
  const m = /^links\[(\d+)\](?:\.to\[(\d+)\])?/.exec(path);
  const l = m && (net.links || [])[Number(m[1])];
  if (!l) return ["PDO links"];
  const parts = ["PDO links", linkName(l, Number(m[1]))];
  const c = m[2] !== undefined ? (l.to || [])[Number(m[2])] : null;
  if (c) parts.push(`node ${c.node} RPDO ${c.rpdo}`);
  return parts;
}

// The Online view's links table (canopen-configurator "Links in the online view").
function linksLive(st) {
  const links = (onlineConfig().links || []);
  if (!links.length) return el("div");
  const state = (id) => { const n = (st.nodes || []).find((x) => x.node_id === num(id)); return n ? n.state : 0; };
  const cell = (id) => { const s = state(id); return el("td", { class: "state-" + s, dataset: { linkLive: String(id) } }, `${id}: ${s ? stateName(s) : "no contact"}`); };
  const rows = links.map((l, i) => {
    const ids = [l.from && l.from.node].concat((l.to || []).map((c) => c.node));
    const down = ids.some((id) => state(id) !== 5);
    const prod = (st.nodes || []).find((x) => x.node_id === num(l.from && l.from.node));
    const t = prod && (prod.pdo_timeouts || []).find((x) => x.tpdo === num(l.from.tpdo));
    return el("tr", { class: down ? "bad" : null, dataset: { linkRow: String(i) } },
      el("td", null, linkName(l, i) + (down ? " (not running)" : "")), cell(l.from && l.from.node),
      el("td", null, (l.to || []).map((c) => { const s = state(c.node); return el("div", { class: "state-" + s, dataset: { linkLive: String(c.node) } }, `${c.node} RPDO ${c.rpdo}: ${s ? stateName(s) : "no contact"}`); })),
      el("td", null, t ? (t.timed_out ? `timed out (${t.count})` : "receiving") : ""));
  });
  return el("table", { class: "online-links" }, el("caption", null, "PDO links"),
    el("thead", null, el("tr", null, thCells(["Link", "Producer", "Consumers", "Producer TPDO timeout"]))), el("tbody", null, rows));
}
