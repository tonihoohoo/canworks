"use strict";
// Commissioning one device (add-device-commissioning): Write configuration
// and Restore defaults in a node's Parameters tab, the PDO test tab on a USB
// adapter, "Only this device is on the bus" for Detect, and in Commission a
// device the Steps panel, the commissioning log and "Add to a config…".
// Loaded after app.js and uses its helpers.

// -- commissioning log ------------------------------------------------------------
// Every change made through the page while on a USB adapter or in Commission
// a device: UTC time, node, what and the result. Kept in the page only: no
// host names or tokens, never written to a project.

function commLogOn() {
  return !!((S.state && S.state.commission) || (S.online && S.online.target === "adapter"));
}

function commLog(node, what, result) {
  if (!commLogOn()) return;
  S.commLog = S.commLog || [];
  S.commLog.push({ time: new Date().toISOString().replace(/\.\d+Z$/, "Z"), node, what, result });
  refreshSteps();
}

// The device the steps are about: the latest node something was done to.
function commDevice() {
  S.commDevice = S.commDevice || {};
  return S.commDevice;
}

function upperFirst(t) { return t ? t.charAt(0).toUpperCase() + t.slice(1) : t; }

// Called by api() after each request: the changes and the steps they finish.
function commLogApi(path, body, ok, data) {
  const route = path.replace(/^\/api\/online\//, "");
  if (route === path) return;
  body = body || {};
  const fail = ok ? null : (data && data.error) || "failed";
  const node = body.node ?? null;
  if (route === "sdo_write") {
    const r = fail || (data.success ? "written" : data.abort_code !== undefined ? `abort ${hex8(data.abort_code)}: ${data.abort_text}` : data.reason || "failed");
    commLog(node, `SDO write ${hex4(num(body.index))} sub ${num(body.subindex || 0)} = ${body.value}`, r);
  } else if (route === "nmt") {
    commLog(node, `NMT ${body.command}`, fail || "sent");
  } else if (route === "lss_set_id") {
    const a = body.address || {};
    commLog(node, `LSS set node ID ${node} (serial number ${hex8(a.serial_number)})${body.store ? " and store" : ""}`,
      fail || (data.stored ? "set and stored" : "set"));
    if (!fail) {
      Object.assign(commDevice(), { node_id: node, vendor_id: a.vendor_id, product_code: a.product_code,
        revision_number: a.revision_number, serial_number: a.serial_number, lss: true });
      stepDone("nodeid", `node ID ${node}${data.stored ? ", stored" : ", not stored"}`);
    }
  } else if (route === "lss_set_bitrate") {
    commLog(null, `LSS set bit rate ${body.bitrate_kbit} kbit/s${body.store ? " and store" : ""}`, fail || (data.stored ? "set and stored" : "set"));
    if (!fail) stepDone("nodeid", `bit rate ${body.bitrate_kbit} kbit/s set${data.stored ? " and stored" : ""}`, true);
  } else if (route === "store") {
    commLog(node, `Store on device (0x1010 sub ${body.subindex})`, fail || (data.stored ? "stored" : `not stored: ${data.error}`));
    if (!fail && data.stored) stepDone("store", `stored (0x1010 sub ${body.subindex})`);
  } else if (route === "restore_defaults") {
    commLog(node, `Restore defaults (0x1011 sub ${body.subindex || 1})${body.reset ? " and reset" : ""}`,
      fail || (data.restored ? (data.reset ? "restored, node reset" : "restored") : `not restored: ${data.error}`));
  } else if (route === "pdo_test_start" && !fail) {
    const names = (data.tpdos || []).concat(data.rpdos || []).map((p) => p.name).join(", ");
    stepDone("pdo", `started (${names})`);
  } else if (route === "lss_find" && ok && data.found && data.device) {
    stepDone("find", `serial number ${hex8(data.device.serial_number)}`);
  } else if (route === "scan" && ok && !data.running && data.nodes && data.nodes.length) {
    stepDone("find", `scan: node${data.nodes.length > 1 ? "s" : ""} ${data.nodes.map((d) => d.node_id).join(", ")}`);
  } else if ((route === "adapter_detect" || route === "adapter_detect_status" || route === "detect_bitrate" || route === "detect_bitrate_status")
    && ok && data.verdict === "detected" && S.online.target === "adapter") {
    stepDone("bitrate", `${kbitText(data.bitrate_kbit)} detected`);
  }
}

// Called by followJob() when a job ends: jobs that change the device or
// finish a step.
function commLogJob(j) {
  const r = j.result;
  if (j.kind === "configure") {
    if (j.state === "failed") { commLog(j.node, "Write configuration", j.error); return; }
    if (!r) return;
    const what = `Write configuration from ${r.plan ? r.plan.source.name : "a source"}${r.restored ? " (defaults restored first)" : ""}`;
    const res = `${r.written.length} written, ${r.failed.length} failed, ${r.cancelled ? "cancelled" : r.verified ? "read-back verified" : "read-back differs"}`;
    commLog(j.node, what, res);
    if (r.store) commLog(j.node, "Store on device (0x1010)", r.store.stored ? "stored" : `not stored: ${r.store.error}`);
    if (!r.cancelled) stepDone("write", res);
    if (r.store && r.store.stored) stepDone("store", "stored after writing");
    if (r.plan && r.plan.source.identity) Object.assign(commDevice(), { node_id: j.node });
  } else if (j.kind === "restore") {
    if (j.state === "failed") { commLog(j.node, "Restore from a backup", j.error); return; }
    if (r) commLog(j.node, "Restore from a backup", `${r.written.length} written, ${r.failed.length} failed${r.cancelled ? ", cancelled" : ""}`);
  } else if (j.kind === "configure_verify" && r) {
    stepDone("verify", r.differences.length ? `${r.differences.length} entries differ from ${r.source.name}` : `no difference from ${r.source.name}`);
  } else if (j.kind === "backup" && r) {
    stepDone("backup", r.name);
  }
}

function downloadText(text, name) {
  const url = URL.createObjectURL(new Blob([text], { type: "text/plain" }));
  const a = el("a", { href: url, download: name });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
}

function commLogText() {
  const d = commDevice();
  const log = S.commLog || [];
  const node = d.node_id ?? (log.length ? log[log.length - 1].node : null) ?? S.onlineNode ?? null;
  const lines = ["CANopen commissioning log", ""];
  lines.push(`Device: ${node !== null ? "node " + node : "node not known"}`);
  const ids = [["vendor_id", "Vendor ID"], ["product_code", "Product code"], ["revision_number", "Revision"], ["serial_number", "Serial number"]]
    .filter(([k]) => d[k] !== undefined && d[k] !== null).map(([k, label]) => `${label} ${hex8(d[k])}`);
  if (ids.length) lines.push("Identity: " + ids.join(", "));
  const eds = d.eds_name || (node !== null && (S.onlineEdsName || {})[node]) || (node !== null && configNode(node) ? configNode(node).eds : null);
  lines.push(`EDS: ${eds || "not known"}`);
  const st = S.onlineLast && S.onlineLast.status;
  if (st && st.local && st.bitrate) lines.push(`Bit rate: ${Math.round(st.bitrate / 1000)} kbit/s`);
  lines.push("");
  for (const e of log) lines.push(`${e.time}  ${e.node !== null && e.node !== undefined ? "node " + e.node : "bus"}  ${e.what}: ${e.result}`);
  if (!log.length) lines.push("No change was made.");
  return { text: lines.join("\n") + "\n", node };
}

function saveCommLog() {
  const { text, node } = commLogText();
  const t = new Date().toISOString().replace(/[-:]/g, "").replace(/\.\d+Z$/, "Z").replace("T", "-");
  downloadText(text, `node${node ?? "x"}-commissioning-${t}.txt`);
}

// -- Steps panel ----------------------------------------------------------------------
// The commissioning steps in Commission a device. Each opens its panel and
// shows done or skipped with a one-line result; any order, none runs by itself.

const COMM_STEPS = [
  ["bitrate", "Bit rate"], ["find", "Find the device"], ["nodeid", "Node ID and bit rate"], ["identity", "Identity and EDS"],
  ["write", "Write configuration"], ["pdo", "PDO test"], ["store", "Store"], ["verify", "Verify after power cycle"], ["backup", "Back up"],
];

function stepDone(key, text, append) {
  S.steps = S.steps || {};
  const old = S.steps[key];
  S.steps[key] = { state: "done", text: append && old && old.state === "done" ? `${old.text}; ${text}` : text };
  refreshSteps();
}

function openStep(key) {
  const nodeTab = (tab) => {
    const id = S.onlineNode ?? commDevice().node_id;
    if (id === undefined || id === null) {
      banner("Open the device first: click it in the node list, or scan the bus and open its object dictionary.", true);
      showView("online");
      return;
    }
    S.onlineNode = id;
    S.onlineTab = tab;
    showView("online");
  };
  if (key === "bitrate") { S.onlineForm = true; showView("online"); return; }
  if (key === "find" || key === "nodeid") {
    showView("online");
    const box = document.querySelector("[data-online=lss]");
    if (box) box.scrollIntoView({ block: "nearest" });
    return;
  }
  if (key === "identity") { showView("scan"); return; }
  if (key === "pdo") { nodeTab("pdo"); return; }
  nodeTab("params");
}

function stepsRows() {
  S.steps = S.steps || {};
  return COMM_STEPS.map(([key, label]) => {
    const s = S.steps[key];
    const state = s ? s.state : "not done";
    return el("tr", { dataset: { step: key, stepState: state.replace(" ", "-") } },
      el("th", { scope: "row" }, label),
      el("td", { class: state === "done" ? "ok-text" : state === "skipped" ? "muted" : null }, state),
      el("td", null, s && s.text ? s.text : ""),
      el("td", null,
        el("button", { type: "button", class: "small", dataset: { stepOpen: key }, onclick: () => openStep(key) }, "Open"),
        el("button", { type: "button", class: "small", dataset: { stepSkip: key }, onclick: () => {
          S.steps[key] = s && s.state === "skipped" ? undefined : { state: "skipped", text: "" };
          refreshSteps();
        } }, s && s.state === "skipped" ? "Undo skip" : "Skip")));
  });
}

function stepsPanel() {
  if (!(S.state && S.state.commission)) return logBar();
  const n = (S.commLog || []).length;
  return el("details", { class: "steps", open: S.stepsClosed ? null : true, dataset: { online: "steps" },
    ontoggle: (e) => { S.stepsClosed = !e.target.open; } },
  el("summary", null, "Steps"),
  el("table", { class: "steps-table" }, el("tbody", { id: "comm-steps" }, stepsRows())),
  el("div", { class: "toolbar" },
    el("button", { type: "button", dataset: { online: "save-log" }, onclick: saveCommLog }, "Save log"),
    el("span", { class: "muted", dataset: { online: "log-count" } }, `${n} change${n === 1 ? "" : "s"} in the log`),
    el("button", { type: "button", dataset: { online: "add-to-config" }, onclick: addToConfig }, "Add to a config…")),
  hint("Each step opens its panel. Steps can be done in any order or skipped, and none runs by itself. The log stays on this page until you save it."));
}

// On a USB adapter target with a config open: only the log.
function logBar() {
  if (!commLogOn()) return null;
  const n = (S.commLog || []).length;
  return el("div", { class: "toolbar", dataset: { online: "log-bar" } },
    el("span", { class: "muted", dataset: { online: "log-count" } }, `Commissioning log: ${n} change${n === 1 ? "" : "s"}`),
    el("button", { type: "button", class: "small", dataset: { online: "save-log" }, onclick: saveCommLog }, "Save log"));
}

function refreshSteps() {
  const body = document.getElementById("comm-steps");
  if (body) body.replaceChildren(...stepsRows());
  const n = (S.commLog || []).length;
  for (const c of document.querySelectorAll("[data-online=log-count]")) {
    c.textContent = c.closest("[data-online=log-bar]") ? `Commissioning log: ${n} change${n === 1 ? "" : "s"}` : `${n} change${n === 1 ? "" : "s"} in the log`;
  }
}

// "Add to a config…": opens a project or standalone config folder with the
// device added as an unsaved node.
async function addToConfig() {
  const d = Object.assign({}, commDevice());
  if (d.node_id === undefined || d.node_id === null) d.node_id = S.onlineNode;
  if (d.node_id === undefined || d.node_id === null) {
    banner("Give the device a node ID first, or open it from a scan.", true);
    return;
  }
  const path = el("input", { type: "text", class: "wide", spellcheck: "false", "aria-label": "Config folder", dataset: { online: "add-folder" } });
  const mode = el("select", { "aria-label": "Folder kind", dataset: { online: "add-mode" } },
    el("option", { value: "standalone" }, "standalone config folder"), el("option", { value: "project" }, "editor project"));
  const file = d.eds_path ? null : el("input", { type: "file", accept: ".eds,.EDS", "aria-label": "EDS file", dataset: { online: "add-eds" } });
  const v = await modal(`Add node ${d.node_id} to a config. The folder opens with the device added as an unsaved node` +
    (d.lss ? " with its serial number and LSS assignment ticked." : "."),
  [["add", "Open and add", true], ["cancel", "Cancel"]],
  el("div", null, el("label", null, "Folder ", path), el("label", { class: "inline" }, " ", mode),
    file ? el("div", null, el("label", null, "The device's EDS file ", file)) : el("p", { class: "muted" }, `EDS: ${d.eds_name || d.eds_path}`)));
  if (v !== "add") return;
  const folder = path.value.trim();
  if (!folder) { banner("Type the config folder.", true); return; }
  const f = file ? file.files[0] : null;
  if (file && !f) { banner("Pick the device's EDS file.", true); return; }
  // Checked before the folder opens, so this page and its log stay.
  try {
    if ((await api("POST", "/api/folder_nodes", { path: folder })).nodes.includes(d.node_id)) {
      banner(`The config in ${folder} already has node ${d.node_id}: give the device another node ID (Set node ID), or pick another config.`, true);
      return;
    }
  } catch (e) { banner(e.message, true); return; }
  try {
    banner("");
    await api("POST", "/api/open", { path: folder, mode: mode.value });
    S.view = "bus";
    await loadState();
  } catch (e) { banner(e.message, true); return; }
  if (configNode(d.node_id)) { banner(`The config already has node ${d.node_id}.`, true); return; }
  const before = (S.config.nodes || []).length;
  await addScannedNode(d, d.eds_path ? { path: d.eds_path, name: d.eds_name } : null, f, false, !!d.lss);
  const node = (S.config.nodes || [])[before];
  if (node && d.serial_number !== undefined && d.serial_number !== null && node.serial_number === undefined) {
    node.serial_number = d.serial_number;
    changed(true);
  }
}

// -- Write configuration and Restore defaults in the Parameters tab --------------------

function configureBox(id, n, allow, status, out) {
  const why = allow ? null : NO_CHANGES;
  const nodes = onlineIsSlave() ? [] : (onlineConfig().nodes || []).filter((x) => x && x.eds);
  const own = nodes.find((x) => num(x.node_id) === id);
  const src = el("select", { "aria-label": "Source", dataset: { online: "configure-source" } },
    nodes.map((x) => el("option", { value: "node:" + num(x.node_id) }, `node ${num(x.node_id)}${x.name ? " " + x.name : ""} of this config`)),
    el("option", { value: "folder" }, "a node of a config folder…"),
    el("option", { value: "dcf" }, "a DCF file"));
  src.value = own ? "node:" + id : nodes.length ? "node:" + num(nodes[0].node_id) : "dcf";
  const file = el("input", { type: "file", accept: ".dcf,.DCF", "aria-label": "DCF file", dataset: { online: "configure-file" } });
  const folder = el("input", { type: "text", spellcheck: "false", class: "wide", placeholder: "config folder on this PC", "aria-label": "Config folder", dataset: { online: "configure-folder" } });
  const fromNode = el("input", { type: "number", min: 1, max: 127, class: "short", value: id, "aria-label": "Node in that config", dataset: { online: "configure-from" } });
  const folderBox = el("span", { class: "row" }, folder, el("label", { class: "inline" }, "node ", fromNode));
  const sync = () => { file.hidden = src.value !== "dcf"; folderBox.hidden = src.value !== "folder"; };
  src.addEventListener("change", sync);
  sync();
  const body = async () => {
    const b = { node: id, port: diagPort() };
    if (src.value === "dcf") {
      const f = file.files[0];
      if (!f) { banner("Choose the DCF file to write.", true); return null; }
      return Object.assign(b, { source: "dcf", file: await fileBase64(f), file_name: f.name });
    }
    if (src.value === "folder") {
      if (!folder.value.trim()) { banner("Type the config folder.", true); return null; }
      return Object.assign(b, { source: "config", config_path: folder.value.trim(), from_node: Number(fromNode.value) });
    }
    return Object.assign(b, { source: "config", from_node: Number(src.value.slice(5)), config: fileConfig() });
  };
  // A node of this page's draft: the server names the saved file, which
  // unsaved changes make the wrong name.
  const named = (j, b) => {
    if (b.config && S.dirty && j.result && j.result.source) j.result.source.name = `node ${b.from_node} of this page's configuration (unsaved changes)`;
    return j;
  };
  const write = async () => {
    const b = await body();
    if (!b) return;
    put(out);
    startJob("/api/online/configure_plan", b, status, (j) => configureDialog(id, named(j, b), b, status, out));
  };
  const verify = async () => {
    const b = await body();
    if (!b) return;
    put(out);
    startJob("/api/online/configure_verify", b, status, (j) => showVerify(named(j, b).result, out));
  };
  return el("fieldset", { dataset: { online: "configure-box" } }, el("legend", null, "Write configuration"),
    el("div", { class: "toolbar" }, el("label", { class: "inline" }, "From ", src), file, folderBox),
    el("div", { class: "toolbar" },
      el("button", { type: "button", disabled: !allow, title: why, dataset: { online: "configure" }, onclick: write }, "Write configuration…"),
      el("button", { type: "button", dataset: { online: "configure-verify" }, onclick: verify }, "Verify")),
    hint("Writes a node's configuration (PDOs, heartbeat, startup SDOs) to the device, for a device that keeps its own configuration. Shows the plan first. Verify compares without writing. Nothing is stored on the device unless you tick it."));
}

async function configureDialog(id, j, body, status, out) {
  const p = j.result;
  const refuse = (p.identity || []).filter((i) => i.level === "refuse");
  const hold = el("input", { type: "checkbox", checked: true, dataset: { online: "configure-hold" } });
  const restore = el("input", { type: "checkbox", dataset: { online: "configure-restore" } });
  const store = el("input", { type: "checkbox", dataset: { online: "configure-store" } });
  const other = el("input", { type: "checkbox", dataset: { online: "configure-other" } });
  const subs = p.store_subindices || [];
  const storeSub = subs.length > 1 ? el("select", { "aria-label": "What to store", dataset: { online: "configure-store-sub" } },
    subs.map((s) => el("option", { value: s }, `sub ${s}`))) : null;
  const rows = [];
  let group = null;
  for (const s of p.steps) {
    if (s.group !== group) {
      group = s.group;
      if (group) {
        const sending = p.steps.some((x) => x.group === group && x.send);
        rows.push(el("tr", { class: "group-row", dataset: { configureGroup: group } }, el("th", { colspan: 6, scope: "rowgroup" },
          sending ? `${group}: written as one sequence (switched off, mapped, switched on)` : `${group}: the device already has it`)));
      }
    }
    const role = { off: "switch off", clear: "clear mapping", on: "switch on" }[s.role];
    rows.push(el("tr", { class: s.send ? null : "muted", dataset: { configureStep: `${hex4(s.index)}:${s.subindex}` } },
      el("td", { class: "mono" }, `${hex4(s.index)}:${s.subindex}`),
      el("td", null, s.name, role ? el("span", { class: "muted" }, ` (${role})`) : null),
      el("td", null, s.comm ? "comm" : ""),
      el("td", null, s.value), el("td", null, s.device ?? "not readable"),
      el("td", null, s.send ? (s.role === "set" && !s.differs ? "write (same)" : "write") : "same")));
  }
  const skipped = p.skipped.length ? el("details", null, el("summary", null, `${p.skipped.length} entries left out`),
    el("table", { class: "od" }, el("tbody", null, p.skipped.map((s) => el("tr", null, el("td", { class: "mono" }, `${hex4(s.index)}:${s.subindex}`),
      el("td", null, s.name || ""), el("td", { class: "muted" }, s.reason)))))) : null;
  const extra = el("div", { class: "restore-preview", dataset: { online: "configure-preview" } },
    el("p", { class: "muted" }, `Source: ${p.source.name}.`),
    (p.identity || []).map((i) => el("p", { class: i.level === "refuse" ? "field-msg" : i.level === "warning" ? "field-msg warning" : "muted" }, upperFirst(i.text) + ".")),
    p.refused && !refuse.length ? el("p", { class: "field-msg", dataset: { online: "configure-refused" } }, upperFirst(p.refused) + ".") : null,
    (p.warnings || []).map((w) => el("p", { class: "field-msg warning" }, upperFirst(w) + ".")),
    rows.length ? el("table", { class: "od", dataset: { online: "configure-plan" } },
      el("thead", null, el("tr", null, thCells(["Entry", "Name", "", "Source", "Device now", "Action"]))), el("tbody", null, rows))
      : el("p", { class: "muted" }, "The source has nothing to write."),
    skipped,
    el("p", { class: "muted", dataset: { online: "configure-counts" } }, `${p.writes} to write, ${p.same} already the same.`),
    el("label", { class: "check" }, hold, " Hold the node in PRE-OPERATIONAL while writing"),
    p.has_restore ? el("label", { class: "check" }, restore, " Restore defaults first (0x1011 sub 1, then reset the node)") : null,
    p.has_store ? el("label", { class: "check" }, store, " Store on device afterwards (0x1010), only when everything was written and read back", storeSub ? " " : null, storeSub) : null,
    refuse.length ? el("label", { class: "check" }, other, " Write to a different product anyway") : null,
    p.allow_changes ? null : el("p", { class: "field-msg warning" }, NO_CHANGES));
  const blocked = !!p.refused && !refuse.length;
  const can = p.allow_changes && !blocked && (p.writes > 0 || p.has_restore);
  const go = modal(`Write ${p.writes} value${p.writes === 1 ? "" : "s"} to node ${id}?`,
    can ? [["cancel", "Cancel"], ["write", "Write", { danger: true }]] : [["cancel", "Close"]], extra);
  const btn = document.querySelector('#modal-buttons button[data-value="write"]');
  if (btn) {
    const upd = () => { btn.disabled = (refuse.length && !other.checked) || (p.writes === 0 && !restore.checked); };
    other.addEventListener("change", upd);
    restore.addEventListener("change", upd);
    upd();
  }
  if (await go !== "write") return;
  startJob("/api/online/configure", { node: id, port: diagPort(), plan: j.id, hold: hold.checked, restore_defaults: restore.checked,
    store: store.checked, store_subindex: storeSub ? Number(storeSub.value) : (subs[0] || 1), ignore_identity: other.checked }, status,
  (r) => showConfigure(r.result, out, id));
}

function stepLine(s) { return `${hex4(s.index)}:${s.subindex} ${s.name}`; }

function showConfigure(r, out, id) {
  if (!r) return;
  odTake(id, null, r.written.concat(r.failed).map((w) => odKey(w.index, w.subindex)));
  put(out, el("p", { dataset: { online: "configure-done" } },
    `${r.written.length} written, ${r.failed.length} failed, ${r.same} already the same${r.cancelled ? ", cancelled" : ""}. `,
    r.cancelled ? null : el("strong", { class: r.verified ? "ok-text" : "bad" }, r.verified ? "Read-back verified." : "The read-back differs.")),
  r.restored ? el("p", { class: "muted" }, "Defaults were restored and the node reset before writing.") : null,
  ...r.failed.map((f) => el("p", { class: "field-msg" }, `${stepLine(f)}: ${f.error}`)),
  ...r.skipped.filter((s) => /stays switched off/.test(s.reason)).map((s) => el("p", { class: "field-msg warning" }, `${stepLine(s)}: ${s.reason}`)),
  r.readback.length ? diffTable(r.readback) : null,
  ...r.notes.map((t) => el("p", { class: "muted" }, upperFirst(t) + ".")),
  r.store ? el("p", { class: r.store.stored ? "ok-text" : "field-msg", dataset: { online: "configure-store" } },
    r.store.stored ? `Stored on the device (0x1010 sub ${r.store.subindex}).` : `Not stored: ${r.store.error}.`)
    : el("p", { class: "field-msg warning" }, "Not stored on the device: the values are lost at power off until Store on device is used."));
}

function diffTable(rows) {
  return el("table", { class: "od compare-rows", dataset: { online: "configure-diff" } },
    el("thead", null, el("tr", null, thCells(["Entry", "Name", "Source", "Device"]))),
    el("tbody", null, rows.map((x) => el("tr", { class: "bad" }, el("td", { class: "mono" }, `${hex4(x.index)}:${x.subindex}`),
      el("td", null, x.name), el("td", null, x.value), el("td", null, x.device ?? (x.error || ""))))));
}

function showVerify(r, out) {
  if (!r) return;
  put(out, el("p", { dataset: { online: "verify-done" } }, `${r.checked} entries checked: `,
    el("strong", { class: r.differences.length ? "bad" : "ok-text" }, r.differences.length ? `${r.differences.length} differ from ${r.source.name}.` : `no difference from ${r.source.name}.`)),
  r.stopped ? el("p", { class: "field-msg" }, "Stopped: " + r.stopped) : null,
  r.differences.length ? diffTable(r.differences) : null);
}

function restoreDefaultsBox(id, data, allow) {
  if (!data.has_restore) return null;
  const names = { 1: "all parameters", 2: "communication parameters", 3: "application parameters" };
  const sub = el("select", { "aria-label": "What to restore", dataset: { online: "defaults-sub" } },
    data.restore_subindices.map((s) => el("option", { value: s }, `sub ${s}: ${names[s] || "manufacturer-specific"}`)));
  return el("div", { class: "toolbar" }, sub,
    el("button", { type: "button", disabled: !allow, title: allow ? null : NO_CHANGES, dataset: { online: "restore-defaults" },
      onclick: () => restoreDefaultsDialog(id, Number(sub.value), names[Number(sub.value)]) }, "Restore defaults…"));
}

async function restoreDefaultsDialog(id, sub, what) {
  const reset = el("input", { type: "checkbox", checked: true, dataset: { online: "defaults-reset" } });
  const v = await modal(`Restore node ${id}'s default ${what || "values"} (write "load" to 0x1011 sub ${sub})? ` +
    "The device takes its factory values at its next reset; what was stored on it is lost.",
  [["cancel", "Cancel"], ["restore", "Restore defaults", { danger: true }]],
  el("label", { class: "check" }, reset, " Reset the node afterwards"));
  if (v !== "restore") return;
  try {
    const r = await api("POST", "/api/online/restore_defaults", Object.assign(nodeSource(id), { subindex: sub, reset: reset.checked }));
    if (r.restored) banner(`Node ${id}: defaults restored (0x1011 sub ${sub}). ${upperFirst(r.note)}.`);
    else banner(`Node ${id} did not restore its defaults: ${r.error}`, true);
  } catch (e) { banner(e.message, true); }
}

// -- PDO test tab (USB adapter only) ------------------------------------------------------

const SYNC_PERIODS = [10, 20, 50, 100, 200, 500, 1000];
const REPEATS = [0, 100, 200, 500, 1000];

// An online request that the adapter refuses while another master runs on
// the bus: ask with `question`, then send it again with force.
async function apiAsk(path, body, question) {
  try {
    return await api("POST", path, body);
  } catch (e) {
    if (!/another master is active/.test(e.message)) throw e;
    const v = await modal(e.message.replace(/; force needed\s*$/, "") + ". " + question,
      [["force", "Run anyway", true], ["cancel", "Cancel"]]);
    if (v !== "force") throw new Error("Not run: another master is active on this bus.");
    return api("POST", path, Object.assign({}, body, { force: true }));
  }
}

function pdoTestLocal() {
  const st = S.onlineLast && S.onlineLast.status;
  return st ? !!st.local : S.online && S.online.target === "adapter";
}

function pdoTestPanel(id, n, allow) {
  const box = el("div", { dataset: { online: "pdo-test" } });
  if (!nodeSource(id)) { put(box, noEds(id)); return box; }
  const why = allow ? null : NO_CHANGES;
  const start = el("input", { type: "checkbox", dataset: { online: "pdo-nmt-start" } });
  const sync = el("select", { "aria-label": "SYNC period", disabled: !allow, dataset: { online: "pdo-sync" } },
    el("option", { value: "0" }, "SYNC off"), SYNC_PERIODS.map((p) => el("option", { value: p }, `SYNC every ${p} ms`)));
  const msg = el("p", { class: "muted", dataset: { online: "pdo-msg" }, "aria-live": "polite" });
  const live = el("div", { dataset: { online: "pdo-live" } });
  const run = { on: false, rpdo: {} };
  const startBtn = el("button", { type: "button", class: "primary", disabled: !allow, title: why, dataset: { online: "pdo-start" } }, "Start PDO test");
  const stopBtn = el("button", { type: "button", disabled: true, dataset: { online: "pdo-stop" } }, "Stop");
  const nmtBtn = el("button", { type: "button", disabled: !allow, title: why, dataset: { online: "pdo-nmt" }, onclick: async () => {
    try { await api("POST", "/api/online/nmt", { node: id, command: "start", port: diagPort() }); msg.textContent = `NMT Start sent to node ${id}.`; }
    catch (e) { msg.textContent = e.message; }
  } }, "NMT Start");

  // asked: the slow path question was answered at Start already.
  const setSync = async (asked) => {
    if (!run.on) return;
    if (Number(sync.value) && asked !== true && !(await askSlowPath("The PDO test's SYNC"))) {
      sync.value = "0";
      return;
    }
    try {
      if (Number(sync.value)) await apiAsk("/api/online/sync_start", { node: id, period_ms: Number(sync.value), port: diagPort(), force: run.forced || undefined },
        "SYNC from this PC would fight it. Send SYNC anyway?");
      else await api("POST", "/api/online/sync_stop", { node: id, port: diagPort() });
    } catch (e) { msg.textContent = e.message; sync.value = "0"; }
  };
  sync.addEventListener("change", () => setSync(false));

  const stop = async (quiet) => {
    if (!run.on) return;
    run.on = false;
    clearTimeout(run.timer);
    try {
      await api("POST", "/api/online/pdo_test_stop", { node: id, port: diagPort() });
      await api("POST", "/api/online/sync_stop", { node: id, port: diagPort() });
    } catch (e) { /* the connection may be gone */ }
    if (!quiet && box.isConnected) {
      msg.textContent = "Stopped.";
      startBtn.disabled = !allow;
      stopBtn.disabled = true;
      sync.value = "0";
    }
  };
  S.pdoTestStop = stop;
  stopBtn.addEventListener("click", () => stop(false));

  const rpdoTable = (pdos) => el("table", { class: "od", dataset: { online: "pdo-rpdos" } },
    el("thead", null, el("tr", null, thCells(["RPDO", "Entry", "Value", "Last sent", ""]))),
    el("tbody", null, pdos.flatMap((p) => {
      const inputs = {};
      const repeat = el("select", { "aria-label": `${p.name} repeat`, disabled: !allow, dataset: { pdoRepeat: p.number } },
        REPEATS.map((r) => el("option", { value: r }, r ? `repeat every ${r} ms` : "send once")));
      const sent = el("span", { class: "muted", dataset: { pdoSent: p.number } }, "0 sent");
      const send = el("button", { type: "button", disabled: !allow, title: why, dataset: { pdoSend: p.number }, onclick: async () => {
        const values = {};
        for (const [k, inp] of Object.entries(inputs)) if (inp.value.trim() !== "") values[k] = inp.value.trim();
        if (!Object.keys(values).length) { msg.textContent = `Type a value for ${p.name} first.`; return; }
        try {
          const r = await api("POST", "/api/online/pdo_test_set", Object.assign({ node: id, rpdo: p.number, values, port: diagPort() },
            p.event ? { repeat_ms: Number(repeat.value) } : {}));
          msg.textContent = `${p.name} set${r.event ? "" : "; it goes out after each SYNC this PC sends"}.`;
        } catch (e) { msg.textContent = e.message; }
      } }, "Send");
      run.rpdo[p.number] = { sent };
      return p.values.map((v, k) => {
        const inp = el("input", { type: "text", class: "short", disabled: !allow, "aria-label": `${p.name} ${v.name}`, dataset: { pdoEntry: `${p.number}:${v.key}` } });
        inputs[v.key] = inp;
        return el("tr", { dataset: { pdoRow: `${p.name}:${v.key}` } },
          el("td", null, k === 0 ? `${p.name} ${"0x" + p.cob_id.toString(16).toUpperCase()}` : ""),
          el("td", null, `${v.name} (${v.type || v.bits + " bits"})`), el("td", null, inp),
          el("td", null, k === 0 ? sent : ""),
          el("td", null, k === 0 ? el("span", { class: "row" }, send, p.event ? repeat : el("span", { class: "muted" }, "after each SYNC")) : ""));
      });
    })));

  const tpdoTable = (pdos) => el("table", { class: "od", dataset: { online: "pdo-tpdos" } },
    el("thead", null, el("tr", null, thCells(["TPDO", "Received", "Period", "Values"]))),
    el("tbody", null, pdos.length ? pdos.map((p) => el("tr", { dataset: { pdoTpdo: p.number } },
      el("td", null, `${p.name} 0x${p.cob_id.toString(16).toUpperCase()}`),
      el("td", null, String(p.count)), el("td", null, p.period_ms ? `${p.period_ms} ms` : "-"),
      el("td", null, p.count ? p.values.map((v) => `${v.name} = ${v.value}`).join(", ") : el("span", { class: "muted" }, "nothing received yet")))) :
      [el("tr", null, el("td", { colspan: 4, class: "muted" }, "The node has no valid TPDO."))]));

  const tpdoBox = el("div");
  const poll = async () => {
    if (!run.on) return;
    if (!box.isConnected || S.onlineTab !== "pdo" || S.onlineNode !== id) { stop(true); return; }
    try {
      const st = await api("POST", "/api/online/pdo_test_status", { node: id, port: diagPort() });
      if (!run.on) return;
      if (!st.running) {
        msg.textContent = `The PDO test ended: ${st.ended || "stopped"}.`;
        run.on = false;
        startBtn.disabled = !allow;
        stopBtn.disabled = true;
        return;
      }
      put(tpdoBox, tpdoTable(st.tpdos));
      for (const p of st.rpdos) if (run.rpdo[p.number]) run.rpdo[p.number].sent.textContent = `${p.sent} sent`;
    } catch (e) { msg.textContent = e.message; }
    run.timer = setTimeout(poll, 500);
  };

  startBtn.addEventListener("click", async () => {
    startBtn.disabled = true;
    // With a SYNC period on a slow path: nothing is sent until the user confirms.
    if (Number(sync.value) && !(await askSlowPath("The PDO test with SYNC every " + sync.value + " ms"))) {
      msg.textContent = "Not started.";
      startBtn.disabled = !allow;
      return;
    }
    msg.textContent = "Reading the PDO layout…";
    let r;
    try {
      r = await apiAsk("/api/online/pdo_test_start", Object.assign(nodeSource(id), { start: start.checked }),
        "A PDO test from this PC would fight it. Run it anyway?");
    } catch (e) { msg.textContent = e.message; startBtn.disabled = !allow; return; }
    run.on = true;
    run.forced = !!r.forced;
    stopBtn.disabled = false;
    msg.textContent = `PDO test of node ${id}, layout ${r.source === "configuration" ? "from the configuration" : "read from the device"}.`;
    put(live, el("h3", null, "TPDOs (from the device)"), tpdoBox, el("h3", null, "RPDOs (to the device)"),
      r.rpdos.length ? rpdoTable(r.rpdos) : el("p", { class: "muted" }, "The node has no valid RPDO."));
    put(tpdoBox, tpdoTable(r.tpdos));
    await setSync(true);
    poll();
  });

  put(box,
    allow ? null : el("p", { class: "field-msg warning", dataset: { online: "pdo-no-changes" } }, "The PDO test sends on the bus: " + NO_CHANGES),
    el("p", { class: "muted" }, "Shows the node's TPDOs and sends its RPDOs from this PC, for a device on the bench without a PLC. The layout comes from the configuration when the node is in it, otherwise from the device. SYNC is sent only when you pick a period; leaving this tab stops the test and the SYNC."),
    el("div", { class: "toolbar" }, startBtn, stopBtn, el("label", { class: "inline" }, start, " NMT Start the node first"), sync, nmtBtn),
    msg, live);
  return box;
}

// Closing the page ends a running PDO test and SYNC.
window.addEventListener("pagehide", () => {
  if (!S.pdoTestStop) return;
  for (const path of ["/api/online/pdo_test_stop", "/api/online/sync_stop"]) {
    try {
      fetch(path, { method: "POST", keepalive: true, headers: { "X-CANopen-Token": TOKEN, "Content-Type": "application/json" },
        body: JSON.stringify({ node: S.onlineNode, port: diagPort() }) });
    } catch (e) { /* the page is going away */ }
  }
});

// -- "Only this device is on the bus" for Detect ---------------------------------------------

const LONE_TEXT = "Only this device is on the bus: the adapter joins the bus at each bit rate in normal mode, so it acknowledges the device's frames, and sends an LSS query so a quiet device answers. At wrong bit rates its error frames reach every device on the bus. Use it only on a bench with this one device and nothing else connected.";

function loneBox() {
  return el("label", { class: "check" }, el("input", { type: "checkbox", dataset: { online: "detect-lone" } }), " Only this device is on the bus");
}

async function askLone() {
  return await modal(LONE_TEXT + " Is this device the only one on the bus?", [["go", "Only this device, detect", true], ["cancel", "Cancel"]]) === "go";
}
