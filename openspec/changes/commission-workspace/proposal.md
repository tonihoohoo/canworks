## Why

This is the third of five changes in the configurator's UI overhaul (research note of 2026-10-15, kept outside the repository). It builds on `ui-shell-and-connection`, which adds the Commission workspace, the connection bar and the connect panel, and on `network-tree-and-node-tabs`, which replaces the side bar with a network tree and splits node pages into tabs.

After those two, the Commission workspace has a frame but its content is still the old Online view and the old commissioning Nodes tab:

- **No home.** With a config, Commission opens on the online node table; without a config, on a list of devices heard. The two look and behave differently, and neither says what to do first when nothing is connected beyond "needs a connection".
- **The scan does not compare.** The scan exists only in Commission a device. With a config there is no way to see, in one place, which configured nodes are on the bus, which are missing, and which devices are on the bus but not in the config. The established PLC engineering tools all offer exactly that: found and configured devices side by side, coloured by match, with "copy to project".
- **A node's live state is spread out.** The online node page has Overview, Object dictionary and Parameters. NMT buttons, EMCY history, the error history (0x1003), boot result and PDO timeouts sit on Overview; there is no per-node record of what happened (state changes, EMCY, SDO aborts, changes made).
- **State is only in the table.** The tree shows the configured nodes but not whether they run, so the user has to go back to the table to see which node stopped.
- **Locked controls are dead ends.** Without Allow changes a write control is disabled with a reason, and the user has to find the lock in the connection bar to change that.
- **Simulated devices are a separate world.** The local simulator runtime runs the config's devices on a simulated bus, but practising commissioning on it means switching between Commission and the Simulation tool to inject a fault or move a value.

## What Changes

- **Nodes table as the Commission home.** The Commission workspace opens on one Nodes table, with and without a config. It lists every node known in the session (configured, heard, scanned, set by LSS, added from an EDS) with NMT state, last heard, last EMCY, boot result and EDS. Not connected, the table's empty state holds the connect form itself and the recent connections, so the first step is in view.
- **Scan compared with the config.** With a config, **Scan the bus** runs through the runtime (asking before it scans a running network) and the table becomes a comparison: **Match**, **Missing** (configured, not found), **Not in config** (found, not configured) and **Identity differs**, with **Add to config** and **Use matching EDS** actions that edit the draft. Without a config the scan works as today.
- **Commission node tabs.** A node opened in Commission has the tabs **Status**, **Object dictionary**, **Parameters**, **PDO test** (adapter only), **Notes** and **Log**. Status gathers NMT state and buttons, boot result, heartbeat, PDO timeouts, the EMCY history and the error history (0x1003).
- **Session log, per node and for the bus.** The Log records state changes, boot results, EMCY, SDO aborts, PDO timeouts and every change made through the page. Each node's Log tab shows its entries; the bottom panel's Log tab shows all. In Commission a device, Save log keeps writing the commissioning record (changes only, bus events on request). With a config the log exists in Commission only, in this page only.
- **Live state on the tree.** While connected in Commission, each node in the tree shows its NMT state by shape and text and a flag for a new EMCY or error history entry. Final colours come with `visual-refresh`.
- **Locked controls offer Unlock.** A write control disabled by the lock says so and offers **Unlock…**, which asks the same question as the lock in the connection bar. On a runtime it explains where Allow changes is set.
- **Simulated devices in Commission.** Connected to the local simulator runtime, Commission works as on a real bus: scan, LSS, object dictionary, Parameters. Simulated nodes are marked in the table, and a simulated node's Status tab gains a **Simulated device** panel with its power state, fault buttons (inject and clear) and live values that can be overridden. Extra simulated devices show as **Not in config**, so adding a found device can be practised without hardware.
- **BREAKING (UI only):** the online node page's **Overview** tab becomes **Status**; the old online node table and the commissioning Nodes tab are replaced by the Nodes table. No file format, protocol or CLI change. The runtime scan route the configurator refused since the last change is opened again for the Commission workspace.

Out of scope: the tree itself, Configure's node tabs and problem badges (`network-tree-and-node-tabs`), the trace's identifier view and transmit list (`trace-workspace`), state colours, icons and density (`visual-refresh`). The rules on connections stay: a USB adapter in Commission a device, a runtime with a config.

## Capabilities

### New Capabilities
None.

### Modified Capabilities
- `canopen-configurator`: Nodes table, connect from the Nodes table, scan compared with the config, adding found devices, scan through a runtime, Commission node tabs, Status tab, session log, live state on the tree, Unlock from a locked control, simulated devices in Commission; the online view, Nodes in commissioning, unconfigured devices, device error history, commissioning log, bottom panel and keyboard access requirements follow.

## Impact

- Configurator page `tools/deploy/canworks/configurator/static/`:
  - new script `nodes.js` (connect form on the table, comparison and its actions, tree state, bus events of the log, Unlock, the Status tab's head and simulated device panel, node tabs);
  - `commission.js` (commissioning Nodes table and the session log with filters), `app.js` (online table, node tabs), `tree.js`, `connection.js`, `shell.js`, `index.html`, `style.css`.
- Configurator server `configurator/server.py`: the runtime scan route is allowed again (from the Commission workspace); the scan result gets a `compare` field per device and the list of configured nodes not found; recent connections in `online.json`.
- No plugin, schema, diagnostics protocol or CLI change. The plugin already answers `scan` and asks for `force` when a node is OPERATIONAL.
- Tests: page tests on the virtual adapter and on the fake plugin runtime (Nodes table, comparison states and actions, scan through the runtime with force, Status and Log tabs, tree state, Unlock), and one on the local simulator runtime in the existing simulator CI job (scan, fault from the Status tab).
- Docs: `docs/configurator.md`, `docs/pc-adapter.md`, `docs/tour.md`, `README.md`.
- Version: PC tools minor bump. No plugin change, so no hardware test is needed beyond one bench run of the comparison on a real bus.
