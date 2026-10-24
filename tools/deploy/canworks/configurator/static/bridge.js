// Modbus bridge page (canopen-configurator "Bridge settings panel",
// "Register map preview and export"; modbus-connections; docs/modbus-bridge.md;
// the project target switch is target.js): the connections with their
// Downloads, the bridge object's settings, Suggest for its blocks, the
// register map with its client channels and Pack for Modbus. Paths "bridge…" live at the
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

// The Modbus TCP server and who may connect and write. With connections,
// the writers follow them and show as "Who may write" (modbus-connections
// "Writers follow the connections").
function bridgeServerFields() {
  const openplc = hasOpenplc();
  const conns = connectionsOf();
  const writers = getPath("bridge.writers");
  return [
    el("fieldset", null, el("legend", null, "Server"),
      el("div", { class: "grid" },
        ...bridgeListenFields(),
        field("Unit ID", "bridge.unit_id", "int", { placeholder: "1", hint: "0 to 255. Requests to unit 0 and 255 are always answered." }),
        choice("Word order", "bridge.word_order", [
          { value: undefined, literal: "high_first", label: "High word first", help: "Default. The first register of a 32- or 64-bit value holds its high word." },
          { value: "low_first", label: "Low word first", help: "The first register holds the low word, for clients that expect that order." + (openplc ? " OpenPLC reads this order." : "") },
        ]),
        field("Maximum clients", "bridge.max_clients", "int", { placeholder: "16", hint: "Connections served at once, 1 to 64." }),
        field("Clients per address", "bridge.max_clients_per_address", "int", { placeholder: "4",
          hint: "Connections from one address at once, 1 to 64. When every slot is taken, a writer's address closes the oldest connection of a client that may not write." }))),
    el("fieldset", null, el("legend", null, "Clients"),
      el("div", { class: "grid" },
        conns.length
          ? el("label", null, "Who may write", el("span", { dataset: { bridgeWho: "1" } },
            Array.isArray(writers) && writers.length ? writers.join(", ") : "nobody"),
          hint("The addresses of the connections with Writes on; no other client can write."),
          el("span", { class: "field-msg", dataset: { for: "bridge.writers" } }))
          : bridgeListField("Writers", "bridge.writers", "The addresses or prefixes (192.168.10.20, 192.168.10.0/24) allowed to write; no other client can. Empty: nobody writes. To let every host write, give 0.0.0.0/0, ::/0.", "nobody writes", []),
        bridgeListField("Readers", "bridge.readers", "Addresses or prefixes allowed to connect. Empty: every client."),
        field("Watchdog (ms)", "bridge.watchdog_ms", "int", { placeholder: openplc ? "5 polls, at least 50" : "1000",
          hint: "Outputs go off when no writer wrote for this long. 0: no watchdog." +
            (conns.some((c) => c && c.kind === "trust") ? " A truST connection needs 500 or more: a truST scan takes about 100-125 ms." : "") }),
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
  const link = b.plc_link === true;
  view.append(el("h2", null, "Modbus bridge"),
    el("p", { class: "muted" },
      "canworks-bridge runs the networks of this config and serves every located value as a Modbus TCP register. " +
      "Input byte n is input register n/2 (even n the high byte), %IXn.b discrete input n·8+b; outputs are holding registers and coils the same way." +
      (link ? " Input bytes 0-11 hold the map hash and the status block, output bytes 0-5 the PLC link header (running, map hash): the bridge takes no output from a PLC whose map differs." : "")),
    el("div", { class: "toolbar" }, el("button", { type: "button", dataset: { bridge: "install-device" },
      title: "Install the bridge on a Linux device over SSH and start it with this project's saved config",
      onclick: () => installOnDevice(null) }, "Install on device…")),
    bridgeConnections(),
    ...bridgeServerFields(),
    el("fieldset", null, el("legend", null, "Bridge blocks"),
      el("p", { class: "muted" }, "Optional. Suggest places a block after the packed data, in a free range."),
      el("div", { class: "grid" },
        link ? el("label", null, "Status block", el("span", { dataset: { bridgeStatusFixed: "1" } }, "%IB4"),
          hint("8 input bytes after the map hash: state, clients, heartbeat counter, control echo and result. Fixed with the PLC link."))
          : bridgeLocation("Status block", "bridge.status_location", "status_location", undefined, "%IB…",
            "8 input bytes: state, clients, heartbeat counter, control echo and result."),
        bridgeLocation("Control block", "bridge.control_location", "control_location", undefined, "%QB…",
          "6 output bytes: counter, command, network, node. A command runs when the counter changes." +
          (link ? " The CO_NMT block uses it." : "")))),
    bridgeLiveLists(b),
    bridgeSdo(b),
    bridgeMailboxes(b, hasOpenplc()),
    el("h3", null, "Register map"),
    el("div", { class: "toolbar" },
      el("button", { type: "button", dataset: { bridge: "pack" }, title: "Every location packed densely from byte 0: data, then status, then the bridge blocks",
        onclick: (e) => busy(e.currentTarget, "Packing…", bridgePack) }, "Pack for Modbus"),
      el("span", { class: "muted", dataset: { bridgeExportsHint: "1" } }, "The map files are the Downloads of the connections above.")),
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
// a switch, the counts, the two areas with Suggest, and, on or off, what
// works without them, which blocks need which part with their config-only
// alternative, what they cost and who needs them (mailboxes-on-demand).
// For OpenPLC a count change moves both areas to a free place at once;
// another client keeps its places until Suggest.
const BRIDGE_MAILBOX_NEEDS = [
  ["Request mailboxes", "the SDO blocks of any size (CO_SDO_READ_BYTES, CO_SDO_READ_STRING, ...), CAN_SEND, CAN_SEND_CYCLIC, J1939_SEND, J1939_REQUEST, J1939_FIND_ECU, J1939_DM_READ and J1939_DM_CLEAR",
    "SDO variables (numbers up to 64 bits) or CO_SDO_READ / CO_SDO_WRITE up to 4 bytes; a sent CAN message (on change or a trigger bit) for CAN_SEND; the J1939 network's sent PGNs and requests"],
  ["Receive mailbox", "CAN_RECEIVE, J1939_RECEIVE and CO_RECV_EMCY",
    "a received CAN message or J1939 PGN on %I locations; the node's EMCY code location for its latest EMCY"],
  ["Cyclic jobs", "CAN_SEND_CYCLIC, one job per running block", "a periodic sent CAN message"],
  ["Network info", "CAN_BUS_INFO and J1939_ECU_INFO", "the network's bus state location and the J1939 address location"],
];
const BRIDGE_WITHOUT_MAILBOXES = "Without mailboxes: the config's values, CO_NMT, CO_NODE_LIVE, and CO_SDO_READ and CO_SDO_WRITE up to 4 bytes.";

// A connection's canworks blocks choice (mailboxes-on-demand): the parts
// it needs, as mailboxuse.CHOICE_PARTS. truST only None or SDO and send.
const CONNECTION_BLOCKS = [
  { value: undefined, label: "None", parts: [], help: "The program uses the values and the blocks over the bridge only (CO_NMT, CO_NODE_LIVE, CO_SDO_READ and CO_SDO_WRITE up to 4 bytes)." },
  { value: "sdo_send", label: "SDO and send", parts: ["request"], help: "Also long SDOs, CAN_SEND and the J1939 requests: 1 request mailbox." },
  { value: "receive", label: "SDO, send and receive", parts: ["request", "receive"], help: "Also CAN_RECEIVE, J1939_RECEIVE and CO_RECV_EMCY: the receive mailbox too." },
  { value: "all", label: "All", parts: ["request", "receive", "cyclic", "info"], help: "Also CAN_SEND_CYCLIC (4 cyclic jobs) and CAN_BUS_INFO / J1939_ECU_INFO (network info)." },
];
const BLOCK_PART_WORDS = { request: "1 request mailbox", receive: "the receive mailbox", cyclic: "4 cyclic jobs", info: "network info" };

function connectionBlocksText(v) {
  const c = CONNECTION_BLOCKS.find((x) => x.value === v) || CONNECTION_BLOCKS[0];
  const w = c.parts.map((p) => BLOCK_PART_WORDS[p]);
  return w.length ? `${c.label} (${w.length > 1 ? w.slice(0, -1).join(", ") + " and " + w[w.length - 1] : w[0]})` : c.label;
}

// The mailboxes with `parts` added, keeping what is on (mailboxuse.mailboxes_for).
function mailboxesWith(current, parts) {
  if (!current) {
    return { requests: parts.includes("request") ? 1 : 0, receive: parts.includes("receive"),
      cyclic_jobs: parts.includes("cyclic") ? 4 : 0, network_info: parts.includes("info") };
  }
  const mb = Object.assign({}, current);
  if (parts.includes("request") && (mb.requests === undefined ? 1 : mb.requests) < 1) mb.requests = 1;
  if (parts.includes("receive") && mb.receive === false) mb.receive = true;
  if (parts.includes("cyclic") && (mb.cyclic_jobs === undefined ? 4 : mb.cyclic_jobs) < 4) mb.cyclic_jobs = 4;
  if (parts.includes("info") && mb.network_info === false) mb.network_info = true;
  return mb;
}

// The choice in a connection's Settings: the parts go into bridge.mailboxes
// in the same undo step, placed; a downloaded file is then out of date.
function connectionBlocksField(c, path) {
  const list = c.kind === "trust" ? CONNECTION_BLOCKS.slice(0, 2) : CONNECTION_BLOCKS;
  return choice("canworks blocks", path + ".blocks", list, { onChange: async (v) => {
    const b = S.model.top.bridge;
    if (v === undefined) delete c.blocks;
    else c.blocks = v;
    if (c.map_hash) c.stale = true;
    const parts = (CONNECTION_BLOCKS.find((x) => x.value === v) || CONNECTION_BLOCKS[0]).parts;
    if (parts.length) {
      const had = b.mailboxes;
      b.mailboxes = mailboxesWith(had, parts);
      if (!had || !had.input_location || !had.output_location || JSON.stringify(had) !== JSON.stringify(b.mailboxes)) {
        await bridgeMailboxPlace(b);
      }
    }
    changed(true);
  } });
}

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
    f.querySelector("input").addEventListener("change", () => bridgeKeepRequest(b));
    if (openplc) f.querySelector("input").addEventListener("change", () => bridgeMailboxPlace(b).then(() => changed(true)));
    return f;
  };
  const requests = field("Request mailboxes", "bridge.mailboxes.requests", "int", { placeholder: "1",
    hint: "0 to 4: how many blocks can ask the bridge at the same moment; more blocks take turns. Each one is 72 input and 72 holding registers. 0: no SDO, send or J1939 request blocks; the receive mailbox and cyclic jobs need at least 1." });
  const cyclic = field("Cyclic jobs", "bridge.mailboxes.cyclic_jobs", "int", { placeholder: "4",
    hint: "0 to 16: CAN_SEND_CYCLIC blocks that can run at once. Each one is 4 input registers and 1 holding register." });
  // Before the count's own change handler (which places the areas): the request count is right by then.
  for (const f of [requests, cyclic]) f.querySelector("input").addEventListener("change", () => bridgeKeepRequest(b));
  return el("fieldset", { dataset: { bridgeMailboxes: mb ? "1" : "0" } }, el("legend", null, "Function blocks"),
    el("div", { class: "check-field" }, el("label", { class: "check" }, on, " Mailboxes for the canworks mailbox blocks"),
      hint("Long SDO objects, any CAN frame, J1939 messages and trouble codes, every EMCY and bus info from the program. " +
        "Off by default, because when on every client polls them on every cycle, whether or not a block is called." +
        (openplc ? " Problems offers them when the program declares a mailbox block." : " A connection's canworks blocks choice turns on what its program uses.")),
      el("span", { class: "field-msg", dataset: { for: "bridge.mailboxes" } })),
    mb ? el("div", { class: "grid" },
      count(requests),
      box("Receive mailbox", "receive", "Received frames, J1939 messages and EMCY for the receiving blocks: 120 input registers per receive block."),
      count(field("Receive blocks", "bridge.mailboxes.receive_blocks", "int", { placeholder: "1",
        hint: "1 or 2: a batch of received records fills them all. One block carries 9 CAN frames per batch, two carry 21 for one more Modbus request per poll." })),
      count(cyclic),
      box("Network info", "network_info", "Bus state and error counters of each network (up to 8): 18 input registers per network."),
      bridgeLocation("Input area", "bridge.mailboxes.input_location", "mailbox_input", undefined, "%IB…", "Where the responses, the receive mailbox, network info and the cyclic job table start."),
      bridgeLocation("Output area", "bridge.mailboxes.output_location", "mailbox_output", undefined, "%QB…", "Where the requests, the receive acknowledgement and the keepalives start.")) : null,
    el("p", { class: "muted", id: "bridge-mailbox-cost", dataset: { bridgeMailboxCost: "1" } }, bridgeMailboxCost()),
    el("p", { class: "muted", id: "bridge-mailbox-who", dataset: { bridgeMailboxWho: "1" } }, bridgeMailboxWho()),
    el("p", { dataset: { bridgeWithout: "1" } }, BRIDGE_WITHOUT_MAILBOXES),
    el("table", { class: "od", dataset: { bridgeMailboxNeeds: "1" } },
      el("thead", null, el("tr", null, thCells(["Part", "Needed by", "Without mailboxes"]))),
      el("tbody", null, BRIDGE_MAILBOX_NEEDS.map(([part, who, alt]) => el("tr", null, el("th", null, part), el("td", null, who), el("td", null, alt))))),
    mb && openplc ? notice("info", "A change here changes the map hash: the editor project needs a Save (or canworks-deploy --into-project) and a new Build before the blocks work.",
      { live: false, dataset: { bridgeMailboxUpdate: "1" } }) : null);
}

// A receiver or a cyclic job is opened through a request mailbox (BRIDGE-7):
// while the receive mailbox or cyclic jobs are on, requests stay at least 1,
// and the field says why when it put the 1 back.
function bridgeKeepRequest(b) {
  const mb = b.mailboxes;
  if (!mb) return;
  const requests = mb.requests === undefined ? 1 : Number(mb.requests);
  const needs = mb.receive !== false || (mb.cyclic_jobs === undefined ? 4 : Number(mb.cyclic_jobs)) > 0;
  if (!needs || !(requests < 1)) return;
  mb.requests = 1;
  const input = document.querySelector('[data-path="bridge.mailboxes.requests"]');
  if (input) input.value = "1";
  const msg = document.querySelector('.field-msg[data-for="bridge.mailboxes.requests"]');
  if (msg) msg.textContent = "At least 1 while the receive mailbox or cyclic jobs are on: they are opened through a request mailbox.";
  changed(false, "bridge.mailboxes.requests");
}

// The cost line of the Function blocks section, from the last register map:
// a difference against the map without mailboxes, on or off.
function bridgeMailboxCost() {
  const r = S.bridgeMap;
  const c = r && r.mailbox_cost;
  if (!c) return "";
  const regs = `+${c.input_registers} input / +${c.output_registers} holding registers`;
  // OpenPLC polls the mailbox blocks in groups of their own every mailbox
  // poll (mailbox-poll), so they add requests there, not every poll.
  const more = c.requests_with - c.requests_without;
  const req = c.mailbox_requests !== undefined && c.requests_without !== undefined
    ? `, ${c.mailbox_requests} more Modbus request${c.mailbox_requests === 1 ? "" : "s"} every ${c.mailbox_poll_ms} ms` +
      (more > 0 ? ` and ${more} more every poll` : "") +
      (c.requests_with + c.mailbox_requests > r.request_budget ? `, more than the ${r.request_budget} OpenPLC keeps up with` : ` (budget ${r.request_budget})`)
    : "";
  const mb = c.on && r.mailboxes;
  const rx = !mb || !mb.can_per_batch ? ""
    : mb.can_per_second ? ` Receiving: about ${mb.can_per_second} CAN frames/s at the ${mb.poll_ms} ms mailbox poll (${mb.can_per_batch} per batch, one batch every two mailbox polls).`
    : ` Receiving: ${mb.can_per_batch} CAN frames per batch, one batch per two of your client's polls.`;
  return (c.on ? "The mailboxes take " : "Turned on with the default parts, the mailboxes would take ") + regs + req + "." + rx;
}

// Who needs the mailboxes: the editor project's mailbox blocks and the
// connections' canworks blocks choices.
function bridgeMailboxWho() {
  const r = S.bridgeMap;
  if (!r) return "";
  const out = [];
  if (Array.isArray(r.program_blocks)) {
    out.push(r.program_blocks.length
      ? "The OpenPLC program declares " + r.program_blocks.map((x) => `${x.block} (${x.pous.join(", ")})`).join(", ") + "."
      : "The OpenPLC program declares no mailbox block.");
  }
  for (const c of r.connection_blocks || []) out.push(`${c.name}: canworks blocks ${c.text}.`);
  return out.join(" ");
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
  bridgeConnectionStates();
  const cost = $("#bridge-mailbox-cost");
  if (cost) cost.textContent = bridgeMailboxCost();
  const who = $("#bridge-mailbox-who");
  if (who) who.textContent = bridgeMailboxWho();
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

// -- connections (modbus-connections) ------------------------------------------

// The kinds Add connection offers, with one line on what each one gets.
const CONNECTION_KINDS = [
  { kind: "openplc", title: "OpenPLC",
    gets: "OpenPLC Runtime on the bridge's device: Save keeps the editor's remote device and the canworks programs in sync." },
  { kind: "trust", title: "truST",
    gets: "A truST runtime: the canworks variables, copy programs and function blocks as PLCopen XML, with its Modbus driver settings." },
  { kind: "plc", title: "Other PLC",
    gets: "Another PLC that imports PLCopen XML or ST: the canworks variables, copy programs and client channels." },
  { kind: "nodered", title: "Node-RED", gets: "A Node-RED flow that reads and writes every value by name." },
  { kind: "hmi", title: "HMI, SCADA or script", gets: "An HMI, SCADA or script: the register map as CSV, JSON or an ST variable list." },
];
const CONNECTION_TITLE = Object.fromEntries(CONNECTION_KINDS.map((k) => [k.kind, k.title]));
const CONNECTION_FORMATS = {
  trust: [{ value: undefined, literal: "plcopen", label: "PLCopen XML", help: "The --export-plcopen folder for truST, as one zip." }],
  plc: [{ value: undefined, literal: "plcopen", label: "PLCopen XML", help: "The --export-plcopen folder for a PLC that imports PLCopen XML, as one zip." },
    { value: "st", label: "ST", help: "The PLC link file as ST: the canworks variable list, its client channels and the copy programs." }],
  hmi: [{ value: undefined, literal: "csv", label: "CSV", help: "The register map as CSV: Modbus table, address, size, type, name and source of every value." },
    { value: "json", label: "JSON", help: "The register map as JSON, for scripts and HMI tools." },
    { value: "st", label: "ST variables", help: "The ST variable list of the register map for a Modbus client program." }],
};
const PLCOPEN_WILDCARD = ["", "0.0.0.0", "::", "*"];

function isLoopback(host) { return host === "localhost" || host === "::1" || /^127\./.test(host || ""); }

// IPv4 by number, then the rest by text: the order of `bridge.writers`.
function addressKey(a) {
  const m = /^(\d+)\.(\d+)\.(\d+)\.(\d+)$/.exec(a);
  return m ? [4, ((+m[1] * 256 + +m[2]) * 256 + +m[3]) * 256 + +m[4], a] : [6, 0, a];
}
function compareAddresses(x, y) {
  const a = addressKey(x), b = addressKey(y);
  return a[0] - b[0] || a[1] - b[1] || (a[2] < b[2] ? -1 : a[2] > b[2] ? 1 : 0);
}

// `bridge.writers` set to the addresses of the connections that write.
function syncWriters() {
  const b = S.model.top.bridge;
  if (!b || !connectionsOf().length) return;
  b.writers = [...new Set(connectionsOf().filter((c) => c.writes === true && typeof c.address === "string" && c.address)
    .map((c) => c.address))].sort(compareAddresses);
}

// A change of the connection at `i`, one undo step with the writers.
function connSet(i, key, value) {
  const c = S.model.top.bridge.connections[i];
  if (value === undefined || value === "") delete c[key];
  else c[key] = value;
  syncWriters();
  changed(false, `bridge.connections[${i}].${key}`);
  const who = document.querySelector("[data-bridge-who]");
  if (who) who.textContent = (S.model.top.bridge.writers || []).join(", ") || "nobody";
}

// The row's state: OpenPLC's editor files, or a download against the map hash.
function connectionState(c) {
  if (c.kind === "openplc") {
    if (S.state.mode !== "project") return { key: "no_project", text: "No editor project" };
    const o = S.state.openplc;
    return o && o.outdated && o.outdated.length ? { key: "out_of_date", text: "Out of date: Save" } : { key: "in_sync", text: "In sync" };
  }
  const refused = connectionRefusal(c);
  if (refused) return { key: "cannot_download", text: "Cannot download", title: refused };
  if (!c.map_hash) return { key: "not_downloaded", text: "Not downloaded yet" };
  if (c.stale) return { key: "out_of_date", text: "Out of date" };
  const now = S.bridgeMap && S.bridgeMap.map_hash;
  return !now || now === c.map_hash ? { key: "up_to_date", text: "In sync" } : { key: "out_of_date", text: "Out of date" };
}

// The first reason the check gives why the connection's Download would be
// refused (modbus-connections "Connections that cannot be downloaded").
function connectionRefusal(c) {
  const list = (S.model.top.bridge || {}).connections;
  const path = `bridge.connections[${Array.isArray(list) ? list.indexOf(c) : -1}]`;
  const it = ((S.check && S.check.items) || []).find((x) => (x.paths || []).includes(path) && / Download refused: /.test(x.message));
  return it ? it.message.slice(it.message.indexOf("Download refused: ") + 18) : null;
}

// The rows' states again once the map hash is known.
function bridgeConnectionStates() {
  const list = (S.model.top.bridge || {}).connections;
  for (const cell of document.querySelectorAll("[data-conn-state]")) {
    const i = Number(cell.closest("tr").nextElementSibling?.dataset.connSettings);
    const c = Array.isArray(list) ? list[i] : null;
    if (!c || c.kind === "openplc") continue;
    const st = connectionState(c);
    cell.dataset.connState = st.key;
    cell.textContent = st.text;
    cell.title = st.title || "";
    const dl = document.querySelector(`[data-conn-download="${i}"]`);
    if (dl) {
      dl.textContent = st.key === "out_of_date" ? "Download again" : "Download";
      dl.classList.toggle("primary", st.key === "out_of_date");
    }
  }
}

function bridgeConnections() {
  const list = Array.isArray(S.model.top.bridge.connections) ? S.model.top.bridge.connections : [];
  const add = el("button", { type: "button", class: "primary", dataset: { connAdd: "1" } }, "Add connection…");
  add.onclick = () => busy(add, "Adding…", addConnection);
  const rows = list.map((c, i) => connectionRow(c, i));
  return el("fieldset", { dataset: { connections: String(list.length) } }, el("legend", null, "Connections"),
    rows.length ? el("table", { class: "od connections" },
      el("thead", null, el("tr", null, thCells(["Name", "Kind", "Address", "Writes", "State", ""]))),
      el("tbody", null, rows.flat()))
      : el("p", { class: "muted", dataset: { connectionsEmpty: "1" } },
        "Programs, HMIs and Node-RED connect here: OpenPLC, truST or another PLC, a Node-RED flow, or an HMI, SCADA or script. Each connection gets its files with Download."),
    el("div", { class: "toolbar" }, add));
}

// One connection: its row, and its Settings below it.
function connectionRow(c, i) {
  const path = `bridge.connections[${i}]`;
  const kind = c && typeof c === "object" ? c.kind : undefined;
  const openplc = kind === "openplc";
  const name = el("input", { type: "text", spellcheck: "false", dataset: { path: path + ".name" }, "aria-label": "Connection name" });
  name.value = c.name || "";
  name.addEventListener("input", () => connSet(i, "name", name.value.trim()));
  const address = el("input", { type: "text", spellcheck: "false", dataset: { path: path + ".address" }, "aria-label": "Address of " + (c.name || kind),
    placeholder: "e.g. 192.168.10.20", disabled: openplc || null, title: openplc ? "OpenPLC runs next to the bridge, on 127.0.0.1" : null });
  address.value = c.address || "";
  address.addEventListener("input", () => connSet(i, "address", address.value.trim()));
  const writes = el("input", { type: "checkbox", dataset: { path: path + ".writes" }, "aria-label": "Writes", disabled: openplc || null });
  writes.checked = c.writes === true;
  writes.addEventListener("change", () => connSet(i, "writes", writes.checked));
  const st = connectionState(c);
  const state = el("span", { class: "conn-state", title: st.title || null, dataset: { connState: st.key } }, st.text);
  const actions = [];
  if (openplc) {
    if (st.key === "out_of_date") actions.push(el("button", { type: "button", class: "small", dataset: { connSave: String(i) }, onclick: () => $("#btn-save").click() }, "Save"));
  } else if (CONNECTION_TITLE[kind]) {
    const dl = el("button", { type: "button", class: st.key === "out_of_date" ? "small primary" : "small", dataset: { connDownload: String(i) } },
      st.key === "out_of_date" ? "Download again" : "Download");
    dl.onclick = () => busy(dl, "Downloading…", () => connectionDownload(i));
    actions.push(dl);
    if (kind === "nodered") {
      const pkg = el("button", { type: "button", class: "small", dataset: { connPackage: String(i) },
        title: "The canworks nodes for Node-RED (values, SDO, NMT, CAN and J1939 blocks), the same .tgz as canworks-deploy --export-nodered-package. Install it once: Manage palette > Install > upload" }, "Package");
      pkg.onclick = () => busy(pkg, "Downloading…", noderedPackageDownload);
      actions.push(pkg);
    }
  }
  actions.push(el("button", { type: "button", class: "small danger", dataset: { connRemove: String(i) },
    "aria-label": `Remove ${c.name || kind}`, onclick: () => removeConnection(i) }, "Remove"));
  const row = el("tr", { dataset: { connection: c.name || String(i), connKind: kind || "" } },
    el("td", null, name, el("span", { class: "field-msg", dataset: { for: path + ".name" } })),
    el("td", null, CONNECTION_TITLE[kind] || String(kind),
      c.blocks && c.blocks !== "none" ? el("div", { class: "muted", dataset: { connBlocks: String(i) } }, "canworks blocks: " + connectionBlocksText(c.blocks)) : null),
    el("td", null, address, el("span", { class: "field-msg", dataset: { for: path + ".address" } })),
    el("td", null, writes, el("span", { class: "field-msg", dataset: { for: path + ".writes" } })),
    el("td", null, state),
    el("td", { class: "conn-actions" }, actions));
  const settings = connectionSettings(c, i);
  return [row, el("tr", { class: "conn-settings", dataset: { connSettings: String(i) } }, el("td", { colspan: "6" }, settings))];
}

// inputs_on_loss (modbus-connections "PLC inputs while the bridge is
// lost"). A downloaded file was made with the old choice: the row says it
// is out of date until the next Download.
function inputsOnLossField(c, path) {
  return choice("Inputs when the bridge is lost", path + ".inputs_on_loss", [
    { value: undefined, label: "Keep last values", help: "While canworks.ok is FALSE the values keep what the bridge last sent; status, state and timeout inputs read 0." },
    { value: "zero", label: "Set to 0", help: "While canworks.ok is FALSE every value reads 0." },
  ], { onChange: (v) => {
    // One undo step: the stale mark goes in with the choice.
    if (c.kind !== "openplc" && c.map_hash) c.stale = true;
    setPath(path + ".inputs_on_loss", v);
    render();
  } });
}

// The mailbox poll of the OpenPLC connection (mailbox-poll): how often
// OpenPLC's Modbus master polls the mailbox blocks, in groups of their own.
// A multiple of the poll, at most 250 ms; each choice says what it gives.
const MAILBOX_POLLS = [10, 20, 50, 100, 200];
function mailboxPollDefault(poll) { return Math.max(poll, Math.ceil(50 / poll) * poll); }
function mailboxPollHelp(ms) {
  const mb = getPath("bridge.mailboxes") || {};
  const perBatch = Number(mb.receive_blocks) === 2 ? 21 : 9;
  const rx = mb.receive === false ? ""
    : ` The receive mailbox keeps up with about ${Math.round(perBatch * 1000 / (2 * ms))} CAN frames per second.`;
  return `Mailbox blocks answer in about ${2 * ms}-${3 * ms} ms plus the bus.` + rx + " A faster mailbox poll costs more PLC CPU. Values and status stay at the poll above.";
}
function mailboxPollField(c, path) {
  const poll = Number.isInteger(c.poll_ms) && c.poll_ms >= 5 ? c.poll_ms : 10;
  const def = mailboxPollDefault(poll);
  const list = [{ value: undefined, label: `${def} ms (default)`, help: mailboxPollHelp(def) }];
  for (const ms of MAILBOX_POLLS) {
    if (ms !== def && ms >= poll && ms % poll === 0) list.push({ value: ms, label: `${ms} ms`, help: mailboxPollHelp(ms) });
  }
  list.sort((a, b) => (a.value || def) - (b.value || def));
  return choice("Mailbox poll", path + ".mailbox_poll_ms", list, { dataset: { mailboxPoll: "1" }, onChange: (v) => {
    setPath(path + ".mailbox_poll_ms", v);
    render();
  } });
}

// The kind's own settings, folded under the row.
function connectionSettings(c, i) {
  const path = `bridge.connections[${i}]`;
  const kind = c.kind;
  const fields = [];
  const notes = [];
  const rowNotes = [];  // shown on the row, outside Settings
  const bound = (f) => {
    // A connection field: writers and the undo step follow the connection.
    for (const x of f.querySelectorAll("input[data-path], select[data-path]")) x.addEventListener("input", syncWriters);
    return f;
  };
  if (kind === "openplc") {
    notes.push(el("p", { class: "muted" }, "Save writes OpenPLC's remote device, the canworks_in and canworks_out programs and the canworks variable list into the editor project (see the Project page). 32- and 64-bit values are low word first, as OpenPLC reads them."),
      openplcFacts());
    fields.push(
      field("Poll (ms)", path + ".poll_ms", "int", { placeholder: "10",
        hint: "How often OpenPLC reads and writes the registers, 5 to 1000 ms. Each poll takes one Modbus request per register group." }),
      ...(getPath("bridge.mailboxes") ? [mailboxPollField(c, path)] : []),
      field("Remote device name", path + ".remote_device", "text", { placeholder: "canworks",
        hint: "The remote device in the editor project: devices/remote/<name>.json." }),
      field("First editor location", path + ".iec_base", "int", { placeholder: "first free from 100",
        hint: "The register groups get %IW and %QW from this word number on in the editor project. Empty: the first number from 100 that the project does not use." }));
  }
  if (kind === "trust" || kind === "plc" || kind === "hmi") {
    fields.push(choice("Format", path + ".format", CONNECTION_FORMATS[kind]));
  }
  if (kind === "openplc" || kind === "trust" || kind === "plc") fields.push(inputsOnLossField(c, path));
  if (kind === "trust" || kind === "plc") {
    const listen = bridgeSplitListen(getPath("bridge.listen") || "")[0];
    fields.push(field("Bridge address the PLC uses", path + ".bridge_host", "text",
      { placeholder: PLCOPEN_WILDCARD.includes(listen) || isLoopback(listen) ? "the bridge's address as the PLC sees it" : listen,
        hint: "Empty: the listen address, when it is neither a wildcard nor loopback." }));
    if ((c.format || "plcopen") === "plcopen") fields.push(checkbox("Include the canworks library", path + ".library", true));
    if (kind === "plc") notes.push(el("p", { class: "hint", dataset: { connCodesys: "1" } }, "CODESYS is not a Modbus client of the bridge: for CODESYS pick the CODESYS target, where CODESYS runs the CANopen master."));
    if (getPath("bridge.plc_link") !== true) {
      rowNotes.push(notice("info", "This PLC needs the bridge's PLC link: the bridge then puts its map hash at input registers 0-1 and takes a header at holding registers 0-2, so a program built for another map leaves the outputs off.",
        { live: false, dataset: { connPlcLink: String(i) }, actions: [el("button", { type: "button", class: "primary", dataset: { plcLinkOn: "1" },
          onclick: (e) => busy(e.currentTarget, "Packing…", plcLinkOn) }, "Turn on the PLC link and repack")] }));
    }
  }
  if (kind === "nodered") {
    fields.push(
      field("Period (ms)", path + ".period_ms", "int", { placeholder: "10", hint: "How often the flow reads and writes the registers, 10 to 60000 ms." }),
      field("Bridge address", path + ".bridge_host", "text", { placeholder: "127.0.0.1", hint: "The bridge's address as Node-RED sees it. Empty: 127.0.0.1." }));
  }
  // With the PLC link the flow is read-only: its block nodes cannot use the mailboxes.
  if (kind === "trust" || kind === "plc" || (kind === "nodered" && (getPath("bridge.plc_link") !== true || c.blocks)))
    fields.push(connectionBlocksField(c, path));
  if (!fields.length && !notes.length) return rowNotes;
  const open = S.connOpen === i;
  const box = el("details", { class: "advanced", open: open || null, dataset: { connSettingsOf: String(i) } }, el("summary", null, "Settings"),
    ...notes, fields.length ? el("div", { class: "grid" }, fields.map(bound)) : null);
  box.addEventListener("toggle", () => { S.connOpen = box.open ? i : (S.connOpen === i ? null : S.connOpen); });
  return rowNotes.concat([box]);
}

// One request mailbox and nothing else, packed: what truST's one request
// each way holds (Problems "Trim the mailboxes for truST"), one undo step.
async function trimMailboxesForTrust() {
  const cfg = fileConfig();
  cfg.bridge.mailboxes = Object.assign({}, cfg.bridge.mailboxes, { requests: 1, receive: false, network_info: false, cyclic_jobs: 0 });
  delete cfg.bridge.mailboxes.receive_blocks;
  try {
    const r = await api("POST", "/api/bridge/pack", { config: cfg });
    bridgeReplaceDraft(r.config);
    changed(true);
    banner("The mailboxes keep one request mailbox, and every location is packed. Undo takes both back.");
  } catch (e) {
    banner(`Pack for Modbus failed: ${e.message}`, true);
  }
}

// Problems' Set canworks blocks to None for a truST connection whose map is
// too big even with one request mailbox: its blocks go, and the mailboxes too
// when neither OpenPLC nor another connection uses them; packed, one undo step.
async function noMailboxesForTrust(i) {
  const cfg = fileConfig();
  const list = cfg.bridge.connections || [];
  if (list[i]) delete list[i].blocks;
  const others = list.some((c, k) => k !== i && c && c.blocks && c.blocks !== "none") || list.some((c) => c && c.kind === "openplc");
  if (!others) delete cfg.bridge.mailboxes;
  try {
    const r = await api("POST", "/api/bridge/pack", { config: cfg });
    bridgeReplaceDraft(r.config);
    changed(true);
    banner((others ? "The connection's canworks blocks are None" : "The connection's canworks blocks are None and the mailboxes are off") +
      ", and every location is packed. Undo takes it back.");
  } catch (e) {
    banner(`Pack for Modbus failed: ${e.message}`, true);
  }
}

async function plcLinkOn() {
  const cfg = fileConfig();
  cfg.bridge.plc_link = true;
  try {
    const r = await api("POST", "/api/bridge/pack", { config: cfg });
    bridgeReplaceDraft(r.config);
    changed(true);
    banner("The PLC link is on and every location is packed. Undo takes both back.");
    return true;
  } catch (e) {
    banner(`Pack for Modbus failed: ${e.message}`, true);
    return false;
  }
}

// Add connection: the five kinds, each with what it gets, then its name,
// address and Writes. OpenPLC on a standalone config also offers New editor
// project… and Move into project…, which add the connection on the way.
async function addConnection() {
  const has = connectionsOf("openplc").length > 0;
  const pick = (k) => el("label", { class: "choice" },
    el("input", { type: "radio", name: "conn-kind", value: k.kind, dataset: { connKind: k.kind },
      disabled: k.kind === "openplc" && has ? "" : null, checked: k.kind === (has ? "hmi" : "openplc") || null }),
    el("strong", null, k.title), el("span", null, k.kind === "openplc" && has ? "The config already has an OpenPLC connection." : k.gets));
  const name = el("input", { type: "text", spellcheck: "false", id: "conn-name", dataset: { connName: "1" } });
  const address = el("input", { type: "text", spellcheck: "false", id: "conn-address", placeholder: "e.g. 192.168.10.20", dataset: { connAddress: "1" } });
  const writes = el("input", { type: "checkbox", dataset: { connWrites: "1" } });
  const addressMsg = el("span", { class: "field-msg", dataset: { connMsg: "address" } });
  const kindOf = () => (form.querySelector("input[name=conn-kind]:checked") || {}).value || "hmi";
  // Next to a PLC link one PLC writes already: a new connection starts read-only (UI-2).
  const link = !!(fileConfig().bridge || {}).plc_link;
  const other = el("div", { class: "grid" },
    el("div", { class: "field" }, el("label", { for: "conn-name" }, "Name"), name, hint("Empty: the kind's name.")),
    el("div", { class: "field" }, el("label", { for: "conn-address" }, "Address"), address, addressMsg,
      hint("The client's IP address, as the bridge sees it.")),
    el("div", { class: "check-field" }, el("label", { class: "check" }, writes, " Writes"),
      hint("On: the bridge takes writes (outputs, blocks) from this address. With the PLC link only the PLC writes.")));
  const standalone = S.state.mode !== "project";
  const cli = !!S.state.openplc_cli;
  const openplcNote = el("p", { class: "hint", dataset: { connOpenplcNote: "1" } },
    "OpenPLC runs next to the bridge and reads and writes it on 127.0.0.1:1502. Adding it turns on the PLC link, low word first and a live list per CANopen master network, and repacks. The mailboxes stay off until the program declares a mailbox block." +
    (standalone ? " Its editor files need an editor project: " + (cli ? "New editor project… or Move into project… make one with this config."
      : "the OpenPLC Editor's command-line tool (openplc-cli) was not found on this PC, so New editor project… is off; Move into project… copies the config into an existing one.") : ""));
  const form = el("div", { class: "new-config", dataset: { connDialog: "1" } },
    el("fieldset", null, el("legend", null, "Kind"), el("div", { class: "target-choices" }, CONNECTION_KINDS.map(pick))),
    other, openplcNote);
  // The buttons follow the kind: OpenPLC on a standalone config also gets
  // New editor project… and Move into project….
  // Node-RED and an HMI usually run on the bridge's device: 127.0.0.1 until the user types another address.
  let prefilled = "";
  // A kind picked: its Writes default and, for Node-RED and an HMI, the prefilled address.
  const syncKind = () => {
    const k = kindOf();
    other.hidden = k === "openplc";
    openplcNote.hidden = k !== "openplc";
    writes.checked = (k === "trust" || k === "plc") && !link;
    if (address.value.trim() === prefilled) {
      prefilled = k === "nodered" || k === "hmi" ? "127.0.0.1" : "";
      address.value = prefilled;
    }
    addressMsg.textContent = "";
    address.removeAttribute("aria-invalid");
    syncButtons();
  };
  const syncButtons = () => {
    const project = kindOf() === "openplc" && standalone;
    const btn = (v) => document.querySelector(`#modal-buttons [data-value=${v}]`);
    if (!btn("add")) return;
    btn("add").textContent = project ? "Add to this config" : "Add";
    btn("new").hidden = btn("move").hidden = !project;
    btn("new").disabled = !cli;
    btn("new").title = cli ? "Create an OpenPLC Editor project with this config and its OpenPLC connection" : "The OpenPLC Editor's command-line tool (openplc-cli) was not found on this PC";
  };
  form.addEventListener("change", (e) => { if (e.target.name === "conn-kind") syncKind(); });
  syncKind();
  let v, kind;
  for (;;) {
    const answer = modal("Add connection", [["add", "Add", true], ["new", "New editor project…"], ["move", "Move into project…"], ["cancel", "Cancel"]], form);
    syncButtons();
    if (addressMsg.textContent) setTimeout(() => address.focus(), 0);
    v = await answer;
    kind = kindOf();
    // The address is required (UI-10): said under the field, and the dialog stays.
    if (v === "add" && kind !== "openplc" && !address.value.trim()) {
      addressMsg.textContent = "Give the client's address";
      address.setAttribute("aria-invalid", "true");
      continue;
    }
    break;
  }
  if (v === "new" || v === "move") {
    if (S.dirty) { banner("Save the config first: the editor project gets the saved config, with an OpenPLC connection.", true); return; }
    await (v === "new" ? newEditorProject() : moveIntoProject());
    return;
  }
  if (v !== "add") return;
  await addConnectionOf(kind, kind === "openplc" ? {} : { name: name.value.trim() || undefined, address: address.value.trim() || undefined, writes: writes.checked });
}

// Adds a connection of `kind` (the server sets an OpenPLC connection's bridge
// settings and repacks), one undo step.
async function addConnectionOf(kind, fields) {
  let r;
  try {
    r = await api("POST", "/api/connections/add", { config: fileConfig(), connection: Object.assign({ kind }, fields || {}) });
  } catch (e) {
    banner(`The connection was not added: ${e.message}`, true);
    return;
  }
  bridgeReplaceDraft(r.config);
  S.connOpen = r.index;
  if (kind === "openplc" && S.view !== "bridge" && S.view !== "project") S.view = "bridge";
  changed(true);
  const c = r.config.bridge.connections[r.index];
  banner(el("span", { dataset: { connAdded: kind } },
    `Added ${c.name}.` + (kind === "openplc" ? " The PLC link, low word first and the live lists are on, and every location is packed. The mailboxes stay off until the program declares a mailbox block." +
      (S.state.mode === "project" ? " Save writes the editor files." : "") +
      (r.old_main ? ` main still declares ${r.old_main} canworks value${r.old_main === 1 ? "" : "s"} at the plugin's locations: after Save, Use canworks.* in main on the Project page.` : "")
      : " Download gives its files.") + " ",
    el("button", { type: "button", class: "link", dataset: { undo: "1" }, onclick: () => undo(false) }, "Undo")));
}

// Removes a connection; OpenPLC asks first (its editor files stay on disk).
async function removeConnection(i) {
  const list = S.model.top.bridge.connections;
  const c = list[i];
  if (c && c.kind === "openplc") {
    const v = await modal(`Remove the OpenPLC connection ${c.name}? Save then writes no editor files; the files already in the editor project stay on disk.`,
      [["cancel", "Cancel"], ["remove", "Remove", { danger: true }]]);
    if (v !== "remove") return;
  }
  list.splice(i, 1);
  syncWriters();
  if (!list.length) delete S.model.top.bridge.connections;
  S.connOpen = null;
  changed(true);
}

// Package on a Node-RED row: the node package the flow needs, the same .tgz
// as `canworks-deploy --export-nodered-package` writes.
async function noderedPackageDownload() {
  let r;
  try {
    r = await api("POST", "/api/nodered_package", {});
  } catch (e) {
    banner(e.message, true);
    return;
  }
  downloadBase64(r.data, r.name, r.content_type);
  banner(`Downloaded ${r.name}. Install it once in Node-RED: Manage palette > Install > upload.`, "done");
}

// Download: the connection's file, the same as the command line writes;
// the map hash goes into the connection, so the row can say when it is out
// of date.
async function connectionDownload(i) {
  const c = S.model.top.bridge.connections[i];
  const cfg = fileConfig();
  let r;
  try {
    r = await api("POST", "/api/connections/download", { config: cfg, index: i });
  } catch (e) {
    banner(e.message, true);
    return;
  }
  if (r.fix_first) {
    // An error on this connection or the listen address it needs (UI-3): nothing downloaded, the row stays as it was.
    const n = r.errors;
    const first = readable(r.items[0].message);
    S.check = exportProblems(r, cfg);
    applyCheck();
    banner(el("span", { dataset: { connFixFirst: String(i) } },
      `The saved config has ${counted(n, "error", "errors")}: fix ${n === 1 ? "it" : "them"} first. ${first} `,
      el("button", { type: "button", class: "link", dataset: { openProblems: "1" }, onclick: openProblems }, "Open Problems")), true);
    return;
  }
  if (r.errors) { exportStopped(c.name || CONNECTION_TITLE[c.kind], r, cfg); return; }
  downloadBase64(r.data, r.name, r.content_type);
  if ((r.map_hash && c.map_hash !== r.map_hash) || c.stale) {
    c.map_hash = r.map_hash || c.map_hash;
    delete c.stale;
    changed(true, `bridge.connections[${i}].map_hash`);
  }
  const notes = (r.notes || []).map((n) => ` Note: ${n}.`).join("");
  const how = c.kind === "nodered" ? ` Import it in Node-RED; it needs the package ${r.package} (Package on this row).` : r.name.endsWith(".zip") ? " Unzip it and follow README.txt." : "";
  banner(`Downloaded ${r.name}.${how} Save keeps its map hash, so the row says when the map changes.${notes}`, notes ? "warning" : "done");
}
