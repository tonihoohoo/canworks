// Project targets (canopen-configurator "Project target", "Only what the
// target uses is shown", "Switching the target", "CODESYS settings",
// "CODESYS actions"; docs/configurator.md): OpenPLC, the Modbus bridge or
// CODESYS. The server's relevance table (S.state.targets, targets.py) says
// what each target uses; the page hides the rest, and a value the target
// does not use but the config still has stays shown, marked, with Remove.
// Loaded after app.js and bridge.js and uses their helpers.
"use strict";

const TARGET_CHOICES = [
  { value: "openplc", label: "OpenPLC",
    help: "The OpenPLC plugin runs the networks. Each location size is its own table: %IW100 and %ID100 are different variables." },
  { value: "bridge", label: "Modbus bridge",
    help: "canworks-bridge runs the networks and serves the values as Modbus TCP registers, with no PLC. Locations are byte addresses: %IW0 is bytes 0 and 1, input register 0." },
  { value: "codesys", label: "CODESYS",
    help: "A CODESYS PLC runs the CANopen master networks: canworks builds the bus, the nodes and their named I/O channels into a CODESYS project. No PLC locations: each PDO entry's variable name names its channel." },
];
const TARGET_TITLE = { openplc: "OpenPLC", bridge: "Modbus bridge", codesys: "CODESYS" };
const TARGET_LABEL = { openplc: "OpenPLC", bridge: "the Modbus bridge", codesys: "CODESYS" };
// The top-level `codesys` keys; the network's own are net_id and interface.
const CODESYS_TOP_KEYS = ["project", "device", "create", "variables"];

// The target of a config (or of the draft's top-level keys).
function targetOf(cfg) {
  const obj = (v) => !!v && typeof v === "object" && !Array.isArray(v);
  if (cfg && obj(cfg.bridge)) return "bridge";
  if (cfg && obj(cfg.codesys)) return "codesys";
  return "openplc";
}

function projectTarget() { return S.model ? targetOf(S.model.top) : "openplc"; }

function targetRow(key) { return ((S.state && S.state.targets) || []).find((r) => r.key === key) || null; }

// Whether the project's target (or `tgt`) uses a key of the table; a key
// the table does not list is used by every target.
function usedBy(key, tgt) {
  const r = targetRow(key);
  return !r || r.targets.includes(tgt || projectTarget());
}

// The table row of a page path ("nodes[2].tx_pdos[0].timeout_ms"), from the
// most specific key down; null when no row covers it.
function pathRow(path) {
  const p = String(path).replace(/\[\d+\]/g, "");
  if (p === "gateway" || p.startsWith("gateway.")) return targetRow("/gateway");
  const parts = p.split(".");
  for (let i = parts.length; i > 0; i--) {
    const r = targetRow(parts.slice(0, i).join("."));
    if (r) return r;
  }
  return null;
}

// Why the target does not use a path, or null when it does.
function unusedWhy(path, tgt) {
  tgt = tgt || projectTarget();
  const r = pathRow(path);
  if (!r || r.targets.includes(tgt)) return null;
  return r.reasons[tgt] || "";
}

function isSetValue(v) {
  return v !== undefined && v !== null && v !== "" && v !== false && !(Array.isArray(v) && !v.length) &&
    !(typeof v === "object" && !Array.isArray(v) && !Object.keys(v).length);
}

// "not used by CODESYS" with the reason as its title, and Remove when the
// value can go (a network's protocol or role cannot: it is the network).
function unusedMark(path, why, removable) {
  const tgt = projectTarget();
  return el("span", { class: "unused-mark", dataset: { unusedFor: path } },
    el("span", { class: "tag warn-tag", title: why || "" }, `not used by ${TARGET_LABEL[tgt]}`),
    removable ? el("button", { type: "button", class: "link", dataset: { unusedRemove: path },
      title: "Remove this setting from the config", onclick: () => { setPath(path, undefined); changed(true); } }, "Remove") : null);
}

// The page after a render: every bound field the target does not use is
// hidden when empty and marked when set; options of a choice the target
// does not use are left out; a section left with no field is hidden.
function applyTarget(root) {
  if (!root || !S.model || !S.state || !S.state.targets) return;
  const tgt = projectTarget();
  for (const x of root.querySelectorAll("input[data-path], select[data-path], textarea[data-path]")) {
    const path = x.dataset.path;
    if (x.tagName === "SELECT") pruneOptions(x, path, tgt);
    const why = unusedWhy(path, tgt);
    if (why === null) continue;
    const box = x.closest(".check-field") || x.closest("label") || x.closest("td") || x.parentElement;
    if (!isSetValue(getPath(path))) {
      if (box.tagName === "TD") x.hidden = true;
      else box.hidden = true;
      continue;
    }
    if (!box.querySelector(`[data-unused-for="${CSS.escape(path)}"]`)) box.append(unusedMark(path, why, true));
  }
  for (const fs of root.querySelectorAll("fieldset, details.advanced")) {
    const fields = [...fs.querySelectorAll("input[data-path], select[data-path], textarea[data-path]")];
    if (fields.length && fields.every((f) => f.hidden || f.closest("[hidden]"))) fs.hidden = true;
  }
}

// The options of a choice that the target does not use ("PLC cycle" for the
// bridge, J1939 for CODESYS) are left out, except the one the config has,
// which is marked.
function pruneOptions(sel, path, tgt) {
  const base = String(path).replace(/\[\d+\]/g, "");
  for (const o of [...sel.options]) {
    if (o.value === "") continue;
    const r = targetRow(`${base}=${o.value}`);
    if (!r || r.targets.includes(tgt)) continue;
    if (o.value !== sel.value) { o.remove(); continue; }
    const box = sel.closest("label") || sel.parentElement;
    const kind = ["role=slave", "protocol=j1939", "protocol=none"].includes(r.key);
    if (!box.querySelector(`[data-unused-for="${CSS.escape(path)}"]`)) box.append(unusedMark(path, r.reasons[tgt] || "", !kind && !(r.refused || []).includes(tgt)));
  }
}

// Removes the value at a check place ({ net, path }) from the draft: a
// network's own path, or a top-level one (net null).
function removeUnused(w) {
  let parts = String(w.path).match(/[^.[\]]+/g) || [];
  // A version 1 file's master.diagnostics is the draft's one diagnostics object.
  if (parts[0] === "master" && (parts[1] === "diagnostics" || parts[1] === "cia309")) { parts = parts.slice(1); w = { net: null }; }
  let obj;
  if (w.net === null || w.net === undefined) {
    if (parts[0] === "diagnostics" || parts[0] === "cia309") {
      if (parts.length === 1) { delete S.model[parts[0]]; changed(true); return; }
      obj = S.model;
    } else obj = S.model.top;
  } else obj = S.model.networks[w.net];
  for (let i = 0; i < parts.length - 1 && obj; i++) obj = obj[/^\d+$/.test(parts[i]) ? Number(parts[i]) : parts[i]];
  if (obj && typeof obj === "object") delete obj[parts[parts.length - 1]];
  changed(true);
}

// -- the Project target field ---------------------------------------------------

function targetField() {
  return el("fieldset", { dataset: { bridgeTarget: "1", projectTarget: "1" } }, el("legend", null, "Project target"),
    el("div", { class: "grid" }, choice("Target", "", TARGET_CHOICES,
      { noPath: true, dataset: { target: "1" }, current: projectTarget(), onChange: switchTarget })));
}

// Switches the project target in one undo step: one dialog names what the
// new target does not use (Remove them, the default, or Keep them) and, as
// it applies, the repacking of the locations; the server does the switch
// (/api/switch_target).
async function switchTarget(target) {
  const from = projectTarget();
  if (target === from) return;
  let preview;
  try {
    preview = await api("POST", "/api/switch_target", { config: fileConfig(), target, preview: true });
  } catch (e) {
    banner(`The switch to ${TARGET_TITLE[target]} failed: ${e.message}`, true);
    render();
    return;
  }
  const removable = preview.unused.filter((u) => u.removable);
  const kept = preview.unused.filter((u) => !u.removable);
  const lines = [`Switch the project to ${TARGET_TITLE[target]}?`];
  if (target !== "openplc" && fileVersion(fileConfig()) === 1) lines.push("The file becomes version 2 (a list of networks) when saved.");
  if (target === "codesys") {
    lines.push("CODESYS assigns the I/O addresses itself: every PDO entry keeps its variable name, written into the config where it was generated.");
  } else if (from === "codesys") {
    if (preview.locations) lines.push(`${preview.locations} PDO entr${preview.locations === 1 ? "y gets a location" : "ies get a location"}` +
      (target === "bridge" ? ", packed for Modbus." : ", per type."));
  }
  if (removable.length) lines.push(`${removable.length} setting${removable.length === 1 ? " is" : "s are"} not used by ${TARGET_LABEL[target]}:`);
  if (kept.length) lines.push(`${kept.length} network${kept.length === 1 ? "" : "s"} ${kept.length === 1 ? "stays" : "stay"} with canworks and ${kept.length === 1 ? "is" : "are"} not exported.`);
  // Between OpenPLC and the bridge the addressing differs: repack, as before.
  const repack = from !== "codesys" && target !== "codesys"
    ? el("label", { class: "check" }, el("input", { type: "checkbox", checked: true, dataset: { switchPack: "1" } }),
      target === "bridge" ? " Pack every location for Modbus" : " Repack every location per type")
    : null;
  const list = preview.unused.length ? el("ul", { class: "switch-unused", dataset: { switchUnused: "1" } },
    preview.unused.slice(0, 12).map((u) => el("li", null, problemPlace(u.path) + humanUnused(u))),
    preview.unused.length > 12 ? el("li", { class: "muted" }, `and ${preview.unused.length - 12} more`) : null) : null;
  const extra = el("div", null, list, repack);
  const buttons = [["cancel", "Cancel"]];
  if (removable.length) buttons.push(["keep", "Switch, keep them"], ["remove", "Switch and remove them", true]);
  else buttons.push(["switch", "Switch", true]);
  const v = await modal(lines.join(" "), buttons, extra);
  if (!v || v === "cancel") { render(); return; }
  const pack = repack ? repack.querySelector("input").checked : true;
  let r;
  try {
    r = await api("POST", "/api/switch_target", { config: fileConfig(), target, keep: v === "keep", pack });
  } catch (e) {
    banner(`The switch to ${TARGET_TITLE[target]} failed: ${e.message}. The target is still ${TARGET_TITLE[from]}.`, true);
    render();
    return;
  }
  bridgeReplaceDraft(r.config);
  if ((S.view === "bridge" && target !== "bridge") || (S.view === "codesys" && target !== "codesys")) S.view = "bus";
  changed(true);
  const page = target === "bridge" ? " See the Modbus bridge page." : target === "codesys" ? " See the CODESYS page." : "";
  banner(`The project targets ${TARGET_TITLE[target]} now` + (r.removed ? `, ${r.removed} unused setting${r.removed === 1 ? "" : "s"} removed.` : ".") + page);
}

// "Node 5 rtd: " for a config path in the switch dialog's list.
function problemPlace(path) {
  const m = /^networks\[(\d+)\]\.(.*)$/.exec(path);
  const w = m ? { net: Number(m[1]), path: m[2] } : { net: m ? null : 0, path };
  try {
    const parts = placeOf(w);
    return parts.length ? parts.join(", ") + ": " : "";
  } catch (e) { return ""; }
}

function humanUnused(u) { return u.message.replace(/ is not used by [^:]*(: )?/, (s, colon) => (colon ? ": " : "")); }

// -- the CODESYS page -------------------------------------------------------------

function codesysOn() { return projectTarget() === "codesys"; }

// The network's CODESYS settings on a CANopen master network's Bus page.
function codesysNetworkFieldset() {
  return el("fieldset", { dataset: { codesysNetwork: "1" } }, el("legend", null, "CODESYS"),
    el("div", { class: "grid" },
      field("Network number", "codesys.net_id", "intstr", { placeholder: "from the interface name",
        hint: "The CANbus's network number in CODESYS, 0 to 255. Empty: the number the interface name ends in (can1 is 1), else 0." }),
      field("CAN interface object", "codesys.interface", "text", { placeholder: "the device's only one",
        hint: "The CAN interface object of the CODESYS device that gets this bus. Empty: the device's only CAN interface, or the one whose name ends in the network number." })));
}

function renderCodesys(view) {
  const found = !!(S.state && S.state.codesys_found);
  view.append(el("h2", null, "CODESYS"),
    el("p", { class: "muted" }, "A CODESYS PLC runs this config's CANopen master networks. canworks builds the CANbus, the CANopen manager, the nodes with their DCFs and the named I/O channels into the CODESYS project. Each network's number and CAN interface object are on its Bus page."),
    targetField(),
    el("fieldset", { dataset: { codesysProject: "1" } }, el("legend", null, "Project"),
      el("div", { class: "grid" },
        field("Project file", "codesys.project", "text", { placeholder: "C:\\Projects\\cell.project",
          hint: "The CODESYS project that Build into CODESYS project updates. Created when it does not exist and a PLC device for a new project is given." }),
        field("Device", "codesys.device", "text", { placeholder: "the active application's device",
          hint: "The device in the project that gets the CANbus. Empty: the device of the project's active application, or its only device." }),
        field("PLC device for a new project", "codesys.create", "text", { placeholder: "4096:0000 0004:3.5.22.40",
          hint: "TYPE:ID:VERSION from CODESYS's device repository: a new project gets this PLC device. Empty: the project must exist." }),
        checkbox("Name the I/O channels", "codesys.variables", true,
          "On: every mapped PDO entry's channel gets its variable name (<node>_<entry>), so the program uses the names."))),
    el("fieldset", null, el("legend", null, "Build"),
      el("p", { class: "muted" }, found
        ? "Build into CODESYS project runs CODESYS on this PC without its window, with the saved config, and shows CODESYS's report."
        : "CODESYS was not found on this PC. Download for CODESYS gives the files and a script to run in CODESYS on another PC (Tools > Scripting > Execute Script File)."),
      el("div", { class: "toolbar" }, codesysBuildButton(), codesysDownloadButton())));
}

function codesysBuildButton() {
  const b = el("button", { type: "button", class: "primary", dataset: { codesysBuild: "1" },
    title: "Build the saved config into the CODESYS project with CODESYS on this PC" }, "Build into CODESYS project…");
  b.onclick = () => busy(b, "Building…", codesysBuild);
  return b;
}

function codesysDownloadButton() {
  const b = el("button", { type: "button", dataset: { codesysDownload: "1" },
    title: "The node DCFs and a script that builds the bus in CODESYS, as one zip" }, "Download for CODESYS");
  b.onclick = () => busy(b, "Exporting…", exportCodesys);
  return b;
}

// Build into CODESYS project: the saved config through canworks-deploy
// --codesys-import, CODESYS's report in a dialog and the log.
async function codesysBuild() {
  if (!(S.state && S.state.codesys_found)) {
    const v = await modal("CODESYS was not found on this PC, so the project cannot be built here. Download for CODESYS gives the files and a script to run in CODESYS.",
      [["cancel", "Close"], ["download", "Download for CODESYS", true]]);
    if (v === "download") await exportCodesys();
    return;
  }
  if (!getPath("codesys.project")) {
    banner("Give the CODESYS project file on the CODESYS page first.", true);
    if (S.view !== "codesys") showView("codesys");
    return;
  }
  if (S.dirty) {
    const v = await modal("Build uses the saved config. Save the changes first?", [["cancel", "Cancel"], ["save", "Save and build", true]]);
    if (v !== "save") return;
    await save();
    if (S.dirty) return;
  }
  let r;
  try {
    r = await api("POST", "/api/codesys/build", {});
  } catch (e) {
    banner(e.message, true);
    return;
  }
  const text = r.ok ? "CODESYS built the bus into the project." : "The CODESYS build failed." + (r.hint ? " " + r.hint : "");
  await modal(text, [["close", "Close", true]], el("pre", { class: "codesys-report", dataset: { codesysReport: "1" } }, r.output || r.report || ""));
  banner(r.ok ? "CODESYS built the bus into the project." : "The CODESYS build failed." + (r.hint ? " " + r.hint : ""), !r.ok);
}
