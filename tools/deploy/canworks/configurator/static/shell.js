"use strict";
// The page's shell (ui-shell-and-connection): the workspaces, Configure
// (the config pages), Commission (the live bus) and Devices (installing on
// devices, devices.js), the tool tabs under the
// header and the bottom panel (Problems, or the commissioning log). Loaded
// after app.js and uses its helpers.

// The views of each workspace. A tool tab (TOOLS) takes the whole width and
// belongs to one workspace (TOOL_WS, one-place-navigation); the others are
// the workspace's own pages.
const TOOLS = ["simfile", "simulation", "trace", "framelab"];
const TOOL_LABELS = { simfile: "Simulation file", simulation: "Simulation", trace: "Trace", framelab: "Frame lab" };
const TOOL_WS = { simfile: "configure", simulation: "commission", trace: "commission", framelab: "commission" };
const COMMISSION_VIEWS = ["online", "nodes"];
const DEVICES_VIEWS = ["devices"];

function isTool(view) { return TOOLS.includes(view); }

// The workspace a page or tool belongs to.
function viewWorkspace(view) {
  if (TOOL_WS[view]) return TOOL_WS[view];
  return DEVICES_VIEWS.includes(view) ? "devices" : COMMISSION_VIEWS.includes(view) ? "commission" : "configure";
}

// The workspace the page shows: Commission a device has no config, so it
// is always Commission.
function workspace() {
  if (S.state && S.state.commission) return "commission";
  return S.workspace === "commission" || S.workspace === "devices" ? S.workspace : "configure";
}

// The workspace's own page: Network (the config pages) or Nodes.
function homeView(ws = workspace()) {
  if (ws === "configure") return S.wsView && S.wsView.configure && !isTool(S.wsView.configure) ? S.wsView.configure : "bus";
  if (ws === "devices") return "devices";
  return S.state && S.state.commission ? "nodes" : "online";
}

function toolsOf(ws = workspace()) {
  if (S.state && S.state.commission) return ["trace", "framelab"];
  if (ws === "devices") return [];
  // A target that does not run canworks has no simulated devices (target.js).
  // A J1939 network keeps Simulation, which points to canworks-j1939-sim, but has no simulation file.
  const sim = !S.model || simulationShown();
  if (ws === "configure") return sim && !isJ1939(S.config) ? ["simfile"] : [];
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
  // A page or tool of a workspace shows that workspace (a node page opened
  // from Commission, a problem's link to the Trace).
  const ws = viewWorkspace(v);
  if (ws !== workspace()) followWorkspace(v, true);
  if (v === "nodes") S.view = "online";
  if (isTool(v) && !toolsOf().includes(v)) S.view = homeView();
}

// A link to a page or tool of the other workspace (a problem, "Explain in
// Frame lab") switches to that workspace.
function followWorkspace(view, shown) {
  if (!S.state || S.state.commission) return;
  const ws = viewWorkspace(view);
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
  S.workspace = ws;
  const kept = S.wsView && S.wsView[ws];
  // A kept page of the other workspace (never kept on purpose) falls back to the home page.
  S.view = kept && ((isTool(kept) && toolsOf(ws).includes(kept)) || (!isTool(kept) && viewWorkspace(kept) === ws)) ? kept : homeView(ws);
  api("POST", "/api/ui", { workspace: ws }).catch(() => {});
  showView(S.view);
  if (ws === "commission" && typeof connEnter === "function") connEnter();
}

function rememberView() {
  S.wsView = S.wsView || {};
  S.wsView[workspace()] = S.view;
}

// The header's workspace switch and the tool tabs; the network tree and the
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
  // The network tree beside the workspace's own page; a tool, and Commission
  // a device (its own node list), take the whole width.
  $("#editor").classList.toggle("tool-view", tool || device || ws === "devices");
  const own = ws === "configure" ? ["network", "Network"] : ws === "devices" ? ["devices", "Devices"] : [homeView(ws), "Nodes"];
  const items = [own].concat(toolsOf(ws).map((t) => [t, TOOL_LABELS[t]]));
  const active = tool ? S.view : own[0];
  const host = $("#tool-tabs");
  // Devices has one page and no tools: no tab row.
  host.hidden = ws === "devices";
  // A redraw keeps keyboard focus on the tool tabs (on the selected one).
  const hadFocus = host.contains(document.activeElement);
  if (hadFocus) setTimeout(() => {
    const a = document.activeElement;
    if (!a || a === document.body || !a.isConnected) { const t = host.querySelector("[role=tab][aria-selected=true]"); if (t) t.focus(); }
  }, 0);
  host.replaceChildren(tabs(items, active, (k) => {
    if (k === "network") showView(S.wsView && S.wsView.configure && !isTool(S.wsView.configure) ? S.wsView.configure : "bus");
    else if (!isTool(k)) {
      // Nodes is the network's page: from a node page it goes back to the table (commission-master-detail).
      if (S.onlineNode !== null && S.onlineNode !== undefined && (S.state.commission || !onlineIsSlave())) { S.onlineBackFrom = S.onlineNode; S.onlineNode = null; }
      showView(k);
    } else { if (!isTool(S.view)) rememberView(); showView(k); }
  }, { class: "tabs tool-tabs", dataset: "view", label: "Pages", panel: "view" }));
  // A tool works on the network picked in the connection bar, the one picker (one-place-navigation).
  connBar();
  renderPanel();
}

// The bottom panel: Problems in a config, the commissioning log in
// Commission a device. Collapsed in Commission with a config.
function renderPanel() {
  const device = !!(S.state && S.state.commission);
  const commission = workspace() === "commission";
  $("#bottom").hidden = false;
  $("#problems").hidden = device || isTool(S.view) || workspace() === "devices";
  // The session log (commission-workspace): Commission only, with or without a config.
  $("#log-panel").hidden = !commission || isTool(S.view);
  if (commission) {
    const body = $("#log-body");
    if (!body.childElementCount || body.dataset.device !== String(device)) { body.dataset.device = String(device); body.replaceChildren(logBox()); }
    refreshLog();
  }
  // Commission: Problems and the Log start as one-line strips (the Log's count in its strip);
  // Configure keeps the user's choice while there are problems.
  const box = $("#problems-box");
  if (S.panelWs !== workspace()) {
    S.panelWs = workspace();
    const want = commission ? false : S.panelOpen !== false && (S.problemsShown === undefined || S.problemsShown > 0);
    if (box.open !== want) { S.panelAuto = true; box.open = want; }
    if (commission && !device) $("#log-box").open = false;
  }
}

function wireShell() {
  for (const b of document.querySelectorAll("#ws [data-ws]")) b.onclick = () => switchWorkspace(b.dataset.ws);
  const box = $("#problems-box");
  box.addEventListener("toggle", () => {
    if (S.panelAuto) { S.panelAuto = false; return; }  // folded or unfolded for its count, not by hand
    if (workspace() !== "configure") return;
    S.panelOpen = box.open;
    api("POST", "/api/ui", { panel: box.open ? "open" : "closed" }).catch(() => {});
  });
  // The header wraps (tool tabs, connection bar): the sticky parts under it follow its height.
  new ResizeObserver(() => document.documentElement.style.setProperty("--header-h", $("#top").offsetHeight + "px")).observe($("#top"));
  // The simulation banner and the message bar stay under it (consistent-message-bars).
  new ResizeObserver(() => document.documentElement.style.setProperty("--bars-h", $("#page-bars").offsetHeight + "px")).observe($("#page-bars"));
  // The bottom panel and status bar cover the end of the window: scrolling keeps fields out from under them.
  new ResizeObserver(() => document.documentElement.style.setProperty("--footer-h", $("#bottom").offsetHeight + "px")).observe($("#bottom"));
}

// The kept workspace and panel state, read once at the start.
async function loadShellSettings() {
  try {
    const ui = await api("GET", "/api/ui");
    S.workspace = ui.workspace === "commission" || ui.workspace === "devices" ? ui.workspace : "configure";
    if (S.workspace === "commission") S.view = "online";  // the page opens on the workspace's own page
    if (S.workspace === "devices") S.view = "devices";
    S.panelOpen = ui.panel !== "closed";
  } catch (e) { S.workspace = "configure"; }
}

// Under 1500 px, with a config open, the secondary header actions (Reload
// from disk, Close, Settings, Quit) go into one "⋯" menu, so the header stays
// one row; wider, or with no config (start page, Devices without a config:
// the header has room), they stay in their places.
const HEADER_MORE = ["#btn-reload", "#btn-close", "#menu-settings", "#btn-quit"];
const HEADER_NARROW = matchMedia("(max-width: 1499px)");
function fitHeaderMore() {
  const more = $("#menu-more");
  if (!more) return;
  const panel = more.querySelector(".menu-panel");
  const config = !$("#actions").hidden && !document.body.classList.contains("devices-only");
  const narrow = HEADER_NARROW.matches && !TRACE_WINDOW && config;
  more.hidden = !narrow;
  if (!narrow) more.open = false;
  for (const sel of HEADER_MORE) {
    const e = $(sel);
    if (narrow && e.parentElement !== panel) {
      const home = document.createComment(sel);
      e.before(home);
      e.homeMark = home;
      panel.append(e);
      if (e.tagName === "BUTTON") e.classList.add("item");
    } else if (!narrow && e.homeMark) {
      e.homeMark.replaceWith(e);
      e.homeMark = null;
      if (e.tagName === "BUTTON") e.classList.remove("item");
    }
  }
  fitHeaderRow();
}
HEADER_NARROW.addEventListener("change", fitHeaderMore);

// The header stays one row (canopen-configurator "Header target action"):
// when it would wrap, the simulation chip shows only "Simulated", its full
// text staying in the tooltip and Details.
function fitHeaderRow() {
  const row = $("header .top-row");
  if (!row) return;
  document.body.classList.remove("header-tight");
  const actions = $("#actions");
  const parts = [...row.children, ...(actions ? actions.children : [])].filter((e) => e !== actions && e.offsetParent !== null)
    .map((e) => e.getBoundingClientRect()).filter((r) => r.height);
  if (parts.length > 1 && Math.max(...parts.map((r) => r.top)) >= Math.min(...parts.map((r) => r.bottom))) document.body.classList.add("header-tight");
}
window.addEventListener("resize", fitHeaderRow);
