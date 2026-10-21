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

// Page texts that differ per target (canopen-configurator "Only what the
// target uses is shown"): { openplc, bridge, codesys }, a missing one is
// OpenPLC's. Bridge and CODESYS texts do not speak of the plugin, the Pi,
// the PLC scan or PLC locations.
const TARGET_TEXT = {
  role_master: {
    openplc: "Default. The plugin is the network's master: it boots and configures the nodes listed here.",
    bridge: "Default. The bridge is the network's master: it boots and configures the nodes listed here.",
    codesys: "Default. The CODESYS CANopen manager is the network's master: it boots and configures the nodes listed here.",
  },
  sim_network: {
    openplc: "A virtual bus inside the plugin: no CAN interface or serial device is used and nothing needs installing. Every node is a simulated device unless switched off (then it is absent). The adapter settings below are kept for switching back.",
    bridge: "A virtual bus inside the bridge: no CAN interface or serial device is used and nothing needs installing. Every node is a simulated device unless switched off (then it is absent). The adapter settings below are kept for switching back.",
  },
  sim_plain: {
    openplc: "A virtual bus inside the plugin: no CAN interface is used. Plain CAN devices from the Simulation view (simulation.json) send and answer on it. The adapter settings below are kept for switching back.",
    bridge: "A virtual bus inside the bridge: no CAN interface is used. Plain CAN devices from the Simulation view (simulation.json) send and answer on it. The adapter settings below are kept for switching back.",
  },
  interface: {
    openplc: "Required. The interface on the PLC (the Pi), not on this computer: can0 for the first CAN HAT, vcan0 for a virtual bus.",
    bridge: "Required. The interface on the computer that runs the bridge, not necessarily this one: can0 for the first CAN interface, vcan0 for a virtual bus.",
  },
  configure_link: {
    openplc: "Plugin sets up the link (bit rate, up)",
    bridge: "Bridge sets up the link (bit rate, up)",
  },
  restart: {
    openplc: "Empty: keep the interface's own setting. 0 turns automatic restart after bus-off off. Used only when the plugin sets up the link.",
    bridge: "Empty: keep the interface's own setting. 0 turns automatic restart after bus-off off. Used only when the bridge sets up the link.",
  },
  lint_communication: {
    openplc: "Default. The PLC stops only on lint findings in the objects 0x1000-0x1FFF that dcfgen writes, and not on findings only about limits. Other findings are logged as one warning per EDS.",
    bridge: "Default. Only lint findings in the objects 0x1000-0x1FFF that dcfgen writes keep the bridge from starting, not findings only about limits. Other findings are logged as one warning per EDS.",
  },
  lint_all: {
    openplc: "The PLC stops on any lint finding, as dcfgen's strict check does. Many vendor EDS files fail it.",
    bridge: "The bridge does not start on any lint finding, as dcfgen's strict check does. Many vendor EDS files fail it.",
  },
  lint_off: {
    openplc: "The PLC never stops on a lint finding; findings are logged as one warning per EDS.",
    bridge: "The bridge always starts; lint findings are logged as one warning per EDS.",
  },
  bus_off_count: {
    openplc: "Bus-off events since the PLC started, also those shorter than a scan. Empty: none.",
    bridge: "Bus-off events since the bridge started. Empty: none.",
  },
  sdo_hidden: {
    openplc: "communication objects the plugin sets from the node's settings",
    bridge: "communication objects the bridge sets from the node's settings",
    codesys: "communication objects CODESYS sets from the node's settings",
  },
  raw_rx: {
    openplc: "Messages the PLC reads from the bus. Their signals go to %I.",
    bridge: "Messages the bridge reads from the bus. Their signals go to input registers.",
  },
  raw_tx: {
    openplc: "Messages the PLC sends. Their signals come from %Q.",
    bridge: "Messages the bridge sends. Their signals come from holding registers.",
  },
  free_location: {
    openplc: "Each signal gets a free PLC location of the right size.",
    bridge: "Each signal gets a free register location of the right size.",
  },
  links: {
    openplc: "the data no longer passes through the PLC scan, and with \"Keep running\" it moves on while the PLC is stopped. " +
      "The master configures both ends at boot and keeps receiving the TPDO, so the PLC can still read it.",
    bridge: "the data no longer passes through the bridge. " +
      "The master configures both ends at boot and keeps receiving the TPDO, so Modbus clients can still read it.",
    codesys: "the data no longer passes through the PLC program. " +
      "The consumers' DCFs carry the link, so CODESYS configures both ends at boot.",
  },
  location_column: {
    openplc: "PLC location",
    bridge: "Location",
  },
  set_by_runtime: {
    openplc: "none: the plugin sets it",
    bridge: "none: the bridge sets it",
  },
  diag_port: {
    openplc: "Off by default; the plugin opens no port without it.",
    bridge: "Off by default; the bridge opens no port without it.",
  },
  links_none: {
    openplc: "No links yet. A link copies a PDO from one node straight to another, without the PLC; add one with Add link.",
    bridge: "No links yet. A link copies a PDO from one node straight to another, without the bridge; add one with Add link.",
    codesys: "No links yet. A link copies a PDO from one node straight to another, without the PLC program; add one with Add link.",
  },
};

function targetText(key) {
  const t = TARGET_TEXT[key];
  return t[projectTarget()] || t.openplc;
}

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

// The page after a render: every bound field the target does not use is
// hidden, set or not (save leaves its value out); options of a choice the
// target does not use are left out; a section left with no field is hidden.
function applyTarget(root) {
  if (!root || !S.model || !S.state || !S.state.targets) return;
  const tgt = projectTarget();
  for (const x of root.querySelectorAll("input[data-path], select[data-path], textarea[data-path]")) {
    const path = x.dataset.path;
    if (x.tagName === "SELECT") pruneOptions(x, path, tgt);
    if (unusedWhy(path, tgt) === null) continue;
    const box = x.closest(".check-field") || x.closest("label") || x.closest("td") || x.parentElement;
    if (box.tagName === "TD") x.hidden = true;
    else box.hidden = true;
  }
  // A section is empty when it had settings and no control is left: a
  // control of its own (Method, Watch a node…) keeps it.
  const gone = (f) => f.hidden || !!f.closest("[hidden]");
  for (const fs of root.querySelectorAll("fieldset, details.advanced, .pdo-row")) {
    const fields = [...fs.querySelectorAll("input[data-path], select[data-path], textarea[data-path]")];
    if (fields.length && fields.every(gone) && [...fs.querySelectorAll("input, select, textarea, button")].every(gone)) fs.hidden = true;
  }
  // A node tab left with nothing says so instead of staying blank.
  const panel = root.querySelector("#node-panel");
  if (panel && panel.children.length && [...panel.children].every((c) => c.hidden)) {
    panel.append(el("p", { class: "muted", dataset: { tabEmpty: "1" } },
      `${TARGET_TITLE[tgt]} does not use the settings on this tab` + (tgt === "codesys" ? ": CODESYS supervises the node and reads its emergencies itself." : ".")));
  }
}

// The options of a choice that the target does not use ("PLC cycle" for the
// bridge, J1939 for CODESYS) are left out, except the one the config has
// (a network's kind stays, and the check says why).
function pruneOptions(sel, path, tgt) {
  const base = String(path).replace(/\[\d+\]/g, "");
  for (const o of [...sel.options]) {
    if (o.value === "") continue;
    const r = targetRow(`${base}=${o.value}`);
    if (!r || r.targets.includes(tgt)) continue;
    if (o.value !== sel.value) o.remove();
  }
}

// The check's warnings for values the target does not use that can go:
// not problems, since save leaves them out (canopen-configurator "Settings
// the target does not use are left out on save").
function isUnusedItem(it) { return !!(it && it.unused && it.removable); }

// -- the Project target field ---------------------------------------------------

function targetField() {
  return el("fieldset", { dataset: { bridgeTarget: "1", projectTarget: "1" } }, el("legend", null, "Project target"),
    el("div", { class: "grid" }, choice("Target", "", TARGET_CHOICES,
      { noPath: true, dataset: { target: "1" }, current: projectTarget(), onChange: switchTarget })));
}

// Switches the project target in one undo step, without asking: the server
// adds the target's marker, removes what the new target does not use and
// packs the locations (/api/switch_target); a message says what was done,
// and Undo takes it back.
async function switchTarget(target) {
  const from = projectTarget();
  if (target === from) return;
  let r;
  try {
    r = await api("POST", "/api/switch_target", { config: fileConfig(), target });
  } catch (e) {
    banner(`The switch to ${TARGET_TITLE[target]} failed: ${e.message}. The target is still ${TARGET_TITLE[from]}.`, true);
    render();
    return;
  }
  bridgeReplaceDraft(r.config);
  if ((S.view === "bridge" && target !== "bridge") || (S.view === "codesys" && target !== "codesys")) S.view = "bus";
  changed(true);
  const done = [];
  if (r.removed) done.push(`${r.removed} setting${r.removed === 1 ? "" : "s"} ${TARGET_LABEL[target]} does not use removed`);
  if (r.located) done.push(`${r.located} PDO entr${r.located === 1 ? "y" : "ies"} got a location`);
  const page = target === "bridge" ? " See the Modbus bridge page." : target === "codesys" ? " See the CODESYS page." : "";
  banner(el("span", { dataset: { switchDone: target } },
    `The project targets ${TARGET_TITLE[target]} now` + (done.length ? ": " + done.join(", ") + "." : ".") + page + " ",
    el("button", { type: "button", class: "link", dataset: { undo: "1" }, onclick: () => undo(false) }, "Undo")));
}

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
        codesysProjectField(),
        field("Device", "codesys.device", "text", { placeholder: "the active application's device",
          hint: "The device's name in the project tree that gets the CANbus. Empty: the device of the project's active application, or its only device." }),
        codesysCreateField(),
        checkbox("Name the I/O channels", "codesys.variables", true,
          "On: every mapped PDO entry's channel gets its variable name (<node>_<entry>), so the program uses the names."))),
    el("fieldset", null, el("legend", null, "Build"),
      el("p", { class: "muted" }, found
        ? "Build into CODESYS project runs CODESYS on this PC without its window, with the saved config, and shows CODESYS's report."
        : "CODESYS was not found on this PC. Download for CODESYS gives the files and a script to run in CODESYS on another PC (Tools > Scripting > Execute Script File)."),
      el("div", { class: "toolbar" }, codesysBuildButton(), codesysDownloadButton())));
}

// The project file with Browse… (the folder dialog in file mode); a name
// without an extension gets .project when the field is left.
function codesysProjectField() {
  const f = field("Project file", "codesys.project", "text", { placeholder: "e.g. C:\\Projects\\cell.project",
    hint: "The CODESYS project that Build into CODESYS project updates, or creates when it does not exist yet." });
  const input = f.querySelector("input");
  const settle = () => {
    const v = input.value.trim();
    const p = v ? codesysProjectPath(v) : "";
    if (p !== v) { input.value = p; setPath("codesys.project", p); }
    refreshCodesysCreate();
  };
  input.addEventListener("change", settle);
  const browse = el("button", { type: "button", dataset: { codesysBrowse: "1" }, onclick: async () => {
    const p = await chooseFolder({ title: "Choose the CODESYS project", start: splitPath(input.value.trim())[0] || "",
      files: ".project", newName: "New project name",
      note: "Pick an existing project, or name a new one: Build creates it with the PLC device you pick." });
    if (p === null) return;
    input.value = p;
    setPath("codesys.project", p);
    refreshCodesysCreate();
  } }, "Browse…");
  const row = el("div", { class: "row" });
  input.replaceWith(row);
  row.append(input, browse);
  f.classList.add("span2");
  return f;
}

// `.project` added to a name without an extension (as canworks-deploy does).
function codesysProjectPath(p) {
  const name = p.replace(/[\\/]+$/, "").split(/[\\/]/).pop();
  return /\.[^.]+$/.test(name) ? p : p + ".project";
}

// The PLC devices installed in CODESYS on this PC (/api/codesys/devices),
// and whether the project file exists; asked once per project path.
async function codesysDevices(project) {
  const key = project || "";
  if (S.codesysDevs && S.codesysDevs.key === key) return S.codesysDevs.r;
  let r;
  try {
    r = await api("GET", "/api/codesys/devices" + (key ? "?project=" + encodeURIComponent(key) : ""));
  } catch (e) {
    r = { devices: [], exists: null };
  }
  S.codesysDevs = { key, r };
  return r;
}

const codesysDeviceText = (d) => `${d.type}:${d.id}:${d.version}`;

// A PLC device picker: the installed PLCs by name and version, and Other…
// for typing TYPE:ID:VERSION; a text field when none are known. onPick
// gets the TYPE:ID:VERSION text ("" for none).
function codesysDevicePicker(devices, value, onPick, id) {
  const text = el("input", { type: "text", spellcheck: "false", id: devices.length ? null : id, dataset: { codesysDeviceText: "1" },
    placeholder: "e.g. 4096:0000 0004:3.5.22.40", "aria-label": "PLC device as TYPE:ID:VERSION" });
  text.value = value || "";
  text.addEventListener("input", () => onPick(text.value.trim()));
  if (!devices.length) return text;
  const known = devices.some((d) => codesysDeviceText(d) === value);
  const sel = el("select", { id, dataset: { codesysDevice: "1" }, "aria-label": "PLC device" },
    el("option", { value: "" }, "Choose the PLC…"),
    ...devices.map((d) => el("option", { value: codesysDeviceText(d) }, `${d.name} ${d.version}`)),
    el("option", { value: "other" }, "Other (type TYPE:ID:VERSION)…"));
  sel.value = !value ? "" : known ? value : "other";
  text.hidden = sel.value !== "other";
  sel.addEventListener("change", () => {
    text.hidden = sel.value !== "other";
    if (sel.value === "other") { text.focus(); onPick(text.value.trim()); } else onPick(sel.value);
  });
  return el("div", { class: "codesys-device" }, sel, text);
}

// "PLC device for a new project": shown while the project file does not
// exist; an existing project says the bus is added to it.
function codesysCreateField() {
  const box = el("div", { dataset: { codesysCreate: "1" } });
  fillCodesysCreate(box);
  return box;
}

function refreshCodesysCreate() {
  const box = document.querySelector("[data-codesys-create]");
  if (box) fillCodesysCreate(box);
}

async function fillCodesysCreate(box) {
  const project = (getPath("codesys.project") || "").trim();
  const r = await codesysDevices(project);
  if (project && r.exists) {
    box.replaceChildren(el("label", null, "PLC device for a new project",
      el("p", { class: "muted", dataset: { codesysExisting: "1" } }, "Existing project: Build adds the bus to it.")));
    return;
  }
  const picker = codesysDevicePicker(r.devices || [], getPath("codesys.create") || "", (v) => setPath("codesys.create", v), "codesys-create");
  box.replaceChildren(el("label", { for: "codesys-create" }, "PLC device for a new project", picker,
    hint(r.devices && r.devices.length
      ? "The PLC of the new project, from the devices installed in CODESYS on this PC."
      : "TYPE:ID:VERSION from CODESYS's device repository: the new project gets this PLC device."),
    el("span", { class: "field-msg", dataset: { for: "codesys.create" } })));
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
  // A project that does not exist yet needs its PLC: asked here rather than failing in CODESYS.
  S.codesysDevs = null;
  const devs = await codesysDevices(getPath("codesys.project"));
  if (devs.exists === false && !getPath("codesys.create")) {
    let pickedDevice = "";
    const picker = codesysDevicePicker(devs.devices || [], "", (v) => { pickedDevice = v; }, "codesys-new-device");
    const extra = el("div", { class: "field", dataset: { codesysNew: "1" } },
      el("label", { for: "codesys-new-device" }, "PLC device"), picker,
      hint("The new project gets this PLC device, and canworks adds the bus to it."));
    let text = `${getPath("codesys.project")} does not exist. Create a new CODESYS project?`;
    for (;;) {
      const v = await modal(text, [["cancel", "Cancel"], ["create", "Create and build", true]], extra);
      if (v !== "create") return;
      if (pickedDevice) break;
      text = "Pick the PLC device of the new project.";
    }
    // Create and build is the go-ahead to save: no second question.
    setPath("codesys.create", pickedDevice);
    if (S.view === "codesys") render();
    await save();
    if (S.dirty) return;
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
  const report = r.output || r.report || "";
  const device = codesysReportDevice(report);
  const text = r.ok ? `CODESYS built the bus into ${device || "the project"}.`
    : "The CODESYS build failed" + (device ? ` on ${device}` : "") + "." + (r.hint ? " " + r.hint : "");
  await modal(text, [["close", "Close", true]], el("pre", { class: "codesys-report", dataset: { codesysReport: "1" } }, report));
  banner(text, !r.ok);
}

// The device the CODESYS report's device line names, with its reason:
// "device   ExampleApp (active application)" -> "ExampleApp (active application)".
function codesysReportDevice(report) {
  const m = /^device\s+(.+?)\s*$/m.exec(report || "");
  return m ? m[1] : "";
}
