## Why

The explore of 2026-10-23 (`research/bridge-failure-hardening-2026-10-23.md`) asked what the nodes and the PLC see when canworks-bridge fails. A clean stop sends every node `master.on_plc_stop` (pre-operational by default). A crash, an out-of-memory kill, a hang or a power loss of the bridge's device sends nothing: SYNC and the master heartbeat just stop. Then:

- **Nodes keep driving their last outputs.** A node reacts only if it watches the master's heartbeat (`heartbeat_consumer`, 0x1016) or has an RPDO deadline (`event_timer_ms`), and neither is set unless the user sets it. Left out, both keep the EDS values, which are usually "off". A valve node then stays OPERATIONAL with its last command for as long as the bridge is gone.
- **A restart re-boots every node.** Without `config_check`, the master resets and downloads every node at each start, so device outputs drop to their defaults during the download. With `config_check`, a node that kept running with the same configuration is taken over without a reset (canopen-master-bringup "Skip configuration when unchanged").
- **Bus-off can last until someone acts.** `adapter.restart_ms` is unset by default, and many controllers then stay bus-off until the interface is restarted.
- **The PLC sees frozen inputs.** When the bridge is gone, `canworks.ok` turns FALSE, but the generated `canworks_in` keeps copying the last register values into the typed inputs, so node status bits still read TRUE. Nothing tells the PLC that a CAN bus (rather than the bridge) is down unless `bus_state_location` was configured.

Toni's rule stays: unset settings mean the EDS's own values, and the bridge never changes that. So the safer settings are written explicitly by the configurator for new nodes and adapters, and existing configs get a warning with a one-click fix. Nothing is saved to a node's non-volatile memory: every setting here goes into the boot download, in RAM.

## What Changes

- **Configurator: safe settings for what the user adds.**
  - A new node whose EDS has a writable 0x1016 and that gets output PDO entries is saved with `"heartbeat_consumer": true`. If the master sends no heartbeat, `master.heartbeat_ms` is set to 100 in the same undo step.
  - A new node whose EDS has a writable 0x1020 is saved with `"config_check": true`.
  - A new `socketcan` adapter with `configure_link` on is saved with `"restart_ms": 100`.
  - Each value shows in its usual field and can be turned off.
- **Warning for nodes not protected against a bridge stop.**
  - A node with output PDO entries is unprotected when it has neither `heartbeat_consumer` true, nor an EDS 0x1016 entry that already watches the master, nor an RPDO `event_timer_ms` above 0.
  - The bridge logs one warning per such node at load. `canworks-deploy --check` prints it as a warning.
  - The configurator's Problems shows it with **Watch the master heartbeat**, which sets `heartbeat_consumer` (and the master heartbeat when needed).
  - None of these refuses the config.
- **Warning for bus-off without restart.** A `socketcan` adapter that configures the link and has no `restart_ms` gets a Problems warning with **Restart after bus-off (100 ms)**.
- **Bus flag for the PLC.**
  - Status block byte 7 bit 1 is set while any CAN network of the bridge is down or bus-off. Bit 0 is `bridge-failure-hardening`'s unclean-start flag.
  - The generated `canworks_in` sets a new `canworks.bus_ok` from it.
- **PLC inputs while the bridge is lost.**
  - While `canworks.ok` is FALSE, the generated `canworks_in` sets node status bits, node state bytes and the live list words to 0 (FALSE: no node is known to run).
  - The other typed inputs follow the connection's `inputs_on_loss`: `"hold"` (default) keeps the last values, `"zero"` sets them to 0.
  - This applies to the OpenPLC, truST and Other PLC connections, and to the Node-RED connection's value outputs when `add-nodered-blocks` has merged.
- **Docs.** `docs/modbus-bridge.md` "When the bridge fails" (from `bridge-failure-hardening`) gets what each node does in each case and the settings that make it react. `docs/config.md` points to it from `heartbeat_consumer`, `event_timer_ms`, `config_check` and `restart_ms`. `docs/plc-library.md` gets `canworks.bus_ok` and that programs gate outputs on `canworks.ok`.

## Capabilities

### Modified Capabilities

All deltas are ADDED requirements:

- `canopen-node-supervision`: Nodes not protected against a bridge stop (bridge log, deploy check).
- `canopen-configurator`: Safe settings for new nodes and adapters; Problems for unprotected nodes and bus-off without restart.
- `modbus-bridge`: Status block (byte 7 bit 1, the bus flag).
- `modbus-connections` (created by `modbus-connections`): PLC inputs while the bridge is lost; Bus state for the PLC.

## Impact

- **Bridge:** a load-time warning per unprotected node (`config.cpp` / `dcf_gen.cpp`, from the EDS 0x1016 default and the config), and byte 7 bit 1 from each network's bus state (`bridge_host.cpp`).
- **PC tools:**
  - `bridgecheck.py`: the same warning;
  - configurator `app.js`: Add node, new adapter and Problems with their fixes;
  - `openplcmodbus.py` and the PLCopen export's `canworks_in`: status zeroing, `inputs_on_loss`, `canworks.bus_ok`;
  - schema: `inputs_on_loss` on connections;
  - Node-RED flow export when `add-nodered-blocks` has merged.
- **Examples:** `examples/modbus-bridge`, `examples/openplc-modbus` and the virtual plant get `heartbeat_consumer`, `config_check` and `restart_ms` where their EDS allow them, and pass with no new warning.
- **Tests:**
  - configurator page tests: new node, new adapter, both Problems with their fixes and undo;
  - deploy check warning tests;
  - a C++ test for the load warning and byte 7 bit 1 (simulated network with the interface taken down);
  - generated ST tests compiled with STruC++: zeroing on `canworks.ok` FALSE, hold and zero.
- **Order:** apply after `modbus-connections` (connections, `inputs_on_loss`) and `bridge-failure-hardening` (byte 7, the docs section). Rebase over `faster-mailboxes`, `add-nodered-blocks` and `mailboxes-on-demand`, which edit the same configurator page and generator.
- **Hardware:** node 23 on the Linux device:
  - with `heartbeat_consumer` true, `kill -9` of the bridge makes node 23 react per its 0x1029; without it, it keeps running;
  - with `config_check`, a bridge restart takes node 23 over without a reset;
  - taking the CAN interface down sets byte 7 bit 1 and `canworks.bus_ok` FALSE, and bringing it up clears them. slcan reports no bus-off, so bus-off itself is covered by the vcan/C++ tests.
