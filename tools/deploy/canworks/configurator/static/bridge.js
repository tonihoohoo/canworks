// Modbus bridge target and page (canopen-configurator "Modbus bridge
// target", "Bridge settings panel", "Register map preview and export";
// docs/modbus-bridge.md): the project target switch, the bridge object's
// settings, Suggest for its blocks, the register map with its client
// channels, Pack for Modbus and the map exports. Paths "bridge…" live at the
// top of the draft. Loaded after app.js and uses its helpers (el, api,
// banner, modal, busy, field, checkbox, choice, getPath, setPath, changed,
// render, fileConfig, toModel, S, ...).
"use strict";

const BRIDGE_LISTEN = "0.0.0.0:502";
const BRIDGE_TABLES = { "input register": "Input registers", "discrete input": "Discrete inputs",
  "holding register": "Holding registers", "coil": "Coils" };

function bridgeOn() { return !!(S.model && S.model.top.bridge); }

// The CANopen master networks a live list can name.
function bridgeMasters() {
  return S.model.networks.filter((n) => !isSlave(n) && !isJ1939(n) && !isPlain(n)).map(netName).filter(Boolean);
}

// The draft replaced by a config the server sent back (a pack), keeping the
// unsaved notes and the open network. The caller calls changed(true), so
// the whole switch is one undo step.
function bridgeReplaceDraft(cfg) {
  const notes = S.model.notes;
  S.model = toModel(cfg);
  if (notes !== undefined) S.model.notes = notes;
  openNet(Math.min(S.net, S.model.networks.length - 1));
}

// -- project target ---------------------------------------------------------

function bridgeTargetField() {
  return el("fieldset", { dataset: { bridgeTarget: "1" } }, el("legend", null, "Project target"),
    el("div", { class: "grid" }, choice("Target", "", [
      { value: "openplc", label: "OpenPLC",
        help: "The OpenPLC plugin runs the networks. Each location size is its own table: %IW100 and %ID100 are different variables." },
      { value: "bridge", label: "Modbus bridge",
        help: "canworks-bridge runs the networks and serves the values as Modbus TCP registers, with no PLC. Locations are byte addresses: %IW0 is bytes 0 and 1, input register 0." },
    ], { noPath: true, dataset: { target: "1" }, current: bridgeOn() ? "bridge" : "openplc", onChange: switchTarget })));
}

// Switches the project target: adds or removes the bridge object and offers
// to repack every location for the new addressing.
async function switchTarget(target) {
  if ((target === "bridge") === bridgeOn()) return;
  const top = S.model.top;
  if (target === "bridge") {
    const v1 = fileVersion(fileConfig()) === 1;
    const v = await modal((v1 ? "The bridge needs a version 2 config: the file becomes version 2 (a list of networks) when saved. " : "") +
      "A bridge config is byte-addressed, so OpenPLC's per-type locations usually overlap there. Pack every location for Modbus?",
      [["cancel", "Cancel"], ["keep", "Switch, keep the locations"], ["pack", "Switch and pack for Modbus", true]]);
    if (v !== "keep" && v !== "pack") { render(); return; }
    top.bridge = { listen: BRIDGE_LISTEN };
    if (v === "pack") {
      try {
        bridgeReplaceDraft((await api("POST", "/api/bridge/pack", { config: fileConfig() })).config);
      } catch (e) {
        delete top.bridge;
        banner(`Pack for Modbus failed: ${e.message}. The target is still OpenPLC.`, true);
        render();
        return;
      }
    }
    changed(true);
    banner(v === "pack" ? "The project is a Modbus bridge now, every location packed for Modbus. See the Modbus bridge page."
      : "The project is a Modbus bridge now. See the Modbus bridge page.");
    return;
  }
  const v = await modal("Switch the project to OpenPLC? The Modbus bridge settings (listen address, blocks, live lists) are removed. " +
    "OpenPLC keeps each location size in its own table: repack every location per type?",
    [["cancel", "Cancel"], ["keep", "Switch, keep the locations"], ["pack", "Switch and repack per type", true]]);
  if (v !== "keep" && v !== "pack") { render(); return; }
  const kept = top.bridge;
  delete top.bridge;
  if (v === "pack") {
    try {
      bridgeReplaceDraft((await api("POST", "/api/pack_openplc", { config: fileConfig() })).config);
    } catch (e) {
      top.bridge = kept;
      banner(`Repacking failed: ${e.message}. The target is still Modbus bridge.`, true);
      render();
      return;
    }
  }
  if (S.view === "bridge") S.view = "bus";
  changed(true);
  banner(v === "pack" ? "The project targets OpenPLC now, every location repacked per type." : "The project targets OpenPLC now.");
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
function bridgeListField(label, path, help) {
  return field(label, path, "text", { placeholder: "every client", hint: help,
    show: (v) => (Array.isArray(v) ? v.join(", ") : v),
    parse: (t) => { const l = t.split(/[\s,]+/).filter(Boolean); return l.length ? l : undefined; } });
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

function renderBridge(view) {
  const b = S.model.top.bridge;
  view.append(el("h2", null, "Modbus bridge"),
    el("p", { class: "muted" }, "canworks-bridge runs the networks of this config and serves every located value as a Modbus TCP register. " +
      "Input byte n is input register n/2 (even n the high byte), %IXn.b discrete input n·8+b; outputs are holding registers and coils the same way."),
    bridgeTargetField(),
    el("fieldset", null, el("legend", null, "Server"),
      el("div", { class: "grid" },
        ...bridgeListenFields(),
        field("Unit ID", "bridge.unit_id", "int", { placeholder: "1", hint: "0 to 255. Requests to unit 0 and 255 are always answered." }),
        choice("Word order", "bridge.word_order", [
          { value: undefined, label: "High word first", help: "Default. The first register of a 32- or 64-bit value holds its high word." },
          { value: "low_first", label: "Low word first", help: "The first register holds the low word, for clients that expect that order." },
        ]),
        field("Maximum clients", "bridge.max_clients", "int", { placeholder: "16", hint: "Connections served at once, 1 to 64." }))),
    el("fieldset", null, el("legend", null, "Clients"),
      el("div", { class: "grid" },
        bridgeListField("Writers", "bridge.writers", "Addresses or prefixes (192.168.10.20, 192.168.10.0/24) allowed to write. Empty: every client that may connect."),
        bridgeListField("Readers", "bridge.readers", "Addresses or prefixes allowed to connect. Empty: every client."),
        field("Watchdog (ms)", "bridge.watchdog_ms", "int", { placeholder: "1000",
          hint: "Outputs go off when no writer wrote for this long. 0: no watchdog." }),
        choice("When the writer is lost", "bridge.on_client_loss", [
          { value: undefined, label: "Stop", help: "Default. No RPDOs and no sent messages until the next write; inputs keep updating." },
          { value: "zero", label: "Zero", help: "Every output is set to 0 and sent once, then outputs stop." },
          { value: "hold", label: "Hold", help: "Outputs keep being sent with their last values." },
        ]))),
    el("fieldset", null, el("legend", null, "Bridge blocks"),
      el("p", { class: "muted" }, "Optional. Suggest places a block after the packed data, in a free range."),
      el("div", { class: "grid" },
        bridgeLocation("Status block", "bridge.status_location", "status_location", undefined, "%IB…",
          "8 input bytes: state, clients, heartbeat counter, control echo and result."),
        bridgeLocation("Control block", "bridge.control_location", "control_location", undefined, "%QB…",
          "6 output bytes: counter, command, network, node. A command runs when the counter changes."))),
    bridgeLiveLists(b),
    bridgeSdo(b),
    el("h3", null, "Register map"),
    el("div", { class: "toolbar" },
      el("button", { type: "button", dataset: { bridge: "pack" }, title: "Every location packed densely from byte 0: data, then status, then the bridge blocks",
        onclick: (e) => busy(e.currentTarget, "Packing…", bridgePack) }, "Pack for Modbus"),
      ...[["csv", "Export CSV"], ["json", "Export JSON"], ["st", "Export ST variables"]].map(([fmt, label]) =>
        el("button", { type: "button", dataset: { bridgeExport: fmt }, onclick: (e) => busy(e.currentTarget, "Exporting…", () => bridgeExport(fmt)) }, label))),
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
  const add = el("button", { type: "button", dataset: { bridge: "add-live-list" }, disabled: !free.length || null }, "Add live list");
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
  // A refresh while the filter is being typed in keeps it focused.
  const old = host.querySelector('[data-bridge="filter"]');
  const typing = old && document.activeElement === old ? old.selectionStart : null;
  if (r.problem) {
    host.replaceChildren(el("p", { class: "field-msg", dataset: { bridge: "map-problem" } },
      `No register map: ${r.problem}. Pack for Modbus or move the locations (see Problems).`));
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
      r.rows.length ? "No entry matches the filter." : "No located values yet."))]));
    count.textContent = rows.length === r.rows.length ? `${r.rows.length} entries` : `${rows.length} of ${r.rows.length} entries`;
  };
  filter.addEventListener("input", () => { S.bridgeFilter = filter.value; fill(); });
  fill();
  const regs = (n) => { const r = Math.ceil(n / 2); return `${n} byte${n === 1 ? "" : "s"} (${r} register${r === 1 ? "" : "s"})`; };
  host.replaceChildren(
    el("p", { class: "muted", dataset: { bridge: "sizes" } }, `Inputs ${regs(r.input_bytes)}, outputs ${regs(r.output_bytes)}.`),
    el("div", { class: "toolbar" }, filter, count),
    el("div", { class: "objects bridge-map", tabindex: "0", role: "region", "aria-label": "Register map" }, el("table", { class: "od" },
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

// Downloads the file `canworks-deploy --export-modbus-map map.<fmt>` writes for the draft.
async function bridgeExport(fmt) {
  try {
    const r = await api("POST", "/api/bridge/export", { config: fileConfig(), format: fmt });
    if (r.errors) {
      banner(`Register map export stopped: ${r.items.map((i) => i.message).join("; ")}. Nothing was downloaded.`, true);
      return;
    }
    downloadBase64(r.data, r.name, r.content_type);
    banner(`Exported ${r.name} (${r.rows} entries).`);
  } catch (e) {
    banner(e.message, true);
  }
}
