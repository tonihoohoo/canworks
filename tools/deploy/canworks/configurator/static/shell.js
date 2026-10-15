"use strict";
// The page's shell (ui-shell-and-connection): the two workspaces, Configure
// (the config pages) and Commission (the live bus), the tool tabs under the
// header and the bottom panel (Problems, or the commissioning log). Loaded
// after app.js and uses its helpers.

// The views of each workspace. A tool tab (TOOLS) shows in a workspace and
// takes the whole width; the others are the workspace's own pages.
const TOOLS = ["declarations", "simulation", "trace", "framelab"];
const TOOL_LABELS = { declarations: "Variable declarations", simulation: "Simulation", trace: "Trace", framelab: "Frame lab" };
const COMMISSION_VIEWS = ["online", "nodes"];

function isTool(view) { return TOOLS.includes(view); }

// The workspace the page shows: Commission a device has no config, so it
// is always Commission.
function workspace() {
  if (S.state && S.state.commission) return "commission";
  return S.workspace === "commission" ? "commission" : "configure";
}

// The workspace's own page: Network (the config pages) or Nodes.
function homeView(ws = workspace()) {
  if (ws === "configure") return S.wsView && S.wsView.configure && !isTool(S.wsView.configure) ? S.wsView.configure : "bus";
  return S.state && S.state.commission ? "nodes" : "online";
}

function toolsOf(ws = workspace()) {
  if (S.state && S.state.commission) return ["trace", "framelab"];
  const sim = !isJ1939(S.config);
  if (ws === "configure") return ["declarations"].concat(sim ? ["simulation"] : [], ["trace", "framelab"]);
  return (sim ? ["simulation"] : []).concat(["trace", "framelab"]);
}

// Keeps S.view inside the workspace: a view of the other workspace, or a
// tool the workspace does not have, goes to the workspace's own page.
function fitView() {
  const v = S.view;
  if (S.state && S.state.commission) {
    if (!isTool(v) && v !== "nodes") S.view = "nodes";
    else if (isTool(v) && !toolsOf().includes(v)) S.view = "nodes";
    return;
  }
  // A page of a workspace shows that workspace (a node page opened from
  // the online view, "Back to the online view").
  if (!isTool(v)) {
    const ws = COMMISSION_VIEWS.includes(v) ? "commission" : "configure";
    if (ws !== workspace()) followWorkspace(v, true);
    if (v === "nodes") S.view = "online";
    return;
  }
  if (!toolsOf().includes(v)) S.view = homeView();
}

// A link to a page of the other workspace (a problem, "Back to the online
// view") switches to that workspace; a tool stays in the one shown.
function followWorkspace(view, shown) {
  if (!S.state || S.state.commission || isTool(view)) return;
  const ws = COMMISSION_VIEWS.includes(view) ? "commission" : "configure";
  if (ws === workspace()) return;
  if (!shown) rememberView();
  S.workspace = ws;
  api("POST", "/api/ui", { workspace: ws }).catch(() => {});
}

// Switches workspace: the draft, the connection and the running jobs stay.
function switchWorkspace(ws) {
  if (S.state && S.state.commission) return;
  if (ws === workspace()) return;
  rememberView();
  banner("");  // a message about the other workspace's page
  if (S.wsNoteDone && S.wsNoteNew) S.wsNoteDone();
  S.workspace = ws;
  const kept = S.wsView && S.wsView[ws];
  // A kept page of the other workspace (never kept on purpose) falls back to the home page.
  S.view = kept && (isTool(kept) || COMMISSION_VIEWS.includes(kept) === (ws === "commission")) ? kept : homeView(ws);
  api("POST", "/api/ui", { workspace: ws }).catch(() => {});
  showView(S.view);
  if (ws === "commission" && typeof connEnter === "function") connEnter();
}

function rememberView() {
  S.wsView = S.wsView || {};
  S.wsView[workspace()] = S.view;
}

// The header's workspace switch and the tool tabs; the side bar and the
// bottom panel per workspace.
function renderShell() {
  const ws = workspace();
  const device = !!(S.state && S.state.commission);
  const sw = $("#ws");
  sw.hidden = device;
  for (const b of sw.querySelectorAll("[data-ws]")) {
    b.setAttribute("aria-pressed", String(b.dataset.ws === ws));
    b.classList.toggle("active", b.dataset.ws === ws);
  }
  document.body.dataset.workspace = ws;
  const tool = isTool(S.view);
  $("#editor").classList.toggle("tool-view", tool || ws === "commission");
  const own = ws === "configure" ? ["network", "Network"] : [homeView(ws), "Nodes"];
  const items = [own].concat(toolsOf(ws).map((t) => [t, TOOL_LABELS[t]]));
  const active = tool ? S.view : own[0];
  const host = $("#tool-tabs");
  host.hidden = false;
  host.replaceChildren(tabs(items, active, (k) => {
    if (k === "network") showView(S.wsView && S.wsView.configure && !isTool(S.wsView.configure) ? S.wsView.configure : "bus");
    else if (!isTool(k)) showView(k);
    else { if (!isTool(S.view)) rememberView(); showView(k); }
  }, { class: "tabs tool-tabs", dataset: "view", label: "Pages", panel: "view" }));
  // A tool works on one network of the config: with several, the network
  // tabs of the side bar are here, since a tool has no side bar.
  if (tool && !device && S.model && several()) {
    host.append(el("div", { class: "segmented tool-net", role: "group", "aria-label": "Network" },
      S.model.networks.map((n, i) => el("button", { type: "button", class: "net-pick", "aria-pressed": String(i === S.net),
        dataset: { net: i }, onclick: () => switchNet(i) }, netLabel(n, i)))));
  }
  connBar();
  renderPanel();
}

// The bottom panel: Problems in a config, the commissioning log in
// Commission a device. Collapsed in Commission with a config.
function renderPanel() {
  const device = !!(S.state && S.state.commission);
  $("#bottom").hidden = false;
  $("#problems").hidden = device || isTool(S.view);
  $("#log-panel").hidden = !device || isTool(S.view);
  if (device) {
    const body = $("#log-body");
    if (!body.childElementCount) body.append(logBox());
    refreshLog();
  }
  // Commission with a config starts collapsed; Configure keeps the user's choice.
  const box = $("#problems-box");
  if (S.panelWs !== workspace()) {
    S.panelWs = workspace();
    box.open = workspace() === "commission" ? false : S.panelOpen !== false;
  }
}

function wireShell() {
  for (const b of document.querySelectorAll("#ws [data-ws]")) b.onclick = () => switchWorkspace(b.dataset.ws);
  const box = $("#problems-box");
  box.addEventListener("toggle", () => {
    if (workspace() !== "configure") return;
    S.panelOpen = box.open;
    api("POST", "/api/ui", { panel: box.open ? "open" : "closed" }).catch(() => {});
  });
  // The header wraps (tool tabs, connection bar): the sticky parts under it follow its height.
  new ResizeObserver(() => document.documentElement.style.setProperty("--header-h", $("#top").offsetHeight + "px")).observe($("#top"));
  // The bottom panel and status bar cover the end of the window: scrolling keeps fields out from under them.
  new ResizeObserver(() => document.documentElement.style.setProperty("--footer-h", $("#bottom").offsetHeight + "px")).observe($("#bottom"));
}

// The kept workspace and panel state, read once at the start.
async function loadShellSettings() {
  try {
    const ui = await api("GET", "/api/ui");
    S.workspace = ui.workspace === "commission" ? "commission" : "configure";
    if (S.workspace === "commission") S.view = "online";  // the page opens on the workspace's own page
    S.panelOpen = ui.panel !== "closed";
    S.wsNoteNew = ui.ws_note !== "seen";
  } catch (e) { S.workspace = "configure"; }
}

// Said once on this PC, next to the switch, the first time a config opens
// with the workspaces; switching or closing the note marks it seen.
function shellNote() {
  const old = document.querySelector("[data-ws-note]");
  if (old) old.remove();
  if (!S.wsNoteNew || (S.state && S.state.commission)) return;
  const done = () => {
    S.wsNoteNew = false;
    const n = document.querySelector("[data-ws-note]");
    if (n) n.remove();
    api("POST", "/api/ui", { ws_note: "seen" }).catch(() => {});
  };
  $("#ws").after(el("span", { class: "ws-note", role: "note", dataset: { wsNote: "1" } },
    "Online moved to Commission. ",
    el("button", { type: "button", class: "small", "aria-label": "Close the note", onclick: done }, "✕")));
  S.wsNoteDone = done;
}
