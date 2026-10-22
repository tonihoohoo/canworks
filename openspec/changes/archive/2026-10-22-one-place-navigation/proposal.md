# Proposal

## Why

The usability hunt of 2026-10-21 (H4, H6, M4, M6) found the same controls in several places, and some leading nowhere:

- **Tools in both workspaces.** Simulation, Trace and Frame lab are tool tabs in Configure *and* in Commission. Trace and live Simulation need the bus, and the Configure page itself says "Work on the live bus is under Commission".
- **Three network pickers on Trace.** The tab row's network chips (io / motion / cell / host), the connection bar's Network select, and Trace's own Network select.
- **The project target on every Bus page.** "Project target" is a field at the top of each network's Bus and master page, and again on the Modbus bridge page. It is a project setting, shown inside a network.
- **Trace Start without a connection** fails with a 409. Then a red banner appears near the top of the page, away from the button: "set up online access … in the **Online view**". The Online view no longer exists (server.py:3981). Two more texts still say "Online view".
- **Connect panel.** It offers three ways to give a runtime host: a found-runtimes select reading "Looking…" or "None found", a host field, and a full-width **Local simulator runtime** button. The token opens a **second dialog on top of the panel**.
- **Two "Simulation" names.** A node's "Simulation" tab says "Live values … are in the Simulation tab", while you are already on a tab called Simulation.

## What Changes

- **Each tool in one workspace.**
  - **Configure** tabs: Network, Variable declarations (OpenPLC), and **Simulation file** (the simulation file and scenarios, no live values).
  - **Commission** tabs: Nodes, **Simulation** (live values, faults, power; with "Edit the simulation file" switching to Configure), **Trace** and **Frame lab**.
  - Commission a device keeps Nodes, Trace and Frame lab.

  A link to a tool in the other workspace (a problem, "Explain in Frame lab", "Send…") switches workspace, as links do today.
- **One network picker.** The connection bar's network picker is the only one. In Commission it is shown even when not connected, listing the config's networks, so Trace files and the Frame lab can still pick a network. The tab-row chips and Trace's own Network select go away.
- **A Project entry in the tree.** At the top of the Configure tree, a **Project** entry opens the project page: the target, with its switch dialog as today, and Online access (which moves there from its own tree entry). The Bus and master pages and the Modbus bridge page lose their Project target field. The header badge still shows the target and opens the Project page.
- **Trace Start without a connection** opens the connect panel. Once connected, the trace starts. Canceling the panel leaves Trace as it was. Every "Online view" text is replaced by the current place ("Commission", "Project → Online access").
- **Connect panel.**
  - Runtime: one host combobox lists the found and remembered runtimes, "Local simulator runtime" and the typed host; while it is still looking it says "Looking for runtimes…".
  - When this PC has no matching token, the token field shows **inside the panel** (a password field with Show) next to Connect, and is checked on Connect.
  - The second token dialog goes away. The same goes for "Adapter on another machine".
- **Names.** A node's tab becomes **Simulated device**. Its text points to "Commission → Simulation" for live values.
- PC tools minor version bump; README and docs/configurator.md (tabs, Project page, connect panel).

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `canopen-configurator`: "Tool tabs" (each tool in one workspace), "Network picker in online and trace views" (the only picker, shown unconnected), "Project target" (on the Project page), "Online access settings" (on the Project page), "Network tree" (Project entry), "Connect panel" (one host combobox, token inline), "Simulation tab of a node" (named Simulated device). New requirement: "Trace Start without a connection".

## Impact

- `tools/deploy/canworks/configurator/static/shell.js`, `index.html` (tabs per workspace), `tree.js` (Project entry), `target.js` (target field moves), `connection.js` (picker always in Commission, panel combobox and inline token), `trace.js` (no own network select, Start opens the panel), `sim.js` (Simulation split into file and live), `node.js` (tab name), `links.js` and `server.py` (wording).
- Tests: page tests for tabs per workspace, links switching workspace, one picker, Project page, Trace Start opening the panel, inline token; update tests that open Trace or Simulation from Configure.
- No plugin, bridge or CODESYS export change. No hardware test.
