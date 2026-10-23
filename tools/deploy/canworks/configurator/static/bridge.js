// Modbus bridge page (canopen-configurator "Bridge settings panel",
// "Register map preview and export"; docs/modbus-bridge.md; the project
// target switch is target.js): the bridge object's settings, Suggest for
// its blocks, the register map with its client channels, Pack for Modbus
// and the map exports. Paths "bridge…" live at the
// top of the draft. Loaded after app.js and uses its helpers (el, api,
// banner, modal, busy, field, checkbox, choice, getPath, setPath, changed,
// render, fileConfig, toModel, S, ...).
"use strict";

const BRIDGE_TABLES = { "input register": "Input registers", "discrete input": "Discrete inputs",
  "holding register": "Holding registers", "coil": "Coils" };

function bridgeOn() { return !!(S.model && S.model.top.bridge); }

// The CANopen master networks a live list can name.
function bridgeMasters() {
  return S.model.networks.filter((n) => !isSlave(n) && !isJ1939(n) && !isPlain(n)).map(netName).filter(Boolean);
}

// The draft replaced by a config the server sent back (a pack, a target
// switch), keeping the unsaved notes and the open network. The caller calls
// changed(true), so the whole switch is one undo step.
function bridgeReplaceDraft(cfg) {
  const notes = S.model.notes;
  S.model = toModel(cfg);
  if (notes !== undefined) S.model.notes = notes;
  openNet(Math.min(S.net, S.model.networks.length - 1));
}

// -- the page ----------------------------------------------------------------

// "address:port" as [address, port]; an IPv6 address is in brackets.
function bridgeSplitListen(text) {
  const t = typeof text === "string" ? text : "";
  const m = /^\[(.*)\]:([^:]*)$/.exec(t) || /^([^:]*):([^:]*)$/.exec(t);
  return m ? [m[1], m[2]] : [t, ""];
}

function bridgeJoinListen(host, port) {
  host = host.trim();
  port = port.trim();
  if (!host && !port) return undefined;
  return `${host.includes(":") ? `[${host}]` : host}:${port}`;
}

function bridgeListenFields() {
  const [host, port] = bridgeSplitListen(getPath("bridge.listen"));
  const a = el("input", { type: "text", spellcheck: "false", dataset: { path: "bridge.listen" }, placeholder: "0.0.0.0", "aria-label": "Listen address" });
  const p = el("input", { type: "text", spellcheck: "false", dataset: { bridge: "port" }, placeholder: "502", "aria-label": "Port" });
  a.value = host;
  p.value = port;
  const put = () => setPath("bridge.listen", bridgeJoinListen(a.value, p.value));
  a.addEventListener("input", put);
  p.addEventListener("input", put);
  return [
    el("label", null, "Listen address", a, hint("A numeric address: 0.0.0.0 for every IPv4 interface, :: for every IPv6 one, or one interface's address."),
      el("span", { class: "field-msg", dataset: { for: "bridge.listen" } })),
    el("label", null, "Port", p, hint("502 is the Modbus TCP port; the bridge's service may bind it.")),
  ];
}

// A comma-separated address list as a JSON list.
// `empty` is what an empty field saves: undefined drops the key.
function bridgeListField(label, path, help, placeholder, empty) {
  return field(label, path, "text", { placeholder: placeholder || "every client", hint: help, empty,
    show: (v) => (Array.isArray(v) ? v.join(", ") : v),
    parse: (t) => { const l = t.split(/[\s,]+/).filter(Boolean); return l.length ? l : empty; } });
}

// A block location with Suggest: the first free range after the packed data.
function bridgeLocation(label, path, block, index, placeholder, help) {
  const btn = el("button", { type: "button", dataset: { bridgeSuggest: index === undefined ? block : `${block}:${index}` } }, "Suggest");
  btn.onclick = () => busy(btn, "Suggesting…", async () => {
    try {
      const r = await api("POST", "/api/bridge/suggest", { config: fileConfig(), block, index });
      setPath(path, r.location);
      render();
    } catch (e) { banner(e.message, true); }
  });
  return el("label", null, label, el("span", { class: "row" }, field(label, path, "text", { placeholder }).querySelector("input"), btn),
    hint(help), el("span", { class: "field-msg", dataset: { for: path } }));
}

async function bridgeSuggested(block, index) {
  return (await api("POST", "/api/bridge/suggest", { config: fileConfig(), block, index })).location;
}

// A bridge of its own: the Modbus TCP server and who may connect and write.
function bridgeServerFields() {
  return [
    el("fieldset", null, el("legend", null, "Server"),
      el("div", { class: "grid" },
        ...bridgeListenFields(),
        field("Unit ID", "bridge.unit_id", "int", { placeholder: "1", hint: "0 to 255. Requests to unit 0 and 255 are always answered." }),
        choice("Word order", "bridge.word_order", [
          { value: undefined, literal: "high_first", label: "High word first", help: "Default. The first register of a 32- or 64-bit value holds its high word." },
          { value: "low_first", label: "Low word first", help: "The first register holds the low word, for clients that expect that order." },
        ]),
        field("Maximum clients", "bridge.max_clients", "int", { placeholder: "16", hint: "Connections served at once, 1 to 64." }),
        field("Clients per address", "bridge.max_clients_per_address", "int", { placeholder: "4",
          hint: "Connections from one address at once, 1 to 64. When every slot is taken, a writer's address closes the oldest connection of a client that may not write." }))),
    el("fieldset", null, el("legend", null, "Clients"),
      el("div", { class: "grid" },
        bridgeListField("Writers", "bridge.writers", "The addresses or prefixes (192.168.10.20, 192.168.10.0/24) allowed to write; no other client can. Empty: nobody writes. To let every host write, give 0.0.0.0/0, ::/0.", "nobody writes", []),
        bridgeListField("Readers", "bridge.readers", "Addresses or prefixes allowed to connect. Empty: every client."),
        field("Watchdog (ms)", "bridge.watchdog_ms", "int", { placeholder: "1000",
          hint: "Outputs go off when no writer wrote for this long. 0: no watchdog." }),
        bridgeLossChoice())),
  ];
}

// OpenPLC through Modbus: OpenPLC's Modbus master is the only client, on
// 127.0.0.1, so the page shows its poll and the editor names instead of the
// server and client settings; word order and the status block are fixed.
function bridgeOpenplcFields() {
  return [
    el("fieldset", { dataset: { bridgeOpenplc: "1" } }, el("legend", null, "OpenPLC"),
      el("p", { class: "muted" }, "Save writes OpenPLC's remote device, the canworks_in and canworks_out programs and the canworks variable list into the editor project (see the Project page). 32- and 64-bit values are low word first, as OpenPLC reads them."),
      openplcFacts(),
      el("div", { class: "grid" },
        field("Poll (ms)", "bridge.openplc.poll_ms", "int", { placeholder: "10",
          hint: "How often OpenPLC reads and writes the registers, 5 to 1000 ms. Each poll takes one Modbus request per register group." }),
        field("Remote device name", "bridge.openplc.remote_device", "text", { placeholder: "canworks",
          hint: "The remote device in the editor project: devices/remote/<name>.json." }),
        field("First editor location", "bridge.openplc.iec_base", "int", { placeholder: "first free from 100",
          hint: "The register groups get %IW and %QW from this word number on in the editor project. Empty: the first number from 100 that the project does not use." }),
        field("Unit ID", "bridge.unit_id", "int", { placeholder: "1", hint: "0 to 255." }))),
    el("fieldset", null, el("legend", null, "PLC link"),
      el("div", { class: "grid" },
        field("Watchdog (ms)", "bridge.watchdog_ms", "int", { placeholder: "5 polls, at least 50",
          hint: "Outputs go off when OpenPLC wrote nothing for this long (PLC stopped or gone). 0: no watchdog." }),
        bridgeLossChoice())),
  ];
}

function bridgeLossChoice() {
  return choice("When the writer is lost", "bridge.on_client_loss", [
    { value: undefined, literal: "stop", label: "Stop", help: "Default. No RPDOs and no sent messages until the next write; inputs keep updating." },
    { value: "zero", label: "Zero", help: "Every output is set to 0 and sent once, then outputs stop." },
    { value: "hold", label: "Hold", help: "Outputs keep being sent with their last values." },
    { value: "preop", label: "Pre-operational", help: "Every node of the CANopen master networks is put pre-operational, so it applies its own communication-loss behaviour; outputs stop." },
  ]);
}

function renderBridge(view) {
  const b = S.model.top.bridge;
  const openplc = projectTarget() === "openplc_modbus";
  view.append(el("h2", null, "Modbus bridge"),
    el("p", { class: "muted" }, (openplc ? "OpenPLC's Modbus master reads and writes these registers on 127.0.0.1. " : "") +
      "canworks-bridge runs the networks of this config and serves every located value as a Modbus TCP register. " +
      "Input byte n is input register n/2 (even n the high byte), %IXn.b discrete input n·8+b; outputs are holding registers and coils the same way." +
      (openplc ? " Input bytes 0-11 hold the map hash and the status block, output bytes 0-5 the PLC link header (running, map hash): the bridge takes no output from a PLC whose map differs." : "")),
    el("div", { class: "toolbar" }, el("button", { type: "button", dataset: { bridge: "install-device" },
      title: "Install the bridge on a Linux device over SSH and start it with this project's saved config",
      onclick: () => installOnDevice(null) }, "Install on device…")),
    ...(openplc ? bridgeOpenplcFields() : bridgeServerFields()),
    el("fieldset", null, el("legend", null, "Bridge blocks"),
      el("p", { class: "muted" }, "Optional. Suggest places a block after the packed data, in a free range."),
      el("div", { class: "grid" },
        openplc ? el("label", null, "Status block", el("span", { dataset: { bridgeStatusFixed: "1" } }, "%IB4"),
          hint("8 input bytes after the map hash: state, clients, heartbeat counter, control echo and result. Fixed for OpenPLC."))
          : bridgeLocation("Status block", "bridge.status_location", "status_location", undefined, "%IB…",
            "8 input bytes: state, clients, heartbeat counter, control echo and result."),
        bridgeLocation("Control block", "bridge.control_location", "control_location", undefined, "%QB…",
          "6 output bytes: counter, command, network, node. A command runs when the counter changes." +
          (openplc ? " The CO_NMT block uses it." : "")))),
    bridgeLiveLists(b),
    bridgeSdo(b),
    bridgeMailboxes(b, openplc),
    el("h3", null, "Register map"),
    el("div", { class: "toolbar" },
      el("button", { type: "button", dataset: { bridge: "pack" }, title: "Every location packed densely from byte 0: data, then status, then the bridge blocks",
        onclick: (e) => busy(e.currentTarget, "Packing…", bridgePack) }, "Pack for Modbus"),
      el("span", { class: "muted", dataset: { bridgeExportsHint: "1" } }, "Export ▾ → For the program has the register map files.")),
    el("div", { id: "bridge-map" }, el("p", { class: "muted" }, "Loading the register map…")));
  bridgeRefreshMap();
}

function bridgeLiveLists(b) {
  const masters = bridgeMasters();
  const lists = Array.isArray(b.live_lists) ? b.live_lists : [];
  const rows = lists.map((entry, i) => {
    const e = entry && typeof entry === "object" ? entry : {};
    const path = `bridge.live_lists[${i}]`;
    const names = masters.includes(e.network) || !e.network ? masters : masters.concat([e.network]);
    const sel = el("select", { dataset: { path: path + ".network" }, "aria-label": "Network" },
      el("option", { value: "" }, "(pick)"), names.map((n) => el("option", { value: n }, n)));
    sel.value = e.network || "";
    sel.addEventListener("change", () => setPath(path + ".network", sel.value || undefined));
    return el("tr", { dataset: { liveList: i } },
      el("td", null, sel, el("span", { class: "field-msg", dataset: { for: path + ".network" } })),
      el("td", null, bridgeLocation("Location", path + ".location", "live_list", i, "%IB…")),
      el("td", null, el("button", { type: "button", class: "danger", "aria-label": `Remove the live list of ${e.network || i + 1}`,
        onclick: () => { lists.splice(i, 1); if (!lists.length) delete b.live_lists; changed(true); } }, "Remove")));
  });
  const free = masters.filter((n) => !lists.some((e) => e.network === n));
  const add = el("button", { type: "button", dataset: { bridge: "add-live-list" },
    disabled: free.length ? null : masters.length ? "Every CANopen master network has a live list." : "The config has no CANopen master network with a name." }, "Add live list");
  add.onclick = () => busy(add, "Adding…", async () => {
    b.live_lists = lists.concat([{ network: free[0] }]);
    try { b.live_lists[b.live_lists.length - 1].location = await bridgeSuggested("live_list", b.live_lists.length - 1); }
    catch (e) { banner(e.message, true); }
    changed(true);
  });
  return el("fieldset", null, el("legend", null, "Live lists"),
    el("p", { class: "muted" }, "16 input bytes per CANopen master network: bit n is set while node n is operational."),
    el("table", { class: "od bridge-lists" },
      el("thead", null, el("tr", null, thCells(["Network", "Location", ""]))),
      el("tbody", null, rows.length ? rows : el("tr", null, el("td", { colspan: "3", class: "muted" }, "None yet")))),
    el("div", { class: "toolbar" }, add,
      masters.length ? null : el("span", { class: "muted" }, "The config has no CANopen master network with a name.")));
}

function bridgeSdo(b) {
  const on = el("input", { type: "checkbox", dataset: { path: "bridge.sdo_bridge_location" } });
  on.checked = !!b.sdo_bridge_location;
  on.addEventListener("change", async () => {
    if (on.checked) {
      b.sdo_bridge_location = {};
      try {
        b.sdo_bridge_location = { request: await bridgeSuggested("sdo_request"), response: await bridgeSuggested("sdo_response") };
      } catch (e) { banner(e.message, true); }
    } else {
      delete b.sdo_bridge_location;
      delete b.sdo_bridge_write;
    }
    changed(true);
  });
  const sdo = b.sdo_bridge_location;
  return el("fieldset", null, el("legend", null, "SDO bridge"),
    el("div", { class: "check-field" }, el("label", { class: "check" }, on, " SDO bridge registers"),
      hint("A client reads (and may write) objects of up to 4 bytes on any node through a request and a response block. Default: off."),
      el("span", { class: "field-msg", dataset: { for: "bridge.sdo_bridge_location" } })),
    sdo ? el("div", { class: "grid" },
      bridgeLocation("Request block", "bridge.sdo_bridge_location.request", "sdo_request", undefined, "%QB…", "14 output bytes."),
      bridgeLocation("Response block", "bridge.sdo_bridge_location.response", "sdo_response", undefined, "%IB…", "14 input bytes."),
      checkbox("Clients may write", "bridge.sdo_bridge_write", false, "On: an SDO write through the bridge is allowed; off, it ends aborted.")) : null);
}

// The function blocks' mailboxes (modbus-bridge-mailboxes; docs/plc-library.md):
// a switch, the counts, the two areas with Suggest, what they cost and which
// blocks need which part. For OpenPLC a count change moves both areas to a
// free place at once; another client keeps its places until Suggest.
const BRIDGE_MAILBOX_NEEDS = [
  ["Request mailboxes", "the SDO blocks (CO_SDO_READ_BYTES, CO_SDO_READ_STRING, ...), CAN_SEND, CAN_SEND_CYCLIC, J1939_SEND, J1939_REQUEST, J1939_FIND_ECU, J1939_DM_READ and J1939_DM_CLEAR"],
  ["Receive mailbox", "CAN_RECEIVE, J1939_RECEIVE and CO_RECV_EMCY"],
  ["Cyclic jobs", "CAN_SEND_CYCLIC, one job per running block"],
  ["Network info", "CAN_BUS_INFO and J1939_ECU_INFO"],
];

async function bridgeMailboxPlace(b) {
  try {
    b.mailboxes.input_location = await bridgeSuggested("mailbox_input");
    b.mailboxes.output_location = await bridgeSuggested("mailbox_output");
  } catch (e) { banner(e.message, true); }
}

function bridgeMailboxes(b, openplc) {
  const on = el("input", { type: "checkbox", dataset: { path: "bridge.mailboxes" } });
  on.checked = !!b.mailboxes;
  on.addEventListener("change", async () => {
    if (on.checked) {
      b.mailboxes = {};
      await bridgeMailboxPlace(b);
    } else {
      delete b.mailboxes;
    }
    changed(true);
  });
  const mb = b.mailboxes;
  // A count change: OpenPLC's areas move to a free place right away.
  const count = (f) => {
    if (!openplc) return f;
    f.querySelector("input").addEventListener("change", () => bridgeMailboxPlace(b).then(() => changed(true)));
    return f;
  };
  const box = (label, key, help) => {
    const f = checkbox(label, `bridge.mailboxes.${key}`, true, help);
    if (openplc) f.querySelector("input").addEventListener("change", () => bridgeMailboxPlace(b).then(() => changed(true)));
    return f;
  };
  return el("fieldset", { dataset: { bridgeMailboxes: mb ? "1" : "0" } }, el("legend", null, "Function blocks"),
    el("div", { class: "check-field" }, el("label", { class: "check" }, on, " Mailboxes for the canworks function blocks"),
      hint("The PLC library's blocks for long SDO objects, raw CAN frames, J1939 and EMCY talk to the bridge through these registers. " +
        (openplc ? "New OpenPLC configs start with them on." : "Default: off.")),
      el("span", { class: "field-msg", dataset: { for: "bridge.mailboxes" } })),
    mb ? [
      el("div", { class: "grid" },
        count(field("Request mailboxes", "bridge.mailboxes.requests", "int", { placeholder: "1",
          hint: "0 to 4: how many blocks can ask the bridge at the same moment; more blocks take turns. Each one is 72 input and 72 holding registers. 0: no SDO, send or J1939 request blocks, and no receiver can be opened." })),
        box("Receive mailbox", "receive", "Received frames, J1939 messages and EMCY for the receiving blocks: 120 input registers."),
        count(field("Cyclic jobs", "bridge.mailboxes.cyclic_jobs", "int", { placeholder: "4",
          hint: "0 to 16: CAN_SEND_CYCLIC blocks that can run at once. Each one is 4 input registers and 1 holding register." })),
        box("Network info", "network_info", "Bus state and error counters of each network (up to 8): 18 input registers per network."),
        bridgeLocation("Input area", "bridge.mailboxes.input_location", "mailbox_input", undefined, "%IB…", "Where the responses, the receive mailbox, network info and the cyclic job table start."),
        bridgeLocation("Output area", "bridge.mailboxes.output_location", "mailbox_output", undefined, "%QB…", "Where the requests, the receive acknowledgement and the keepalives start.")),
      el("p", { class: "muted", id: "bridge-mailbox-cost", dataset: { bridgeMailboxCost: "1" } }, bridgeMailboxCost()),
      el("table", { class: "od", dataset: { bridgeMailboxNeeds: "1" } }, el("tbody", null,
        BRIDGE_MAILBOX_NEEDS.map(([part, who]) => el("tr", null, el("th", null, part), el("td", null, who))))),
      openplc ? notice("info", "A change here changes the map hash: the editor project needs Update declarations (Save does it in a project opened here) and a new Build before the blocks work.",
        { live: false, dataset: { bridgeMailboxUpdate: "1" } }) : null,
    ] : null);
}

// The cost line of the Function blocks section, from the last register map.
function bridgeMailboxCost() {
  const r = S.bridgeMap;
  if (!r || !r.mailboxes) return "";
  const m = r.mailboxes;
  const regs = `The blocks take ${m.input_registers} input and ${m.output_registers} holding registers.`;
  if (projectTarget() !== "openplc_modbus") return regs;
  return regs + ` The whole map needs ${r.requests} Modbus request${r.requests === 1 ? "" : "s"} per poll` +
    (r.requests > r.request_budget ? `, more than the ${r.request_budget} OpenPLC keeps up with.` : ` (budget ${r.request_budget}).`);
}

// -- register map ---------------------------------------------------------------

async function bridgeRefreshMap() {
  if (S.view !== "bridge" || !bridgeOn()) return;
  const seq = S.bridgeSeq = (S.bridgeSeq || 0) + 1;
  let r;
  try {
    r = await api("POST", "/api/bridge/map", { config: fileConfig() });
  } catch (e) {
    r = { rows: [], channels: [], problem: e.message };
  }
  if (seq !== S.bridgeSeq) return;
  S.bridgeMap = r;
  bridgeFillMap();
}

function bridgeMatches(row, text) {
  if (!text) return true;
  const hay = [row.table, row.address, row.location, row.type, row.name, row.network, row.source, row.object].join(" ").toLowerCase();
  return text.toLowerCase().split(/\s+/).filter(Boolean).every((w) => hay.includes(w));
}

function bridgeFillMap() {
  const host = $("#bridge-map");
  if (!host || !S.bridgeMap) return;
  const r = S.bridgeMap;
  const cost = $("#bridge-mailbox-cost");
  if (cost) cost.textContent = bridgeMailboxCost();
  // A refresh while the filter is being typed in keeps it focused.
  const old = host.querySelector('[data-bridge="filter"]');
  const typing = old && document.activeElement === old ? old.selectionStart : null;
  if (r.problem) {
    host.replaceChildren(notice("warning", `No register map: ${r.problem}. Pack for Modbus or move the locations (see Problems).`,
      { live: false, dataset: { bridge: "map-problem" } }));
    return;
  }
  const filter = el("input", { type: "search", dataset: { bridge: "filter" }, placeholder: "Filter: name, network, table, address…",
    "aria-label": "Filter the register map" });
  filter.value = S.bridgeFilter || "";
  const body = el("tbody");
  const count = el("span", { class: "muted", "aria-live": "polite" });
  const fill = () => {
    const rows = r.rows.filter((row) => bridgeMatches(row, S.bridgeFilter));
    body.replaceChildren(...(rows.length ? rows.map(bridgeRow) : [el("tr", null, el("td", { colspan: "7", class: "muted" },
      r.rows.length ? "No entry matches the filter." : "No located values yet. The register map lists every PLC location the config uses; map a PDO entry or SDO variable first."))]));
    count.textContent = rows.length === r.rows.length ? `${r.rows.length} entries` : `${rows.length} of ${r.rows.length} entries`;
  };
  filter.addEventListener("input", () => { S.bridgeFilter = filter.value; fill(); });
  fill();
  const regs = (n) => { const r = Math.ceil(n / 2); return `${n} byte${n === 1 ? "" : "s"} (${r} register${r === 1 ? "" : "s"})`; };
  host.replaceChildren(
    el("p", { class: "muted", dataset: { bridge: "sizes" } }, `Inputs ${regs(r.input_bytes)}, outputs ${regs(r.output_bytes)}.`),
    el("div", { class: "toolbar" }, filter, count),
    el("div", { class: "objects bridge-map", dataset: { box: "bridge_map", boxLabel: "the register map" }, tabindex: "0", role: "region", "aria-label": "Register map" }, el("table", { class: "od" },
      el("thead", null, el("tr", null, thCells(["Table", "Address", "Size", "Type", "Name", "Source", "Location"]))), body)),
    el("h3", null, "Suggested client channels"),
    el("p", { class: "muted" }, "Requests that cover every used register within the Modbus limits (125 registers per read, 123 per write). Bits are read in the registers they live in."),
    el("table", { class: "od bridge-channels", dataset: { bridge: "channels" } },
      el("thead", null, el("tr", null, thCells(["Function", "Start", "Count", "Request"]))),
      el("tbody", null, r.channels.length ? r.channels.map((c) => el("tr", null,
        el("td", { class: "num" }, String(c.function)), el("td", { class: "num" }, String(c.start)), el("td", { class: "num" }, String(c.count)),
        el("td", null, c.direction === "input" ? "read input registers" : "write holding registers")))
        : el("tr", null, el("td", { colspan: "4", class: "muted" }, "None: nothing is located.")))));
  if (typing !== null) { filter.focus(); filter.setSelectionRange(typing, typing); }
}

function bridgeRow(row) {
  const bits = row.table === "discrete input" || row.table === "coil";
  const address = String(row.address) + (row.count > 1 ? `..${row.address + row.count - 1}` : "") +
    (row.byte_in_register ? ` (${row.byte_in_register} byte)` : "");
  const size = bits ? "1 bit" : `${row.count} register${row.count === 1 ? "" : "s"}`;
  const source = [row.network, row.source, row.object].filter(Boolean).join(" ");
  return el("tr", { dataset: { bridgeRow: row.name } },
    el("td", null, BRIDGE_TABLES[row.table] || row.table), el("td", { class: "mono" }, address), el("td", null, size),
    el("td", null, row.type + (row.word_order ? `, ${row.word_order === "low_first" ? "low" : "high"} word first` : "")),
    el("td", null, row.name), el("td", null, source), el("td", { class: "mono" }, row.location));
}

async function bridgePack() {
  try {
    const r = await api("POST", "/api/bridge/pack", { config: fileConfig() });
    bridgeReplaceDraft(r.config);
    changed(true);
    banner("Packed every location for Modbus.");
  } catch (e) {
    banner(`Pack for Modbus failed: ${e.message}`, true);
  }
}

// Export → For another PLC (PLCopen XML)…: the folder `canworks-deploy
// --export-plcopen DIR --for <plc>` writes, as a zip (plcopen-export). The
// config needs the PLC link: offered first, with Pack for Modbus, one undo step.
const PLCOPEN_PLCS = [["codesys", "CODESYS (Modbus client of the bridge)"], ["trust", "truST"],
  ["generic", "Other PLC with PLCopen XML"]];
const PLCOPEN_WILDCARD = ["", "0.0.0.0", "::", "*"];

function plcopenDefaultHost(plc) {
  const host = bridgeSplitListen(getPath("bridge.listen") || "")[0];
  const loopback = host === "localhost" || host === "::1" || host.startsWith("127.");
  if (PLCOPEN_WILDCARD.includes(host)) return plc === "trust" ? "127.0.0.1" : "";
  return plc === "codesys" && loopback ? "" : host;
}

async function plcLinkOn() {
  const cfg = fileConfig();
  cfg.bridge.plc_link = true;
  try {
    const r = await api("POST", "/api/bridge/pack", { config: cfg });
    bridgeReplaceDraft(r.config);
    changed(true);
    return true;
  } catch (e) {
    banner(`Pack for Modbus failed: ${e.message}`, true);
    return false;
  }
}

async function exportPlcopen() {
  if (getPath("bridge.plc_link") !== true) {
    const v = await modal("Another PLC needs the bridge's PLC link: the bridge then puts its map hash at input " +
      "registers 0-1 and takes a header at holding registers 0-2, so a program built for another map leaves the " +
      "outputs off. Turn it on and run Pack for Modbus? Undo takes both back.",
    [["cancel", "Cancel"], ["link", "Turn on the PLC link and repack", true]]);
    if (v !== "link" || !await plcLinkOn()) return;
  }
  const plc = el("select", { id: "plcopen-plc", dataset: { plcopenPlc: "1" } },
    ...PLCOPEN_PLCS.map(([v, label]) => el("option", { value: v }, label)));
  const host = el("input", { type: "text", id: "plcopen-host", spellcheck: "false", dataset: { plcopenHost: "1" } });
  const address = el("input", { type: "text", id: "plcopen-address", spellcheck: "false", placeholder: "optional",
    dataset: { plcopenAddress: "1" } });
  const library = el("input", { type: "checkbox", checked: true, dataset: { plcopenLibrary: "1" } });
  const main = el("input", { type: "checkbox", dataset: { plcopenMain: "1" } });
  const plcName = el("input", { type: "text", id: "plcopen-device", spellcheck: "false", placeholder: "the active application's device",
    dataset: { plcopenDevice: "1" } });
  const ethernet = el("input", { type: "text", id: "plcopen-ethernet", spellcheck: "false", placeholder: "the PLC's only one, or a new one",
    dataset: { plcopenEthernet: "1" } });
  const codesysNote = el("p", { class: "hint", dataset: { plcopenCodesys: "1" } },
    "CODESYS reads and writes the bridge's registers; canworks-bridge still runs the CAN networks. To let CODESYS run " +
    "the CANopen master itself, ", el("a", { href: "#", onclick: (e) => {
      e.preventDefault();
      $("#modal").close();
      switchWorkspace("configure");
      showView("project");
    } }, "switch the project target to CODESYS"), ".");
  const codesysFields = el("div", { class: "grid", dataset: { plcopenCodesysFields: "1" } },
    el("div", { class: "field" }, el("label", { for: "plcopen-device" }, "PLC device in CODESYS"), plcName),
    el("div", { class: "field" }, el("label", { for: "plcopen-ethernet" }, "Ethernet adapter in CODESYS"), ethernet));
  const mainField = el("label", { class: "check" }, main, " Add an empty main program to the task");
  const hostHint = el("span", { class: "hint" });
  const update = () => {
    const v = plc.value;
    codesysNote.hidden = codesysFields.hidden = v !== "codesys";
    mainField.hidden = v === "codesys";
    host.placeholder = plcopenDefaultHost(v) || "the bridge's address as the PLC sees it";
    hostHint.textContent = v === "trust" ? "truST's driver moves one request each way: configs with the default mailboxes are refused, with how to trim them."
      : v === "generic" ? "The README lists the Modbus client channels to set up." : "";
  };
  plc.onchange = update;
  update();
  const extra = el("div", { dataset: { plcopenDialog: "1" } },
    el("div", { class: "field" }, el("label", { for: "plcopen-plc" }, "PLC"), plc), codesysNote,
    el("div", { class: "field" }, el("label", { for: "plcopen-host" }, "Bridge address the PLC uses"), host, hostHint),
    el("div", { class: "field" }, el("label", { for: "plcopen-address" }, "PLC's own address"), address,
      hint("Checked against the bridge's writers: the bridge takes writes only from those.")),
    el("div", { class: "check-field" }, el("label", { class: "check" }, library, " Include the canworks library")),
    el("div", { class: "check-field" }, mainField), codesysFields);
  for (;;) {
    const v = await modal("Export the canworks variables, copy programs and function blocks as PLCopen XML, with what " +
      "connects them to the bridge on that PLC.", [["cancel", "Cancel"], ["export", "Export", true]], extra);
    if (v !== "export") return;
    const target = plc.value;
    if (target === "codesys" && !host.value.trim() && !plcopenDefaultHost(target)) {
      host.focus();
      banner("Give the bridge's address as the CODESYS PLC sees it: the bridge listens on every interface or on loopback.", true);
      continue;
    }
    const cfg = fileConfig();
    try {
      const r = await busy($("#menu-export > summary"), "Exporting…", () => api("POST", "/api/export_plcopen", {
        config: cfg, target, host: host.value, library: library.checked, with_main: main.checked,
        plc: plcName.value, ethernet: ethernet.value, plc_address: address.value }));
      if (!r) return;
      if (r.errors) { exportStopped("PLCopen XML", r, cfg); return; }
      downloadBase64(r.data, r.name, r.content_type);
      const notes = (r.notes || []).map((n) => ` Note: ${n}.`).join("");
      banner(`Exported ${r.name}: unzip it and follow README.txt.${notes}`, notes ? "warning" : "done");
    } catch (e) {
      banner(e.message, true);
    }
    return;
  }
}

// Downloads the file `canworks-deploy --export-modbus-map map.<fmt>` writes for the draft
// (`--export-nodered <folder>_node-red.json` for "nodered").
async function bridgeExport(fmt) {
  try {
    const r = await api("POST", "/api/bridge/export", { config: fileConfig(), format: fmt });
    if (r.errors) { exportStopped(fmt === "nodered" ? "Node-RED flow" : "Register map", r, fileConfig()); return; }
    downloadBase64(r.data, r.name, r.content_type);
    const notes = (r.notes || []).map((n) => ` Note: ${n}.`).join("");
    banner(fmt === "nodered" ? `Exported ${r.name} (${r.rows} values). Import it in Node-RED.${notes}`
      : `Exported ${r.name} (${r.rows} entries).`, notes ? "warning" : "done");
  } catch (e) {
    banner(e.message, true);
  }
}
