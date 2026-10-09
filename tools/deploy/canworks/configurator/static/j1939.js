"use strict";
// J1939 networks (j1939-pc-tools "J1939 network in the configurator", "J1939
// online view"): the protocol choice of a network, the J1939 network page
// (ECU identity, DBC import with a message picker, the rx, tx and request
// tables) and the network's live status in the online view. Loaded after
// app.js and uses its helpers.

const isJ1939 = (net) => !!net && net.protocol === "j1939";
// A network's j1939 object, or an empty one when the draft has none (the
// check says so); j1939Of(net, true) adds it to the draft.
function j1939Of(net, add) {
  if (net.j1939 && typeof net.j1939 === "object" && !Array.isArray(net.j1939)) return net.j1939;
  if (add) net.j1939 = { ecu: { name: {}, address: J1939_ADDRESS } };
  return add ? net.j1939 : {};
}

// A new J1939 network's ECU: NAME fields left out are 0 (false).
const J1939_ADDRESS = 128;
function newJ1939Network(bitrate) {
  return { protocol: "j1939", adapter: { type: "socketcan", bitrate: bitrate || 250000 },
    j1939: { ecu: { name: { identity_number: 1 }, address: J1939_ADDRESS }, rx: [], tx: [] } };
}

// The NAME fields: [key, label, bit offset, bits, help].
const J1939_NAME_FIELDS = [
  ["identity_number", "Identity number", 0, 21, "0 to 2097151: the ECU's serial number, unique among ECUs of one manufacturer."],
  ["manufacturer_code", "Manufacturer code", 21, 11, "0 to 2047."],
  ["ecu_instance", "ECU instance", 32, 3, "0 to 7."],
  ["function_instance", "Function instance", 35, 5, "0 to 31."],
  ["function", "Function", 40, 8, "0 to 255."],
  ["vehicle_system", "Vehicle system", 49, 7, "0 to 127."],
  ["vehicle_system_instance", "Vehicle system instance", 56, 4, "0 to 15."],
  ["industry_group", "Industry group", 60, 3, "0 to 7."],
];
const J1939_CLAIM = { 0: "claiming", 1: "claimed", 2: "cannot claim", 3: "no bus" };
const PDU2_FROM = 0xF000;

function pgnText(pgn) {
  const n = num(pgn);
  return Number.isInteger(n) ? `0x${n.toString(16).toUpperCase().padStart(4, "0")} (${n})` : String(pgn ?? "?");
}
const isPdu1 = (pgn) => Number.isInteger(num(pgn)) && ((num(pgn) >> 8) & 0xFF) < 0xF0;

// Typed text as the config takes it: integers (decimal or 0x hex), real numbers.
function intValue(t) {
  if (/^-?[0-9]+$/.test(t)) return parseInt(t, 10);
  if (/^0x[0-9a-f]+$/i.test(t)) return parseInt(t, 16);
  return t;
}
function realValue(t) { return /^-?([0-9]+\.?[0-9]*|\.[0-9]+)(e[-+]?[0-9]+)?$/i.test(t) ? Number(t) : t; }

// The 64-bit NAME of the draft's NAME fields, as 0x hex.
function j1939NameHex(name) {
  name = name || {};
  let v = 0n;
  for (const [key, , shift, bits] of J1939_NAME_FIELDS) {
    const f = num(name[key]);
    if (Number.isInteger(f) && f >= 0 && f < 2 ** bits) v |= BigInt(f) << BigInt(shift);
  }
  if (name.arbitrary_address_capable === true) v |= 1n << 63n;
  return "0x" + v.toString(16).toUpperCase().padStart(16, "0");
}

// The NAME fields of a 0x hex or decimal NAME, or null.
function j1939NameFields(text) {
  let v;
  try { v = BigInt(text); } catch (e) { return null; }
  const out = {};
  for (const [key, , shift, bits] of J1939_NAME_FIELDS) out[key] = Number((v >> BigInt(shift)) & ((1n << BigInt(bits)) - 1n));
  out.arbitrary_address_capable = (v >> 63n) === 1n;
  return out;
}

// -- protocol -----------------------------------------------------------------

function protocolField() {
  return el("fieldset", null, el("legend", null, "Protocol"),
    el("div", { class: "grid" }, choice("This network runs", "protocol", [
      { value: undefined, label: "CANopen", help: "Default. A CANopen master with its nodes, or a CANopen slave device." },
      { value: "j1939", label: "J1939", help: "The PLC is an ECU on a J1939 network: it claims an address, receives and sends parameter groups (PGNs), usually from a DBC file." },
    ], { onChange: switchProtocol, dataset: { j1939: "protocol" } })));
}

// Switching drops the other protocol's settings (asked first when there are any).
async function switchProtocol(protocol) {
  const net = S.config;
  if ((protocol === "j1939") === isJ1939(net)) return;
  const label = netLabel(net, S.net);
  if (protocol === "j1939") {
    const k = (net.nodes || []).length;
    if (k || isSlave(net)) {
      const v = await modal(`Make network ${label} a J1939 network? Its CANopen settings` +
        (k ? ` and its ${k} node${k === 1 ? "" : "s"}` : "") + " are dropped. Their EDS files stay in the folder.",
      [["j1939", "Make it J1939", true], ["cancel", "Cancel"]]);
      if (v !== "j1939") { render(); return; }
    }
    const fresh = newJ1939Network();
    for (const key of ["role", "master", "nodes", "slave"]) delete net[key];
    if (net.adapter) delete net.adapter.simulate;
    net.protocol = "j1939";
    net.j1939 = fresh.j1939;
  } else {
    const j = net.j1939 || {};
    if ((j.rx || []).length || (j.tx || []).length || (j.requests || []).length) {
      const v = await modal(`Make network ${label} a CANopen network? Its ECU and messages are dropped. The DBC file stays in the folder.`,
        [["canopen", "Make it CANopen", true], ["cancel", "Cancel"]]);
      if (v !== "canopen") { render(); return; }
    }
    delete net.protocol;
    delete net.j1939;
    net.master = { node_id: 1, sync_period_us: 10000 };
    net.nodes = [];
  }
  changed(true);
}

// -- the network page ---------------------------------------------------------------

function renderJ1939(view) {
  const j = j1939Of(S.config);
  view.append(
    el("h2", null, "Bus and ECU" + (several() ? `: network ${netLabel(S.config, S.net)}` : "")),
    el("span", { class: "field-msg", dataset: { for: "j1939" } }),
    protocolField(),
    adapterFieldset(),
    j1939Ecu(),
    j1939Dbc(j),
    j1939Messages("rx"),
    j1939Messages("tx"),
    j1939Requests(),
    onlineAccessSettings());
}

// A Suggest button that fills `path` with a free location from /api/place.
function suggestButton(path, direction, type, label) {
  return el("button", { type: "button", class: "small", dataset: { suggest: path }, title: "A free location",
    "aria-label": label ? `Suggest a location for ${label}` : null,
    onclick: async () => {
      try {
        const r = await api("POST", "/api/place", { config: fileConfig(), network: S.net, direction, type });
        setPath(path, r.location);
        render();
      } catch (e) { banner(e.message, true); }
    } }, "Suggest");
}

function locationField(label, path, direction, placeholder, help) {
  return el("label", null, label, el("span", { class: "row" },
    field("", path, "text", { placeholder }).querySelector("input"), suggestButton(path, direction, undefined, label)),
  hint(help), el("span", { class: "field-msg", dataset: { for: path } }), declNote(path));
}

function j1939Ecu() {
  const base = "j1939.ecu";
  const nameOut = el("output", { class: "mono", dataset: { j1939: "name" } }, j1939NameHex(getPath(base + ".name")));
  const range = getPath(base + ".address_range");
  const lo = el("input", { type: "text", spellcheck: "false", placeholder: "low", "aria-label": "Address range low", dataset: { path: base + ".address_range[0]" } });
  const hi = el("input", { type: "text", spellcheck: "false", placeholder: "high", "aria-label": "Address range high", dataset: { path: base + ".address_range[1]" } });
  if (Array.isArray(range)) { lo.value = range[0] ?? ""; hi.value = range[1] ?? ""; }
  const setRange = () => {
    const a = lo.value.trim(), b = hi.value.trim();
    setPath(base + ".address_range", a === "" && b === "" ? undefined : [intValue(a), intValue(b)]);
  };
  lo.addEventListener("input", setRange);
  hi.addEventListener("input", setRange);
  const fs = el("fieldset", { dataset: { section: "ecu" } }, el("legend", null, "ECU identity"),
    el("p", { class: "muted" }, "The PLC's own ECU: its NAME, which it claims its address with, and the address it prefers."),
    el("div", { class: "grid" },
      field("Preferred address", base + ".address", "int", { parse: intValue, placeholder: String(J1939_ADDRESS),
        hint: "Required, 0 to 253: the source address the ECU claims." }),
      el("label", null, "Address range", el("span", { class: "row" }, lo, "to", hi),
        hint("Optional: the addresses the ECU may move to when a lower NAME takes its address. Needs Arbitrary address capable."),
        el("span", { class: "field-msg", dataset: { for: base + ".address_range" } })),
      locationField("Claim state", base + ".state_location", "j1939_state", "%IB…",
        "Byte input: 0 claiming, 1 claimed, 2 cannot claim, 3 no bus. Empty: none."),
      locationField("Current address", base + ".address_location", "j1939_address", "%IB…",
        "Byte input: the address the ECU holds (254 while it holds none). Empty: none.")),
    el("h3", null, "NAME"),
    el("div", { class: "grid" },
      J1939_NAME_FIELDS.map(([key, label, , , help]) => field(label, `${base}.name.${key}`, "int", { parse: intValue, placeholder: "0", hint: help })),
      checkbox("Arbitrary address capable", base + ".name.arbitrary_address_capable", false,
        "On: the ECU may claim another address of its range when it loses its own."),
      el("label", null, "NAME value", nameOut, hint("The 64-bit NAME these fields make, as the ECU sends it."))));
  const refresh = () => { nameOut.textContent = j1939NameHex(getPath(base + ".name")); };
  fs.addEventListener("input", refresh);
  fs.addEventListener("change", refresh);
  return fs;
}

// -- DBC import ---------------------------------------------------------------------

function j1939Dbc(j) {
  const input = el("input", { type: "file", accept: ".dbc,.DBC", dataset: { j1939: "dbc-input" } });
  input.addEventListener("change", () => { const f = input.files[0]; input.value = ""; if (f) importDbc(f); });
  return el("fieldset", { dataset: { section: "dbc" } }, el("legend", null, "DBC file"),
    el("p", null, j.dbc ? ["Messages come from ", el("strong", { dataset: { j1939: "dbc" } }, j.dbc), "."]
      : el("span", { class: "muted", dataset: { j1939: "dbc" } }, "No DBC file yet.")),
    el("div", { class: "toolbar" },
      el("label", { class: "file-button" }, "Import DBC…", input),
      j.dbc ? el("button", { type: "button", dataset: { j1939: "pick" }, onclick: () => pickFromDbc(j.dbc) }, "Pick messages…") : null),
    hint("Import copies the DBC file into the config folder when you save, then lists its messages: mark each to receive or to send. " +
      "Each signal gets a free PLC location of the right size."));
}

async function importDbc(file) {
  const data = await fileBase64(file);
  let res;
  try {
    res = await api("POST", "/api/j1939/dbc", { name: file.name, data });
  } catch (e) {
    if (e.status === 409 && e.body.conflict) {
      const v = await modal(e.message + ". Replace it, or keep both under a new name?",
        [["cancel", "Cancel"], ["replace", "Replace", { danger: true }], ["keep_both", "Keep both", true]]);
      if (!v || v === "cancel") return;
      try { res = await api("POST", "/api/j1939/dbc", { name: file.name, data, on_conflict: v }); } catch (e2) { banner(e2.message, true); return; }
    } else {
      banner(e.message, true);
      return;
    }
  }
  return pickMessages(res);
}

async function pickFromDbc(name) {
  try { return pickMessages(await api("POST", "/api/j1939/dbc", { name })); } catch (e) { banner(e.message, true); }
}

// Whether a DBC message comes from the PLC's own ECU: its source address,
// or a sender named PLC or like the network.
function fromEcu(m) {
  const ecu = getPath("j1939.ecu") || {};
  const sender = (m.sender || "").toLowerCase();
  return m.source === num(ecu.address) || sender === "plc" || (sender !== "" && sender === netName(S.config).toLowerCase());
}

// The message picker: receive, send or leave out each message of the DBC.
async function pickMessages(res) {
  const j = j1939Of(S.config, true);
  const have = { rx: new Set((j.rx || []).map((e) => num(e.pgn))), tx: new Set((j.tx || []).map((e) => num(e.pgn))) };
  const rows = res.messages.map((m, i) => {
    const already = have.rx.has(m.pgn) ? "rx" : have.tx.has(m.pgn) ? "tx" : null;
    const sel = el("select", { "aria-label": `${m.name}: receive, send or leave out`, dataset: { pick: m.name } },
      el("option", { value: "" }, "Leave out"), el("option", { value: "rx" }, "Receive"), el("option", { value: "tx" }, "Send"));
    sel.value = already ? "" : fromEcu(m) ? "tx" : "rx";
    return { m, i, sel, row: el("tr", null,
      el("td", null, el("strong", null, m.name), m.comment ? el("div", { class: "hint" }, m.comment) : null),
      el("td", { class: "mono" }, pgnText(m.pgn)),
      el("td", null, m.sender || "", m.source !== undefined ? el("span", { class: "muted" }, ` (address ${m.source})`) : null),
      el("td", null, `${m.length} B`, m.cycle_ms ? el("div", { class: "muted" }, `every ${m.cycle_ms} ms`) : null),
      el("td", null, m.signals.join(", ")),
      el("td", null, sel, already ? el("div", { class: "muted" }, `already in ${already === "rx" ? "received" : "sent"} PGNs`) : null)) };
  });
  const extra = el("div", { class: "j1939-picker" },
    el("table", null, el("thead", null, el("tr", null, thCells(["Message", "PGN", "Sender", "Length", "Signals", "PLC"]))),
      el("tbody", null, rows.map((r) => r.row))),
    res.problems && res.problems.length ? el("details", { class: "muted" }, el("summary", null, `Left out of the import (${res.problems.length})`),
      el("ul", null, res.problems.map((p) => el("li", null, p)))) : null);
  const v = await modal(`${res.name}: ${res.messages.length} J1939 message${res.messages.length === 1 ? "" : "s"}. ` +
    "Receive takes a message into %I inputs, Send sends it from %Q outputs. Send is preselected for messages from this ECU.",
  [["cancel", "Cancel"], ["add", "Add picked messages", true]], extra);
  if (v !== "add") return;
  const picks = rows.filter((r) => r.sel.value).map((r) => ({ index: r.i, direction: r.sel.value }));
  try {
    const out = picks.length ? await api("POST", "/api/j1939/entries", { config: fileConfig(), network: S.net, name: res.name, picks }) : { entries: [] };
    const count = { rx: 0, tx: 0 };
    for (const { direction, entry } of out.entries) {
      (j[direction] = j[direction] || []).push(entry);
      count[direction]++;
    }
    j.dbc = res.name;
    banner(`Added ${count.rx} received and ${count.tx} sent PGN${count.rx + count.tx === 1 ? "" : "s"} from ${res.name}.`);
    changed(true);
  } catch (e) { banner(e.message, true); }
}

// -- rx and tx tables ---------------------------------------------------------------

// An input of a table cell bound to `path`.
function cellInput(path, label, parse, placeholder) {
  const input = el("input", { type: "text", spellcheck: "false", dataset: { path }, "aria-label": label, placeholder });
  const v = getPath(path);
  input.value = v === undefined || v === null ? "" : String(v);
  input.addEventListener("input", () => {
    const t = input.value.trim();
    setPath(path, t === "" ? undefined : parse ? parse(t) : t);
  });
  return input;
}

function cell(input, path) {
  return el("td", null, input, el("span", { class: "field-msg", dataset: { for: path } }), declNote(path));
}

const J1939_DIR = {
  rx: { title: "Received PGNs (rx)", one: "Received PGN", area: "%I",
    text: "Parameter groups the PLC receives: each signal arrives as a raw integer in its %I location; scale, offset and unit are for the declarations and the tools." },
  tx: { title: "Sent PGNs (tx)", one: "Sent PGN", area: "%Q",
    text: "Parameter groups the PLC sends from its %Q locations: periodically, on change, and when another ECU requests them." },
};

function j1939Messages(dir) {
  const d = J1939_DIR[dir];
  const list = getPath("j1939." + dir) || [];
  const fs = el("fieldset", { dataset: { section: "j1939-" + dir, path: "j1939." + dir } }, el("legend", null, d.title),
    el("p", { class: "muted" }, d.text),
    el("span", { class: "field-msg", dataset: { for: "j1939." + dir } }));
  list.forEach((m, i) => fs.append(j1939Message(dir, m, i)));
  if (!list.length) fs.append(el("p", { class: "muted" }, "None yet: import a DBC file, or add one by hand."));
  fs.append(el("div", { class: "toolbar" }, el("button", { type: "button", dataset: { j1939Add: dir }, onclick: () => addMessage(dir) },
    dir === "rx" ? "Add received PGN" : "Add sent PGN")));
  return fs;
}

function j1939Message(dir, m, i) {
  const base = `j1939.${dir}[${i}]`;
  const signals = Array.isArray(m.signals) ? m.signals : [];
  const grid = dir === "rx" ? [
    field("Source address", base + ".source", "int", { parse: intValue, placeholder: "any", hint: "Take the PGN only from this address, 0 to 253. Empty: from any ECU." }),
    field("Source NAME", base + ".source_name", "text", { placeholder: "any", hint: "Or take it only from the ECU with this NAME (0x hex or decimal), wherever it claimed its address." }),
    m.source_name !== undefined ? field("NAME mask", base + ".source_name_mask", "text", { placeholder: "all bits", hint: "The NAME bits to compare. Empty: all." }) : null,
    field("Timeout (ms)", base + ".timeout_ms", "int", { parse: intValue, placeholder: "none", hint: "The status input goes FALSE when no message arrived for this long. Empty or 0: no supervision." }),
    locationField("Status", base + ".status_location", "j1939_status", "%IX…", "Bit input: TRUE while the PGN arrives in time. Empty: none."),
  ] : [
    field("Priority", base + ".priority", "int", { parse: intValue, placeholder: "6", hint: "0 (highest) to 7. Default 6." }),
    isPdu1(m.pgn) ? field("Destination", base + ".destination", "int", { parse: intValue, placeholder: "255 (global)", hint: "0 to 253, or 255 for every ECU." }) : null,
    field("Length (bytes)", base + ".length", "int", { parse: intValue, placeholder: "auto", hint: "Empty: the smallest length of at least 8 that holds every signal; over 8 goes by the transport protocol." }),
    field("Period (ms)", base + ".period_ms", "int", { parse: intValue, placeholder: "0", hint: "0: send on change and on request only." }),
    field("Least gap (ms)", base + ".min_gap_ms", "int", { parse: intValue, placeholder: "0", hint: "The least time between two sends on change." }),
  ];
  const rows = signals.map((s, k) => j1939Signal(dir, base, s, k));
  return el("div", { class: "pdo j1939-msg", dataset: { path: base, j1939Msg: `${dir}:${i}` } },
    el("div", { class: "pdo-title" },
      el("strong", null, `PGN ${pgnText(m.pgn)}${m.name ? " " + m.name : ""}`),
      el("span", { class: "muted" }, `${signals.length} signal${signals.length === 1 ? "" : "s"}`),
      el("span", { class: "field-msg", dataset: { for: base } }),
      el("button", { type: "button", class: "small", "aria-label": `Remove PGN ${num(m.pgn)}`, dataset: { j1939Remove: `${dir}:${i}` },
        onclick: () => { getPath("j1939." + dir).splice(i, 1); changed(true); } }, "Remove")),
    el("div", { class: "pdo-grid" },
      field("PGN", base + ".pgn", "int", { parse: intValue, hint: "Decimal or 0x hex. A PDU1 PGN (below 0xF000) has its low byte 0." }),
      field("Name", base + ".name", "text", { placeholder: "none" }),
      ...grid),
    el("div", { class: "table-scroll" }, el("table", { class: "j1939-signals" },
      el("thead", null, el("tr", null, thCells(["Signal", "Start bit", "Bits", "Byte order", "Signed", "Scale", "Offset", "Unit", ""]))),
      el("tbody", null, rows.length ? rows.flat() : el("tr", null, el("td", { colspan: 9, class: "muted" }, "No signals."))))),
    el("button", { type: "button", class: "small", dataset: { j1939AddSignal: `${dir}:${i}` }, onclick: () => addSignal(dir, i) }, "Add signal"));
}

function j1939Signal(dir, base, s, k) {
  const sp = `${base}.signals[${k}]`;
  const order = el("select", { "aria-label": `Byte order of ${s.name || "signal"}`, dataset: { path: sp + ".byte_order" } },
    el("option", { value: "" }, "little"), el("option", { value: "big" }, "big"));
  order.value = s.byte_order === "big" ? "big" : "";
  order.addEventListener("change", () => setPath(sp + ".byte_order", order.value || undefined));
  const signed = el("input", { type: "checkbox", "aria-label": `${s.name || "signal"} is signed`, dataset: { path: sp + ".signed" } });
  signed.checked = s.signed === true;
  signed.addEventListener("change", () => setPath(sp + ".signed", signed.checked || undefined));
  const who = s.name || `signal ${k + 1}`;
  // Two lines per signal, so the table fits next to Problems: the layout,
  // then the PLC locations with their labels.
  const loc = (label, input, button, path) => el("div", null, el("span", { class: "hint" }, label),
    el("span", { class: "row" }, input, button),
    el("span", { class: "field-msg", dataset: { for: path } }), declNote(path));
  return [el("tr", { dataset: { path: sp } },
    el("td", null, cellInput(sp + ".name", "Signal name", null), el("span", { class: "field-msg", dataset: { for: sp } }),
      el("span", { class: "field-msg", dataset: { for: sp + ".name" } })),
    cell(cellInput(sp + ".start_bit", `Start bit of ${who}`, intValue), sp + ".start_bit"),
    cell(cellInput(sp + ".length", `Bits of ${who}`, intValue), sp + ".length"),
    cell(order, sp + ".byte_order"),
    el("td", null, signed),
    cell(cellInput(sp + ".scale", `Scale of ${who}`, realValue, "1"), sp + ".scale"),
    cell(cellInput(sp + ".offset", `Offset of ${who}`, realValue, "0"), sp + ".offset"),
    cell(cellInput(sp + ".unit", `Unit of ${who}`, null), sp + ".unit"),
    el("td", null, el("button", { type: "button", title: "Remove", "aria-label": `Remove signal ${who}`,
      onclick: () => { getPath(base + ".signals").splice(k, 1); changed(true); } }, "✕"))),
  el("tr", { class: "j1939-locations" }, el("td", { colspan: 9 }, el("div", { class: "j1939-locs" },
    loc("PLC location", cellInput(sp + ".iec_location", `PLC location of ${who}`, null, J1939_DIR[dir].area + "…"),
      suggestButton(sp + ".iec_location", "j1939_" + dir, s.length, who), sp + ".iec_location"),
    dir === "rx" ? loc("Valid input", cellInput(sp + ".valid_location", `Valid input of ${who}`, null, "%IX…"),
      suggestButton(sp + ".valid_location", "j1939_valid", undefined, who + " valid"), sp + ".valid_location") : null)))];
}

// A message by hand: the first proprietary PGN (0xFF00 up) the direction has not.
function addMessage(dir) {
  const j = j1939Of(S.config, true);
  const list = j[dir] = j[dir] || [];
  let pgn = 0xFF00;
  while (list.some((m) => num(m.pgn) === pgn) && pgn < 0xFFFF) pgn++;
  list.push(dir === "rx" ? { pgn, signals: [] } : { pgn, period_ms: 100, signals: [] });
  changed(true);
}

// A signal by hand: 8 bits after the message's last signal, at a free location.
async function addSignal(dir, i) {
  const m = S.config.j1939[dir][i];
  m.signals = m.signals || [];
  const start = m.signals.reduce((end, s) => Math.max(end, (num(s.start_bit) || 0) + (num(s.length) || 0)), 0);
  const sig = { name: `Signal${m.signals.length + 1}`, start_bit: start, length: 8 };
  try {
    sig.iec_location = (await api("POST", "/api/place", { config: fileConfig(), network: S.net, direction: "j1939_" + dir, type: 8 })).location;
  } catch (e) { banner(e.message, true); }
  m.signals.push(sig);
  changed(true);
}

// -- requests ---------------------------------------------------------------------

function j1939Requests() {
  const list = getPath("j1939.requests") || [];
  const rows = list.map((q, i) => {
    const qp = `j1939.requests[${i}]`;
    return el("tr", { dataset: { path: qp } },
      cell(cellInput(qp + ".pgn", "Requested PGN", intValue), qp + ".pgn"),
      cell(cellInput(qp + ".destination", "Request destination", intValue, "255 (global)"), qp + ".destination"),
      cell(cellInput(qp + ".period_ms", "Request period (ms)", intValue), qp + ".period_ms"),
      el("td", null, el("span", { class: "field-msg", dataset: { for: qp } }),
        el("button", { type: "button", title: "Remove", "aria-label": `Remove the request of PGN ${num(q.pgn)}`,
          onclick: () => { list.splice(i, 1); if (!list.length) delete S.config.j1939.requests; changed(true); } }, "✕")));
  });
  return el("fieldset", { dataset: { section: "j1939-requests", path: "j1939.requests" } }, el("legend", null, "Requests"),
    el("p", { class: "muted" }, "PGNs the PLC asks for periodically (Request, PGN 59904), such as data an ECU sends only on request. The answers arrive like any received PGN, so add the PGN to the received ones too."),
    rows.length ? el("table", null, el("thead", null, el("tr", null, thCells(["PGN", "Destination", "Every (ms, 100 to 600000)", ""]))),
      el("tbody", null, rows)) : el("p", { class: "muted" }, "No requests."),
    el("div", { class: "toolbar" }, el("button", { type: "button", dataset: { j1939Add: "requests" }, onclick: () => {
      const j = j1939Of(S.config, true);
      const rx = (j.rx || []).find((m) => !(j.requests || []).some((q) => num(q.pgn) === num(m.pgn)));
      (j.requests = j.requests || []).push({ pgn: rx ? rx.pgn : 0xFF00, period_ms: 1000 });
      changed(true);
    } }, "Add request")));
}

// Where a J1939 check path is, in the page's words (placeOf()).
function j1939Place(net, path) {
  const j = (net && net.j1939) || {};
  if (path.startsWith("j1939.ecu")) return ["ECU identity"];
  const m = /^j1939\.(rx|tx|requests)\[(\d+)\](?:\.signals\[(\d+)\])?/.exec(path);
  if (!m) return ["J1939"];
  const entry = (j[m[1]] || [])[Number(m[2])] || {};
  if (m[1] === "requests") return [`Request of PGN ${num(entry.pgn) || "?"}`];
  const parts = [`${J1939_DIR[m[1]].one} ${num(entry.pgn) || "?"}${entry.name ? " " + entry.name : ""}`];
  const s = m[3] !== undefined ? (entry.signals || [])[Number(m[3])] : null;
  if (s) parts.push(`signal ${s.name || Number(m[3]) + 1}`);
  return parts;
}

// -- online view --------------------------------------------------------------------

// A received signal's value in the config's terms: raw x scale + offset and unit.
function signalText(sig, conf) {
  const raw = Number(sig.raw);
  if (!conf || !Number.isFinite(raw)) return `${sig.name} = ${sig.raw}`;
  const scale = Number.isFinite(conf.scale) ? conf.scale : 1;
  const offset = Number.isFinite(conf.offset) ? conf.offset : 0;
  const value = Number((raw * scale + offset).toPrecision(12));
  return `${sig.name} = ${value}${conf.unit ? " " + conf.unit : ""}` + (scale !== 1 || offset !== 0 ? ` (raw ${sig.raw})` : "");
}

function ageText(ms) { return ms === null || ms === undefined ? "never" : ms >= 10000 ? `${Math.round(ms / 1000)} s` : `${ms} ms`; }

// The draft's rx entry a status row is about: same PGN and source filter.
function configRx(rows, row) {
  const same = rows.filter((m) => num(m.pgn) === row.pgn);
  return same.find((m) => (m.source ?? null) === (row.source ?? null) && (m.source_name ?? null) === (row.source_name ?? null)) || same[0] || null;
}

function nameCell(text) {
  const f = j1939NameFields(text);
  return el("td", { class: "mono", title: f ? `identity ${f.identity_number}, manufacturer ${f.manufacturer_code}, function ${f.function}, ` +
    `industry group ${f.industry_group}${f.arbitrary_address_capable ? ", arbitrary address capable" : ""}` : null }, text || "?");
}

function j1939Live(st) {
  const j = st.j1939 || {};
  const bus = st.bus || {};
  const conf = onlineConfig().j1939 || {};
  const name = (list, pgn) => { const m = (list || []).find((x) => num(x.pgn) === pgn); return m && m.name ? m.name : ""; };
  const f = j1939NameFields(j.name);
  const ecus = (j.ecus || []).map((e) => el("tr", { dataset: { j1939Ecu: e.address }, class: e.address === j.address ? "active" : null },
    el("td", null, String(e.address), e.address === j.address ? el("span", { class: "tag" }, "this PLC") : null),
    nameCell(e.name), el("td", null, ageText(e.age_ms))));
  const rx = (j.rx || []).map((row) => {
    const c = configRx(conf.rx || [], row);
    const filter = row.source !== undefined ? `address ${row.source}` : row.source_name
      ? `NAME ${row.source_name}${row.source_name_mask ? " mask " + row.source_name_mask : ""}` : "any";
    const sigs = (row.signals || []).map((s) => {
      const sc = c ? (c.signals || []).find((x) => x.name === s.name) : null;
      return el("div", { class: s.valid === false ? "bad" : null, dataset: { j1939Signal: s.name } },
        signalText(s, sc) + (s.valid === false ? ", not available" : ""));
    });
    return el("tr", { dataset: { j1939Rx: row.pgn } },
      el("td", { class: "mono" }, pgnText(row.pgn)), el("td", null, c && c.name ? c.name : ""),
      el("td", null, filter), el("td", null, (row.sources || []).join(", ") || "none yet"),
      el("td", null, String(row.count ?? 0)), el("td", null, ageText(row.age_ms)),
      el("td", { class: row.timed_out ? "bad" : null, dataset: { j1939Timeout: row.pgn } },
        row.timed_out ? "timed out" : "in time", row.timeouts ? el("span", { class: "muted" }, ` (${row.timeouts} timeout${row.timeouts === 1 ? "" : "s"})`) : null),
      el("td", null, sigs.length ? sigs : el("span", { class: "muted" }, "no values yet")));
  });
  const tx = (j.tx || []).map((row) => el("tr", { dataset: { j1939Tx: row.pgn } },
    el("td", { class: "mono" }, pgnText(row.pgn)), el("td", null, name(conf.tx, row.pgn)),
    el("td", null, String(row.sent ?? 0)), el("td", null, String(row.requests_answered ?? 0))));
  const req = (j.requests || []).map((row) => el("tr", { dataset: { j1939Request: row.pgn } },
    el("td", { class: "mono" }, pgnText(row.pgn)), el("td", null, name(conf.rx, row.pgn)), el("td", null, String(row.sent ?? 0))));
  const none = (n, text) => [el("tr", null, el("td", { colspan: n, class: "muted" }, text))];
  const state = j.state_name || J1939_CLAIM[j.state] || String(j.state ?? "?");
  $("#online-live").replaceChildren(
    el("table", { class: "online-bus" }, el("tbody", null,
      el("tr", null, el("th", null, "Bus"), el("td", { dataset: { online: "bus" } }, `${bus.interface || "?"}: ${BUS_STATES[bus.state] || bus.state || "?"}`),
        el("th", null, "TX / RX errors"), el("td", null, `${bus.tx_errors ?? "-"} / ${bus.rx_errors ?? "-"}`),
        el("th", null, "Bus-off"), el("td", null, String(bus.bus_off_count ?? "-"))),
      el("tr", null, el("th", null, "ECU"),
        el("td", { class: "j1939-claim-" + j.state, dataset: { j1939: "claim" } }, `${state}, address ${j.address === 254 || j.address === undefined ? "none" : j.address}`),
        el("th", null, "NAME"), el("td", { class: "mono", colspan: 3, dataset: { j1939: "name" } }, j.name || "?",
          f ? el("span", { class: "muted" }, ` (identity ${f.identity_number}, function ${f.function})`) : null)))),
    el("h3", null, "ECUs on the bus"),
    el("table", { class: "online-nodes", dataset: { j1939: "ecus" } },
      el("thead", null, el("tr", null, thCells(["Address", "NAME", "Last claim"]))),
      el("tbody", null, ecus.length ? ecus : none(3, "No ECU has claimed an address yet."))),
    el("h3", null, "Received PGNs"),
    el("table", { class: "online-nodes", dataset: { j1939: "rx" } },
      el("thead", null, el("tr", null, thCells(["PGN", "Name", "Filter", "From", "Messages", "Age", "Timeout", "Signals"]))),
      el("tbody", null, rx.length ? rx : none(8, "No received PGNs in the configuration the runtime runs."))),
    el("h3", null, "Sent PGNs"),
    el("table", { class: "online-nodes", dataset: { j1939: "tx" } },
      el("thead", null, el("tr", null, thCells(["PGN", "Name", "Sent", "Requests answered"]))),
      el("tbody", null, tx.length ? tx : none(4, "No sent PGNs."))),
    req.length ? el("h3", null, "Requests") : null,
    req.length ? el("table", { class: "online-nodes", dataset: { j1939: "requests" } },
      el("thead", null, el("tr", null, thCells(["PGN", "Name", "Requests sent"]))), el("tbody", null, req)) : null);
}
