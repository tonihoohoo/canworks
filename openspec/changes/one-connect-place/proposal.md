## Why

The Commission workspace offers Connect in several places at once. With nothing connected:

- **Nodes** shows "Not connected" with **Connect…** in the connection bar, and under it the table's own connect form (or "Not connected to the runtime" with a second **Connect…**).
- **Simulation** shows the bar's **Connect…**, then a **Connect to** box with a Runtime / Standalone simulator choice and its own **Connect…** (or address, token and **Connect** for the simulator), then a "Not connected." line, then "Connect to see live values" in the Live values tab. That is four statements of the same fact and two Connect buttons on one screen.
- **Trace** says recording needs a connection and has its own **Connect…** button.

A user has to work out whether these buttons are the same thing, and the Simulation view's standalone simulator connection really is a different one that the bar does not show. One place to connect, always in the same spot, removes the doubt.

## What Changes

- **The connection bar is the only place to connect.** Its **Connect…** opens the connect panel; its **Disconnect** closes the connection. No page has a connect form, a Connect button or a button that opens the panel.
- **The bar shows where it is needed.** Always in Commission (as now), and in Configure while connected (as now) and also on the Trace and Simulation tool tabs, so those two always have the bar to connect from.
- **Pages without a connection say what they need, in one line, with no button.** Nodes: "Connect with Connect… above to see the nodes." Trace: recording needs a connection; files still open. Simulation: live values need a connection; the file and scenarios stay editable. Online access off keeps its link to Configure → Online access.
- **Recent connections move into the connect panel.** The up to three recent connections that the Nodes table offers today are listed first in the panel, one click each, with the same rules (adapter still runs the bit rate check, Allow changes starts off, no tokens kept).
- **Standalone simulator becomes a target in the connect panel.** With a config, the panel offers **Runtime** (default) and **Standalone simulator** (address and token, kept on this PC as today). The bar then shows the simulator's address and Disconnect. The Simulation view loses its **Connect to** box and its own "Not connected." line, and shows only what is particular to simulation (nothing simulated, read-only and why).
- On a standalone simulator connection, Nodes, Trace recording and the PDO test say they need a runtime connection.

No file format or CLI change. `online.json` keeps `sim_target`, `sim_address` and `sim_token`; the panel writes them instead of the Simulation view.

## Capabilities

### New Capabilities
None.

### Modified Capabilities
- `canopen-configurator`: Connection bar (the one place to connect, shown on Trace and Simulation in Configure, simulator target), Connect panel (only place to connect, recent connections first, Standalone simulator target), One connection for every view (no page has a Connect button, Simulation included), Trace view and Simulation view (no own Connect), Nodes in commissioning (not-connected text); the requirement "Connect from the Nodes table" is removed.

## Impact

- Configurator page, `tools/deploy/canworks/configurator/static/`:
  - `connection.js`: panel with recent connections and the Standalone simulator target; bar shows the simulator connection and shows on Trace and Simulation in Configure;
  - `nodes.js`, `app.js` (`renderOnline`), `commission.js` (`renderCommNodes`): the inline connect form becomes a one-line empty state;
  - `sim.js`: `simConnectBox` and the `#sim-conn` line go; the view follows the bar's connection;
  - `trace.js`: the Connect… button in the not-connected note goes.
- Server: none expected; `/api/sim/settings` keeps its fields, the panel calls it.
- Tests: page tests that press the Nodes table form, the recent buttons, `[data-sim=open-connect]`, `[data-sim-target]`, `[data-sim=connect]` or `[data-trace=open-connect]` move to the bar and the panel; a new test checks each page has exactly one Connect… button.
- Docs: `docs/configurator.md` (Simulation view, Commission, Trace), README if it mentions connecting from the Simulation view.
- Overlap: `name-nodes-and-standard-dictionary` (PR #99) touches `connection.js` and `commission.js` lightly, and `fix-clipped-text-configure` touches the tree and dialogs; whichever merges later rebases. Neither changes where Connect lives.
