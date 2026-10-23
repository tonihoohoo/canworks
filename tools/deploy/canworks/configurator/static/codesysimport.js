"use strict";
// Import from CODESYS… (canopen-configurator "Import from CODESYS", "Import
// preview"): a CODESYS .project (CODESYS on this PC exports it without its
// window) or a PLCopenXML .xml, the device when the file has several, then
// the preview with each node's EDS and what is not carried. Create config…
// writes a new config; in a CODESYS config Add to this config adds the
// networks to the draft. Nothing is written before either.

const CI_EDS_STATES = { config: "EDS in this config", library: "EDS from the library",
  repository: "EDS from CODESYS on this PC", added: "EDS added", missing: "EDS missing" };

async function codesysImport() {
  const found = !!(S.state && S.state.codesys_found);
  const path = await chooseFolder({ title: "Import from CODESYS", start: S.lastFolder || S.state.home,
    files: found ? ".project,.xml" : ".xml",
    note: found ? "A CODESYS project (CODESYS on this PC reads it without opening its window and does not change it), or a PLCopenXML file exported in CODESYS."
      : "CODESYS is not installed on this PC, so a .project cannot be read here. In CODESYS, export the device with the CANopen Manager (Project > Export PLCopenXML) and pick that .xml file." });
  if (!path) return;
  const project = /\.project$/i.test(path);
  let r = await ciCall("open", { path }, project
    ? `CODESYS is reading ${folderName(path)}. This takes a minute or two; close the project in the CODESYS window first if it is open there.`
    : `Reading ${folderName(path)}…`);
  if (!r) return;
  if (r.devices) {
    const device = await ciPickDevice(folderName(path), r.devices);
    if (!device) return;
    r = await ciCall("device", { device }, project ? `CODESYS is exporting ${device} from ${folderName(path)}…` : `Reading ${device}…`);
    if (!r) return;
  }
  await ciPreview(r);
}

// One step of the import with a waiting dialog; null after a refusal, which a dialog explains.
async function ciCall(step, body, waiting) {
  let close = null;
  if (waiting) {
    $("#modal-text").textContent = waiting;
    $("#modal-extra").replaceChildren();
    close = modalWorking("Working…");
  }
  let r = null, error = null;
  try {
    r = await api("POST", "/api/codesys/import/" + step, body);
  } catch (e) {
    error = e;
  }
  if (close) close();
  if (error) await modal(error.message, [["close", "Close", true]]);
  return r;
}

// The devices with a CANopen Manager: one picked, the active application's first.
async function ciPickDevice(source, devices) {
  const active = devices.find((d) => d.active) || devices[0];
  const list = el("div", { class: "target-choices", dataset: { ciDevices: "1" } }, ...devices.map((d) =>
    el("label", { class: "choice" },
      el("input", { type: "radio", name: "ci-device", value: d.name, dataset: { ciDevice: d.name }, checked: d === active || null }),
      el("strong", null, d.name + (d.active ? " (active application)" : "")),
      el("span", null, `${(d.buses || []).join(", ")}: ${d.nodes} node${d.nodes === 1 ? "" : "s"}`))));
  const v = await modal(`${source} has ${devices.length} devices with a CANopen Manager. Which one do you import?`,
    [["cancel", "Cancel"], ["import", "Import", true]], list);
  if (v !== "import") return null;
  return (list.querySelector("input:checked") || {}).value || null;
}

function ciEdsCell(row, onAdd) {
  const text = CI_EDS_STATES[row.eds_state] || row.eds_state;
  const cell = el("td", { dataset: { ciEds: row.name } }, el("span", { class: row.eds_state === "missing" ? "bad" : null }, text),
    row.eds ? el("span", { class: "muted" }, " " + row.eds) : null, row.note ? el("div", { class: "hint" }, row.note) : null);
  if (row.eds_state === "missing" || row.eds_state === "added") {
    const input = el("input", { type: "file", accept: ".eds,.EDS,.dcf,.DCF", dataset: { ciAddEds: row.device } });
    input.addEventListener("change", () => { if (input.files[0]) onAdd(row, input.files[0]); });
    cell.append(" ", el("label", { class: "file-button small" }, row.eds_state === "missing" ? "Add EDS…" : "Other EDS…", input));
  }
  return cell;
}

// The preview until Cancel, Create config… or Add to this config.
async function ciPreview(r) {
  const adding = !!S.model && codesysOn();
  for (;;) {
    let next = null;
    const onAdd = async (row, file) => {
      try {
        next = await api("POST", "/api/codesys/import/eds", { device: row.device, name: file.name, data: await fileBase64(file) });
      } catch (e) {
        err.say(`${file.name}: ${e.message}`);
        return;
      }
      $('#modal-buttons button[data-value="refresh"]').click();
    };
    const err = msgBar({ ciError: "1" });
    const nodes = r.networks.reduce((n, net) => n + net.nodes.length, 0);
    const box = el("div", { class: "codesys-import", dataset: { ciPreview: "1" } }, err,
      ...r.networks.map((net) => el("fieldset", { dataset: { ciNetwork: net.name } },
        el("legend", null, `${net.name}: CODESYS network ${net.net_id}, ${net.bitrate / 1000} kbit/s`),
        el("table", null,
          el("thead", null, el("tr", null, el("th", null, "Node"), el("th", null, "Name"), el("th", null, "In CODESYS"), el("th", null, "EDS"))),
          el("tbody", null, ...net.nodes.map((row) => el("tr", { dataset: { ciNode: row.name } },
            el("td", null, String(row.node_id)), el("td", null, row.name), el("td", null, row.device), ciEdsCell(row, onAdd))))))),
      r.report.length
        ? el("details", { dataset: { ciReport: "1" } }, el("summary", null, `Not carried over (${r.report.length})`),
          el("ul", null, ...r.report.map((n) => el("li", null, `${n.where}: ${n.setting}: ${n.note}`))))
        : el("p", { class: "muted", dataset: { ciReport: "1" } }, "Everything in the export is carried over."),
      r.missing ? el("p", { class: "hint", dataset: { ciMissing: "1" } },
        `${r.missing} node${r.missing === 1 ? " has" : "s have"} no EDS: add one with Add EDS… to go on.`) : null);
    const buttons = [["cancel", "Cancel"], ["refresh", "", { hidden: true }], ["create", "Create config…", !adding]];
    if (adding) buttons.push(["add", "Add to this config", true]);
    const answer = modal(`${r.source}${r.device ? ", device " + r.device : ""}: ${r.networks.length} network${r.networks.length === 1 ? "" : "s"}, ${nodes} node${nodes === 1 ? "" : "s"}.`,
      buttons, box);
    for (const b of $("#modal-buttons").querySelectorAll('button[data-value="create"], button[data-value="add"]')) b.disabled = !!r.missing;
    const v = await answer;
    if (v === "refresh" && next) { r = next; continue; }
    if (v === "create") { if (await ciCreate(r)) return; continue; }
    if (v === "add") { if (await ciAdd(r)) return; continue; }
    return;
  }
}

// Create config…: the name and location of the new config folder.
async function ciCreate(r) {
  const stem = (r.project ? folderName(r.project) : r.source || "codesys").replace(/\.(project|xml|gz)$/ig, "");
  const name = el("input", { type: "text", spellcheck: "false", "aria-label": "Name", dataset: { ciNew: "name" } });
  name.value = stem.replace(/[\\/]/g, "_");
  const where = el("input", { type: "text", spellcheck: "false", "aria-label": "Location", id: "ci-new-location", dataset: { ciNew: "location" } });
  where.value = S.lastFolder || S.state.home;
  const choose = el("button", { type: "button", onclick: async () => {
    const p = await chooseFolder({ title: "Where the new config goes", start: where.value.trim() || S.state.home });
    if (p) where.value = p;
  } }, "Choose…");
  const err = msgBar({ ciNew: "error" });
  const form = el("div", { class: "new-config", dataset: { ciNew: "form" } }, err,
    el("label", null, "Name (its folder: new, or an existing empty one)", name),
    el("div", { class: "field" }, el("label", { for: "ci-new-location" }, "Location"), el("div", { class: "row" }, where, choose)));
  for (;;) {
    const v = await modal("New CODESYS config from the import", [["cancel", "Back"], ["create", "Create", true]], form);
    if (v !== "create") return false;
    const nm = name.value.trim();
    if (!nm || /[\\/]/.test(nm)) { err.say("Give the new config a folder name without slashes."); continue; }
    try {
      await api("POST", "/api/codesys/import/create", { path: joinPath(where.value.trim(), nm) });
    } catch (e) {
      err.say("Not created: " + e.message);
      continue;
    }
    await opened();
    banner(`Imported ${r.networks.length} network${r.networks.length === 1 ? "" : "s"} from ${r.source} into a new CODESYS config.` +
      (r.project ? " Build into CODESYS project updates that project in place." : ""));
    return true;
  }
}

// Add to this config: the networks into the draft; a name or network number in use asks Rename or Replace.
async function ciAdd(r) {
  const answers = {};
  for (;;) {
    let res;
    try {
      res = await api("POST", "/api/codesys/import/add", { config: fileConfig(), answers });
    } catch (e) {
      if (e.status === 409 && e.body && e.body.conflicts) {
        for (const c of e.body.conflicts) {
          const v = await modal(`The imported network ${c.name} (CODESYS network ${c.net_id}) clashes with ${c.with} in this config.`,
            [["cancel", "Cancel"], ["rename", "Add it as a new network"], ["replace", `Replace ${c.with}`, { danger: true }]]);
          if (v !== "rename" && v !== "replace") return false;
          answers[c.name] = v;
        }
        continue;
      }
      await modal(e.message, [["close", "Close", true]]);
      return false;
    }
    S.state.eds = Object.assign(S.state.eds || {}, res.eds);
    if (Object.keys(res.eds).length) S.unsavedFiles = true;
    bridgeReplaceDraft(res.config);
    changed(true);
    banner(`Added ${r.networks.length} network${r.networks.length === 1 ? "" : "s"} from ${r.source}. Save writes them.`);
    return true;
  }
}
