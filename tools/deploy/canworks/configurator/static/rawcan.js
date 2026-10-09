// CAN messages page (canopen-configurator "CAN messages page";
// docs/raw-can.md): the received and sent raw messages of the open network,
// their signals and bit layout, Suggest addresses, Import DBC and Copy as ST
// call. Loaded after app.js and uses its helpers (el, api, banner, modal,
// field, checkbox, choice, getPath, setPath, changed, render, S, ...).
"use strict";

const RAW_KINDS = [["rx", "Received messages", "Messages the PLC reads from the bus. Their signals go to %I."],
  ["tx", "Sent messages", "Messages the PLC sends. Their signals come from %Q."]];
const RAW_STD_MAX = 0x7FF;
const RAW_EXT_MAX = 0x1FFFFFFF;
const RAW_COLORS = 8;

function rawHex(v) { return typeof v === "number" ? "0x" + v.toString(16).toUpperCase() : v; }
function rawParseHex(t) {
  if (/^0x[0-9a-f]+$/i.test(t)) return parseInt(t.slice(2), 16);
  if (/^[0-9]+$/.test(t)) return parseInt(t, 10);
  return t;
}

// The bits a signal covers, as bit numbers of the frame (bit 0 = LSB of byte
// 0), with DBC numbering; the same walk as canworks/raw/signals.py.
function rawBits(start, length, big) {
  const out = [];
  let pos = start;
  for (let i = 0; i < length; i++) {
    out.push(pos);
    if (big) pos = pos % 8 === 0 ? pos + 15 : pos - 1;
    else pos += 1;
  }
  return out;
}

function rawEntry(kind, i) { return ((getPath("raw." + kind) || [])[i]) || null; }

function rawTiming(kind, m) {
  if (kind === "rx") return m.timeout_ms ? `timeout ${m.timeout_ms} ms` : "no timeout";
  const parts = [];
  if (m.period_ms) parts.push(`every ${m.period_ms} ms`);
  if (m.on_change) parts.push("on change");
  if (m.trigger_location) parts.push("on trigger");
  return parts.join(", ") || "never (needs a period, on change or a trigger)";
}

function rawAdd(kind, entry) {
  const list = (getPath("raw." + kind) || []).slice();
  list.push(entry);
  setPath("raw." + kind, list);
  S.rawOpen = { kind, index: list.length - 1 };
  changed(true);
}

function rawRemove(kind, i) {
  const list = (getPath("raw." + kind) || []).slice();
  list.splice(i, 1);
  setPath("raw." + kind, list.length ? list : undefined);
  if (S.rawOpen && S.rawOpen.kind === kind) S.rawOpen = null;
  if (!getPath("raw.rx") && !getPath("raw.tx") && !getPath("raw.dbc") && !getPath("raw.program_override_protocol")) {
    setPath("raw", undefined);
  }
  changed(true);
}

function renderCanMessages(view) {
  const none = getPath("protocol") === "none";
  const listenOnly = getPath("adapter.listen_only") === true;
  view.append(
    el("h2", null, "CAN messages" + (several() ? `: network ${netLabel(S.config, S.net)}` : "")),
    el("p", { class: "muted" }, none
      ? "A plain CAN network: only the messages below run on it."
      : "Plain CAN messages next to the network's protocol, for devices that speak neither CANopen nor J1939. " +
        "Identifiers the protocol uses need Override protocol on the message."),
    el("fieldset", null, el("legend", null, "Network"),
      el("div", { class: "grid" },
        none ? checkbox("Listen only", "adapter.listen_only", false,
          "The PLC only watches the bus: it never acknowledges or sends a frame. Sent messages are not allowed then.") : null,
        field("DBC file", "raw.dbc", "text", { placeholder: "none",
          hint: "The DBC file the messages came from, next to canworks.json. The bus trace decodes its messages too." }),
        none ? null : checkbox("Program may send protocol identifiers", "raw.program_override_protocol", false,
          "On: CAN_SEND and CAN_SEND_CYCLIC may use identifiers the protocol owns (ERROR_ID 4 otherwise)."))),
    el("div", { class: "row" },
      el("button", { type: "button", id: "raw-import", onclick: rawImportDbc }, "Import DBC…")));
  for (const [kind, title, help] of RAW_KINDS) {
    if (kind === "tx" && listenOnly) {
      view.append(el("h3", null, title), el("p", { class: "muted" }, "None: the network is listen-only."));
      continue;
    }
    const list = getPath("raw." + kind) || [];
    const rows = list.map((m, i) => {
      const open = S.rawOpen && S.rawOpen.kind === kind && S.rawOpen.index === i;
      return el("tr", rowAttrs(() => { S.rawOpen = open ? null : { kind, index: i }; render(); },
        { class: open ? "selected" : null, dataset: { raw: `${kind}:${i}` }, "aria-expanded": String(open) }),
        el("td", null, m.name || el("span", { class: "muted" }, "(no name)")),
        el("td", { class: "mono" }, rawHex(m.id) + (m.extended ? " ext" : "") + (kind === "rx" && m.mask !== undefined ? ` / ${rawHex(m.mask)}` : "")),
        el("td", null, m.rtr ? "remote" : m.dlc ?? ""),
        el("td", null, rawTiming(kind, m)),
        el("td", null, String((m.signals || []).length)),
        el("td", null, el("button", { type: "button", class: "danger", "aria-label": "Remove " + (m.name || rawHex(m.id)),
          onclick: (e) => { e.stopPropagation(); rawRemove(kind, i); } }, "Remove")));
    });
    view.append(el("h3", null, title), el("p", { class: "muted" }, help),
      el("table", { class: "od raw-table", dataset: { rawTable: kind } },
        el("thead", null, el("tr", null, thCells(["Name", "Identifier", "DLC", kind === "rx" ? "Timeout" : "Sent", "Signals", ""]))),
        el("tbody", null, rows.length ? rows : el("tr", null, el("td", { colspan: "6", class: "muted" }, "None yet")))),
      el("button", { type: "button", dataset: { rawAdd: kind },
        onclick: () => rawAdd(kind, kind === "rx" ? { name: "", id: 0, dlc: 8 } : { name: "", id: 0, dlc: 8, period_ms: 100 }) },
        kind === "rx" ? "Add received message" : "Add sent message"));
    if (S.rawOpen && S.rawOpen.kind === kind && rawEntry(kind, S.rawOpen.index)) {
      view.append(rawEditor(kind, S.rawOpen.index));
    }
  }
}

function rawEditor(kind, i) {
  const base = `raw.${kind}[${i}]`;
  const m = rawEntry(kind, i);
  const idField = field("Identifier", base + ".id", "text", { show: rawHex, parse: rawParseHex,
    hint: `Hex (0x123) or decimal. ${m.extended ? "29-bit: up to 0x1FFFFFFF." : "11-bit: up to 0x7FF."}` });
  const common = [
    field("Name", base + ".name", "text", { hint: "Used in declarations, the trace and the online view." }),
    idField,
    checkbox("Extended (29-bit) identifier", base + ".extended", false),
    checkbox("Remote frame", base + ".rtr", false, kind === "rx" ? "Match remote frames instead of data frames." : "Send a remote request (no data)."),
    field("DLC", base + ".dlc", "int", { placeholder: kind === "rx" ? "any" : "from the signals",
      hint: kind === "rx" ? "The expected length: shorter frames that do not hold every signal are not applied." : "0 to 8." }),
  ];
  const own = kind === "rx" ? [
    field("Mask", base + ".mask", "text", { show: rawHex, parse: rawParseHex, placeholder: "every bit",
      hint: "A frame matches when (id AND mask) = (identifier AND mask)." }),
    field("Timeout (ms)", base + ".timeout_ms", "int", { placeholder: "none", hint: "The status bit goes FALSE after this long without the message." }),
    field("Status bit", base + ".status_location", "text", { placeholder: "%IX…" }),
    field("Receive counter", base + ".counter_location", "text", { placeholder: "%IW…" }),
    field("Received identifier", base + ".id_location", "text", { placeholder: "%ID…" }),
    field("Received DLC", base + ".dlc_location", "text", { placeholder: "%IB…" }),
    field("Whole frame", base + ".data_location", "text", { placeholder: "%IL…" }),
  ] : [
    field("Period (ms)", base + ".period_ms", "int", { placeholder: "none", hint: "1 to 60000." }),
    checkbox("Also on change", base + ".on_change", false, "Sent when a signal value changes; restarts the period."),
    field("Minimum gap (ms)", base + ".min_gap_ms", "int", { placeholder: "0" }),
    field("Trigger bit", base + ".trigger_location", "text", { placeholder: "%QX…", hint: "A rising edge sends the message once." }),
    field("Enable bit", base + ".enable_location", "text", { placeholder: "%QX…", hint: "FALSE stops periodic and on-change sends." }),
    field("Fill byte", base + ".fill", "int", { placeholder: "0", hint: "For bits no signal covers." }),
    field("Whole frame", base + ".data_location", "text", { placeholder: "%QL…", hint: "Signals are written on top." }),
    checkbox("Override protocol", base + ".override_protocol", false, "Send it even though the network's protocol uses this identifier."),
  ];
  const sigs = m.signals || [];
  const sigRows = sigs.map((s, j) => {
    const sp = `${base}.signals[${j}]`;
    const cell = (label, path, kind2, opts) => el("td", null, field(label, path, kind2, opts).querySelector("input"));
    const order = el("select", { dataset: { path: sp + ".byte_order" }, "aria-label": "Byte order" },
      el("option", { value: "" }, "little"), el("option", { value: "big" }, "big"));
    order.value = s.byte_order === "big" ? "big" : "";
    order.addEventListener("change", () => { setPath(sp + ".byte_order", order.value || undefined); render(); });
    const signed = el("input", { type: "checkbox", "aria-label": "Signed", dataset: { path: sp + ".signed" } });
    signed.checked = !!s.signed;
    signed.addEventListener("change", () => setPath(sp + ".signed", signed.checked || undefined));
    return el("tr", { dataset: { signal: j } },
      el("td", null, el("span", { class: `raw-swatch raw-c${j % RAW_COLORS}` })),
      cell("Name", sp + ".name", "text"),
      cell("Start bit", sp + ".start_bit", "int"),
      cell("Length", sp + ".length", "int"),
      el("td", null, order),
      el("td", null, signed),
      cell("Scale", sp + ".scale", "text", { parse: (t) => (isNaN(Number(t)) ? t : Number(t)), placeholder: "1" }),
      cell("Unit", sp + ".unit", "text"),
      cell("PLC address", sp + ".iec_location", "text", { placeholder: kind === "rx" ? "%I…" : "%Q…" }),
      el("td", null, el("button", { type: "button", class: "danger", "aria-label": "Remove signal " + (s.name || j),
        onclick: () => { const l = sigs.slice(); l.splice(j, 1); setPath(base + ".signals", l.length ? l : undefined); changed(true); } }, "Remove")));
  });
  return el("section", { class: "raw-editor", dataset: { rawEditor: `${kind}:${i}` } },
    el("h3", null, (kind === "rx" ? "Received: " : "Sent: ") + (m.name || rawHex(m.id))),
    el("div", { class: "grid" }, ...common, ...own),
    el("h4", null, "Signals"),
    el("table", { class: "od raw-signals" },
      el("thead", null, el("tr", null, thCells(["", "Name", "Start bit", "Length", "Byte order", "Signed", "Scale", "Unit", "PLC address", ""]))),
      el("tbody", null, sigRows.length ? sigRows : el("tr", null, el("td", { colspan: "10", class: "muted" }, "No signals")))),
    el("div", { class: "row" },
      el("button", { type: "button", dataset: { rawAddSignal: "1" }, onclick: () => {
        const used = new Set(sigs.flatMap((s) => rawBits(s.start_bit || 0, s.length || 1, s.byte_order === "big")));
        let start = 0;
        while (used.has(start) && start < 63) start++;
        setPath(base + ".signals", sigs.concat([{ name: "", start_bit: start, length: 8 }]));
        changed(true);
      } }, "Add signal"),
      el("button", { type: "button", dataset: { rawSuggest: "1" }, onclick: (e) => busy(e.currentTarget, "Suggesting…", () => rawSuggest(kind, i)) }, "Suggest addresses"),
      el("button", { type: "button", dataset: { rawSt: "1" }, onclick: (e) => busy(e.currentTarget, "Copying…", () => rawCopySt(kind, i)) }, "Copy as ST call")),
    rawBitGrid(m));
}

// 8 rows of 8 bits (byte 0 on top, bit 7 on the left as data sheets draw
// it); each cell is coloured by the signal that owns it.
function rawBitGrid(m) {
  const owner = new Map();
  const clash = new Set();
  (m.signals || []).forEach((s, j) => {
    for (const b of rawBits(Number(s.start_bit) || 0, Number(s.length) || 1, s.byte_order === "big")) {
      if (b < 0 || b > 63) continue;
      if (owner.has(b)) clash.add(b);
      owner.set(b, j);
    }
  });
  const dlc = typeof m.dlc === "number" ? m.dlc : 8;
  const rows = [];
  for (let byte = 0; byte < 8; byte++) {
    const cells = [el("th", { scope: "row" }, `Byte ${byte}`)];
    for (let bit = 7; bit >= 0; bit--) {
      const n = byte * 8 + bit;
      const j = owner.get(n);
      const cls = ["raw-bit", j !== undefined ? `raw-c${j % RAW_COLORS}` : null, clash.has(n) ? "raw-clash" : null,
        byte >= dlc ? "raw-out" : null].filter(Boolean).join(" ");
      cells.push(el("td", { class: cls, title: j !== undefined ? `bit ${n}: ${(m.signals[j].name || "signal " + j)}` : `bit ${n}` }, String(n)));
    }
    rows.push(el("tr", null, cells));
  }
  return el("div", { class: "raw-grid-wrap" },
    el("h4", null, "Bit layout"),
    el("table", { class: "raw-grid", "aria-label": "Bit layout" }, el("tbody", null, rows)),
    clash.size ? el("p", { class: "field-msg error" }, "Signals overlap in the red bits.") : null);
}

async function rawSuggest(kind, i) {
  try {
    const r = await api("POST", "/api/raw/suggest", { config: fileConfig(), network: S.net, kind, index: i });
    setPath(`raw.${kind}[${i}]`, r.entry);
    changed(true);
    banner(r.filled.length ? `Suggested ${r.filled.length} address${r.filled.length === 1 ? "" : "es"}.` : "Every location is already set.");
  } catch (e) { banner(e.message, true); }
}

async function rawCopySt(kind, i) {
  try {
    const r = await api("POST", "/api/raw/st", { config: fileConfig(), network: S.net, kind, index: i });
    await copyText(r.text);
    banner("Copied the Structured Text call. It needs the canworks library in the project.");
  } catch (e) { banner(e.message, true); }
}

async function rawImportDbc() {
  const input = el("input", { type: "file", accept: ".dbc", "aria-label": "DBC file" });
  const pick = await modal("Import messages from a DBC file:", [["next", "Next", true], ["cancel", "Cancel"]], input);
  if (pick !== "next" || !input.files.length) return;
  const file = input.files[0];
  const text = await file.text();
  let list;
  try { list = (await api("POST", "/api/raw/dbc", { text })).messages; } catch (e) { banner(e.message, true); return; }
  if (!list.length) { banner("The DBC file has no messages.", true); return; }
  const listenOnly = getPath("adapter.listen_only") === true;
  const selects = new Map();
  const rows = list.map((m) => {
    const sel = el("select", { "aria-label": "Use " + m.name },
      el("option", { value: "" }, "skip"), el("option", { value: "receive" }, "receive"),
      listenOnly ? null : el("option", { value: "send" }, "send"));
    sel.value = m.senders.includes("PLC") && !listenOnly ? "send" : "";
    selects.set(m.name, sel);
    return el("tr", null, el("td", null, m.name), el("td", { class: "mono" }, rawHex(m.id) + (m.extended ? " ext" : "")),
      el("td", null, String(m.dlc)), el("td", null, m.cycle_ms ? `${m.cycle_ms} ms` : "event"),
      el("td", null, String(m.signals) + (m.multiplexed ? " (multiplexed left out)" : "")), el("td", null, sel));
  });
  const table = el("div", { class: "raw-import" }, el("table", { class: "od" },
    el("thead", null, el("tr", null, thCells(["Message", "Identifier", "DLC", "Cycle", "Signals", "Use"]))),
    el("tbody", null, rows)));
  const go = await modal(`${file.name}: pick the messages and whether the PLC receives or sends them. Free PLC addresses are suggested.`,
    [["import", "Import", true], ["cancel", "Cancel"]], table);
  if (go !== "import") return;
  const picks = {};
  for (const [name, sel] of selects) if (sel.value) picks[name] = sel.value;
  if (!Object.keys(picks).length) return;
  try {
    const r = await api("POST", "/api/raw/dbc_import", { config: fileConfig(), network: S.net, text, picks });
    for (const kind of ["rx", "tx"]) {
      if (r[kind].length) setPath("raw." + kind, (getPath("raw." + kind) || []).concat(r[kind]));
    }
    if (!getPath("raw.dbc")) setPath("raw.dbc", file.name);
    S.rawOpen = null;
    changed(true);
    const n = r.rx.length + r.tx.length;
    banner(`Imported ${n} message${n === 1 ? "" : "s"}.` + (r.notes.length ? " " + r.notes.join("; ") + "." : ""), r.notes.length > 0);
  } catch (e) { banner(e.message, true); }
}

// --- Plain CAN networks (protocol "none") ---

const isPlain = (net) => !!net && net.protocol === "none";

function renderPlainBus(view) {
  view.append(
    el("h2", null, "Bus" + (several() ? `: network ${netLabel(S.config, S.net)}` : "")),
    protocolField(),
    el("fieldset", { dataset: { section: "network" } }, el("legend", null, "Network"),
      el("div", { class: "grid" },
        choice("Network", "adapter.simulate", [
          { value: undefined, label: "Real", help: "The CAN adapter below." },
          { value: true, label: "Simulated",
            help: "A virtual bus inside the plugin: no CAN interface is used. Plain CAN devices from the Simulation view (simulation.json) send and answer on it. The adapter settings below are kept for switching back." },
        ], { onChange: (v) => {
          const ad = S.config.adapter || (S.config.adapter = {});
          if (v === true) ad.simulate = true; else delete ad.simulate;
          changed(true);
        } }))),
    adapterFieldset(),
    el("p", { class: "muted" }, "Only plain CAN messages run on this network. Set them up under ",
      el("button", { type: "button", class: "link", dataset: { go: "raw" }, onclick: () => showView("raw") }, "CAN messages"), "."),
    onlineAccessSettings());
}

// The raw part of an online status answer: config messages and the
// program's frame blocks, on any network.
function rawLive(st) {
  const box = $("#online-raw");
  if (!box) return;
  const raw = st.raw;
  if (!raw || (!(raw.rx || []).length && !(raw.tx || []).length && !(raw.program || {}).receivers &&
      !(raw.program || {}).cyclic_jobs && !(raw.program || {}).frames_sent && !(raw.simulated_devices || []).length)) {
    box.replaceChildren();
    return;
  }
  const prog = raw.program || {};
  const idText = (v) => "0x" + (v || 0).toString(16).toUpperCase().padStart(v > 0x7FF ? 8 : 3, "0");
  const rx = (raw.rx || []).map((m) => {
    let state = !m.seen ? "never received" : m.timed_out ? "timed out" : `${m.age_ms} ms ago`;
    if (m.short_frames) state += `, ${m.short_frames} short`;
    return el("tr", { dataset: { rawRx: m.message } },
      el("td", null, m.message), el("td", null, String(m.count ?? 0)),
      el("td", { class: m.timed_out ? "bad" : null }, state),
      el("td", { class: "mono" }, m.seen ? `${idText(m.last_id)} [${m.last_dlc}] ${m.last_data || ""}` : "-"));
  });
  const tx = (raw.tx || []).map((m) => el("tr", { dataset: { rawTx: m.message } },
    el("td", null, m.message), el("td", null, String(m.count ?? 0)),
    el("td", { class: m.error ? "bad" : null }, m.error || "-")));
  const parts = [el("h3", null, "CAN messages"),
    el("p", { dataset: { online: "raw" } }, `${raw.running ? "Running" : "Not running"}: ${raw.frames_sent ?? 0} frames sent, ` +
      `${raw.frames_received ?? 0} received, bus load ${raw.bus_load ?? 0} %${raw.listen_only ? ", listen-only" : ""}.`)];
  if (prog.receivers || prog.cyclic_jobs || prog.frames_sent)
    parts.push(el("p", { dataset: { online: "raw-program" } },
      `Program blocks: ${prog.receivers ?? 0} receivers, ${prog.cyclic_jobs ?? 0} cyclic jobs, ${prog.frames_sent ?? 0} frames sent, ${prog.dropped ?? 0} dropped.`));
  if ((raw.simulated_devices || []).length)
    parts.push(el("p", { dataset: { online: "raw-devices" } }, "Simulated plain CAN devices: " + raw.simulated_devices.join(", ") + "."));
  if (rx.length) parts.push(el("table", { class: "od", dataset: { online: "raw-rx" } },
    el("thead", null, el("tr", null, thCells(["Received message", "Count", "State", "Last frame"]))), el("tbody", null, rx)));
  if (tx.length) parts.push(el("table", { class: "od", dataset: { online: "raw-tx" } },
    el("thead", null, el("tr", null, thCells(["Sent message", "Count", "Error"]))), el("tbody", null, tx)));
  box.replaceChildren(...parts);
}

// The bus row of a plain CAN network.
function plainLive(st) {
  const bus = st.bus || {};
  $("#online-live").replaceChildren(
    el("table", { class: "online-bus" }, el("tbody", null,
      el("tr", null, el("th", null, "Bus"), el("td", { dataset: { online: "bus" } },
        `${bus.interface || "?"}: ${BUS_STATES[bus.state] || bus.state || "?"}` + (st.simulated_network ? " (simulated)" : "")),
        el("th", null, "Bit rate"), el("td", null, bus.bitrate ? `${bus.bitrate / 1000} kbit/s` : "?"),
        el("th", null, "TX / RX errors"), el("td", null, `${bus.tx_errors ?? "-"} / ${bus.rx_errors ?? "-"}`),
        el("th", null, "Bus-off"), el("td", null, String(bus.bus_off_count ?? "-"))))));
}
