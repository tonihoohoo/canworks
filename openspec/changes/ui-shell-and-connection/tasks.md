## 1. Groundwork

- [ ] 1.1 Load the page as ES modules (`<script type="module">`), with no build step; add a small event emitter on `S`; move nothing else yet
- [ ] 1.2 Page test helpers `openWorkspace(name)`, `openTool(name)`, `connectAdapter(...)`, `connectRuntime(...)`; move the existing page tests from side bar clicks to them, all green before anything new is added

## 2. Server

- [ ] 2.1 `/api/online/status`: one answer shape for adapter and runtime targets (`kind`, `target`, `connected`, `ended_reason`, `bitrate`, `check`, `path`, `rtt_ms`, `bus`, `frames`, `other_master`, `allow_changes`, `allow_changes_source`, `networks`)
- [ ] 2.2 `/api/jobs`: running jobs of the session (parameter job, scan, LSS find, trace recording, PDO test and SYNC, send jobs) with label, progress, start time and stop route
- [ ] 2.3 Stops: LSS find ends between fastscan steps; back up and compare honour the parameter job's stop flag; tests for each
- [ ] 2.4 Explicit disconnect for a runtime connection (closes the diagnostics client and its trace and send jobs)
- [ ] 2.5 `ui.json`: `workspace` per folder and `panel_height`; older files load unchanged

## 3. Shell

- [ ] 3.1 `shell.js`: header (title, workspace switch, folder name and unsaved mark, settings menu with the theme, Reload, Close, Project, Export, Save); Commission a device shows title, settings menu and Close only
- [ ] 3.2 Workspaces: Configure (config pages) and Commission (online view as Nodes; commissioning Nodes without a config); kept per folder and in the URL hash; one-time note on the switch
- [ ] 3.3 Tool tabs: Variable declarations, Simulation, Trace, Frame lab per workspace; full width; tab pattern and keyboard; remove the tools from the side bar

## 4. Connection

- [ ] 4.1 `connection.js`: the only poller of `/api/online/status`; events `connected`, `changed`, `ended`; replace `S.online` connection reads, trace `onlineReady()` and the Simulation view's runtime fields
- [ ] 4.2 Connection bar: states (not connected, connecting with check step and Cancel, adapter, runtime, ended, lost), network picker, fault-only colours, live region and alert
- [ ] 4.3 Connect panel (dialog): adapter form in Commission a device; runtime list, host, Local simulator runtime and token prompt with a config; refused check keeps the panel open; link to Online access when it is off; opens once on entering Commission while not connected
- [ ] 4.4 Allow changes: switch with confirmation on an adapter; read-only text with lock and source on a runtime
- [ ] 4.5 Remove the commissioning Bus and master tab, the online view's Connect box and connection line, and the trace and simulation connection hints; their "needs a connection" notes get a Connect… button

## 5. Status bar and bottom panel

- [ ] 5.1 `jobs.js` and the status bar: job list with progress and Cancel on every page, collapse above two, confirmation for restore and write configuration, frame rate and bus load while connected
- [ ] 5.2 `panel.js`: bottom panel with Problems (Configure; collapsed in Commission with a config) and Log (Commission a device), counts in tab titles, height kept; remove the right-hand Problems column
- [ ] 5.3 Narrow layout: side bar as top bar below 1000 px, bottom panel kept, Problems strip removed; layout fit check at 1000, 1280 and 1440 px

## 6. Tests

- [ ] 6.1 Page tests: workspace switch keeps draft, connection and jobs; reload keeps the workspace; tool tabs per workspace and full width
- [ ] 6.2 Page tests: connect panel on the virtual adapter (wrong rate refused, Disconnect frees the adapter, Allow changes without "another master") and on the fake plugin runtime (token prompt, path and round trip in the bar, network picker)
- [ ] 6.3 Page tests: Trace records and Simulation's Runtime target work through the bar's connection, with no connect form; both offer Connect… without a connection
- [ ] 6.4 Page tests: scan and LSS find cancelled from the status bar on another page; restore Cancel asks; bus-off ends the connection and the bar announces it
- [ ] 6.5 axe-core on the header, connection bar, connect panel, status bar and bottom panel in both themes; one keyboard-only run: connect, switch workspace, open each tool, cancel a job, disconnect

## 7. Docs and release

- [ ] 7.1 `docs/configurator.md` (page layout, workspaces, connection bar, connect panel, jobs, bottom panel; Online becomes Commission), `docs/pc-adapter.md`, `docs/tour.md`, `README.md`
- [ ] 7.2 PC tools minor version bump and changelog line
