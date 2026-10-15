## 1. Connection bar and panel

- [ ] 1.1 `connection.js`: standalone simulator as a connection kind (`S.simOn`); `connIsOn`, `connReady`, `connEnsure`, `connDisconnect` and `connSession` handle it; connecting to one kind closes the other
- [ ] 1.2 Connect panel with a config: Runtime / Standalone simulator choice (Runtime default, last choice from `sim_target`); simulator address and token form saving through `/api/sim/settings`; Forget token; online access off disables only the Runtime target
- [ ] 1.3 Recent connections listed first in the panel (moved from `nodes.js`), focus on the first one; same rules as today
- [ ] 1.4 Bar: simulator address and Disconnect; shown in Configure on the Trace and Simulation tool tabs as well as while connected

## 2. Pages

- [ ] 2.1 Nodes (`app.js` `renderOnline`, `commission.js` `renderCommNodes`, `nodes.js`): the inline connect form becomes a one-line empty state; simulator connection says it needs a runtime
- [ ] 2.2 Simulation (`sim.js`): remove `simConnectBox` and `#sim-conn`; follow the bar's connection kind; one not-connected line; simulated/real network and device count in the Live values header; keep nothing-simulated and read-only messages
- [ ] 2.3 Trace (`trace.js`): remove the note's Connect… button; simulator connection says recording needs a runtime or adapter
- [ ] 2.4 PDO test: simulator connection says it needs a runtime

## 3. Tests and docs

- [ ] 3.1 Move page tests from the Nodes form, recent buttons, `data-sim` connect controls and `data-trace=open-connect` to the bar and panel
- [ ] 3.2 New page test: with nothing connected, Nodes, Simulation and Trace in both workspaces each have exactly one Connect button (the bar's); connecting to a standalone simulator from the panel feeds Simulation
- [ ] 3.3 `docs/configurator.md` (Commission, Trace, Simulation view, connect panel) and README where connecting is described
- [ ] 3.4 Bump the tools version; layout and accessibility checks stay green

## 4. Hardware

- [ ] 4.1 On the bench: connect from the bar to an adapter and to the runtime, reconnect from the panel's recent list, and confirm no page shows a second Connect button
