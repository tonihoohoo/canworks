## Why

This is the first of five changes in the configurator's UI overhaul. The research behind it compared the configurator with established PLC engineering tools, CANopen configuration tools and CAN bus analysers (research note of 2026-10-15, kept outside the repository). Toni chose five phased changes.

The configurator does more than most of those tools, but the way into it is hard to read:

- **One shell for two jobs.** Editing a config and working on a live bus share one header and one side bar. Parts are hidden by mode flags (`data-config`, `data-commission`), so Commission a device looks like a config with things missing.
- **The connection is never in view.** Whether the page is connected, through what, at which bit rate and whether changes are allowed lives on **Bus and master** (commissioning) or inside **Online** (config). After leaving that page nothing shows it.
- **Three connect forms.** Online has a Connect box for a runtime, commissioning has the adapter form on Bus and master, and Simulation has its own Runtime or Standalone choice. Trace and Simulation only say "connect elsewhere".
- **Tools sit among the nodes.** Online, Trace, Simulation and Frame lab are side bar entries under the node list, next to Variable declarations.
- **Long jobs report in their own panel only.** A scan, Read all or a backup shows progress on the page that started it. After switching page there is no sign that it still runs or how to stop it.
- **Problems take a column.** The Problems pane is a fixed right-hand column on every config page and becomes a special strip in a narrow window.

The tools compared all solve these the same way: separate offline and online modes in the PLC engineering tools, one connect dialog and a status bar that always shows the bus in the bus analysers, and tools as their own full-width windows.

## What Changes

- **Two workspaces.** With a config open, the header has a **Configure | Commission** switch:
  - **Configure** holds today's config pages.
  - **Commission** holds the live pages: today's Online view of the runtime, with its node pages.

  Commission a device (no config) opens straight into Commission, with no switch. Switching workspace keeps the connection and the draft.
- **Tool tabs.** Trace, Frame lab, Simulation (config only) and Variable declarations (Configure only) move out of the side bar into tabs next to the workspace's own tab ("Network" in Configure, "Nodes" in Commission). A tool tab uses the full page width, with no side bar.
- **Connection bar.** A one-line bar under the header shows the connection whenever the page is connected, and in Commission also while it is not:
  - the target (adapter, or runtime name and address);
  - the bit rate and how it was confirmed (adapter), or the path and round trip (runtime);
  - the bus state and the frame and error counters;
  - another master, when one is seen;
  - whether changes are allowed;
  - **Connect…** or **Disconnect**.

  It is neutral when all is well and coloured only for a fault.
- **One connect panel.** **Connect…** opens one panel:
  - Commission a device connects through a USB adapter: the found adapters, bit rate, the check node ID and **Allow changes**.
  - A config connects to a runtime: the found and remembered runtimes, host, **Local simulator runtime**, and the token prompt.

  This replaces the Online Connect box and the commissioning **Bus and master** tab. The rules from the last change stay: no adapter in config mode, no runtime in Commission a device, and a bit rate check on every adapter connect.
- **One connection for every view.** Commission pages, Trace (recording and Send), Simulation's **Runtime** target and the PDO test all use the connection in the bar. None of them has a connect form of its own. Simulation keeps its **Standalone simulator** address, because that is a control channel to `canworks-sim`, not a bus connection.
- **Allow changes in the bar.**
  - On an adapter it is a switch, as today: off at every connect, asks before switching on, and takes effect without reconnecting.
  - On a runtime it shows the runtime's own setting (`master.diagnostics.allow_changes`), read-only, and says where it is set.
- **Status bar and jobs.** A bar at the bottom lists running jobs: scan, LSS find, Read all, back up, compare, restore, write configuration, trace recording, PDO test and cyclic sends. Each shows its progress and has **Cancel**, on every page. Jobs that cannot be stopped today get a stop: LSS find, and back up and compare where they lack one.
- **Bottom panel.** The right-hand Problems pane becomes a collapsible panel under the page:
  - **Problems** in Configure;
  - **Log** (the commissioning log with **Save log**) in Commission a device;
  - **Problems**, collapsed, in Commission with a config.

  The panel replaces the narrow-window Problems strip.
- **Header.** Title, workspace switch, the config's name with an unsaved mark, then Reload from disk, Close, Project, Export and Save as today. The theme choice moves into a small settings menu.
- **BREAKING (UI only):**
  - The **Bus and master** tab of Commission a device is removed; its parts move to the connection bar, the connect panel and the Log panel.
  - The **Online** side bar entry becomes the Commission workspace.
  - The Online **Connection…** box, Trace's connection hint and Simulation's runtime fields give way to the connect panel.

  No file format, server protocol or CLI changes.

Out of scope (later changes): the network tree and tabbed node pages (`network-tree-and-node-tabs`), scan compared with the config and node Status and Log tabs (`commission-workspace`), the trace's identifier view and transmit list (`trace-workspace`), and new state colours and icons (`visual-refresh`).

## Capabilities

### New Capabilities
None.

### Modified Capabilities
- `canopen-configurator`: workspaces, tool tabs, connection bar, connect panel, one shared connection, status bar with jobs, bottom panel, header; the Trace view, Simulation view, Commission a device, Commissioning log, Nodes in commissioning, connect box, path and round trip and narrow layout requirements follow; Bus and master in commissioning is removed.

## Impact

- Configurator page: `tools/deploy/canworks/configurator/static/`
  - `index.html`
  - `style.css`
  - `app.js`: split into ES modules for the shell, the connection service, jobs and panels
  - `commission.js`, `trace.js`, `sim.js`
- Configurator server: `configurator/server.py` and `online.py`:
  - one status route for the connection bar (target, check, bus state, counters, other master, allow changes);
  - a jobs route listing running jobs with progress and their stop route;
  - an explicit disconnect for a runtime connection;
  - stop for LSS find.
- Tests: configurator page tests (layout, workspaces, connect panel, connection bar, jobs and Cancel across pages, bottom panel, narrow layout, axe-core on the new parts), with the existing browser tests moved to the new places.
- Docs: `docs/configurator.md`, `docs/pc-adapter.md`, `docs/tour.md`, `README.md`.
- Version: PC tools minor bump. No plugin change, so no hardware test is needed beyond the page tests.
