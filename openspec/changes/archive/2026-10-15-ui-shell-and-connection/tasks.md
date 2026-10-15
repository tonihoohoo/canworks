## 1. Groundwork

- [x] 1.1 New page scripts next to the others, loaded as plain scripts with no build step (`shell.js`, `connection.js`, `jobs.js`), and `boot.js` that starts the page once every script is loaded (design decision 9: no ES module split yet)
- [x] 1.2 Move the existing page tests to the new places: the Commission switch (`#ws`), the tool tabs (`#tool-tabs`), the connect panel (`#conn-dialog`) and the connection bar (`#conn-bar`); all green before new tests

## 2. Server

- [x] 2.1 `/api/online/status`: a `conn` summary with one shape for adapter and runtime targets (`kind`, `target`, `bitrate`, `check`, `path`, `rtt_ms`, `bus`, `other_master`, `allow_changes`, `allow_changes_source`, `networks`)
- [x] 2.2 `/api/online/jobs`: running jobs of the session (parameter job, scan, LSS find, trace recording, PDO test and SYNC, cyclic sends) with label, progress and stop request; bus jobs asked only while one was started and the connection is open
- [x] 2.3 Stops: the parameter jobs and the scan already stop; LSS find is listed without Cancel (it ends by itself; no plugin change in this UI change)
- [x] 2.4 Disconnect closes a runtime connection too, with its trace, Send panel and watched jobs
- [x] 2.5 `ui.json`: `workspace`, `panel` and `ws_note`; older files load unchanged
- [x] 2.6 The Simulation view's standalone simulator on a connection of its own (`sim_connection`), so it never closes or retargets the runtime connection

## 3. Shell

- [x] 3.1 Header: title, workspace switch, folder name with the unsaved mark, Settings menu with the theme, Reload, Close, Project, Export, Save; Commission a device shows title, Settings and Close only
- [x] 3.2 Workspaces: Configure (config pages) and Commission (online view as Nodes; commissioning Nodes without a config); kept in `ui.json`; links to the other workspace's pages switch to it; one-time note next to the switch
- [x] 3.3 Tool tabs: Variable declarations, Simulation, Trace, Frame lab per workspace; full width; tab pattern and keyboard; the tools leave the side bar

## 4. Connection

- [x] 4.1 `connection.js`: the only poller of `/api/online/status`; the online views draw from its answers (`onlineApply`); trace `onlineReady()` and the Simulation view's Runtime target use it
- [x] 4.2 Connection bar: not connected, connecting with Cancel, adapter, runtime, ended, lost (with Change…), network picker, fault-only colours, status role and alert
- [x] 4.3 Connect panel (dialog): adapter form in Commission a device (a refused check keeps it open with the reason); runtime list, host, Local simulator runtime and token prompt with a config; note and link when online access is off; opened on entering Commission when the connection cannot open by itself
- [x] 4.4 Allow changes: switch with confirmation on an adapter; read-only text with lock on a runtime
- [x] 4.5 Remove the commissioning Bus and master tab, the online view's Connect box and Connection… button, and the trace and simulation connection hints; their "needs a connection" notes get Connect…

## 5. Status bar and bottom panel

- [x] 5.1 `jobs.js` and the status bar: jobs with progress and Cancel on every page, collapse above two, confirmation for restore and write configuration, frame rate and bus load on an adapter
- [x] 5.2 Bottom panel: Problems (Configure; closed in Commission with a config) and Log (Commission a device) with counts; the right-hand Problems column removed
- [x] 5.3 Narrow layout: side bar as top bar below 1100 px, bottom panel kept, Problems strip removed

## 6. Tests

- [x] 6.1 Page tests: workspace switch keeps draft and connection; reload keeps the workspace; tool tabs per workspace and full width; one-time note
- [x] 6.2 Page tests: connect panel on the virtual adapter (wrong rate keeps the panel, Disconnect frees the adapter, Allow changes without "another master") and on the fake plugin runtime (Change…, read-only runtime setting, network picker in the bar, lost connection in the bar)
- [x] 6.3 Page tests: Trace and Simulation's Runtime target work through the bar's connection with no form of their own, and offer Connect… without one
- [x] 6.4 Page tests: scan cancelled from the status bar on another page; LSS find listed without Cancel; restore Cancel asks
- [x] 6.5 axe-core on the connection bar, connect panel, status bar and bottom panel in both themes; keyboard: tool tabs with the arrow keys, Disconnect from the bar

## 7. Docs and release

- [x] 7.1 `docs/configurator.md` (page layout, workspaces, connection bar, connect panel, jobs, bottom panel; Online is the Commission workspace), `docs/pc-adapter.md`, `docs/tour.md`, `docs/diagnostics.md`, `docs/simulator.md`, `README.md`
- [x] 7.2 PC tools minor version bump
