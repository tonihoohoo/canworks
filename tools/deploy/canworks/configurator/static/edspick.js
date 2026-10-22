// One EDS picker (one-eds-picker): every place that picks an EDS uses the
// list below, in the Add node dialogs or in chooseEds's own dialog, and a
// page that shows a chosen EDS shows it with edsField.

function edsLabel(product, name) { return product ? `${product} (${name})` : name; }

function edsProduct(name) {
  const e = (S.state && S.state.eds || {})[name];
  return (e && e.device && e.device.product_name) || "";
}

// The folder Browse… starts in: the last one browsed, else the EDS library.
function edsBrowseStart() {
  return S.edsBrowsed || (S.online && S.online.eds_library) || S.lastFolder || (S.state && S.state.home) || "";
}

// A file picked in the page's file browser, imported for the draft (or for
// this page in Commission a device), asking on a name conflict. Returns the
// /api/eds_path answer, or null.
async function importEdsPath(path, lint) {
  try {
    return await api("POST", "/api/eds_path", { path, eds_lint: lint });
  } catch (e) {
    if (e.status === 409 && e.body.conflict) {
      const v = await modal(e.message + ". Replace it, or keep both under a new name?",
        [["cancel", "Cancel"], ["replace", "Replace", { danger: true }], ["keep_both", "Keep both", true]]);
      if (!v || v === "cancel") return null;
      try { return await api("POST", "/api/eds_path", { path, on_conflict: v, eds_lint: lint }); }
      catch (e2) { banner(e2.message, true); return null; }
    }
    banner(e.message, true);
    return null;
  }
}

// The list: groups Matches this device, Built here, In this project (or the
// files picked on this page in Commission a device) and EDS library, each
// entry with its product and file name, and Browse…. Options:
// `current` (a file name or path to select), `matches` (the device's EDS
// matches, best first), `builtHere` (the slave page), `files` (names in
// place of the project's EDS files, the simulation's), `dcf` (DCF files
// too), `lint`, `dataset` (the select's), `onBrowsed(res)`, `onEnter()`.
// Returns { list, browse, empty, choice(), fill(), select(v) }; choice() is
// { kind: "project" | "match" | "library" | "picked", name, path, product, res }.
function edsList(opts) {
  const o = Object.assign({}, opts);
  o.matches = o.matches || [];
  o.dataset = o.dataset || {};
  const commission = !!(S.state && S.state.commission);
  const list = el("select", { size: 8, "aria-label": "Device description", dataset: Object.assign({ eds: "list" }, o.dataset) });
  const browse = el("button", { type: "button", dataset: { eds: "browse" } }, "Browse…");
  const empty = el("p", { class: "muted", dataset: { eds: "empty" } }, "No EDS file here yet: Browse… for the device's EDS file.");
  const entries = {};  // option value -> choice
  const picked = [];  // Commission a device: files browsed on this page
  let lib = null;
  const opt = (value, choice, text) => { entries[value] = choice; return el("option", { value, title: choice.path || choice.name }, text); };
  const group = (label, items) => (items.length ? el("optgroup", { label }, items) : null);
  const fill = () => {
    const keep = list.value;
    const seen = new Set();
    const own = new Set(Object.keys((S.state && S.state.slave_descriptions) || {}));
    const matches = group("Matches this device", o.matches.map((m, k) => {
      seen.add(m.path);
      return opt("m:" + k, { kind: "match", name: m.name, path: m.path, product: m.product_name || "" },
        edsLabel(m.product_name, m.name) + (m.revision_match ? ", exact revision" : "") + (m.where === "project" ? ", in this project" : ""));
    }));
    const built = o.builtHere ? group("Built here", [...own].filter((n) => (S.state.eds || {})[n]).map((n) =>
      opt(n, { kind: "project", name: n, product: edsProduct(n) }, edsLabel(edsProduct(n), n)))) : null;
    const mine = o.files ? o.files.map((n) => ({ name: n, product: edsProduct(n), uses: 0 }))
      : commission ? [] : projectEdsChoices().filter((c) => !o.builtHere || !own.has(c.name));
    const project = group(commission ? "Picked on this page" : "In this project", mine.map((c) =>
      opt(c.name, { kind: "project", name: c.name, product: c.product }, edsLabel(c.product, c.name) +
        (c.uses ? `, used by ${c.uses} node${c.uses === 1 ? "" : "s"}` : "")))
      .concat(picked.map((r) => opt("p:" + r.name, { kind: "picked", name: r.name, path: r.name, res: r, product: ((r.summary || {}).device || {}).product_name || "" },
        edsLabel(((r.summary || {}).device || {}).product_name, r.name)))));
    const library = lib ? group("EDS library", lib.filter((f) => !seen.has(f.path) && (o.dcf || /\.eds$/i.test(f.name))).map((f) =>
      opt("lib:" + f.path, { kind: "library", name: f.name, path: f.path, product: f.product_name || "" }, edsLabel(f.product_name, f.name)))) : null;
    list.replaceChildren(...[matches, built, project, library].filter(Boolean));
    empty.hidden = list.options.length > 0;
    if (keep && select(keep)) return;
    if (o.current && select(o.current)) return;
    if (list.options.length) list.selectedIndex = 0;
  };
  // Selects the entry with that option value, file name or path.
  const select = (v) => {
    const hit = [...list.options].find((x) => x.value === v) ||
      [...list.options].find((x) => { const c = entries[x.value]; return c && (c.name === v || c.path === v); });
    if (hit) list.value = hit.value;
    return !!hit;
  };
  browse.onclick = async () => {
    const path = await chooseFolder({ title: "Browse for an EDS file", start: edsBrowseStart(), files: o.dcf ? ".eds,.dcf" : ".eds" });
    if (!path) return;
    S.edsBrowsed = splitPath(path)[0];
    const res = await busy(browse, "Adding…", () => importEdsPath(path, o.lint));
    if (!res) return;
    if (commission) picked.push(res);
    else {
      S.state.eds = S.state.eds || {};
      S.state.eds[res.name] = res.summary;
      if (o.files && !o.files.includes(res.name)) o.files.push(res.name);
    }
    fill();
    select(commission ? "p:" + res.name : res.name);
    const c = entries[list.value];
    if (c) c.res = res;  // its import report and the notes next to it
    if (o.onBrowsed) o.onBrowsed(res);
  };
  list.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && list.value && o.onEnter) { e.preventDefault(); e.stopPropagation(); o.onEnter(); }
  });
  list.addEventListener("dblclick", () => { if (list.value && o.onEnter) o.onEnter(); });
  if (S.online && S.online.eds_library) {
    api("POST", "/api/online/eds_library", {}).then((r) => { lib = r.files || []; fill(); if (o.onFill) o.onFill(); }).catch(() => {});
  }
  fill();
  return { list, browse, empty, fill, select, choice: () => entries[list.value] || null };
}

// The EDS dialog: the list, Browse…, `fields` (an element with the place's
// own fields) and `actions` ([value, label, opts] buttons beside Cancel and
// the main button). `check(choice)` returns why the main button cannot go
// on, or "". Without `fields`, a file picked with Browse… is used at once.
// Resolves { choice } or { action }, or null on Cancel or Escape.
async function chooseEds({ title, current, matches, builtHere, files, dcf, lint, main = "Use", cancelLabel = "Cancel", fields = null, actions = [], check = null, focus = null, dataset = {} }) {
  const err = msgBar({ eds: "msg" }, "");
  let finish = () => {};
  const e = edsList({ current, matches, builtHere, files, dcf, lint, dataset,
    onBrowsed: () => { if (!fields) finish(); },
    onEnter: () => finish() });
  const ok = el("button", { type: "button", class: "primary", dataset: { eds: "use" } }, main);
  const cancel = el("button", { type: "button", dataset: { eds: "cancel" } }, cancelLabel);
  const extra = actions.map(([value, label, o]) => el("button", { type: "button", class: o && o.danger ? "danger" : null, dataset: { edsAction: value } }, label));
  const dlg = el("dialog", { class: "add-node-dialog eds-dialog", "aria-labelledby": "eds-dialog-title", dataset: { eds: "dialog" } },
    el("h2", { id: "eds-dialog-title" }, title),
    err,
    el("div", { class: "grid" },
      el("label", { class: "wide" }, "Device description", e.list, el("div", { class: "row" }, e.browse), e.empty),
      fields),
    el("menu", null, ...extra, cancel, ok));
  const opener = document.activeElement;
  document.body.append(dlg);
  const answer = await new Promise((resolve) => {
    finish = () => {
      const c = e.choice();
      if (!c) { err.say("Pick the device's EDS file, or Browse… for it."); e.list.focus(); return; }
      const why = check ? check(c) : "";
      if (why) { err.say(why); return; }
      resolve({ choice: c });
    };
    ok.onclick = finish;
    extra.forEach((b) => { b.onclick = () => resolve({ action: b.dataset.edsAction }); });
    cancel.onclick = () => resolve(null);
    dlg.addEventListener("cancel", (ev) => { ev.preventDefault(); resolve(null); });
    dlg.showModal();
    (focus || (e.list.options.length ? e.list : e.browse)).focus();
  });
  dlg.close();
  dlg.remove();
  if (opener && opener.isConnected) opener.focus();
  return answer;
}

// A choice made available to the draft: a project file as it is, a match or
// library file imported (with the notes next to it). Returns the import's
// answer ({ name, summary, ... }), or null when it failed.
async function edsIntoDraft(choice, lint) {
  if (choice.kind === "project") return choice.res || { name: choice.name, summary: (S.state.eds || {})[choice.name] };
  if (choice.kind === "picked") return choice.res;
  try {
    const res = await api("POST", "/api/online/use_eds", { path: choice.path, eds_lint: lint });
    S.state.eds = S.state.eds || {};
    S.state.eds[res.name] = res.summary;
    return res;
  } catch (e) {
    banner(e.message, true);
    return null;
  }
}

// A choice as Commission a device uses it: { path, name } of the file.
function edsForPage(choice) {
  return { path: choice.path || choice.name, name: choice.name };
}

// The EDS field: product and file name as text (or `none`), with Choose
// EDS… (none yet) or Change EDS… beside it, and `extra` controls.
// `dataset` goes on the text, `buttonData` on the button.
function edsField({ name, product, none = "None yet", onChoose, label = "", dataset = {}, buttonData = {}, extra = [] }) {
  const text = name ? el("span", { class: "eds-name", title: name, dataset: Object.assign({ edsName: "1" }, dataset) },
    product ? [product, " ", el("span", { class: "muted" }, `(${name})`)] : name)
    : el("span", { class: "muted", dataset: Object.assign({ edsName: "" }, dataset) }, none);
  const btn = el("button", { type: "button", class: "small", dataset: Object.assign({ edsChoose: "1" }, buttonData),
    "aria-label": label ? `${name ? "Change" : "Choose"} the EDS of ${label}` : null, onclick: onChoose }, name ? "Change EDS…" : "Choose EDS…");
  return el("span", { class: "eds-field row" }, text, btn, ...extra);
}

// After an EDS from a folder went into the draft: the notes next to it as
// unsaved edits when the config has none for that EDS (one Undo step with
// the change that used it), else a message; a datasheet notes file named.
function edsNotesArrived(res) {
  if (!res) return;
  const lines = [];
  const notes = res.notes && res.notes.objects ? res.notes.objects : null;
  const k = notes ? Object.keys(notes).length : 0;
  if (k && S.model) {
    const block = notesOf(res.name);
    if (block && !block.error && Object.values(block.device || {}).some(noteFilled)) {
      lines.push(el("div", { dataset: { notesKept: "1" } }, `This config already has notes for ${res.name}, so they are kept. ` +
        `${res.notes.file} next to the picked file was not copied: use Import notes… on the node's Notes tab to bring it in.`));
    } else if (block && !block.error && block.editable) {
      S.model.notes = S.model.notes || {};
      S.model.notes[res.name] = Object.assign({}, S.model.notes[res.name] || {}, notes);
      undoBase();
      S.dirty = draftDirty();
      render();
      lines.push(el("div", { dataset: { notesCame: "1" } }, `${k === 1 ? "1 note" : k + " notes"} from ${res.notes.file} came with ${res.name}; Save keeps ${k === 1 ? "it" : "them"}.`));
    }
  }
  if (res.notes_copied) lines.push(el("div", { dataset: { notesCame: "1" } }, `The notes of ${res.name} came with it (${res.notes_copied.file}).`));
  if (res.notes_kept) lines.push(el("div", { dataset: { notesKept: "1" } }, `Notes for ${res.name} are already on this PC, so they are kept; ` +
    `${res.notes_kept.file} next to the picked file can be brought in with Import notes… on the Notes tab.`));
  if (res.datasheet_notes) lines.push(el("div", { dataset: { datasheetNotes: "1" } }, `${res.datasheet_notes} is next to the picked file: ` +
    "bring it in with Import notes… on the node's Notes tab, which shows the changes first."));
  for (const l of lines) bannerAdd(l);
}
