## 1. Connection bar and panel

- [x] 1.1 `connection.js`: standalone simulator as a connection kind (`S.simOn`); `connIsOn`, `connReady`, `connEnsure`, `connDisconnect` and `connSession` handle it; connecting to one kind closes the other
- [x] 1.2 Connect panel with a config: Runtime / Standalone simulator choice (Runtime default, last choice from `sim_target`); simulator address and token form saving through `/api/sim/settings`; Forget token; online access off disables only the Runtime target
- [x] 1.3 Recent connections listed first in the panel (moved from `nodes.js`), focus on the first one; same rules as today
- [x] 1.4 Bar: simulator address and Disconnect; shown in Configure on the Trace and Simulation tool tabs as well as while connected

## 2. Pages

- [x] 2.1 Nodes (`app.js` `renderOnline`, `commission.js` `renderCommNodes`, `nodes.js`): the inline connect form becomes a one-line empty state; simulator connection says it needs a runtime
- [x] 2.2 Simulation (`sim.js`): remove `simConnectBox`; `#sim-conn` only once connected, with simulation facts alone; follow the bar's connection kind; one not-connected line; keep nothing-simulated and read-only messages
- [x] 2.3 Trace (`trace.js`): remove the note's Connect… button; simulator connection says recording needs a runtime or adapter
- [x] 2.4 PDO test: nothing to change; it runs on the USB adapter connection of Commission a device only, where there is no simulator target

## 3. Tests and docs

- [x] 3.1 Move page tests from the Nodes form, recent buttons, `data-sim` connect controls and `data-trace=open-connect` to the bar and panel
- [x] 3.2 New page test: with nothing connected, Nodes, Simulation and Trace in both workspaces each have exactly one Connect button (the bar's); connecting to a standalone simulator from the panel feeds Simulation
- [x] 3.3 `docs/configurator.md` (Commission, Trace, Simulation view, connect panel) and README where connecting is described
- [x] 3.4 Bump the tools version; layout and accessibility checks stay green

## 4. Hardware

- [x] 4.1 On the bench: connect from the bar to an adapter and to the runtime, reconnect from the panel's recent list, and confirm no page shows a second Connect button (2026-10-15 bench: connected from the bar to the Pi runtime and to the gs_usb adapter, reconnected from the recent list by click and by Enter; no page shows a second Connect button)
