"use strict";
// Frame explanations (add-frame-inspector): the inspector panel with its four
// layers (meaning, identifier, data bits, wire), the Trace view's Sequences
// tab and the Frame lab view. The explanation model comes from the server
// (bustrace/explain.py); this file only draws it.

const FX_COLORS = 6;
const FX_WIRE_PART = { sof: "frame", id: "id", srr: "ctl", ide: "ctl", rtr: "ctl", r1: "ctl", r0: "ctl", dlc: "ctl",
  data: "data", crc: "crc", crcdel: "crc", ack: "ack", ackdel: "ack", eof: "frame", ifs: "frame", stuff: "stuff" };
const FX_LEGEND = [["frame", "Start and end"], ["id", "Identifier"], ["ctl", "Control"], ["data", "Data"], ["crc", "CRC"],
  ["ack", "Acknowledge"], ["stuff", "Stuff bit"]];
const FX_BITRATES = [10000, 20000, 50000, 125000, 250000, 500000, 800000, 1000000];
const FX_ARBITRATION = new Set(["sof", "id", "srr", "ide", "rtr", "stuff"]);
const FX_BUILD = [["sdo", "SDO read or write"], ["pdo", "PDO from values"], ["nmt", "NMT command"],
  ["heartbeat", "Heartbeat"], ["emcy", "EMCY"]];

// The page's choices for the Frame lab and the Sequences tab.
const FX = {
  lab: { frame: "", bitrate: "", what: "sdo", form: {}, built: null, examples: null, pdos: null, nodes: [],
    arbA: "185#", arbB: "183#", info: null, seq: 0 },
  seq: { sub: "sdo", node: "", result: "", picked: null, n: 0, at: null, data: null, seq: 0 },
};

function fxSvg(tag, attrs, text) {
  const e = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [k, v] of Object.entries(attrs || {})) if (v != null) e.setAttribute(k, v);
  if (text != null) e.textContent = text;
  return e;
}

// replaceChildren() without the nulls and nested lists el() also skips.
function fxFill(e, ...kids) {
  e.replaceChildren(...kids.flat(Infinity).filter((k) => k != null && k !== false));
}

// A style property set through the CSSOM: the page's CSP refuses style attributes.
function fxStyle(e, prop, value) {
  if (value != null) e.style.setProperty(prop, value);
  return e;
}

function fxColor(group) {
  return group === "unused" || group == null ? "var(--fx-unused)" : `var(--fx-g${group % FX_COLORS})`;
}

function fxUs(us) {
  if (us == null) return "";
  if (Math.abs(us) >= 10000) return (us / 1000).toFixed(1) + " ms";
  if (Math.abs(us) >= 1000) return (us / 1000).toFixed(2) + " ms";
  return Math.round(us) + " µs";
}

function fxRate(r) { return r >= 1000000 ? r / 1000000 + " Mbit/s" : r / 1000 + " kbit/s"; }

// ---------------------------------------------------------------------------
// The inspector panel

// The panel for an explanation `m`. opts.actions: extra buttons under the
// meaning (the Trace view's links to sequences).
function fxInspector(m, opts) {
  opts = opts || {};
  const I = { m, refs: new Map(), wireAt: new Map(), owner: [] };
  const bytes = m.frame.rtr || m.frame.err ? [] : (m.frame.data ? m.frame.data.split(" ").map((h) => parseInt(h, 16)) : []);
  I.bytes = bytes;
  const total = bytes.length * 8;
  I.owner = new Array(total).fill(-1);
  m.fields.forEach((f, k) => { for (let b = f.start; b < f.start + f.length && b < total; b++) if (I.owner[b] < 0) I.owner[b] = k; });
  if (m.wire) m.wire.bits.forEach((b) => { if (b.ref !== "stuff" && !I.wireAt.has(b.ref)) I.wireAt.set(b.ref, b.n); });

  const box = el("section", { class: "fx-box", "aria-live": "polite", "aria-label": "Selected field", dataset: { fx: "box" } });
  I.box = box;
  const main = el("div", { class: "fx-main" },
    fxMeaning(I, opts),
    m.identifier ? fxIdentifier(I) : null,
    fxData(I),
    m.wire ? fxWire(I) : el("section", { class: "fx-layer" }, el("h3", null, "On the wire"),
      el("p", { class: "muted" }, "An error frame is the CAN controller's report, not a frame on the bus: it has no wire layer.")));
  const root = el("div", { class: "fx", dataset: { fx: "inspector", kind: m.kind } }, main, box);
  I.root = root;
  fxOverview(I);
  return root;
}

function fxMeaning(I, opts) {
  const m = I.m;
  const f = m.frame;
  return el("section", { class: "fx-layer fx-meaning" },
    el("div", { class: "fx-title" }, el("strong", null, m.title || "Frame"),
      el("span", { class: "mono muted" }, f.candump + (f.time_us && opts.time ? "  ·  " + opts.time : ""))),
    el("p", { class: "fx-says", dataset: { fx: "meaning" } }, m.meaning),
    m.notes && m.notes.length ? el("ul", { class: "fx-notes" }, m.notes.map((n) => el("li", null, humanise(n)))) : null,
    m.about ? el("details", { class: "fx-about" }, el("summary", null, "About this kind of message"), el("p", null, m.about)) : null,
    opts.actions && opts.actions.length ? el("div", { class: "toolbar" }, opts.actions) : null);
}

// Arrow keys move the focus inside a group of bit buttons (one tab stop).
function fxRoving(container, selector, cols) {
  container.addEventListener("keydown", (e) => {
    const items = [...container.querySelectorAll(selector)];
    const k = items.indexOf(document.activeElement);
    if (k < 0) return;
    const step = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -(cols || 1), ArrowDown: cols || 1, Home: -k, End: items.length - 1 - k }[e.key];
    if (step === undefined) return;
    e.preventDefault();
    const next = items[Math.max(0, Math.min(items.length - 1, k + step))];
    for (const it of items) it.tabIndex = it === next ? 0 : -1;
    next.focus();
  });
}

function fxBitButton(I, ref, v, label, cls, color, explain, small) {
  const b = el("button", { type: "button", class: "fx-bit" + (v ? " on" : "") + (cls ? " " + cls : ""), tabindex: "-1",
    "aria-label": label, dataset: { ref } }, small != null ? el("small", null, String(small)) : null, String(v));
  if (color) b.style.setProperty("--c", color);
  b.addEventListener("mouseenter", explain);
  b.addEventListener("focus", explain);
  b.addEventListener("click", explain);
  return b;
}

// The parts of a J1939 identifier (j1939-trace): colour and caption.
const FX_J1939_COLOR = { priority: "id", reserved: "unused", dp: "unused", pf: "fc", ps: "g2", source: "node" };
const fxHex2 = (v) => "0x" + v.toString(16).toUpperCase().padStart(2, "0");

function fxJ1939Caption(j, p) {
  if (p === "priority") return `Priority ${j.priority}`;
  if (p === "reserved") return `R ${j.reserved}`;
  if (p === "dp") return `DP ${j.dp}`;
  if (p === "pf") return `PF ${fxHex2(j.pf)}`;
  if (p === "ps") return j.pdu1 ? (j.ps === 255 ? "Destination 255 (global)" : `Destination ${j.ps}`) : `Group extension ${fxHex2(j.ps)}`;
  return `Source ${fxHex2(j.source)}`;
}

function fxPartColor(id, p) {
  if (id.j1939) return `var(--fx-${FX_J1939_COLOR[p] || "id"})`;
  return `var(--fx-${p === "function" ? "fc" : p === "node" ? "node" : "id"})`;
}

function fxIdentifier(I) {
  const id = I.m.identifier;
  const parts = [];
  for (const b of id.bits) {
    const last = parts[parts.length - 1];
    if (last && last.part === b.part) last.bits.push(b); else parts.push({ part: b.part, bits: [b] });
  }
  const color = (p) => fxPartColor(id, p);
  const caption = (p) => id.j1939 ? fxJ1939Caption(id.j1939, p)
    : p === "function" ? `Function code ${id.function_code}` + (id.message ? ` = ${id.message}` : "")
    : p === "node" ? `Node ID ${id.node}` : `Identifier 0x${id.text_id}` + (id.message ? ` = ${id.message}` : "");
  const row = el("div", { class: "fx-idrow", dataset: { fx: "identifier" } }, parts.map((p) => el("div", { class: "fx-group" },
    el("div", { class: "fx-bits" }, p.bits.map((b) => fxBitButton(I, "id." + b.n, b.v, `Identifier bit ${b.n} = ${b.v}`, null,
      color(p.part), () => fxExplainId(I, b), b.n))),
    fxStyle(el("div", { class: "fx-cap" }, caption(p.part)), "color", color(p.part)))));
  const first = row.querySelector(".fx-bit");
  if (first) first.tabIndex = 0;
  fxRoving(row, ".fx-bit");
  const lines = [];
  if (id.j1939) {
    const j = id.j1939;
    lines.push(el("p", { dataset: { fx: "pgn" } }, el("strong", null, `PGN 0x${j.pgn.toString(16).toUpperCase().padStart(4, "0")} = ${j.pgn}`),
      id.message ? ` (${id.message})` : "", `, from ${id.sender}` + (j.pdu1 ? ` to ${j.destination_label}` : "") + "."));
    lines.push(el("p", { class: "muted" }, id.math + "."));
    return el("section", { class: "fx-layer" }, el("h3", null, "Identifier: who and what"),
      el("p", { class: "muted" }, "A 29-bit J1939 identifier: 3 priority bits, a reserved bit, the data page, the PDU format (PF), the PDU specific (PS: the destination address when PF is below 240, else a group extension) and the source address. Reserved bit, data page, PF and, from PF 240 up, PS make the PGN."),
      row, lines, el("p", { class: "muted fx-small" }, id.priority));
  }
  if (id.math) lines.push(id.math + (id.message ? `: ${id.message}, ${id.what}` : "") + (id.node_label ? ` of ${id.node_label}` : "") + ".");
  else if (id.configured_text) lines.push(id.configured_text);
  else if (id.what) lines.push(`0x${id.text_id}: ${id.what}.`);
  return el("section", { class: "fx-layer" }, el("h3", null, "Identifier: who and what"),
    el("p", { class: "muted" }, id.width === 11
      ? "The 11-bit identifier names the message and is its priority. CANopen splits it into a 4-bit function code (what kind of message) and a 7-bit node ID (which device)."
      : "A 29-bit extended identifier. CANopen uses 11-bit identifiers, so this frame belongs to another protocol."),
    row, lines.map((t) => el("p", null, t)), el("p", { class: "muted fx-small" }, id.priority));
}

function fxData(I) {
  const m = I.m;
  const sec = el("section", { class: "fx-layer" }, el("h3", null, "Data bits"));
  if (m.error_classes) {
    sec.append(el("p", null, "The identifier of an error frame holds the error classes:"),
      el("ul", { class: "fx-classes" }, m.error_classes.bits.map((b) => el("li", { class: b.set ? "set" : "muted" },
        `${b.set ? "■" : "□"} bit ${b.n}: ${b.name}`))));
  }
  if (!I.bytes.length) {
    sec.append(el("p", { class: "muted" }, m.frame.rtr
      ? "A remote request carries no data bytes."
      : "This frame has no data bytes: the identifier alone is the message."));
    return sec;
  }
  sec.append(el("p", { class: "muted" }, "One row per byte, most significant bit on the left as in the hex value. The small number is the CANopen bit number, counted from bit 0 of byte 0. Numbers are little-endian: the low byte comes first."));
  const grid = el("table", { class: "fx-bytes", dataset: { fx: "grid" } },
    el("thead", null, el("tr", null, el("th"), [7, 6, 5, 4, 3, 2, 1, 0].map((i) => el("th", { scope: "col" }, "b" + i)), el("th"))),
    el("tbody", null, I.bytes.map((v, bi) => el("tr", null, el("th", { scope: "row" }, "byte " + bi),
      [7, 6, 5, 4, 3, 2, 1, 0].map((i) => {
        const pb = bi * 8 + i;
        const k = I.owner[pb];
        const f = m.fields[k];
        const bit = (v >> i) & 1;
        return el("td", null, fxBitButton(I, `data.${bi}.${i}`, bit, `Byte ${bi} bit ${i} = ${bit}` + (f ? `, ${f.name}` : ""),
          f && f.group === "unused" ? "unused" : null, f ? fxColor(f.group) : null, () => fxExplainData(I, bi, i), pb));
      }),
      el("td", { class: "fx-hex" }, "0x" + v.toString(16).toUpperCase().padStart(2, "0"), el("span", null, " = " + v))))));
  const first = grid.querySelector(".fx-bit");
  if (first) first.tabIndex = 0;
  fxRoving(grid, ".fx-bit", 8);
  const fields = el("div", { class: "fx-fields", dataset: { fx: "fields" } }, m.fields.map((f, k) => {
    const b = el("button", { type: "button", class: "fx-field" + (f.group === "unused" ? " unused" : ""), dataset: { field: k } },
      el("span", { class: "fx-sw" }),
      el("span", null, el("b", null, f.name), " ", el("span", { class: "muted mono" }, f.length === 1 ? `bit ${f.start}` : `bits ${f.start}-${f.start + f.length - 1}`)),
      el("span", { class: "fx-val mono" }, f.value),
      f.how ? el("span", { class: "fx-how mono muted" }, f.how) : null,
      f.location ? el("span", { class: "fx-how mono" }, "PLC: " + f.location + (f.variables && f.variables.length ? " " + f.variables.join(", ") : "")) : null);
    b.style.setProperty("--c", fxColor(f.group));
    const show = () => fxExplainField(I, f);
    b.addEventListener("mouseenter", show);
    b.addEventListener("focus", show);
    b.addEventListener("click", show);
    return b;
  }));
  sec.append(el("div", { class: "fx-scroll" }, grid), fields);
  return sec;
}

function fxWire(I) {
  const w = I.m.wire;
  const W = 16, top = 22, n = w.bits.length;
  const width = n * W + 20, height = 132;
  const svg = fxSvg("svg", { viewBox: `0 0 ${width} ${height}`, width, height, role: "img", tabindex: "0", class: "fx-wire",
    "aria-label": `The frame on the wire: ${n} bits. Use the arrow keys to go through them.`, "data-fx": "wire" });
  let i = 0;
  while (i < n) {
    const part = (b) => (b.field === "stuff" ? null : b.field);
    const f = part(w.bits[i]);
    let j = i + 1;
    while (j < n && (part(w.bits[j]) === f || (w.bits[j].field === "stuff" && j + 1 < n && part(w.bits[j + 1]) === f))) j++;
    if (f) {
      svg.append(fxSvg("rect", { x: 10 + i * W, y: 2, width: (j - i) * W - 1, height: 14, rx: 2, fill: `var(--fx-w-${FX_WIRE_PART[f]})` }));
      const label = (w.fields[f] || {}).name || f;
      if ((j - i) * W > label.length * 6 + 6) svg.append(fxSvg("text", { x: 10 + i * W + 4, y: 13, class: "fx-band" }, label));
    }
    i = j;
  }
  const cells = [];
  w.bits.forEach((b, k) => {
    const g = fxSvg("g", { "data-ref": b.ref, "data-wn": k, class: "fx-wbit" + (b.field === "stuff" ? " stuff" : "") });
    g.style.setProperty("--c", `var(--fx-w-${FX_WIRE_PART[b.field]})`);
    g.append(fxSvg("rect", { x: 10 + k * W, y: top, width: W - 1, height: 22, rx: 2 }),
      fxSvg("text", { x: 10 + k * W + W / 2 - 0.5, y: top + 15, "text-anchor": "middle" }, String(b.v)));
    const show = () => { I.wsel = k; fxExplainWire(I, k); };
    g.addEventListener("mouseenter", show);
    g.addEventListener("click", show);
    cells.push(g);
    svg.append(g);
  });
  const yH = 62, yL = 98;
  let d = `M 10 ${w.bits[0].v ? yH : yL}`;
  w.bits.forEach((b, k) => { const y = b.v ? yH : yL; d += ` L ${10 + k * W} ${y} L ${10 + (k + 1) * W} ${y}`; });
  svg.append(fxSvg("path", { d, class: "fx-level" }),
    fxSvg("text", { x: 12, y: yH - 6, class: "fx-axis" }, "recessive 1"),
    fxSvg("text", { x: 12, y: yL + 14, class: "fx-axis" }, "dominant 0"));
  for (let k = 0; k <= n; k += 10) svg.append(fxSvg("text", { x: 10 + k * W, y: 128, class: "fx-axis" }, String(k)));
  svg.addEventListener("keydown", (e) => {
    const step = { ArrowLeft: -1, ArrowRight: 1, Home: -1e6, End: 1e6 }[e.key];
    if (step === undefined) return;
    e.preventDefault();
    I.wsel = Math.max(0, Math.min(n - 1, (I.wsel == null ? -1 : I.wsel) + step));
    if (I.wsel < 0) I.wsel = 0;
    fxExplainWire(I, I.wsel);
    const x = 10 + I.wsel * W, sc = svg.parentNode;
    if (sc && (x < sc.scrollLeft || x > sc.scrollLeft + sc.clientWidth - W)) sc.scrollLeft = x - sc.clientWidth / 2;
  });
  svg.addEventListener("focus", () => { if (I.wsel == null) { I.wsel = 0; fxExplainWire(I, 0); } });
  const assumed = w.bitrate_assumed ? " (assumed: no bit rate known)" : "";
  return el("section", { class: "fx-layer" }, el("h3", null, "On the wire"),
    el("p", { class: "muted" }, "The controller adds a start bit, control bits, a CRC, the acknowledge slot and end bits. After five equal bits it inserts one opposite stuff bit (marked) so receivers keep their clocks in step. A 0 is dominant and wins over a recessive 1."),
    el("div", { class: "fx-legend" }, FX_LEGEND.map(([k, l]) => fxStyle(el("span", null, el("i"), l), "--c", `var(--fx-w-${k})`))),
    el("div", { class: "fx-scroll fx-wire-scroll" }, svg),
    el("div", { class: "fx-stats", dataset: { fx: "stats" } },
      el("span", null, "Frame ", el("b", null, `${w.frame_bits} bits`), " + 3 intermission"),
      el("span", null, "Stuff bits ", el("b", null, String(w.stuff_bits))),
      el("span", null, "CRC ", el("b", null, w.crc_text)),
      el("span", null, "On the bus ", el("b", null, fxUs(w.duration_us)), ` at ${fxRate(w.bitrate)}${assumed}`),
      el("span", null, "Data share ", el("b", null, w.data_share + " %"))),
    el("p", { class: "muted fx-small" }, w.note));
}

// -- the explanation box and the linked highlight ---------------------------------

// Lights `refs` (and wire bits `wns`) in every layer; `soft` refs (the
// rest of a pointed-at bit's field) get a lighter mark.
function fxHighlight(I, refs, wns, soft) {
  const set = new Set(refs || []);
  const ws = new Set((wns || []).map(String));
  const so = new Set(soft || []);
  for (const e of I.root.querySelectorAll("[data-ref]")) {
    const on = set.has(e.dataset.ref) && (e.dataset.ref !== "stuff" || ws.has(e.dataset.wn)) || ws.has(e.dataset.wn);
    e.classList.toggle("hl", !!on);
    e.classList.toggle("hl-soft", !on && so.has(e.dataset.ref));
  }
}

function fxShow(I, tag, color, title, rows, text) {
  fxFill(I.box, fxStyle(el("span", { class: "fx-tag" }, tag), "color", color),
    el("h4", null, title),
    el("dl", null, rows.filter(Boolean).flatMap(([k, v]) => [el("dt", null, k), el("dd", null, v)])),
    text ? el("p", null, text) : null);
}

function fxOverview(I) {
  const m = I.m;
  fxHighlight(I, []);
  fxShow(I, "Frame", null, m.title || "Frame", [["Frame", m.frame.candump], m.wire && ["Bits on the wire", String(m.wire.frame_bits)]],
    "Point at or tab to any bit or field to see what it is. Arrow keys move between bits.");
}

function fxFieldRefs(f) {
  const refs = [];
  for (let b = f.start; b < f.start + f.length; b++) refs.push(`data.${b >> 3}.${b & 7}`);
  return refs;
}

function fxExplainField(I, f) {
  fxHighlight(I, fxFieldRefs(f));
  fxShow(I, "Field", fxColor(f.group), f.name, [
    ["Bits", f.length === 1 ? String(f.start) : `${f.start}-${f.start + f.length - 1} (${f.length} bits)`],
    ["Value", f.value], f.how && ["Working", f.how],
    f.object && ["Object", f.object + (f.object_name ? " " + f.object_name : "")], f.type && ["Type", f.type],
    f.location && ["PLC", f.location], f.variables && f.variables.length && ["Variables", f.variables.join(", ")]], f.text);
}

// The PLC address of one bit of a field: the location itself for a bit
// mapping, else the bit of the byte, word or double word.
function fxPlcBit(f, k) {
  if (!f.location) return null;
  if (f.length === 1) return f.location;
  return `bit ${k} of ${f.location}`;
}

function fxExplainData(I, bi, i) {
  const m = I.m;
  const pb = bi * 8 + i;
  const v = (I.bytes[bi] >> i) & 1;
  const f = m.fields[I.owner[pb]];
  const k = f ? pb - f.start : null;
  const name = f && f.bits && f.bits[k] ? f.bits[k].name : null;
  const wn = I.wireAt.get(`data.${bi}.${i}`);
  fxHighlight(I, [`data.${bi}.${i}`], wn != null ? [wn] : [], f && !name ? fxFieldRefs(f) : []);
  const weight = k != null ? (k < 31 ? String(2 ** k) : "2^" + k) : null;
  fxShow(I, "Data bit", f ? fxColor(f.group) : null, name ? `${name} = ${v ? "set" : "clear"}` : `Bit ${pb} = ${v}`, [
    ["Byte and bit", `byte ${bi}, bit ${i} (weight ${1 << i} in the byte)`],
    ["CANopen bit", String(pb)],
    f && ["Field", f.name], f && f.length > 1 && ["Bit of the field", `${k} of ${f.length} (weight ${weight})`],
    f && f.value && ["Field value", f.value],
    f && f.location && ["PLC", fxPlcBit(f, k)],
    f && f.object && ["Object", f.object + (f.object_name ? " " + f.object_name : "")],
    ["Level", v ? "recessive (1)" : "dominant (0)"],
    wn != null && ["Wire bit", `${wn} of ${m.wire.bits.length}`]], f ? f.text : null);
}

function fxExplainId(I, b) {
  const id = I.m.identifier;
  const wn = I.wireAt.get("id." + b.n);
  fxHighlight(I, ["id." + b.n], wn != null ? [wn] : []);
  const J1939_PART = { priority: ["priority", 26], reserved: ["reserved bit", 25], dp: ["data page", 24], pf: ["PDU format", 16],
    ps: [id.j1939 && id.j1939.pdu1 ? "PDU specific: destination address" : "PDU specific: group extension", 8], source: ["source address", 0] };
  const jp = id.j1939 ? J1939_PART[b.part] : null;
  const part = jp ? `${jp[0]} (its bit ${b.n - jp[1]})`
    : b.part === "function" ? `function code (its bit ${b.n - 7})` : b.part === "node" ? `node ID (its bit ${b.n})` : "identifier";
  fxShow(I, "Identifier bit", fxPartColor(id, b.part), `Identifier bit ${b.n} = ${b.v}`, [
    ["Part of", part], ["Weight", `${b.weight} (0x${b.weight.toString(16).toUpperCase()})`],
    ["Level", b.v ? "recessive (1)" : "dominant (0)"], wn != null && ["Wire bit", String(wn)],
    id.function_code != null && b.part === "function" && ["Function code", String(id.function_code)],
    id.node != null && b.part === "node" && ["Node ID", String(id.node)]],
  "The identifier goes out most significant bit first. While several nodes send at once, each compares the bus with its own bit: one that sends a recessive 1 but reads a dominant 0 has lost and stops. A 0 here makes this frame win over frames with a 1 in the same place.");
}

function fxExplainWire(I, k) {
  const w = I.m.wire;
  const b = w.bits[k];
  const field = w.fields[b.field] || { name: b.field, text: "" };
  const refs = b.ref === "stuff" ? [] : [b.ref];
  fxHighlight(I, refs, [k]);
  let what = field.name;
  if (b.ref.startsWith("id.")) what = `Identifier bit ${b.ref.slice(3)}`;
  else if (b.ref.startsWith("dlc.")) what = `Data length bit ${b.ref.slice(4)}`;
  else if (b.ref.startsWith("crc.")) what = `CRC bit ${b.ref.slice(4)}`;
  else if (b.ref.startsWith("data.")) { const [, by, bit] = b.ref.split("."); what = `Data byte ${by}, bit ${bit}`; }
  fxShow(I, "Wire bit", `var(--fx-w-${FX_WIRE_PART[b.field]})`, `Wire bit ${k}: ${what}`, [
    ["Value", `${b.v} (${b.level})`], ["Field", field.name],
    ["Starts at", `${(k * w.bit_time_us).toFixed(1)} µs`], b.field === "crc" && ["CRC", w.crc_text]], field.text);
}

// ---------------------------------------------------------------------------
// The Trace view: inspector under the frame list

async function fxInspectSeq(seq, target, opts) {
  const box = target || $("#trace-inspector");
  if (!box) return;
  const my = (box._fxSeq = (box._fxSeq || 0) + 1);
  let m;
  try {
    m = await api("POST", "/api/trace/explain", { seq });
  } catch (e) {
    if (box._fxSeq === my) fxFill(box, el("p", { class: "muted" }, e.message));
    return;
  }
  if (box._fxSeq !== my || !box.isConnected) return;
  const actions = [];
  const go = (sub, label) => actions.push(el("button", { type: "button", dataset: { fxGo: sub }, onclick: () => {
    FX.seq.sub = sub;
    FX.seq.at = seq;
    FX.seq.picked = null;
    T.tab = "sequences";
    renderTraceTab();
  } }, label));
  if (!(opts && opts.noLinks)) {
    if (m.kind === "sdo") go("sdo", "Show its SDO conversation");
    if (m.kind === "pdo" || m.kind === "sync") go("sync", "Show its SYNC cycle");
    if (m.kind === "sdo" || m.kind === "nmt" || (m.kind === "heartbeat" && m.frame.data === "00")) go("boot", "Show the boot story");
  }
  fxFill(box, fxInspector(m, { actions, time: typeof secText === "function" ? secText(m.t_us) : null }));
}

// Up and down in the frame list move the selection (and the inspector).
function fxMoveSelection(step) {
  const list = $("#trace-list");
  if (!list) return;
  const rows = [...document.querySelectorAll("#trace-rows .trace-row[data-seq]")];
  if (!rows.length) return;
  let k = rows.findIndex((r) => Number(r.dataset.seq) === T.selected);
  const visible = Math.max(1, Math.floor((list.clientHeight - 2) / ROW_H));
  const first = firstRow();
  // Home and End: the top or the bottom of the whole trace, then its first or last row.
  if (!Number.isFinite(step)) {
    const before = list.scrollTop;
    list.scrollTop = step < 0 ? 0 : list.scrollHeight;
    T.selected = null;
    if (list.scrollTop !== before) { T.pendingStep = step < 0 ? 1 : -1; requestRows(); } else fxMoveSelection(step < 0 ? 1 : -1);
    return;
  }
  const next = k < 0 ? (step > 0 ? 0 : rows.length - 1) : Math.max(-1, Math.min(rows.length, k + step));
  if (next < 0 || next >= rows.length) {
    const before = list.scrollTop;
    list.scrollTop += step * ROW_H;
    if (list.scrollTop !== before) { T.pendingStep = step; requestRows(); }
    return;
  }
  const r = rows[next];
  selectRow({ seq: Number(r.dataset.seq), t_us: Number(r.dataset.t) });
  if (next >= visible - 1 && step > 0) list.scrollTop += ROW_H;
  if (next === 0 && step < 0 && first > 0) list.scrollTop -= ROW_H;
}

// ---------------------------------------------------------------------------
// The Sequences tab

function fxRenderSequences(box) {
  const s = FX.seq;
  const sub = el("div", { class: "segmented", role: "group", "aria-label": "Sequence kind" },
    [["sdo", "SDO conversations"], ["boot", "Boot stories"], ["sync", "SYNC cycles"]].map(([v, l]) =>
      el("button", { type: "button", "aria-pressed": String(s.sub === v), dataset: { fxSub: v }, onclick: () => {
        s.sub = v; s.picked = null; s.at = null; fxRenderSequences(box);
      } }, l)));
  const node = el("input", { type: "text", placeholder: "Node", "aria-label": "Node", value: s.node, dataset: { fxFilter: "node" } });
  node.style.width = "8ch";
  node.addEventListener("change", () => { s.node = node.value.trim(); fxLoadSequences(); });
  const results = s.sub === "sdo" ? [["", "Any result"], ["done", "Done"], ["aborted", "Aborted"], ["unanswered", "Unanswered"], ["open", "Open"]]
    : [["", "Any result"], ["problems", "With problems"], ["running", "Running"], ["operational", "Operational"], ["started", "Started"], ["not started", "Not started"]];
  const result = el("select", { "aria-label": "Result", dataset: { fxFilter: "result" } },
    results.map(([v, l]) => el("option", { value: v, selected: s.result === v }, l)));
  result.onchange = () => { s.result = result.value; fxDrawSequences(); };
  fxFill(box, el("div", { class: "toolbar" }, sub, s.sub !== "sync" ? node : null, s.sub !== "sync" ? result : null),
    el("div", { id: "fx-seq-body", dataset: { fx: "sequences" } }, el("p", { class: "muted" }, "Loading…")),
    el("div", { id: "fx-seq-detail" }),
    el("div", { id: "fx-seq-inspector", class: "fx-host" }));
  fxLoadSequences();
}

async function fxLoadSequences(n) {
  const s = FX.seq;
  const my = ++s.seq;
  const body = { kind: s.sub };
  const node = parseInt(s.node, 10);
  if (s.sub !== "sync" && node >= 1 && node <= 127) body.node = node;
  if (s.sub === "sync") body.n = n != null ? n : s.at != null ? undefined : s.n;
  if (s.at != null) body.at = s.at;
  let r;
  try { r = await api("POST", "/api/trace/sequence", body); } catch (e) {
    const b = $("#fx-seq-body");
    if (b) fxFill(b, el("p", { class: "muted" }, e.message));
    return;
  }
  if (my !== s.seq || !$("#fx-seq-body")) return;
  s.data = r;
  if (r.selected != null) s.picked = r.selected;
  if (r.kind === "sync" && r.cycle) s.n = r.cycle.n;
  const at = s.at;
  s.at = null;
  fxDrawSequences();
  if (at != null) fxInspectSeq(at, $("#fx-seq-inspector"), { noLinks: true });
}

function fxDrawSequences() {
  const s = FX.seq, r = s.data, body = $("#fx-seq-body");
  if (!body || !r) return;
  if (r.kind === "sdo") return fxDrawConversations(body, r);
  if (r.kind === "boot") return fxDrawBoots(body, r);
  return fxDrawSync(body, r);
}

function fxPick(list, seq) { return list.find((x) => x.seq === seq) || null; }

function fxDrawConversations(body, r) {
  const s = FX.seq;
  const shown = r.conversations.filter((c) => !s.result || c.result === s.result);
  const t0 = T.st ? traceT0() : 0;
  fxFill(body, 
    el("p", { class: "muted" }, `${r.total} SDO conversation${r.total === 1 ? "" : "s"}` +
      (r.total > r.conversations.length ? `, the newest ${r.conversations.length} listed` : "") + "."),
    shown.length ? el("div", { class: "fx-list" }, el("table", { class: "fx-table" },
      el("thead", null, el("tr", null, thCells(["Time", "Node", "Operation", "Object", "Result", "Value", "Frames", "Took"]))),
      el("tbody", null, shown.map((c) => el("tr", { class: (c.seq === s.picked ? "selected " : "") + "r-" + c.result, tabindex: "0",
        dataset: { seq: c.seq }, onclick: () => { s.picked = c.seq; fxDrawSequences(); },
        onkeydown: (e) => { if (e.key === "Enter") { s.picked = c.seq; fxDrawSequences(); } } },
      el("td", null, ((c.start_us - t0) / 1e6).toFixed(3)), el("td", null, c.node_label),
      el("td", null, `${c.op} (${c.mode})`), el("td", null, c.object + (c.object_name ? " " + c.object_name : "")),
      el("td", null, c.result), el("td", null, c.result === "aborted" ? c.abort_text : c.value || ""),
      el("td", null, String(c.frames)), el("td", null, fxUs(c.duration_us))))))) : el("p", { class: "muted" }, "No SDO conversations match."));
  const c = s.picked != null ? fxPick(r.conversations, s.picked) : null;
  const detail = $("#fx-seq-detail");
  if (!c) { fxFill(detail); return; }
  fxFill(detail, el("h3", null, `${c.op} ${c.object}${c.object_name ? " " + c.object_name : ""}, ${c.node_label}`),
    el("p", null, c.result === "done" ? `${c.mode} ${c.op}, ${c.size} byte${c.size === 1 ? "" : "s"}: ${c.value}`
      : c.result === "aborted" ? `Aborted: ${c.abort_text} (0x${(c.abort >>> 0).toString(16).toUpperCase().padStart(8, "0")})` : `Result: ${c.result}`),
    fxDiagram(c.steps.map((st) => ({ seq: st.seq, from: st.from === "PLC" ? "left" : "right", text: `${st.id}#${st.data.replace(/ /g, "")}  ${st.text}`,
      dt: st.dt_us, bad: st.text.startsWith("abort") })), "PLC (SDO client)", c.node_label + " (SDO server)"));
}

// A sequence diagram between two lifelines; each arrow opens its frame.
function fxDiagram(steps, left, right) {
  const W = 640, x1 = 80, x2 = W - 80, top = 34, gap = 38;
  const h = top + steps.length * gap + 16;
  const svg = fxSvg("svg", { viewBox: `0 0 ${W} ${h}`, class: "fx-diagram", role: "group", "aria-label": `Sequence between ${left} and ${right}`, "data-fx": "diagram" });
  svg.append(fxSvg("text", { x: 4, y: 14, class: "fx-life" }, left),
    fxSvg("text", { x: W - 4, y: 14, "text-anchor": "end", class: "fx-life" }, right),
    fxSvg("line", { x1, y1: 20, x2: x1, y2: h - 4, class: "fx-lifeline" }),
    fxSvg("line", { x1: x2, y1: 20, x2, y2: h - 4, class: "fx-lifeline" }));
  steps.forEach((st, k) => {
    const y = top + k * gap + 18;
    const a = st.from === "left" ? x1 : x2, b = st.from === "left" ? x2 : x1;
    const dir = b > a ? -1 : 1;
    const g = fxSvg("g", { class: "fx-arrow" + (st.bad ? " bad" : "") + (st.mid ? " mid" : ""), tabindex: "0", role: "button",
      "aria-label": st.text, "data-seq": st.seq });
    if (st.mid) {
      g.append(fxSvg("circle", { cx: a, cy: y - 3, r: 5 }));
    } else {
      g.append(fxSvg("line", { x1: a, y1: y, x2: b + dir * 2, y2: y }),
        fxSvg("path", { d: `M ${b} ${y} l ${dir * 9} -5 l 0 10 z` }));
    }
    // Labels stay between the lifelines; a long one is cut, the whole text is its tooltip.
    const fit = Math.floor((x2 - x1 - 16) / 6.6);
    const label = st.text.length > fit ? st.text.slice(0, fit - 1) + "\u2026" : st.text;
    g.append(fxSvg("title", null, st.text),
      fxSvg("text", { x: (x1 + x2) / 2, y: y - 6, "text-anchor": "middle" }, label),
      fxSvg("text", { x: 4, y: y + 4, class: "fx-axis" }, k ? "+" + fxUs(st.dt) : "0"));
    const open = () => {
      for (const o of svg.querySelectorAll(".fx-arrow")) o.classList.toggle("picked", o === g);
      fxInspectSeq(st.seq, $("#fx-seq-inspector"), { noLinks: true });
    };
    g.addEventListener("click", open);
    g.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); } });
    svg.append(g);
  });
  return el("div", { class: "fx-scroll" }, svg);
}

const FX_BOOT_RESULT = { "not started": "did not get the NMT start", started: "got the NMT start but no heartbeat in Operational was seen",
  operational: "reached Operational", running: "reached Operational and sent process data" };

function fxDrawBoots(body, r) {
  const s = FX.seq;
  const bad = (b) => b.summary && (b.summary.refused || b.summary.missing || b.summary.different || b.summary.unanswered);
  const shown = r.stories.filter((b) => !s.result || (s.result === "problems" ? bad(b) || b.result !== "running" : b.result === s.result));
  const t0 = T.st ? traceT0() : 0;
  const summary = (b) => b.summary ? Object.entries(b.summary).map(([k, n]) => `${n} ${k}`).join(", ") : "not compared";
  fxFill(body, 
    el("p", { class: "muted" }, `${r.total} boot${r.total === 1 ? "" : "s"} found.` +
      (r.compared ? " The master's writes are compared with what the configuration writes at boot." : " The configuration's boot writes could not be computed, so writes are not compared.")),
    shown.length ? el("div", { class: "fx-list" }, el("table", { class: "fx-table" },
      el("thead", null, el("tr", null, thCells(["Time", "Node", "Began with", "Result", "Writes", "Took"]))),
      el("tbody", null, shown.map((b) => el("tr", { class: (b.seq === s.picked ? "selected " : "") + (bad(b) ? "r-aborted" : ""), tabindex: "0",
        dataset: { seq: b.seq }, onclick: () => { s.picked = b.seq; fxDrawSequences(); },
        onkeydown: (e) => { if (e.key === "Enter") { s.picked = b.seq; fxDrawSequences(); } } },
      el("td", null, ((b.start_us - t0) / 1e6).toFixed(3)), el("td", null, b.node_label), el("td", null, b.how),
      el("td", null, b.result), el("td", null, summary(b)), el("td", null, fxUs(b.duration_us))))))) : el("p", { class: "muted" }, "No boots match."));
  const b = s.picked != null ? fxPick(r.stories, s.picked) : null;
  const detail = $("#fx-seq-detail");
  if (!b) { fxFill(detail); return; }
  const from = { "boot-up": "right", sdo: "left", nmt: "left", heartbeat: "right", pdo: "right" };
  fxFill(detail, el("h3", null, `Boot of ${b.node_label}`),
    el("p", { dataset: { fx: "boot-result" } }, `The node ${FX_BOOT_RESULT[b.result] || b.result}.`),
    fxDiagram(b.steps.map((st) => ({ seq: st.seq, from: from[st.what] || "right", mid: st.what.startsWith("reset") && false,
      text: st.text, dt: st.dt_us, bad: / refused|abort|unanswered/.test(st.text) })), "PLC (master)", b.node_label),
    b.writes ? el("div", { class: "fx-list" }, el("table", { class: "fx-table", dataset: { fx: "writes" } },
      el("thead", null, el("tr", null, thCells(["Object", "Name", "Expected", "Written", "Result"]))),
      el("tbody", null, b.writes.map((w) => el("tr", { class: "w-" + w.status, tabindex: w.seq != null ? "0" : null,
        onclick: w.seq != null ? () => fxInspectSeq(w.seq, $("#fx-seq-inspector"), { noLinks: true }) : null },
      el("td", null, w.object), el("td", null, w.object_name || ""),
      el("td", { class: "mono" }, w.expected_text || w.expected || ""), el("td", { class: "mono" }, w.actual_text || w.actual || ""),
      el("td", null, el("span", { class: "fx-status s-" + w.status }, w.status), w.abort_text ? " " + w.abort_text : "")))))) : null);
}

function fxDrawSync(body, r) {
  const s = FX.seq;
  if (!r.count) {
    fxFill(body, el("p", { class: "muted" }, "This trace has no SYNC frames."));
    fxFill($("#fx-seq-detail"));
    return;
  }
  const c = r.cycle;
  const num = el("input", { type: "number", min: "1", max: String(r.count), value: String(c.n + 1), "aria-label": "SYNC cycle", dataset: { fxSync: "n" } });
  num.style.width = "9ch";
  num.addEventListener("change", () => fxLoadSequences(Math.max(0, Math.min(r.count - 1, Number(num.value) - 1))));
  const nextLate = r.late.find((n) => n > c.n);
  fxFill(body, 
    el("p", { class: "muted" }, `${r.count} SYNC period${r.count === 1 ? "" : "s"}` +
      (r.period_min_us != null ? `, ${fxUs(r.period_min_us)} to ${fxUs(r.period_max_us)} apart` : "") +
      (r.slowest != null ? `. The latest synchronous TPDO came ${fxUs(r.slowest_us)} after its SYNC, in cycle ${r.slowest + 1}` : "") +
      (r.late.length ? `. ${r.late.length} cycle${r.late.length === 1 ? " has" : "s have"} TPDOs outside the SYNC window.` : ".")),
    el("div", { class: "toolbar" },
      el("button", { type: "button", disabled: c.n <= 0, dataset: { fxSync: "prev" }, onclick: () => fxLoadSequences(c.n - 1) }, "Previous"),
      el("label", { class: "inline" }, "Cycle ", num, ` of ${r.count}`),
      el("button", { type: "button", disabled: c.n >= r.count - 1, dataset: { fxSync: "next" }, onclick: () => fxLoadSequences(c.n + 1) }, "Next"),
      r.slowest != null ? el("button", { type: "button", dataset: { fxSync: "slowest" }, onclick: () => fxLoadSequences("slowest") }, "Slowest cycle") : null,
      nextLate != null ? el("button", { type: "button", dataset: { fxSync: "late" }, onclick: () => fxLoadSequences(nextLate) }, "Next late cycle") : null));
  fxFill($("#fx-seq-detail"), fxTimeline(c));
}

const FX_LANES = [["sync", "SYNC"], ["sync_pdo", "Synchronous PDOs"], ["pdo", "Other PDOs"], ["sdo", "SDO"], ["other", "Other"]];

function fxTimeline(c) {
  const W = 700, left = 130, right = 16, laneH = 30, top = 18;
  const last = c.frames.reduce((m, f) => Math.max(m, f.offset_us), 0);
  const span = Math.max(c.period_us || 0, last, c.window_us || 0, 1) * 1.04;
  const x = (us) => left + (W - left - right) * us / span;
  const h = top + FX_LANES.length * laneH + 26;
  const svg = fxSvg("svg", { viewBox: `0 0 ${W} ${h}`, class: "fx-timeline", role: "group", "aria-label": `SYNC cycle ${c.n + 1}`, "data-fx": "timeline" });
  if (c.window_us) {
    svg.append(fxSvg("rect", { x: x(0), y: top - 4, width: x(c.window_us) - x(0), height: FX_LANES.length * laneH, class: "fx-window" }),
      fxSvg("text", { x: x(c.window_us) - 4, y: top + 6, "text-anchor": "end", class: "fx-axis" }, `SYNC window ${fxUs(c.window_us)}`));
  }
  FX_LANES.forEach(([g, label], k) => {
    const y = top + k * laneH + laneH / 2;
    svg.append(fxSvg("text", { x: 4, y: y + 4, class: "fx-lane" }, label), fxSvg("line", { x1: left, y1: y, x2: W - right, y2: y, class: "fx-lifeline" }));
  });
  for (let k = 0; k <= 4; k++) {
    const us = span / 1.04 * k / 4;
    svg.append(fxSvg("text", { x: x(us), y: h - 6, "text-anchor": "middle", class: "fx-axis" }, fxUs(us)));
  }
  const open = (f, g) => {
    for (const o of svg.querySelectorAll(".fx-mark")) o.classList.toggle("picked", o === g);
    fxInspectSeq(f.seq, $("#fx-seq-inspector"), { noLinks: true });
  };
  for (const f of c.frames) {
    const lane = FX_LANES.findIndex(([g]) => g === f.group);
    const y = top + lane * laneH + laneH / 2;
    const late = f.in_window === false;
    const g = fxSvg("g", { class: "fx-mark g-" + f.group + (late ? " late" : ""), tabindex: "0", role: "button", "data-seq": f.seq,
      "aria-label": `${f.id} ${f.name} at +${fxUs(f.offset_us)}${late ? ", outside the SYNC window" : ""}` });
    g.append(fxSvg("title", null, `${f.id} ${f.name} +${fxUs(f.offset_us)}`), fxSvg("rect", { x: x(f.offset_us) - 3, y: y - 8, width: 6, height: 16, rx: 1 }));
    g.addEventListener("click", () => open(f, g));
    g.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(f, g); } });
    svg.append(g);
  }
  return el("div", null, el("h3", null, `SYNC cycle ${c.n + 1}` + (c.period_us != null ? `, ${fxUs(c.period_us)} until the next SYNC` : "")),
    el("div", { class: "fx-scroll" }, svg),
    el("div", { class: "fx-list" }, el("table", { class: "fx-table", dataset: { fx: "cycle" } },
      el("thead", null, el("tr", null, ["After SYNC", "ID", "Name", "Group", "Transmission", "SYNC window"].map((t) => el("th", null, t)))),
      el("tbody", null, c.frames.map((f) => el("tr", { tabindex: "0", class: f.in_window === false ? "r-aborted" : "",
        onclick: () => fxInspectSeq(f.seq, $("#fx-seq-inspector"), { noLinks: true }) },
      el("td", null, "+" + fxUs(f.offset_us)), el("td", { class: "mono" }, f.id), el("td", null, f.name),
      el("td", null, (FX_LANES.find(([g]) => g === f.group) || [0, f.group])[1]),
      el("td", null, f.transmission != null ? `${f.direction} ${transmissionName(f.transmission)}` : ""),
      el("td", { dataset: { window: f.in_window == null ? "" : String(f.in_window) } }, f.in_window == null ? "" : f.in_window ? "inside" : "outside (late)")))))));
}

function transmissionName(t) {
  if (t === 0) return "0 (acyclic synchronous)";
  if (t <= 240) return `${t} (every ${t === 1 ? "" : t + " "}SYNC)`.replace("every SYNC", "every SYNC");
  if (t === 254 || t === 255) return `${t} (event-driven)`;
  return String(t);
}

// ---------------------------------------------------------------------------
// The Frame lab view

function fxLabBody(extra) {
  const body = Object.assign({}, extra);
  if (S.model) {
    body.config = fileConfig();
    const net = several() ? netName(S.config) : "";
    if (net) body.network = net;
  }
  if (FX.lab.bitrate) body.bitrate = Number(FX.lab.bitrate);
  return body;
}

function renderFrameLab(view) {
  const L = FX.lab;
  // Another network: the frame and its result belonged to the previous one.
  const net = S.model ? netName(S.config) : "";
  if (L.net !== undefined && L.net !== net) Object.assign(L, { frame: "", built: null, form: {} });
  L.net = net;
  const input = el("input", { type: "text", spellcheck: "false", autocomplete: "off", placeholder: "705#7F", "aria-label": "Frame (ID#DATA)",
    value: L.frame, dataset: { fx: "lab-frame" } });
  input.style.width = "24ch";
  const go = () => { L.frame = input.value.trim(); fxLabExplain(L.frame); };
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") go(); });
  const rate = el("select", { "aria-label": "Bit rate", dataset: { fx: "lab-bitrate" } },
    el("option", { value: "" }, "Bit rate of the configuration"), FX_BITRATES.map((r) => el("option", { value: String(r), selected: String(r) === L.bitrate }, fxRate(r))));
  rate.onchange = () => { L.bitrate = rate.value; if (L.frame) fxLabExplain(L.frame); };
  view.append(el("h2", null, "Frame lab"),
    el("p", { class: "fx-note", dataset: { fx: "nothing-sent" } }, "Nothing here is sent: the Frame lab explains frames on this PC only. It needs no runtime, no adapter and no trace."),
    el("section", { class: "fx-lab-section" },
      el("h3", null, "Explain a frame"),
      el("p", { class: "muted" }, "Type or paste a frame as ID#DATA in hex, as candump writes it: 185#2500EA00, 705#7F, 701#R for a remote request, 8 digits for an extended identifier."),
      el("div", { class: "toolbar" }, input, el("button", { type: "button", class: "primary", dataset: { fx: "lab-explain" }, onclick: go }, "Explain"), rate),
      el("div", { id: "fx-lab-error", class: "fx-error", role: "status" })),
    el("section", { class: "fx-lab-section" }, el("h3", null, "Example frames from this configuration"),
      el("div", { id: "fx-lab-examples", dataset: { fx: "examples" } }, el("p", { class: "muted" }, "Loading…"))),
    el("details", { class: "fx-lab-section", open: L.builderOpen ? true : null, ontoggle: (e) => { L.builderOpen = e.target.open; } },
      el("summary", null, el("h3", { class: "inline-h" }, "Build a frame")), el("div", { id: "fx-lab-builder" })),
    el("details", { class: "fx-lab-section", open: L.arbOpen ? true : null, ontoggle: (e) => { L.arbOpen = e.target.open; } },
      el("summary", null, el("h3", { class: "inline-h" }, "Arbitration: two frames at once")), fxArbitrationForm()),
    el("div", { id: "fx-lab-inspector", class: "fx-host", dataset: { fx: "lab-inspector" } }));
  fxLabLoad();
  if (L.frame) fxLabExplain(L.frame);
}

async function fxLabLoad() {
  const L = FX.lab;
  const my = ++L.seq;
  let ex, pd;
  try {
    [ex, pd] = await Promise.all([api("POST", "/api/explain/build", fxLabBody({ what: "examples" })),
      api("POST", "/api/explain/build", fxLabBody({ what: "pdos" }))]);
  } catch (e) {
    const b = $("#fx-lab-examples");
    if (b) fxFill(b, el("p", { class: "fx-error" }, e.message));
    return;
  }
  if (my !== L.seq || !$("#fx-lab-examples")) return;
  L.info = ex;
  L.examples = ex.examples;
  L.pdos = pd.pdos;
  L.nodes = pd.nodes;
  const groups = new Map();
  for (const x of ex.examples) {
    if (!groups.has(x.group)) groups.set(x.group, []);
    groups.get(x.group).push(x);
  }
  fxFill($("#fx-lab-examples"), 
    ex.warnings && ex.warnings.length ? el("p", { class: "muted" }, ex.warnings.map(humanise).join(" ")) : null,
    [...groups].map(([g, xs]) => el("div", { class: "fx-examples" }, el("span", { class: "fx-group-name" }, g),
      xs.map((x) => el("button", { type: "button", class: "chip", dataset: { fxExample: x.label }, onclick: () => fxLabFrames(x.frames, x.label) }, x.label)))));
  fxBuilder();
}

function fxLabFrames(frames, label) {
  const L = FX.lab;
  L.built = { label, frames: frames.map((f) => ({ label: f.label, frame: f.frame })) };
  L.frame = frames[0].frame;
  const input = document.querySelector("[data-fx=lab-frame]");
  if (input) input.value = L.frame;
  fxLabExplain(L.frame);
}

async function fxLabExplain(text) {
  const L = FX.lab;
  const err = $("#fx-lab-error");
  const box = $("#fx-lab-inspector");
  if (!box) return;
  const my = (box._fxSeq = (box._fxSeq || 0) + 1);
  let r;
  try {
    r = await api("POST", "/api/explain", fxLabBody({ frame: text }));
  } catch (e) {
    if (box._fxSeq !== my) return;
    if (err) err.textContent = e.message;
    fxFill(box);
    return;
  }
  if (box._fxSeq !== my) return;
  if (err) err.textContent = "";
  const parts = [];
  const built = L.built && L.built.frames.some((f) => f.frame === r.explanation.candump) ? L.built : null;
  if (built && built.frames.length > 1) {
    parts.push(el("div", { class: "toolbar fx-built", dataset: { fx: "built" } }, el("span", { class: "muted" }, built.label + ":"),
      built.frames.map((f) => el("button", { type: "button", class: "chip", "aria-pressed": String(f.frame === r.explanation.candump),
        onclick: () => { L.frame = f.frame; const i = document.querySelector("[data-fx=lab-frame]"); if (i) i.value = f.frame; fxLabExplain(f.frame); } },
      f.label))));
  }
  parts.push(fxInspector(r.explanation));
  fxFill(box, ...parts);
}

function fxBuilder() {
  const L = FX.lab, F = L.form;
  const box = $("#fx-lab-builder");
  if (!box) return;
  const what = el("select", { "aria-label": "What to build", dataset: { fxBuild: "what" } },
    FX_BUILD.map(([v, l]) => el("option", { value: v, selected: L.what === v }, l)));
  what.onchange = () => { L.what = what.value; fxBuilder(); };
  const field = (key, label, attrs) => {
    const i = el("input", Object.assign({ type: "text", spellcheck: "false", dataset: { fxBuild: key }, "aria-label": label }, attrs || {}));
    i.value = F[key] != null ? F[key] : (attrs && attrs.value) || "";
    i.addEventListener("input", () => { F[key] = i.value; });
    return el("label", { class: "fx-form-field" }, label, i);
  };
  const select = (key, label, options) => {
    const s = el("select", { dataset: { fxBuild: key }, "aria-label": label }, options.map(([v, l]) => el("option", { value: v }, l)));
    if (F[key] != null && options.some(([v]) => v === F[key])) s.value = F[key]; else F[key] = s.value;
    s.onchange = () => { F[key] = s.value; if (key === "pdo") fxBuilder(); };
    return el("label", { class: "fx-form-field" }, label, s);
  };
  const nodes = (L.nodes || []).map((n) => [String(n.node), n.label]);
  const nodeField = nodes.length ? select("node", "Node", nodes) : field("node", "Node ID", { value: "1" });
  let fields = [];
  if (L.what === "sdo") {
    fields = [nodeField, field("index", "Index (hex)", { placeholder: "1017", value: "1017" }), field("subindex", "Subindex", { value: "0" }),
      select("op", "Operation", [["read", "Read"], ["write", "Write"]]),
      field("value", "Value", { placeholder: "empty: the EDS default" }), field("type", "Type", { placeholder: "from the EDS" }),
      el("label", { class: "check inline" }, (() => { const c = el("input", { type: "checkbox", checked: !!F.segmented, dataset: { fxBuild: "segmented" } }); c.onchange = () => { F.segmented = c.checked; }; return c; })(), "Segmented")];
  } else if (L.what === "pdo") {
    if (!(L.pdos || []).length) fields = [el("p", { class: "muted" }, "The configuration has no PDOs.")];
    else {
      fields = [select("pdo", "PDO", L.pdos.map((p) => [String(p.cob_id), `${p.id} ${p.name}`]))];
      const p = L.pdos.find((x) => String(x.cob_id) === F.pdo) || L.pdos[0];
      F.values = F.values && F.valuesFor === p.cob_id ? F.values : {};
      F.valuesFor = p.cob_id;
      for (const sg of p.signals) {
        const i = el("input", { type: "text", "aria-label": sg.name, dataset: { fxSignal: sg.key }, placeholder: "0" });
        i.value = F.values[sg.key] != null ? F.values[sg.key] : "";
        i.addEventListener("input", () => { F.values[sg.key] = i.value; });
        fields.push(el("label", { class: "fx-form-field" }, `${sg.name}${sg.location ? " " + sg.location : ""} (${sg.type || sg.bits + " bits"})`, i));
      }
    }
  } else if (L.what === "nmt") {
    fields = [select("command", "Command", [["start", "Start"], ["stop", "Stop"], ["preop", "Pre-operational"], ["reset", "Reset node"], ["reset-comm", "Reset communication"]]),
      field("target", "Node (0 = all)", { value: "0" })];
  } else if (L.what === "heartbeat") {
    fields = [nodeField, select("state", "State", [["operational", "Operational"], ["preop", "Pre-operational"], ["stopped", "Stopped"], ["boot-up", "Boot-up"]])];
  } else {
    fields = [nodeField, field("code", "Error code (hex)", { value: "1000" }), field("register", "Error register (hex)", { value: "01" }),
      field("manufacturer", "Manufacturer data (hex)", { placeholder: "up to 5 bytes" })];
  }
  fxFill(box, el("div", { class: "fx-form" }, el("label", { class: "fx-form-field" }, "Frame", what), fields,
    el("button", { type: "button", class: "primary", dataset: { fxBuild: "go" }, onclick: fxBuild }, "Build and explain")),
  el("div", { id: "fx-build-error", class: "fx-error", role: "status" }));
}

async function fxBuild() {
  const L = FX.lab, F = L.form;
  const body = { what: L.what };
  if (L.what === "sdo") Object.assign(body, { node: F.node || "1", index: F.index || "1017", subindex: F.subindex || "0", op: F.op || "read",
    value: F.value || "", type: F.type || "", segmented: !!F.segmented });
  else if (L.what === "pdo") Object.assign(body, { cob_id: Number(F.pdo || (L.pdos[0] || {}).cob_id), values: F.values || {} });
  else if (L.what === "nmt") Object.assign(body, { command: F.command || "start", node: F.target || 0 });
  else if (L.what === "heartbeat") Object.assign(body, { node: F.node || "1", state: F.state || "operational" });
  else Object.assign(body, { node: F.node || "1", code: F.code || "1000", register: F.register || "01", manufacturer: F.manufacturer || "" });
  const err = $("#fx-build-error");
  let r;
  try { r = await api("POST", "/api/explain/build", fxLabBody(body)); } catch (e) {
    if (err) err.textContent = e.message;
    const box = $("#fx-lab-inspector");
    if (box) { box._fxSeq = (box._fxSeq || 0) + 1; fxFill(box); }
    return;
  }
  if (err) err.textContent = "";
  fxLabFrames(r.frames, (FX_BUILD.find(([v]) => v === L.what) || [0, "Built"])[1]);
}

// -- arbitration ------------------------------------------------------------------

function fxArbitrationForm() {
  const L = FX.lab;
  const inp = (key, label) => {
    const i = el("input", { type: "text", spellcheck: "false", "aria-label": label, value: L[key], dataset: { fxArb: key } });
    i.style.width = "22ch";
    i.addEventListener("input", () => { L[key] = i.value; });
    return el("label", { class: "fx-form-field" }, label, i);
  };
  return el("div", null,
    el("p", { class: "muted" }, "When two nodes start sending at the same moment, both send their identifiers bit by bit and read the bus back. A dominant 0 overwrites a recessive 1, so the sender of a 1 that reads a 0 knows it has lost, stops and tries again after the other frame. Write two frames (ID# is enough) and see which wins."),
    el("div", { class: "fx-form" }, inp("arbA", "Frame A"), inp("arbB", "Frame B"),
      el("button", { type: "button", class: "primary", dataset: { fxArb: "go" }, onclick: fxArbitrate }, "Run both")),
    el("div", { id: "fx-arb", dataset: { fx: "arbitration" } }));
}

async function fxArbitrate() {
  const L = FX.lab;
  const out = $("#fx-arb");
  let a, b;
  try {
    [a, b] = await Promise.all([api("POST", "/api/explain", fxLabBody({ frame: L.arbA.trim() })),
      api("POST", "/api/explain", fxLabBody({ frame: L.arbB.trim() }))]);
  } catch (e) { fxFill(out, el("p", { class: "fx-error" }, e.message)); return; }
  fxFill(out, fxArbitration(a.explanation, b.explanation));
}

// Both frames side by side from the start bit until the bit that decides.
function fxArbitration(a, b) {
  const wa = a.wire.bits, wb = b.wire.bits;
  let k = 0, decided = -1;
  while (k < wa.length && k < wb.length && FX_ARBITRATION.has(wa[k].field) && FX_ARBITRATION.has(wb[k].field)) {
    if (wa[k].v !== wb[k].v) { decided = k; break; }
    k++;
  }
  const end = decided >= 0 ? decided : Math.min(k, wa.length, wb.length) - 1;
  const show = Math.min(Math.max(wa.length, wb.length), end + 3);
  const name = (m) => `${m.title} (0x${m.frame.id_text})`;
  const label = (bit) => bit.ref.startsWith("id.") ? "ID" + bit.ref.slice(3) : bit.field === "stuff" ? "stuff" : bit.field.toUpperCase();
  const W = 28, left = 74;
  const svg = fxSvg("svg", { viewBox: `0 0 ${left + show * W + 8} 116`, width: left + show * W + 8, height: 116, class: "fx-arbsvg", role: "img",
    "aria-label": `Arbitration between ${name(a)} and ${name(b)}` });
  const rows = [["A", wa], ["B", wb]];
  for (let n = 0; n < show; n++) {
    const x = left + n * W;
    const ref = wa[n] || wb[n];
    svg.append(fxSvg("text", { x: x + W / 2, y: 12, "text-anchor": "middle", class: "fx-axis" }, label(ref)));
    rows.forEach(([lbl, bits], r) => {
      const bit = bits[n];
      const stopped = decided >= 0 && n > decided && bits[decided].v === 1;
      if (!bit) return;
      svg.append(fxSvg("rect", { x, y: 20 + r * 30, width: W - 2, height: 24, rx: 2,
        class: "fx-arbcell" + (n === decided ? (bit.v ? " lost" : " won") : "") + (stopped ? " stopped" : "") }),
      fxSvg("text", { x: x + W / 2 - 1, y: 37 + r * 30, "text-anchor": "middle" }, stopped ? "–" : String(bit.v)));
    });
    const bus = (wa[n] ? wa[n].v : 1) & (wb[n] ? wb[n].v : 1);
    svg.append(fxSvg("rect", { x, y: 84, width: W - 2, height: 24, rx: 2, class: "fx-arbcell bus" + (n === decided ? " won" : "") }),
      fxSvg("text", { x: x + W / 2 - 1, y: 101, "text-anchor": "middle" }, String(bus)));
  }
  svg.append(fxSvg("text", { x: 4, y: 37, class: "fx-lane" }, "A sends"), fxSvg("text", { x: 4, y: 67, class: "fx-lane" }, "B sends"),
    fxSvg("text", { x: 4, y: 101, class: "fx-lane" }, "Bus"));
  let text;
  if (decided < 0) {
    text = a.frame.candump.split("#")[0] === b.frame.candump.split("#")[0] && a.frame.rtr === b.frame.rtr
      ? "Both frames have the same identifier, so arbitration cannot decide: both senders go on and collide in the data, which every node sees as a bit error. Two nodes must never send the same identifier."
      : "Arbitration ends without a difference in the bits shown.";
  } else {
    const winA = wa[decided].v === 0;
    const win = winA ? a : b, lose = winA ? b : a;
    const ref = wa[decided].ref;
    const where = ref.startsWith("id.") ? `identifier bit ${ref.slice(3)}` : (a.wire.fields[wa[decided].field] || {}).name || wa[decided].field;
    text = `Both send the same bits up to ${where} (wire bit ${decided}). There ${name(win)} sends a dominant 0 and ${name(lose)} a recessive 1. ` +
      `The sender of ${name(lose)} reads 0 where it sent 1, so it stops sending and tries again after the other frame. ${name(win)} wins: the lower identifier has the higher priority. ` +
      "Nothing is lost: the winning frame goes on undisturbed.";
  }
  return el("div", null, el("div", { class: "fx-scroll" }, svg), el("p", { dataset: { fx: "arb-result" } }, text));
}
