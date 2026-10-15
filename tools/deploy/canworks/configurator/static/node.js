"use strict";
// A node of a config in tabs (network-tree-and-node-tabs): General, PDOs,
// SDOs, Supervision, CiA 402 (drives), Simulation (simulated nodes), Notes
// and Advanced, one subject at a time. The open tab stays when the user
// opens another node, and is kept on this PC. Loaded after app.js.

const NODE_TABS = [["general", "General"], ["pdos", "PDOs"], ["sdos", "SDOs"], ["supervision", "Supervision"],
  ["cia402", "CiA 402"], ["simulation", "Simulation"], ["notes", "Notes"], ["advanced", "Advanced"]];

// The tabs node i has: CiA 402 for a drive (or a node with an axis already),
// Simulation for a simulated node.
function nodeTabs(i) {
  const n = S.config.nodes[i];
  const eds = edsFor(n);
  const drive = !!(objectInfo(eds, "0x6040", 0) && objectInfo(eds, "0x6041", 0));
  const axis = !!n.axis && typeof n.axis === "object";
  return NODE_TABS.filter(([k]) => (k !== "cia402" || drive || axis) && (k !== "simulation" || nodeSimulated(n)));
}

function nodeTab(i) {
  const have = nodeTabs(i).map(([k]) => k);
  return have.includes(S.nodeTab) ? S.nodeTab : "general";
}

function setNodeTab(k) {
  if (S.nodeTab === k) return;
  S.nodeTab = k;
  banner("");
  api("POST", "/api/ui", { node_tab: k }).catch(() => {});
}

function renderNode(view, i) {
  const n = S.config.nodes[i];
  const base = `nodes[${i}]`;
  const eds = edsFor(n);
  const tab = nodeTab(i);
  const exportBtn = el("button", { type: "button", dataset: { exportDcf: i }, title: "This node as a CiA 306 DCF file, checked",
    onclick: () => busy(exportBtn, "Exporting…", () => exportDcf(n.node_id, tabNetwork())) }, "Export DCF");
  const list = tabs(nodeTabs(i), tab, (k) => { setNodeTab(k); render(); },
    { class: "tabs node-tabs", dataset: "nodeTab", panel: "node-panel", label: `Node ${n.node_id ?? "?"} ${n.name || ""}`.trim() });
  view.append(
    el("div", { class: "toolbar" }, el("h2", { dataset: { nodeHeading: i } }, `Node ${n.node_id ?? "?"} ${n.name || ""}`),
      el("div", { class: "spacer" }), exportBtn,
      el("button", { type: "button", dataset: { removeNode: i }, onclick: () => removeNode(i) }, "Remove node")),
    list);
  const panel = el("div", { id: "node-panel", role: "tabpanel", "aria-labelledby": "node-panel-tab-" + tab, dataset: { nodeTabPanel: tab } });
  view.append(panel);
  if (tab === "general") {
    const edsSel = el("select", { dataset: { path: base + ".eds" }, "aria-label": "EDS file" },
      Object.keys(S.state.eds || {}).map((name) => el("option", { value: name }, name)));
    edsSel.value = n.eds || "";
    edsSel.addEventListener("change", () => { setPath(base + ".eds", edsSel.value); render(); });
    panel.append(el("fieldset", null, el("legend", null, "Node"),
      el("div", { class: "grid" },
        field("Node ID", base + ".node_id", "intstr"),
        field("Name", base + ".name", "text"),
        el("label", null, "EDS", edsSel, el("span", { class: "field-msg", dataset: { for: base + ".eds" } })),
        simSwitch(i))));
    if (eds && eds.error) panel.append(el("p", { class: "field-msg" }, eds.error));
  } else if (tab === "pdos") {
    if (eds && eds.error) panel.append(el("p", { class: "field-msg" }, eds.error));
    panel.append(el("div", { class: "pdo-columns" },
      renderPdos(i, "tx_pdos", "input", "Inputs (TPDOs, slave to PLC)", eds),
      renderPdos(i, "rx_pdos", "output", "Outputs (RPDOs, PLC to slave)", eds)));
  } else if (tab === "sdos") {
    panel.append(renderSdos(i, eds), renderSdoVars(i, eds));
  } else if (tab === "supervision") {
    panel.append(supervisionTab(i));
  } else if (tab === "cia402") {
    panel.append(axisFields(i, eds));
  } else if (tab === "simulation") {
    panel.append(nodeSimTab(n));
  } else if (tab === "notes") {
    panel.append(nodeNotesTab(n, eds));
  } else {
    S.advOpen = S.advOpen || {};
    if (S.advOpen["node" + i] === undefined) S.advOpen["node" + i] = true;  // the tab holds nothing else
    panel.append(nodeAdvanced(i, eds));
  }
  nodeTabBadges();
  // A node just added from an EDS gets its name field.
  if (S.focusName === i) { S.focusName = null; const name = view.querySelector(`input[data-path="${base}.name"]`); if (name) name.focus(); }
}

// Supervision and EMCY: how the master watches the node and where the PLC
// sees its state.
function supervisionTab(i) {
  const base = `nodes[${i}]`;
  const suggestBtn = (direction, key) => el("button", { type: "button", dataset: { suggest: direction },
    onclick: async () => {
      const r = await api("POST", "/api/place", { config: fileConfig(), network: S.net, node: i, direction });
      setPath(base + "." + key, r.location);
      render();
    } }, "Suggest");
  const nodeInput = (label, direction, key, placeholder, help) =>
    el("label", null, label, el("span", { class: "row" },
      field("", base + "." + key, "text", { placeholder }).querySelector("input"), suggestBtn(direction, key)),
      hint(help),
      el("span", { class: "field-msg", dataset: { for: base + "." + key } }),
      declNote(base + "." + key));
  return el("div", null,
    el("fieldset", null, el("legend", null, "Supervision"),
      el("div", { class: "grid" }, supervisionFields(i),
        nodeInput("Status bit", "status", "status_location", "%IX…",
          "Optional. TRUE while the node is configured and running. Empty: no status bit."),
        nodeInput("State byte", "state", "state_location", "%IB…",
          "Optional. The node's NMT state: 5 operational, 127 pre-operational, 4 stopped, 0 no contact. Kept current by heartbeat or guarding. Empty: no state byte."),
        nodeInput("NMT command", "nmt", "nmt_command_location", "%QB…",
          "Optional output byte the program uses to command the node: 0 or 1 run (1 also starts a node with boot off), 2 keep STOPPED, 128 keep PRE-OPERATIONAL, a change to 129 resets the node and to 130 its communication (once). Empty: none."),
        nodeInput("Boot error byte", "boot_error", "boot_error_location", "%IB…",
          "Optional. Why the last boot failed, as a CiA 302 letter code (66 B no answer, 77 M wrong product code, 74 J configuration refused, ...); 0 once the node boots. Empty: none."))),
    el("fieldset", null, el("legend", null, "Emergency (EMCY)"),
      el("div", { class: "grid" },
        nodeInput("EMCY code", "emcy", "emcy_code_location", "%IW…",
          "Optional. Error code of the node's latest emergency message, 0 when no error is active (after its error reset or a restart). Every EMCY is also logged. Empty: not mapped."),
        nodeInput("Error register", "errreg", "error_register_location", "%IB…",
          "Optional. Error register (object 0x1001 bits) from the latest emergency message, 0 after a restart. Empty: not mapped."),
        emcyCobField(i))));
}

// The node's part of simulation.json: value sources, faults at start and
// default behaviour, edited in the same draft as the Simulation tool.
function nodeSimTab(n) {
  if (!SIM.file) simLoad(); else simBind();
  const id = num(n.node_id);
  const box = el("div", { dataset: { nodeSim: String(id) } },
    el("div", { class: "toolbar" }, el("p", { class: "muted" },
      "What this simulated device does from the start, saved in simulation.json. Live values and faults on a running device are in the Simulation tab."),
      el("div", { class: "spacer" }), simSaveBar()),
    el("div", { dataset: { simProblems: "" } }));
  if (!Number.isInteger(id)) box.append(el("p", { class: "field-msg" }, "Give the node an ID first: the simulation file names devices by node ID."));
  else box.append(simDeviceFile(id, `Node ${id} ${n.name || ""}`, null));
  return box;
}

// The objects of the node's EDS that have a note, built-in or the user's own.
function nodeNotesTab(n, eds) {
  const box = el("div", { dataset: { nodeNotes: "1" } });
  const block = notesOf(n.eds);
  if (!n.eds || !eds || eds.error || !eds.objects) {
    box.append(el("p", { class: "muted" }, "No notes: the node has no EDS that could be read."));
    return box;
  }
  const editable = notesEditable(n.eds);
  const search = el("input", { type: "search", placeholder: "Index or name", "aria-label": "Search notes", dataset: { notesSearch: "1" } });
  search.value = S.notesFilter || "";
  const exportBtn = el("button", { type: "button", dataset: { exportNotes: "1" },
    title: "The notes of every object of this node's EDS, built-in and your own merged, as one file",
    onclick: () => busy(exportBtn, "Exporting…", () => exportNotes(n.eds)) }, "Export merged notes");
  const tbody = el("tbody");
  const fill = () => {
    const q = search.value.trim().toLowerCase().replace(/^0x/, "");
    S.notesFilter = search.value;
    const rows = [];
    for (const o of eds.objects) {
      const note = noteFor(block, n.eds, o.index, o.subindex, !!o.var);
      if (!Object.keys(note).length) continue;
      const idx = `${o.index}:${o.subindex}`;
      if (q && !idx.toLowerCase().replace(/0x/g, "").includes(q) && !(o.name || "").toLowerCase().includes(q)) continue;
      const meaning = [note.unit ? "unit " + note.unit : "", note.values ? Object.entries(note.values).map(([k, v]) => `${k} = ${v}`).join(", ") : ""].filter(Boolean).join("; ");
      rows.push(el("tr", { dataset: { noteRow: idx } },
        el("td", { class: "mono" }, idx), el("td", null, o.name || ""),
        el("td", null, note.text || "", meaning ? el("div", { class: "muted" }, meaning) : null),
        el("td", { class: "actions" }, editable ? el("button", { type: "button", class: "small", dataset: { noteEdit: idx },
          onclick: async () => { if (await editNote(n.eds, block, o.index, o.subindex, !!o.var, `${idx} ${o.name || ""}`)) fill(); } }, "Note") : null)));
    }
    put(tbody, rows.length ? rows : [el("tr", null, el("td", { colspan: 4, class: "muted" }, q ? "No note matches." : "No object of this EDS has a note yet."))]);
  };
  search.addEventListener("input", fill);
  fill();
  box.append(el("div", { class: "toolbar" }, search, el("div", { class: "spacer" }), exportBtn));
  if (!editable) box.append( el("p", { class: "muted", dataset: { notesReadonly: "1" } },
      block && block.error ? `The notes file cannot be read: ${block.error}` : "These notes cannot be edited here (the EDS's notes file is not writable)."));
  box.append(el("table", { class: "od notes-table" }, el("thead", null, el("tr", null, thCells(["Object", "Name", "Note", ""]))), tbody));
  return box;
}

// The problem counts on the open node's tabs.
function nodeTabBadges() {
  if (!S.view.startsWith("node:") || workspace() !== "configure") return;
  const i = S.view.slice(5);
  const counts = treeCounts();
  for (const b of document.querySelectorAll(".node-tabs [role=tab]")) {
    const old = b.querySelector(".tree-badge");
    if (old) old.remove();
    const x = badge(counts[`${S.net}:node:${i}/${b.dataset.nodeTab}`]);
    if (x) b.append(" ", x);
  }
}
