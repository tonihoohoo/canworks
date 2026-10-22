"use strict";
// A node of a config in tabs (network-tree-and-node-tabs): General, PDOs,
// SDOs, Supervision, CiA 402 (drives), Simulation (simulated nodes), Notes
// and Advanced, one subject at a time. The open tab stays when the user
// opens another node, and is kept on this PC. Loaded after app.js.

const NODE_TABS = [["general", "General"], ["pdos", "PDOs"], ["sdos", "SDOs"], ["supervision", "Supervision"],
  ["cia402", "CiA 402"], ["simulation", "Simulated device"], ["notes", "Notes"], ["advanced", "Advanced"]];

// The tabs node i has: CiA 402 for a drive (or a node with an axis already)
// when the target runs the axis, Simulation for a simulated node.
function nodeTabs(i) {
  const n = S.config.nodes[i];
  const eds = edsFor(n);
  const drive = !!(objectInfo(eds, "0x6040", 0) && objectInfo(eds, "0x6041", 0));
  const axis = !!n.axis && typeof n.axis === "object";
  return NODE_TABS.filter(([k]) => (k !== "cia402" || ((drive || axis) && usedBy("nodes.axis"))) && (k !== "simulation" || nodeSimulated(n)));
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
  const list = tabs(nodeTabs(i).map(([k, label]) => [k, k === "notes" ? notesTabLabel(n.eds, eds) : label]), tab, (k) => { setNodeTab(k); render(); },
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
    if (eds && eds.error) panel.append(notice("error", eds.error, { live: false, dataset: { nodeMsg: "eds-error" } }));
    panel.append(el("fieldset", null, el("legend", null, "Node"),
      el("div", { class: "grid" },
        field("Node ID", base + ".node_id", "intstr"),
        field("Name", base + ".name", "text"),
        el("label", null, "EDS", edsSel, el("span", { class: "field-msg", dataset: { for: base + ".eds" } })),
        simSwitch(i))));
  } else if (tab === "pdos") {
    if (eds && eds.error) panel.append(notice("error", eds.error, { live: false, dataset: { nodeMsg: "eds-error" } }));
    panel.append(el("div", { class: "pdo-columns" },
      renderPdos(i, "tx_pdos", "input", "Inputs (TPDOs, slave to PLC)", eds),
      renderPdos(i, "rx_pdos", "output", "Outputs (RPDOs, PLC to slave)", eds)));
  } else if (tab === "sdos") {
    // SDO variables are the plugin's and the bridge's.
    panel.append(renderSdos(i, eds), ...(usedBy("nodes.sdo_variables") ? [renderSdoVars(i, eds)] : []));
  } else if (tab === "supervision") {
    panel.append(supervisionTab(i, eds));
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
function supervisionTab(i, eds) {
  const base = `nodes[${i}]`;
  const emcy = edsHasEmcy(eds);
  const emcyKeys = ["emcy_code_location", "error_register_location", "emcy_cob_id"];
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
  return el("div", { class: "wide-cols" },
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
    // The EMCY settings are canworks's: CODESYS reads emergencies itself
    // (canopen-configurator "Only what the target uses is shown").
    !(usedBy("nodes.emcy_cob_id") || usedBy("nodes.emcy_code_location")) ? null
      : emcyFieldset(emcy, emcyKeys.some((k) => getPath(base + "." + k) !== undefined), () => emcyKeys.forEach((k) => setPath(base + "." + k, undefined)),
      el("div", { class: "grid" },
        nodeInput("EMCY code", "emcy", "emcy_code_location", "%IW…",
          "Optional. Error code of the node's latest emergency message, 0 when no error is active (after its error reset or a restart). Every EMCY is also logged. Empty: not mapped."),
        nodeInput("Error register", "errreg", "error_register_location", "%IB…",
          "Optional. Error register (object 0x1001 bits) from the latest emergency message, 0 after a restart. Empty: not mapped."),
        emcyCobField(i))));
}

// The Emergency (EMCY) section: when the node's EDS has no 0x1014 it is one
// line with the reason and no controls (canopen-configurator "EMCY section
// follows the EDS"); fields left in the file stay, with Remove.
function emcyFieldset(supported, leftover, remove, grid) {
  const box = el("fieldset", { dataset: { emcySection: supported ? "" : "unsupported" } }, el("legend", null, "Emergency (EMCY)"));
  if (supported) { box.append(grid); return box; }
  const why = "The EDS has no EMCY COB-ID (0x1014), so this device sends no emergency messages.";
  box.append(edsLimit(why, leftover, { label: "Remove the EMCY settings", dataset: { emcyRemove: "" }, run: remove },
    { emcyLimit: "" }, true));
  if (leftover) box.append(grid);
  return box;
}

// The node's part of simulation.json: value sources, faults at start and
// default behaviour, edited in the same draft as the Simulation tool.
function nodeSimTab(n) {
  if (!SIM.file) simLoad(); else simBind();
  const id = num(n.node_id);
  const box = el("div", { dataset: { nodeSim: String(id) } },
    Number.isInteger(id) ? null : notice("info", "Give the node an ID first: the simulation file names devices by node ID.", { live: false }),
    el("div", { class: "toolbar" }, el("p", { class: "muted" },
      "What this simulated device does from the start, saved in simulation.json. Live values and faults on a running device are in Commission → Simulation."),
      el("div", { class: "spacer" }), simSaveBar()),
    el("div", { dataset: { simProblems: "" } }));
  if (Number.isInteger(id)) box.append(simDeviceFile(id, `Node ${id} ${n.name || ""}`, null));
  return box;
}

// -- Notes tab (notes-tab-own-notes): the user's own notes first, with
// views for all notes and all objects, and the place to add, import and
// export notes. The Note editor is opened from here only.
const NOTE_VIEWS = [["mine", "My notes"], ["all", "All notes"], ["objects", "All objects"]];

function noteFilled(entry) {
  return !!entry && NOTE_FIELDS.some((f) => entry[f] !== undefined && entry[f] !== "");
}

// One row of an EDS object for the Notes tab: its merged note and where the
// note comes from ("mine", "builtin", "changed" or "" for none).
function noteRowOf(block, name, o) {
  const isVar = !!o.var;
  const note = noteFor(block, name, o.index, o.subindex, isVar);
  if (!block) return { o, note, source: "" };
  const device = block.error ? {} : applyNoteEdits(block.device, name ? noteEdits(name) : null);
  const own = noteFilled(noteLayer(device, o.index, o.subindex, isVar));
  const built = noteFilled(noteLayer(block.builtin || {}, o.index, o.subindex, isVar));
  return { o, note, source: own ? (built ? "changed" : "mine") : built ? "builtin" : "" };
}

const NOTE_SOURCE = { mine: "Mine", builtin: "Built-in", changed: "Built-in, changed" };

// `block` stands in for the EDS's notes in the page state (the notes an
// online object dictionary was read with); null: the page state's.
function noteRows(name, eds, block) {
  block = block || notesOf(name);
  return eds && eds.objects ? eds.objects.map((o) => noteRowOf(block, name, o)) : [];
}

// The number of objects with a note of the user's own, for the tab label.
function ownNoteCount(name, eds) {
  return noteRows(name, eds).filter((r) => r.source === "mine" || r.source === "changed").length;
}

// "Notes" with the count of the user's own notes, as the Log tab shows its entries.
function notesTabLabel(name, eds) {
  const c = name && eds && !eds.error ? ownNoteCount(name, eds) : 0;
  return c ? `Notes ${c}` : "Notes";
}

// `readBlock`: notes shown read-only (the notes an object dictionary was read
// with). `live` (Commission a device, which has no Save): {id, path, block},
// notes written at once to the notes file next to the node's EDS.
function nodeNotesTab(n, eds, readBlock, live) {
  const box = el("div", { dataset: { nodeNotes: "1" } });
  const name = n.eds;
  if (live) readBlock = live.block;
  const block = readBlock || notesOf(name);
  if (!name || !eds || eds.error || !eds.objects) {
    box.append(el("p", { class: "muted" }, "No notes: the node has no EDS that could be read."));
    return box;
  }
  const editable = live ? !!(live.block.editable && !live.block.error) : !readBlock && notesEditable(name);
  const openNote = async (o, idx) => {
    if (await editNote(name, block, o.index, o.subindex, !!o.var, `${idx} ${o.name || ""}`, live ? liveNoteCommit(live) : null)) afterNoteEdit(idx);
  };
  const view = NOTE_VIEWS.some(([k]) => k === S.notesView) ? S.notesView : "mine";
  const search = el("input", { type: "search", placeholder: "Index or name", "aria-label": "Search notes", dataset: { notesSearch: "1" } });
  search.value = S.notesFilter || "";
  const views = el("div", { class: "segmented", role: "group", "aria-label": "Show", dataset: { notesView: view } },
    NOTE_VIEWS.map(([k, label]) => el("button", { type: "button", "aria-pressed": String(view === k), dataset: { notesViewPick: k },
      onclick: () => { S.notesView = k; render(); focusSel(`[data-notes-view-pick="${k}"]`); } }, label)));
  const addBtn = editable ? el("button", { type: "button", dataset: { addNote: "1" }, title: "Write a note for any object of this EDS",
    onclick: () => addNote(name, eds, live) }, "Add note…") : null;
  const importBtn = editable ? el("button", { type: "button", dataset: { importNotes: "1" }, title: "Add the notes of a notes file, with a preview first",
    onclick: () => importNotes(name, live) }, "Import notes…") : null;
  const exportBtn = el("button", { type: "button", dataset: { exportNotes: "1" }, title: "Your own notes, or all notes merged with the built-in ones, as a notes file",
    onclick: () => exportNotesAsk(name, eds, exportBtn, readBlock) }, "Export notes…");
  const rows = noteRows(name, eds, readBlock);
  const shown = rows.filter((r) => view === "objects" || (view === "all" ? !!Object.keys(r.note).length : r.source === "mine" || r.source === "changed"));
  const tbody = el("tbody");
  const empty = el("div", { dataset: { notesEmpty: view } });
  const fill = () => {
    const q = search.value.trim().toLowerCase().replace(/^0x/, "");
    S.notesFilter = search.value;
    const out = [];
    for (const { o, note, source } of shown) {
      const idx = `${o.index}:${o.subindex}`;
      if (q && !idx.toLowerCase().replace(/0x/g, "").includes(q) && !(o.name || "").toLowerCase().includes(q)
        && !(note.text || "").toLowerCase().includes(q)) continue;
      const sum = noteSummary(note);
      const meaning = sum ? sum.short : "";
      // The row opens its note on a click, as the Add note picker's rows do;
      // the Note button is the keyboard's. A click that selects text does not.
      out.push(el("tr", { class: editable ? "row-open" : null, dataset: { noteRow: idx, noteSource: source || "none" },
        onclick: editable ? (e) => { if (!e.target.closest("button, a, input") && !textSelected()) openNote(o, idx); } : null },
        el("td", { class: "mono" }, idx), el("td", null, o.name || ""),
        el("td", null, note.text || "", meaning ? el("div", { class: "muted", title: sum.short !== sum.full ? sum.full : null }, meaning) : null),
        el("td", { class: "muted note-source" }, NOTE_SOURCE[source] || ""),
        el("td", { class: "actions" }, editable ? el("button", { type: "button", class: "small", dataset: { noteEdit: idx },
          "aria-label": `Note for ${idx} ${o.name || ""}`.trim(), onclick: () => openNote(o, idx) }, "Note") : null)));
    }
    put(tbody, out);
    table.hidden = !out.length;
    if (out.length) { empty.replaceChildren(); return; }
    if (q && shown.length) { empty.replaceChildren(el("p", { class: "muted" }, "No note matches.")); return; }
    const showAll = el("button", { type: "button", dataset: { notesShowAll: "1" },
      onclick: () => { S.notesView = "all"; render(); focusSel('[data-notes-view-pick="all"]'); } }, "Show all notes");
    empty.replaceChildren(view === "mine"
      ? el("div", { class: "empty-state" }, el("p", { class: "muted" }, "You have not written any notes for this device yet. "
          + (editable ? "Add a note for any object, or import a notes file." : "")),
        el("div", { class: "toolbar" }, editable ? el("button", { type: "button", onclick: () => addNote(name, eds, live) }, "Add note…") : null,
          editable ? el("button", { type: "button", onclick: () => importNotes(name, live) }, "Import notes…") : null, showAll))
      : el("p", { class: "muted" }, "No object of this EDS has a note yet."));
  };
  const table = el("table", { class: "od notes-table" },
    el("thead", null, el("tr", null, thCells(["Object", "Name", "Note", "From", ""]))), tbody);
  search.addEventListener("input", fill);
  box.append(el("div", { class: "toolbar notes-toolbar" }, search, views, addBtn, importBtn, exportBtn));
  if (!editable) box.append(el("p", { class: "muted", dataset: { notesReadonly: "1" } },
    block && block.error ? `The notes file cannot be read: ${block.error}`
      : live && live.block.why ? `These notes cannot be edited here: ${live.block.why}.`
      : S.state && S.state.commission ? "These notes cannot be edited here: the node's EDS has no notes file of its own."
      : "These notes cannot be edited here (the EDS's notes file is not writable)."));
  else if (live && live.block.file) box.append(el("p", { class: "muted", dataset: { notesLive: "1" } },
    `Notes are written at once to ${live.block.file} next to the EDS.`));
  box.append(table, empty);
  fill();
  return box;
}

function focusSel(sel) { const x = document.querySelector(sel); if (x) x.focus(); }

function textSelected() { const t = window.getSelection ? String(window.getSelection()) : ""; return !!t.trim(); }

// After a note was written on the Notes tab: the tab (and its count) again,
// with the focus on that object's row (the Commission tab builds a tick later).
function afterNoteEdit(idx) {
  render();
  const sel = `[data-note-row="${idx}"] button[data-note-edit]`;
  focusSel(sel);
  setTimeout(() => focusSel(sel), 0);
}

// "Add note…": a list of every object of the EDS; a click on a row (or its
// object button, Enter, Space) picks it, then the Note editor opens.
async function addNote(name, eds, live) {
  const block = live ? live.block : notesOf(name);
  const rows = noteRows(name, eds, live ? live.block : null);
  const filter = el("input", { type: "search", placeholder: "Index or name", "aria-label": "Find an object", dataset: { notePickerFilter: "1" } });
  const body = el("tbody");
  let picked = null;
  const choose = (r) => { picked = r; const b = document.querySelector('#modal-buttons [data-value="pick"]'); if (b) b.click(); };
  const buttons = () => [...body.querySelectorAll("button[data-note-pick]")];
  const fill = () => {
    const q = filter.value.trim().toLowerCase().replace(/^0x/, "");
    body.replaceChildren(...rows.filter(({ o }) => !q || `${o.index}:${o.subindex}`.toLowerCase().replace(/0x/g, "").includes(q)
      || (o.name || "").toLowerCase().includes(q)).map((r) => {
      const idx = `${r.o.index}:${r.o.subindex}`;
      return el("tr", { class: "row-open", dataset: { notePickRow: idx }, onclick: (e) => { if (!e.target.closest("button")) choose(r); } },
        el("td", null, el("button", { type: "button", class: "small mono", dataset: { notePick: idx },
          "aria-label": `${r.source ? "Edit the note of" : "Write a note for"} ${idx} ${r.o.name || ""}`.trim(), onclick: () => choose(r) }, idx)),
        el("td", null, r.o.name || ""),
        el("td", { class: "muted" }, r.source ? NOTE_SOURCE[r.source] : "no note"));
    }));
  };
  filter.addEventListener("input", fill);
  filter.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      const first = buttons()[0];
      if (first) first.click();
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      const first = buttons()[0];
      if (first) first.focus();
    }
  });
  // Up and Down move between the rows; Up on the first row back to the search.
  body.addEventListener("keydown", (e) => {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    const list = buttons();
    const i = list.indexOf(document.activeElement);
    if (i < 0) return;
    e.preventDefault();
    const next = e.key === "ArrowDown" ? list[Math.min(i + 1, list.length - 1)] : i === 0 ? filter : list[i - 1];
    next.focus();
    if (next !== filter) next.scrollIntoView({ block: "nearest" });
  });
  fill();
  const box = el("div", { class: "note-picker" }, filter,
    el("div", { class: "note-picker-list" }, el("table", { class: "od note-pick-table" },
      el("colgroup", null, el("col", { class: "c-obj" }), el("col"), el("col", { class: "c-from" })),
      el("thead", null, el("tr", null, thCells(["Object", "Name", "Note"]))), body)));
  const v = await modal("Add a note: click the object.", [["cancel", "Cancel"], ["pick", "Pick", { hidden: true }]], box);
  if (v !== "pick" || !picked) return;
  const idx = `${picked.o.index}:${picked.o.subindex}`;
  if (await editNote(name, block, picked.o.index, picked.o.subindex, !!picked.o.var, `${idx} ${picked.o.name || ""}`,
    live ? liveNoteCommit(live) : null)) {
    if (S.notesView !== "objects") S.notesView = S.notesView || "mine";
    S.notesFilter = "";
    afterNoteEdit(idx);
  }
}

// "Import notes…": a notes file, a preview of what it changes, then one draft edit.
async function importNotes(name, live) {
  const input = el("input", { type: "file", accept: ".json", "aria-label": "Notes file", dataset: { importNotesFile: "1" } });
  const pick = await modal("Import notes from a notes file (.notes.json, also a file made by Export notes):",
    [["next", "Next", true], ["cancel", "Cancel"]], input);
  if (pick !== "next" || !input.files.length) return;
  const file = input.files[0];
  let r;
  try {
    r = await api("POST", "/api/import_notes", live ? { eds_path: live.path, file: file.name, text: await file.text() }
      : { config: fileConfig(), eds: name, file: file.name, text: await file.text(), notes: S.model.notes });
  } catch (e) { banner(e.message, true); return; }
  const p = r.preview;
  const count = Object.keys(r.changes).length;
  const label = (k) => `${k} ${r.names[k] || ""}`.trim();
  const group = (key, title) => p[key].length ? el("details", { dataset: { importGroup: key } },
    el("summary", null, `${title}: ${p[key].length}`), el("ul", null, p[key].map((k) => el("li", null, label(k))))) : null;
  const box = el("div", { class: "note-import", dataset: { importPreview: "1" } },
    r.warnings.length ? el("div", { class: "notice-slot" },
      r.warnings.map((w) => notice("warning", w + ".", { live: false, dataset: { importWarning: "1" } }))) : null,
    el("p", null, `New notes: ${p.new.length}. Changed notes: ${p.changed.length}. Already the same: ${p.same.length}. `
      + `Skipped (not in ${name}): ${p.skipped.length}.`),
    group("new", "New notes"), group("changed", "Changed notes"), group("same", "Already the same"), group("skipped", "Skipped"));
  if (!count) {
    await modal(`${file.name}: nothing to import, the notes are already the same.`, [["cancel", "Close"]], box);
    return;
  }
  const go = await modal(`${file.name} into the notes of ${name}:`, [["cancel", "Cancel"], ["import", `Import ${count} note${count === 1 ? "" : "s"}`, true]], box);
  if (go !== "import") return;
  if (live) {
    S.notesView = "mine";
    S.notesFilter = "";
    await liveNotesWrite(live, r.changes, `Import ${count} note${count === 1 ? "" : "s"} from ${file.name}`);
    return;
  }
  S.model.notes = S.model.notes || {};
  S.model.notes[name] = Object.assign(S.model.notes[name] || {}, r.changes);
  S.notesView = "mine";
  S.notesFilter = "";
  changed(true);
  banner(`Imported ${count} note${count === 1 ? "" : "s"} from ${file.name}. Save to keep them; Ctrl+Z undoes the import.`);
}

// "Export notes…": the user's own notes, or all notes merged with the built-in ones.
async function exportNotesAsk(name, eds, button, readBlock) {
  const own = readBlock ? Object.values(readBlock.device || {}).filter(noteFilled).length : ownNoteCount(name, eds);
  const buttons = [["cancel", "Cancel"], ["merged", "Merged with built-in"]];
  if (own) buttons.push(["own", "My notes", true]);
  const v = await modal(own ? `Export the notes of ${name}: your own ${own} note${own === 1 ? "" : "s"}, or every note merged with canworks' built-in ones.`
    : `Export the notes of ${name}: you have no notes of your own yet, so only the merged file (with canworks' built-in notes) is offered.`, buttons);
  if (v !== "own" && v !== "merged") return;
  if (readBlock) { exportNotesRead(name, eds, readBlock, button, v === "own"); return; }
  await busy(button, "Exporting…", () => exportNotes(name, v === "own"));
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

// Export without a config (Commission a device): the notes the object
// dictionary was read with, built on the page, as one notes file: the
// user's own (the device file's filled entries) or merged with the built-in.
async function exportNotesRead(name, eds, block, button, own) {
  await busy(button, "Exporting…", async () => {
    const objects = {};
    if (own) {
      for (const [k, v] of Object.entries(block.device || {})) if (noteFilled(v)) objects[k] = v;
    } else {
      for (const { o, note } of noteRows(name, eds, block)) {
        if (Object.keys(note).length) objects[o.var && num(o.subindex) === 0 ? noteKey(o.index) : noteKey(o.index, o.subindex)] = note;
      }
    }
    const file = (name.split(/[\\/]/).pop() || "device") + (own ? "" : ".merged") + ".notes.json";
    const url = URL.createObjectURL(new Blob([JSON.stringify({ format: "canworks-notes.v1", eds: { file: name }, objects }, null, 2) + "\n"], { type: "application/json" }));
    const a = el("a", { href: url, download: file });
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 10000);
    banner(`Exported ${file}.`);
  });
}

// -- Commission a device: notes written at once (no Save there) -------------

// The Note editor's commit for a live tab: one change written to the file.
function liveNoteCommit(live) {
  return (changes, label) => liveNotesWrite(live, changes, `Note ${label.trim()}`);
}

// Writes `changes` ({key: note}) to the notes file next to the node's EDS;
// the tabs that show this EDS's notes get the new notes, the banner offers
// Undo and the commissioning log has the change. Returns whether it was written.
async function liveNotesWrite(live, changes, what) {
  let r;
  try { r = await api("POST", "/api/notes/write", { eds_path: live.path, changes }); }
  catch (e) { banner(e.message, true); return false; }
  liveNotesSet(live.path, r.notes);
  S.notesUndo = { path: live.path, node: live.id, text: r.previous, file: r.file, what };
  commLog(live.id, `${what} → ${r.file}`, "written");
  notesBanner(`${what}: written to ${r.path}. `);
  render();
  return true;
}

function notesBanner(text) {
  banner(el("span", { dataset: { timed: "1", notesWritten: "1" } }, text,
    el("button", { type: "button", class: "link", dataset: { notesUndo: "1" }, onclick: () => liveNotesUndo() }, "Undo")));
}

// The notes of an EDS path in every cached object dictionary that uses it.
function liveNotesSet(path, notes) {
  for (const c of Object.values(S.odEntries || {})) {
    let key = null;
    try { key = JSON.parse(c.key); } catch (e) { /* not a path key */ }
    if (Array.isArray(key) && key[0] === path && c.data) c.data.notes = notes;
  }
}

// Undo (banner or Ctrl+Z) of the last note write: the file as it was.
async function liveNotesUndo() {
  const u = S.notesUndo;
  if (!u) return false;
  let r;
  try { r = await api("POST", "/api/notes/write", { eds_path: u.path, restore: true, text: u.text }); }
  catch (e) { banner(e.message, true); return true; }
  S.notesUndo = null;
  liveNotesSet(u.path, r.notes);
  commLog(u.node, `Undo: ${u.what} → ${u.file}`, "written");
  banner(`Undone: ${u.what}. ${u.file} is as it was.`);
  render();
  return true;
}
