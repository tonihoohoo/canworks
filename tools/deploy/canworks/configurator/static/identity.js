"use strict";
// Device names without a scan (name-nodes-and-standard-dictionary): the
// identity of each heard node read with a few SDO reads, one node at a time;
// what the Device column, the node heading and the Status tab show of it;
// the standard object dictionary's source for a node without an EDS; and
// Change EDS… for an EDS picked on the page. Loaded after nodes.js and uses
// the helpers of app.js, connection.js, commission.js and nodes.js.

const PROFILE_NAMES = { 301: "CiA 301 device", 401: "CiA 401 I/O device", 402: "CiA 402 drive", 404: "CiA 404 measuring device",
  406: "CiA 406 encoder", 408: "CiA 408 hydraulic drive", 410: "CiA 410 inclinometer", 413: "CiA 413 truck gateway",
  418: "CiA 418 battery module", 419: "CiA 419 battery charger", 443: "CiA 443 SIIS level-2 device", 447: "CiA 447 car add-on device" };
const STANDARD_PROFILES = [401, 402];
const SDO_NO_OBJECT = 0x06020000;
const SDO_NO_SUB = 0x06090011;

function profileOf(deviceType) { return Number.isInteger(deviceType) ? deviceType & 0xFFFF : null; }
function profileName(p) { return p ? PROFILE_NAMES[p] || `CiA ${p} device` : "CiA 301 device"; }

// The page's identity records of this connection: {nodes: {id: {status, data, prev}}, busy}.
// status: "new" (to read), "reading", "done", "none" (no SDO answer), "waiting" (STOPPED).
function identityState() {
  S.identity = S.identity || { nodes: {}, busy: false };
  return S.identity;
}

function identityReset() { S.identity = null; }

function scannedOf(id) {
  return ((S.scanResult && S.scanResult.nodes) || []).find((d) => d.node_id === id) || null;
}

// What this page knows of node `id`'s device: the identity read, else the scan's answer.
function identityOf(id) {
  const r = (S.identity && S.identity.nodes[id]) || null;
  const d = scannedOf(id);
  if (r && r.data && r.data.answered) return d ? Object.assign({}, d, r.data, { eds_matches: r.data.eds_matches || d.eds_matches }) : r.data;
  return d;
}

function heardState(n) { return !!n && n.state !== null && n.state !== undefined && n.state !== 0; }

// Each status answer: which nodes to read. A node is read once per
// connection, again after it boots up (heard again after not answering),
// and waits while it is STOPPED (it does not answer SDO then).
function identitySeen(st) {
  if (!st || st.role === "slave" || (st.protocol && st.protocol !== "canopen") || !connIsOn()) return;
  if (!connAdapter() && workspace() !== "commission" && !S.runtimeOn) return;
  const I = identityState();
  for (const n of st.nodes || []) {
    const id = n.node_id;
    const r = I.nodes[id] || (I.nodes[id] = { status: "new", data: null, prev: null });
    const heard = heardState(n);
    if (heard && r.prev === false && (r.status === "done" || r.status === "none")) r.status = "new";
    r.prev = heard;
    if (r.status === "new" && scannedOf(id)) { r.status = "done"; r.data = null; }
    if (r.status === "new" && heard && n.state === 4) r.status = "waiting";
    else if (r.status === "waiting" && heard && n.state !== 4) r.status = "new";
    r.stopped = heard && n.state === 4;
  }
  identityNext();
}

async function identityNext() {
  const I = identityState();
  if (I.busy) return;
  const live = new Map(((S.onlineLast && S.onlineLast.status && S.onlineLast.status.nodes) || []).map((n) => [n.node_id, n]));
  const id = Object.keys(I.nodes).map(Number).sort((a, b) => a - b)
    .find((k) => I.nodes[k].status === "new" && heardState(live.get(k)));
  if (id === undefined) return;
  const r = I.nodes[id];
  r.status = "reading";
  I.busy = true;
  identityShow(id);
  let res = null;
  try { res = await api("POST", "/api/online/identify", { node: id, port: diagPort() }); } catch (e) { r.error = e.message; }
  if (S.identity !== I) return;  // disconnected meanwhile
  I.busy = false;
  r.data = res;
  r.status = res && res.answered ? "done" : "none";
  identityShow(id);
  identityNext();
}

// Read again: a node that did not answer, from its Device cell or Status tab.
function identityAgain(id) {
  const r = identityState().nodes[id] || (identityState().nodes[id] = { status: "new", data: null, prev: true });
  r.status = "new";
  r.data = null;
  identityNext();
  identityShow(id);
}

// The Nodes table, the node heading and the Status tab's device line, after a read.
function identityShow(id) {
  if (typeof onlineRedraw === "function" && S.onlineLast && $("#online-live")) {
    if (S.state && S.state.commission && S.view === "nodes") patchLive($("#online-live"), [commNodeTable(S.onlineLast.status)]);
    else onlineRedraw();
  }
  if (S.onlineNode !== id) return;
  const head = document.querySelector("[data-online=node-heading]");
  if (head) head.textContent = nodeHeading(id);
  const line = document.querySelector("[data-online=node-device]");
  if (line) line.replaceWith(deviceLine(id));
  // The standard dictionary follows the device's profile once 0x1000 is known.
  const st = S.od && S.od[id];
  if (S.onlineTab === "od" && st && st.standardType !== undefined) {
    const d = identityOf(id);
    const t = d && Number.isInteger(d.device_type) ? d.device_type : null;
    if (profileKey(t) !== profileKey(st.standardType)) renderOnlineNode();
  }
}

function profileKey(t) { const p = profileOf(t); return STANDARD_PROFILES.includes(p) ? p : null; }

// The device's name as shown: 0x1008, else the matching EDS's product
// name, else the profile from 0x1000, else vendor and product numbers.
function deviceName(d) {
  if (!d) return "";
  if (d.device_name) return d.device_name;
  const m = (d.eds_matches || [])[0];
  if (m && m.product_name) return m.product_name;
  if (Number.isInteger(d.device_type)) return profileName(profileOf(d.device_type));
  return [d.vendor_id !== undefined ? `vendor ${hex8(d.vendor_id)}` : "", d.product_code !== undefined ? `product ${hex8(d.product_code)}` : ""]
    .filter(Boolean).join(", ");
}

// The muted details after the name: vendor, product and profile not already shown.
function deviceDetails(d) {
  if (!d) return "";
  const name = deviceName(d);
  const m = (d.eds_matches || [])[0];
  const out = [];
  if (d.vendor_id !== undefined) out.push(`vendor ${hex8(d.vendor_id)}${m && m.vendor_name ? " " + m.vendor_name : ""}`);
  if (d.product_code !== undefined) out.push(`product ${hex8(d.product_code)}`);
  if (Number.isInteger(d.device_type)) out.push(profileName(profileOf(d.device_type)));
  return out.filter((t) => !name.includes(t)).join(", ");
}

// The Device cell of the Nodes table.
function deviceCell(id, n) {
  const d = identityOf(id);
  const r = S.identity && S.identity.nodes[id];
  if (d && (d.answered !== false)) {
    const name = deviceName(d);
    const more = deviceDetails(d);
    if (name) return el("div", { class: "device-cell", dataset: { device: id } }, el("span", { class: "device-name" }, name),
      more ? el("div", { class: "muted" }, more) : null);
  }
  if (!r) return null;
  if (r.status === "reading" || (r.status === "new" && heardState(n))) return el("span", { class: "muted", dataset: { device: id } }, "Reading…");
  if (r.status === "waiting") return el("span", { class: "muted", dataset: { device: id } }, "Waits for the node to leave Stopped");
  if (r.status === "none") {
    return el("span", { dataset: { device: id } }, el("span", { class: "muted" }, r.error ? `Not read: ${r.error}` : "No SDO answer"), " ",
      el("button", { type: "button", class: "small", dataset: { deviceAgain: id }, onclick: () => identityAgain(id) }, "Read again"));
  }
  return null;
}

// With a config: the device's own name under the configured one, when read and different.
function ownName(id, configured) {
  const d = identityOf(id);
  const name = d && d.answered !== false ? deviceName(d) : "";
  return name && name !== configured ? el("div", { class: "muted", dataset: { device: id } }, name) : null;
}

// The node page's heading: the configured name, else the device's.
function nodeHeading(id) {
  const n = onlineIsSlave() ? null : configNode(id);
  if (onlineIsSlave()) return `Node ${id} this PLC (slave device)`;
  const name = n && n.name ? n.name : deviceName(identityOf(id)) || (S.onlineEdsName || {})[id] || "";
  return `Node ${id} ${name}`.trim();
}

// The Status tab's first line: the device as read.
function deviceLine(id) {
  const d = identityOf(id);
  const r = S.identity && S.identity.nodes[id];
  const parts = [];
  if (d && d.answered !== false) {
    if (d.device_name) parts.push(d.device_name);
    if (d.vendor_id !== undefined) parts.push(`vendor ${hex8(d.vendor_id)}`);
    if (d.product_code !== undefined) parts.push(`product ${hex8(d.product_code)}`);
    if (d.revision_number !== undefined) parts.push(`revision ${hex8(d.revision_number)}`);
    if (d.serial_number !== undefined) parts.push(`serial number ${hex8(d.serial_number)}`);
    if (d.hardware_version) parts.push(`hardware ${d.hardware_version}`);
    if (d.software_version) parts.push(`software ${d.software_version}`);
    if (Number.isInteger(d.device_type)) parts.push(profileName(profileOf(d.device_type)));
  }
  const text = parts.length ? parts.join(", ") : r && r.status === "reading" ? "Reading…" : r && r.status === "waiting"
    ? "Read when the node leaves Stopped." : r && r.status === "none" ? "No SDO answer." : "Not read yet.";
  const again = connIsOn() && (!r || r.status !== "reading")
    ? el("button", { type: "button", class: "small", dataset: { deviceAgain: id }, onclick: () => identityAgain(id) }, "Read again") : null;
  return el("p", { class: "device-line", dataset: { online: "node-device" } }, el("strong", null, "Device: "), text, " ", again);
}

// -- the standard object dictionary of a node without an EDS

// The source of a node's object dictionary: its EDS (nodeSource), else the
// standard dictionary with the profile its 0x1000 names.
function odSource(id) {
  const src = nodeSource(id);
  if (src || onlineIsSlave()) return src;
  const d = identityOf(id);
  const st = odState(id);
  const out = { node: id, standard: true, port: diagPort() };
  if (d && Number.isInteger(d.device_type)) out.device_type = d.device_type;
  if (st.pdos) Object.assign(out, st.pdos);
  return out;
}

// The EDS files that match the device (from its identity or the scan).
function edsMatchesOf(id) {
  const d = identityOf(id);
  return (d && d.eds_matches) || [];
}

// The EDS choices of a node without one: matching library files and Pick EDS file….
function edsChoices(id, where) {
  const matches = edsMatchesOf(id);
  const input = el("input", { type: "file", accept: ".eds,.EDS", dataset: { online: "pick-eds" } });
  input.addEventListener("change", () => { const f = input.files[0]; if (f) openPickedOd(Object.assign({ node_id: id }, identityOf(id) || {}), f); });
  return el("span", { class: "eds-choices", dataset: { edsChoices: where } },
    matches.map((m, k) => el("button", { type: "button", class: "small", dataset: { edsMatch: k }, title: m.path,
      onclick: () => openScannedOd(Object.assign({ node_id: id }, identityOf(id) || {}), m) }, `Use ${m.name}`)),
    el("label", { class: "file-button small" }, "Pick EDS file…", input));
}

// The line at the top of a standard dictionary.
function standardNote(id, data) {
  const p = data.profile;
  const known = !p || p === 301 || STANDARD_PROFILES.includes(p);
  const what = p && STANDARD_PROFILES.includes(p) ? `the CiA 301 objects and the CiA ${p} objects` : "the CiA 301 objects";
  return notice("info", [
    el("p", null, `Node ${id} has no EDS here, so this shows ${what} the standards define. The device may lack some of them; ` +
      "Read all hides those it lacks. Its own manufacturer objects need its EDS." +
      (known ? "" : ` Its ${profileName(p)} objects are not built in.`)),
    edsChoices(id, "od")], { live: false, dataset: { online: "od-standard" } });
}

// The Parameters tab of a node without an EDS.
function paramsNeedEds(id) {
  return notice("info", [
    el("p", null, `Back up, compare and restore need the device's EDS: node ${id} has none here.`),
    onlineIsSlave() || connAdapter() || !configNode(id) ? edsChoices(id, "params") : null], { live: false, dataset: { online: "no-eds" } });
}

// -- Change EDS… for an EDS picked, matched or added on this page

function pageEdsOf(id) {
  if (configNode(id)) return null;
  const path = (S.onlineEds || {})[id];
  return path ? { name: (S.onlineEdsName || {})[id] || path.split(/[\\/]/).pop(), path } : null;
}

async function changeEds(id) {
  const cur = pageEdsOf(id);
  const added = commNodes()[id] && !commNodes()[id].lss;
  const n = ((S.onlineLast && S.onlineLast.status && S.onlineLast.status.nodes) || []).find((x) => x.node_id === id);
  const onlyAdded = added && !heardState(n) && !scannedOf(id);
  const matches = edsMatchesOf(id).filter((m) => !cur || m.path !== cur.path);
  const buttons = matches.map((m, k) => ["m" + k, `Use ${m.name}`]).concat([["pick", "Pick EDS file…"],
    onlyAdded ? ["remove", "Remove node", { danger: true }] : ["clear", "Clear EDS"], ["cancel", "Cancel"]]);
  const v = await modal(`Node ${id} uses ${cur ? cur.name : "no EDS"} on this page. ` +
    (onlyAdded ? "Use another EDS, or remove the node from this page." : "Use another EDS, or clear it to see the standard objects."), buttons);
  if (!v || v === "cancel") return;
  if (v === "pick") {
    const input = el("input", { type: "file", accept: ".eds,.EDS", hidden: true, dataset: { online: "change-eds-file" } });
    document.body.append(input);
    input.addEventListener("change", () => {
      const f = input.files[0];
      input.remove();
      if (f) openPickedOd(Object.assign({ node_id: id }, identityOf(id) || {}), f, cur);
    });
    input.click();
    return;
  }
  if (v === "clear" || v === "remove") {
    dropPageEds(id);
    if (v === "remove") {
      delete commNodes()[id];
      if (S.onlineNode === id) S.onlineNode = null;
      commLog(id, "Remove node from this page", cur ? `had ${cur.name}` : "done");
    } else commLog(id, `Clear EDS ${cur ? cur.name : ""}`.trim(), "standard objects shown");
    edsChanged(id);
    return;
  }
  const m = matches[Number(v.slice(1))];
  if (m) openScannedOd(Object.assign({ node_id: id }, identityOf(id) || {}), m, cur);
}

// Forgets the EDS the page holds for node `id`, with what was read through it.
function dropPageEds(id) {
  if (S.onlineEds) delete S.onlineEds[id];
  if (S.onlineEdsName) delete S.onlineEdsName[id];
  const c = commNodes()[id];
  if (c) {
    delete c.eds_path;
    delete c.eds_name;
    if (!Object.keys(c).length) delete commNodes()[id];
  }
  if (S.commDevice && S.commDevice.node_id === id) { delete S.commDevice.eds_path; delete S.commDevice.eds_name; }
  dropOdState(id);
}

function dropOdState(id) {
  if (S.odEntries) delete S.odEntries[id];
  if (S.od && S.od[id]) {
    const st = S.od[id];
    st.watchToken = null;
    if (st.plot) { st.plot.destroy(); st.plot = null; }
    delete S.od[id];
  }
}

function edsChanged(id) {
  if (S.view === "nodes" || onlineViews().includes(S.view)) render();
}
