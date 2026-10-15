## Context

The configurator is one page, `static/index.html`, with about 22,000 lines of plain JavaScript (`app.js` alone is 6,800) and no build step. Its server (`configurator/server.py`) already keeps every live job outside the page: the online client, the adapter target, parameter jobs (Read all, backup, compare, restore, write configuration), the scan, LSS find, trace recording and send jobs. A reload or a view switch does not stop them.

Since `rework-commission-and-trim-configurator`:
- Commission a device connects only through a USB adapter, with a bit rate check, and has the tabs Bus and master, Nodes, Trace and Frame lab.
- A config's Online view connects only to a runtime.

This change is the shell of the UI overhaul: where things are and how the connection is shown. It changes no file format, protocol or CLI.

## Goals / Non-Goals

**Goals:**
- Offline editing and live work are two named workspaces, and the user always knows which one is open.
- The connection state is visible on every page while connected, and there is exactly one place to connect and disconnect.
- Every view that needs the bus uses that one connection.
- Every long job is visible and can be stopped from any page.
- Tools get the full page width.

**Non-Goals:**
- The network tree, node tabs, scan comparison, trace identifier view, new state colours and icons. These are the four later changes.
- New connection types. The rules stay: adapter in Commission a device, runtime with a config.
- A front-end framework or a build step.

## Decisions

### 1. Two workspaces, switched in the header
`S.state.workspace` is `configure` or `commission`. With a config open the header shows a segmented **Configure | Commission** switch. Commission a device has no config, so it is always `commission` and shows no switch.

- **Configure** shows the config pages: the side bar as today minus the tools, the page, and the bottom panel with Problems.
- **Commission** with a config shows today's Online view as the workspace's **Nodes** tab, with the node list and node pages (Overview, Object dictionary, Parameters).
- **Commission a device** shows today's commissioning Nodes tab.

The workspace is kept per folder in `ui.json` and in the page URL hash, so a reload returns to it. Switching never touches the draft or the connection.

*Alternative:* two commands or two pages. Rejected by Toni: one app with two workspaces.

### 2. Tool tabs
Next to the workspace's own tab ("Network" in Configure, "Nodes" in Commission) the header row under the title has tool tabs. Which tools show:

| Tool | Configure | Commission (config) | Commission a device |
|---|---|---|---|
| Variable declarations | ✓ | | |
| Simulation | ✓ | ✓ | |
| Trace | ✓ | ✓ | ✓ |
| Frame lab | ✓ | ✓ | ✓ |

A tool tab hides the side bar and the bottom panel and takes the full width. Trace and Simulation already took the Problems pane's room, so their layouts need only lose the side bar. The tabs follow the existing tab pattern (arrow keys, `aria-selected`).

### 3. One connection service in the page
A small module (`connection.js`) owns the connection. Today it lives in pieces: `S.online`, the commissioning adapter state, the trace's `onlineReady()` and the Simulation view's runtime fields.

- It polls one server route, `GET /api/online/status`. The route already exists; it is extended so it answers the same shape for both kinds of target:
  - `kind`, `target`, `connected`, `ended_reason`;
  - `bitrate`, `check` (result and how);
  - `path`, `rtt_ms`;
  - `bus` (state, tx/rx errors, error frames);
  - `frames`, `other_master`;
  - `allow_changes`, `allow_changes_source` (`switch` or `runtime`).
- Views subscribe to its events (`connected`, `changed`, `ended`) instead of polling on their own.
- Trace's `onlineReady()` and Simulation's **Runtime** target read this module.
- The Online view's own connection line and the commissioning Bus and master tab are removed.

The server keeps one target per page session, as now, so no protocol changes.

### 4. Connection bar
The connection bar is a single line under the header. It shows in Commission always, and in Configure only while connected.

| State | Bar |
|---|---|
| Not connected | "Not connected" · **Connect…** |
| Connecting / checking | "Connecting to gs_usb:0 at 500 kbit/s…" with the check step · **Cancel** |
| Adapter connected | dot · `gs_usb:0` · `500 kbit/s, confirmed by traffic` · bus state · frames / error frames · other master (when seen) · lock switch · **Disconnect** |
| Runtime connected | dot · runtime name and address · path and round trip (amber above 100 ms, red above 300 ms, as today) · bus state of the picked network · lock (read-only text) · **Disconnect** |
| Ended or lost | the reason ("connection ended: bus-off") or "not answering, last data 4 s ago", coloured · **Connect…** / retrying |

Colour only marks a fault: an ended connection, error passive or bus-off, a slow path, another master. Everything else is neutral text. The bar is a polite live region for state changes and an alert when a connection ends. The network picker for a runtime with several networks moves into the bar, next to the bus state, so Commission and Trace share it.

### 5. Connect panel
**Connect…** opens a dialog (native `<dialog>`, focus trapped, Escape closes).

**Commission a device: adapter.**
- Found adapters with Refresh, while the panel is open.
- A typed target.
- The bit rate from the CiA 301 list, with no default.
- "Device's node ID, to check the bit rate", for adapters without send confirmation.
- **Allow changes**, unticked.
- **Connect**.

A refused check keeps the panel open with the reason under the bit rate and the form filled in, as the Bus and master tab does today.

**Config: runtime.**
- The runtime list (found and remembered), the host field and **Local simulator runtime**.
- **Connect**.
- The token prompt when this PC has no matching token, inside the same dialog.
- The Online access settings (port, bind, token, internet access) stay in Configure → Bus and master, because they are config data. The panel links there when online access is off.

The last target is kept on this PC as today (`online.json`). Opening the Commission workspace while not connected opens the panel once. Closing it leaves the bar's **Connect…**.

### 6. Allow changes in the bar
- **Adapter:** a switch, off for every new connection. Switching it on asks first, as today, and applies to the open connection without reconnecting.
- **Runtime:** the switch is shown read-only, because the runtime decides (`allow_changes` in the uploaded config). Its tooltip says "Set in Configure → Bus and master → Online access, then upload".

### 7. Jobs in the status bar
`GET /api/jobs` lists the running jobs of this page session: `id`, `kind`, `label`, `progress` (done/total or a fraction), `started`, `stoppable`, and the stop route. It is built from the state the server already keeps:
- the parameter job;
- the scan;
- LSS find;
- the trace recording;
- the PDO test and SYNC;
- send jobs.

The status bar shows each job with a short label ("Scan 41/127", "Read all node 5 – 120/310", "Trace – 12,400 frames") and **Cancel**. More than two jobs collapse into "3 jobs ▾".

Missing stops are added:
- LSS find, by ending the fastscan loop between steps;
- back up and compare, if they do not already honour the parameter job's stop flag.

Cancel of a job that changes the device (restore, write configuration) asks first, as their own Cancel does today. The status bar also shows, while connected, the bus load estimate and the frame rate.

### 8. Bottom panel
The bottom panel replaces the right-hand `#problems` column. It is collapsible, with its height kept in `ui.json`.

| Workspace | Tab | Default |
|---|---|---|
| Configure | **Problems** (with Allow overlap) | open while there are problems |
| Commission a device | **Log** (the commissioning log, its count and **Save log**) | collapsed |
| Commission with a config | **Problems** | collapsed |

The tab title carries the count in all cases. It gives the page the full width, and the narrow layout no longer needs its own Problems strip: below 1000 px the panel stays and only the side bar becomes the top bar.

### 9. Code layout
`app.js` is split into ES modules loaded with `<script type="module">`:
- `shell.js`: header, workspaces, tool tabs;
- `connection.js`;
- `jobs.js`;
- `panel.js`: the bottom panel.

The rest of `app.js` stays as one module for now, and later changes split it further. There is still no build step, and every file stays in `static/`. The modules share state through the existing `S` object, with a small event emitter added.

*Alternative:* a framework (React, Svelte). Rejected: it needs a build pipeline and the packaging is Python-only, and the gain is not in usability.

## Risks / Trade-offs

- **[Many page tests click side bar entries that move]** → The test helpers get `openTool(name)` and `openWorkspace(name)`, and the 250 page tests are moved in one task before new tests are added.
- **[Users of the Online view look for it in the side bar]** → The Commission switch shows a one-time hint ("Online is now the Commission workspace") the first time a config opens after the update, and the docs say it.
- **[A runtime's allow-changes looks like a switch that does nothing]** → It is drawn as read-only text with a lock, not a switch, on a runtime.
- **[Status polling doubles up]** → The connection module is the only poller of `/api/online/status`. Jobs are polled only while the list is not empty, plus every 5 s.

## Migration Plan

UI only, with nothing stored to migrate:
- `ui.json` gains `workspace` and `panel_height`, and older files lack them.
- `online.json` is unchanged.
- Rollback is the previous tools version.

## Open Questions

None. The defaults picked here (Simulation in both workspaces of a config, Problems collapsed in Commission with a config, the connect panel opened once on entering Commission) are easy to change in review.
