// DBC import, shared by J1939 networks and the CAN messages page: the file
// button that opens the system file picker, the upload with the same-name
// question, and the message picker (Receive, Send or Leave out per message).

// "Import DBC…": a file button; `onFile` gets the picked file.
function dbcFileButton(onFile, dataset) {
  const input = el("input", { type: "file", accept: ".dbc,.DBC", "aria-label": "DBC file", dataset });
  input.addEventListener("change", () => { const f = input.files[0]; input.value = ""; if (f) onFile(f); });
  return el("label", { class: "file-button" }, "Import DBC…", input);
}

// Uploads `file` to `url` (kept with the draft, written to the config folder
// on save). A different file of that name asks Replace or Keep both. Returns
// the server's {name, messages, problems}, or null when cancelled or refused.
async function uploadDbc(url, file) {
  const data = await fileBase64(file);
  try {
    return await api("POST", url, { name: file.name, data });
  } catch (e) {
    if (e.status === 409 && e.body.conflict) {
      const v = await modal(e.message + ". Replace it, or keep both under a new name?",
        [["cancel", "Cancel"], ["replace", "Replace", { danger: true }], ["keep_both", "Keep both", true]]);
      if (!v || v === "cancel") return null;
      try { return await api("POST", url, { name: file.name, data, on_conflict: v }); } catch (e2) { banner(e2.message, true); return null; }
    }
    banner(e.message, true);
    return null;
  }
}

// The message picker. `rows`: [{name, cells: [td content…], comment,
// already: "rx"|"tx"|null, send: preselect Send}]; `columns` heads the cells
// after Message; `lists` names the page's lists for the "already in" note.
// Returns [{index, direction "rx"|"tx"}] of the picked rows,
// or null when cancelled.
async function pickDbcMessages({ text, columns, rows, problems, listenOnly, lists = { rx: "received messages", tx: "sent messages" } }) {
  const picks = rows.map((r) => {
    const sel = el("select", { "aria-label": `${r.name}: receive, send or leave out`, dataset: { pick: r.name } },
      el("option", { value: "" }, "Leave out"), el("option", { value: "rx" }, "Receive"),
      listenOnly ? null : el("option", { value: "tx" }, "Send"));
    sel.value = r.already ? "" : r.send && !listenOnly ? "tx" : "rx";
    return { sel, row: el("tr", { dataset: { dbcRow: r.name } },
      el("td", null, el("strong", null, r.name), r.comment ? el("div", { class: "hint" }, r.comment) : null),
      r.cells.map((c) => el("td", null, c)),
      el("td", null, sel, r.already ? el("div", { class: "muted", dataset: { already: r.name } },
        `already in ${lists[r.already]}`) : null)) };
  });
  const extra = el("div", { class: "dbc-picker" },
    el("table", null, el("thead", null, el("tr", null, thCells(["Message", ...columns, "PLC"]))),
      el("tbody", null, picks.map((p) => p.row))),
    problems && problems.length ? el("details", { class: "muted" }, el("summary", null, `Left out of the import (${problems.length})`),
      el("ul", null, problems.map((p) => el("li", null, p)))) : null);
  const v = await modal(text, [["cancel", "Cancel"], ["add", "Add picked messages", true]], extra);
  if (v !== "add") return null;
  return picks.map((p, index) => ({ index, direction: p.sel.value })).filter((p) => p.direction);
}

// Whether a DBC sender is the PLC: a node named PLC or like the network.
function senderIsPlc(sender) {
  const s = (sender || "").toLowerCase();
  return s !== "" && (s === "plc" || s === netName(S.config).toLowerCase());
}
