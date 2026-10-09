# Proposal: fix-gui-test-findings

## Why

A bug hunt drove every view of `canworks-config` in Chromium against the real plugin. The plugin ran the shipped examples on its simulated bus with `CANWORKS_FORCE_SIMULATE=1`, so no hardware was needed. The hunt found 76 bugs: 9 high, 25 medium and 42 low.

The worst ones are in three groups:
- **Configs the configurator saves but the plugin refuses at start.** A missing CAN interface, numbers typed in hex that skip range checks, duplicate PDO COB-IDs, and a simulation value source on an object the master writes.
- **Plugin faults that only show up online.** A simulated node's power cycle hangs the network's bus thread. A PDO receive timeout never fires again after the first PDO has arrived.
- **Views that silently show less than they should.** The trace decodes the shipped virtual-plant example without any PDOs. The watch-list graph draws no lines.

The existing page tests run on small one-network fixtures with a fake plugin, so none of these were caught. This change fixes the bugs and adds browser coverage that would have caught them, without raising PR CI time.

## What Changes

**Validation: the configurator refuses what the plugin refuses**
- A network adapter without an interface is reported.
- Numbers entered in hex get the same range checks as decimal.
- Duplicate PDO COB-IDs on a network are reported.
- TIME COB-IDs and axis scale fields get the plugin's range checks.
- Heartbeat timeouts shorter than their period get a warning.
- A simulation value source on an object the master writes (a mapped RPDO entry) is reported, as are overrides that don't fit the object's type and scenario steps on unknown nodes.
- Messages say what is wrong in the user's terms, not as raw schema or regex text.

**Plugin**
- A monitored input PDO times out whenever no PDO has arrived for `timeout_ms`, also after it has been seen. Today this relies on a Lely deadline that never fires on the simulated bus.
- A simulated device's power off/on no longer hangs the network's bus thread, and a refused simulation no longer spins it.
- Frames the plugin's own master sends are recorded as Tx on a simulated bus.
- The "Last EMCY" count is the real count, not the history length.

**Configurator**
- *Server robustness.* Opening an unreadable folder fails with a message and leaves the configurator usable. Saving to a read-only folder says so. Open standalone refuses a non-existent folder. New refuses a folder that already has a config.
- *Moving a config.* Move into project… and New editor project… keep `simulation.json` and the slave EDS description.
- *Online view.*
  - The watch-list graph draws its series.
  - The node table keeps focus and click targets across polls.
  - Connection… works for runtime targets.
  - Values refresh after Compare and after writes.
  - Writing a PDO-mapped object warns that the program overwrites it.
  - The panel greys out while the connection is lost.
  - Smaller wording fixes.
- *Trace and Frame lab.*
  - Decoding uses the config's PDOs even when a gateway-routed entry has no PLC location.
  - Hex IDs work in the ID filter.
  - The graph, Frame lab and Simulation views drop the previous network's state on a network switch.
  - "Send this frame" opens the Send panel.
  - J1939 networks show only J1939 controls.
- *Editing.*
  - Network rename and node ID changes carry into gateway routes.
  - An empty PDO can be removed.
  - The slave EDS builder loads the project's description.
  - A second DBC import asks before replacing the first.
  - Removing the gateway's upper network asks about the gateway.
  - The rename dialog works with Enter.
  - Variable declarations no longer suggest a global variable list.
- *Layout and keyboard.*
  - The gateway routes, slave objects and J1939 signal tables fit at 1280 px.
  - The Recent list, folder browser and "Add node from EDS…" can be reached with the keyboard.
  - Focus returns after dialogs and menus.
  - Exports show progress.
  - Export failures don't pile up in Problems.
  - The favicon no longer gives a 404.
- *Smaller items.* The low items listed in tasks.md.

**CI: browser coverage that would have caught these, at no extra PR time**
- **Example sweep.** A page test sweeps every view of the shipped examples for errors and layout. To pay for it, the existing layout sweep runs at two widths instead of three.
- **Validation parity.** A test feeds a corpus of bad configs to both the configurator's check and the plugin's loader, and requires both to refuse each one.
- **Weekly end-to-end run.** A separate workflow, outside PR CI, runs the browser against the real plugin on its simulated bus: weekly, on Run workflow, and on pull requests that touch the online code.
- **Fewer page-test runs.** The page tests run only when the configurator's code or what it uses changed.

## Capabilities

### New Capabilities
None.

### Modified Capabilities
- `canopen-pdo-io`: input PDO timeout detection no longer depends on the master's deadline.
- `canopen-configurator`:
  - the check refuses what the plugin refuses, with plain messages;
  - unreadable or read-only folders are handled;
  - Move and New editor project keep the simulation file;
  - edits that other parts of the config depend on (network rename, node ID change, removing the upper network, a second DBC import) carry through or ask first;
  - keyboard reach;
  - online view refresh, focus and the watch graph.
- `canopen-bus-trace`: decoding with gateway-routed entries, hex ID filters, and per-network trace state.
- `canopen-device-simulator`: a simulation file check matching the plugin; power cycle without a hang.
- `canopen-online-diagnostics`: the EMCY count; Tx direction on a simulated bus.
- `canopen-ci`: example sweep, validation parity, weekly end-to-end browser run, page tests selected by path.

## Impact

- **Plugin:** `plugin/src/canopen/network.cpp` (input PDO check, EMCY count), `bus.cpp` (simulated bus session, Tx tap), simulation start.
- **PC tools:**
  - `tools/deploy/canworks/contract.py`, `configurator/server.py`, `simulation.py`, `tracing.py`, `bustrace/decode.py`, `dbcexport.py`;
  - the configurator's static files (`app.js`, `trace.js`, `sim.js`, `explain.js`, `j1939.js`, `index.html`, `style.css`).
- **Tests:** new page tests, a parity test in the tools job, C++ simulation tests for the timeout and the power cycle.
- **CI:** a new `browser.yml` workflow; `ci.yml` and `.github/ci/` get path selection for the page tests.
- **Docs:** `docs/configurator.md`, `docs/trace.md`, `docs/simulator.md`, `docs/development.md` (how to run the plugin in a container without vcan); README if a listed feature changes.
- **Version:** PC tools minor version bump.
