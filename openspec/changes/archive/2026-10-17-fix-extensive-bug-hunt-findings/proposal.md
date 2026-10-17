# Proposal: fix-extensive-bug-hunt-findings

## Why

An extensive bug hunt of main 7dba547 (2026-10-17) covered the CANopen runtime, J1939 and plain CAN, the PLC block library, the config loader with EDS and DCF, the PC tools, the simulator, every network-facing surface, the configurator in a real browser, and known vulnerabilities in third-party components. It found 8 high, 29 medium and 49 low issues. Nothing crashes, no XSS, no control without a login, no reachable high-impact CVE, and every earlier fix (2026-10-09 audit, 2026-10-09 GUI hunt, 2026-10-15 critical hunt) is still in place.

The real problems are again wrong or stale values on the bus:
- **Configs that harm a device.** Both the configurator and the plugin accept a startup SDO on 0x1010/0x1011, so the device's NVM is saved (or reset to defaults) at every boot. Both accept PDOs on SYNC, TIME, SDO, heartbeat, LSS and EMCY identifiers, so a typo can turn PLC outputs into SDO requests.
- **Stops and holds that come undone.** Routed gateway outputs go to 0 after the field bus restarts. `stop_all_nodes`, `CO_NETWORK_STOP` and the gateway's "hold" are lifted by a link bounce, a node reset or an upper master reset.
- **Plain CAN and J1939 outside the safety gate.** Program cyclic jobs and queued frames keep sending with the outputs gate or scan watchdog closed, J1939-only and plain-CAN-only projects have no watchdog, and receive status and valid bits stay TRUE with frozen values while the interface is gone.
- **PC tools on a live bus.** `replay --loop` floods the bus, and the adapter's `--force` guard misses nodes another master runs.
- **Simulator.** A plain CAN scenario `repeat` with no wait spins a core.

Details, evidence and the full finding table are in design.md.

## What Changes

**Config contract and EDS**
- A PDO COB-ID or the master's TIME COB-ID on a restricted CAN-ID (SYNC, TIME, NMT, SDO, heartbeat, LSS) or on a configured node's EMCY identifier is refused, in the PC tools and the plugin.
- A startup SDO to 0x1010 or 0x1011 is refused with a pointer to `store_configuration`/`restore_configuration`; a write SDO variable on them needs a `trigger_location`.
- Version 1 configs get the IEC location overlap check on the PC side.
- JSON integers above 2^53 in 64-bit fields are refused on both sides ("write it as a string").
- `error_behavior` values written as strings are range-checked; number strings with a trailing newline, `"-0"` on unsigned types and NaN/Infinity are refused by the PC tools as by the plugin.
- `auto` PDO COB-IDs are clash-checked after they are resolved.
- The EDS check on the PC refuses what the plugin's EDS load refuses (bare `$NODEID` is rewritten to `$NODEID+0`, unsupported data types), reads an empty `DefaultValue` as 0 as the plugin does, converts integer defaults on REAL objects, and caps `SupportedObjects`.
- The master heartbeat consumer time is never shorter than `heartbeat_timeout_ms`.

**CANopen runtime and gateway**
- A gateway pulls every route down at network start, so a field bus restart never sends 0.
- `on_upper_loss: "hold"` forwards only values the upper master wrote; a reset of the gateway or a slave session restart no longer forwards EDS defaults.
- A `stop_all_nodes` master stop lasts for the PLC run.
- `CO_NETWORK_STOP` survives node resets and the gateway's release; the gateway's `stop_nodes` hold is kept the same way on every path (command byte, reset, operator, CiA 309-3).
- A held node that boots OPERATIONAL is not set up as running.
- A scan watchdog trip lasts until the scan moves again, not until a session ends.

**Plain CAN, J1939 and blocks**
- Program cyclic jobs pause and queued program frames are dropped while the outputs gate is closed.
- A scan watchdog also runs for projects with only J1939 or plain CAN networks.
- Receive status and valid bits go FALSE when the interface is gone, on plain CAN and J1939.
- `on_change` messages with a trigger record a baseline at start instead of waiting for the first trigger.
- Signed J1939 signals are not checked for "not available"; unsigned signals use the J1939-71 ranges; the PC simulator follows the same rule.
- A global Request of a PDU1 PGN is answered to global, in the plugin and the simulator; a Request answer must be addressed to us or global.
- Extended-ID program frames are checked against 29-bit PDO COB-IDs on CANopen networks.
- The ST call generator refuses big-endian signals.

**PC tools**
- `replay --loop` waits between loops and limits the rate across loops; trace readers honour ASC `base dec` and relative timestamps, read TRC 1.0 correctly, refuse unknown layouts, and report damaged files as format errors.
- On an adapter, SDO writes, non-start NMT and restores need `--force` when another master is seen.
- The PDO test leaves out a PDO whose mapping cannot be fully read.
- `restore --hold-preop` on an adapter starts the node again only if it was OPERATIONAL.
- `--into-project` copies DBC and device-notes files and, with `--force`, keeps the old folder as a backup.
- `gs_usb:N` numbers adapters the same way when listing and opening.
- Smaller fixes: per-user adapter lock folder, `notes skeleton -o` refuses an existing file, dropped trace frames are reported, pcapng without a CAN interface is refused, SDO upload size mismatch aborts.

**Simulator**
- A plain CAN scenario pass that never waits runs once per tick; `repeat` without `count` repeats forever on both network types.
- SDO abort and refuse-write faults apply to SDO access of PDO-mapped objects.
- `sim_set` on a powered-off device is refused.
- Expression spellings and semantics are the same in the PC check and the plugin, and the configurator's offline expression check works.
- A stored LSS node ID is checked against the node IDs seen on a real bus, and the guard follows a new LSS ID.
- NMT reset node resets the CiA 402 drive model; CSV sources seek instead of scanning; the control socket handles a bounded number of lines per loop.

**Network surfaces and supply chain**
- The Modbus bridge caps its request buffer.
- The remote link closes idle unpaired connections, counts failed pairings per address, and rate-limits the `manage` login; the PC forwarders cap concurrent local connections.
- `zeroconf>=0.149.16` and `libusb>=1.0.30`; `requires-python >= 3.10`.
- The bridge builds against the pinned runtime release with a checked archive hash.
- Workflows get `permissions: contents: read`, actions are pinned by SHA, Dependabot keeps the action pins current, and the repo gets a SECURITY.md.

**Configurator**
- A raw signal with an empty or invalid length gets a field error, not a 500.
- PDO links and heartbeat watches follow a node ID change; removing a node names and offers to remove what uses it; renaming or removing a network updates the Modbus bridge live lists.
- Smaller fixes: Commission tree click error, explicit defaults shown by name, PDO-link problem wording, a missing HOME, Plain CAN trace and Frame lab controls, disabled-reason and target size, a quiet status poll while the runtime is unreachable.

**Exports**
- The DBC export uses the EDS EMCY COB-ID, and the DCF export runs the CiA 306 check only on lines it wrote.

## Capabilities

### New Capabilities
None.

### Modified Capabilities
- `canopen-config-contract`: restricted IDs, NVM objects, 64-bit numbers, number strings, v1 overlaps, auto clash check, heartbeat consumer time.
- `canopen-master-bringup`: EDS parity between the PC check and the plugin.
- `canopen-gateway`: route values at start, hold on upper loss.
- `canopen-plc-nmt`: master stop and network stop persistence, gateway hold on every path.
- `canopen-pdo-io`: scan watchdog trip, program frames and the outputs gate, watchdog for J1939/plain CAN.
- `can-plc-frames`: cyclic jobs while the gate is closed, extended-ID ownership.
- `can-raw-messages`: receive timeouts while the link is down, on-change baseline.
- `j1939-ecu`: valid bits on bus loss, not-available rule, Request answers.
- `j1939-pc-tools`: ST call generator and big-endian signals.
- `canopen-device-simulator`: scenario passes, SDO faults on mapped objects, set while off, expressions, stored LSS IDs, drive reset.
- `canopen-local-bus`: other-master guard, adapter numbering, lock folder.
- `canopen-bus-trace`: replay and trace file dialects, damaged files, dropped frames.
- `canopen-device-parameters`: PDO test layout, restore with hold.
- `canopen-deploy`: `--into-project` files.
- `canopen-device-notes`: skeleton overwrite.
- `modbus-bridge`: request buffer cap, pinned runtime build.
- `remote-link`: unpaired timeout, failure count per address, manage rate limit.
- `canopen-cia309-gateway`: forwarder connection cap.
- `canopen-configurator`: raw signal length, node and network renames, smaller UI fixes.
- `canopen-pc-install`: dependency floors.
- `canopen-ci`: workflow permissions, pinned actions, security policy.
- `canopen-dbc-export`, `canopen-dcf-export`: export fixes.

## Impact

- Plugin: `can/config.cpp`, `canopen/eds_check.cpp`, `canopen/dcf_gen.cpp`, `canopen/network.cpp`/`.h`, `canopen/network_plc.cpp`, `canopen/network_diag.cpp`, `canopen/plc_slave.cpp`, `canopen/run_state.h`, `can/engine.cpp`, `can/raw/plc_frames.cpp`, `can/raw/raw_io.cpp`, `can/raw/engine.cpp`, `can/raw/raw_runtime.cpp`, `j1939/j1939_network.cpp`, `j1939/j1939_signal.h`, `canopen/sim/*`, `tools/sim/control.cpp`, `tools/sim/sim_run.cpp`, `bridge/modbus_server.cpp`.
- PC tools: `contract.py`, `edslint.py`, `eds.py`, `links.py`, `cia306.py`, `raw/contract.py`, `raw/replay.py`, `bustrace/formats.py`, `bustrace/model.py`, `localbus/client.py`, `localbus/adapter.py`, `localbus/sdo.py`, `pdotest.py`, `parameters.py`, `project.py`, `cli.py`, `diag.py`, `simfile.py`, `j1939/sim.py`, `j1939/stcall.py`, `link/device.py`, `dbcexport.py`, `dcfexport.py`, `configurator/*` (server, simulation, app.js, tree.js, bridge.js, trace.js), the schemas, `pyproject.toml`.
- Repo: `scripts/install-bridge.sh`, `.github/workflows/*`, `.github/dependabot.yml`, `SECURITY.md`.
- Breaking (clean cut, nothing is in real use): configs with startup writes to 0x1010/0x1011, PDOs on restricted IDs, JSON integers above 2^53 in 64-bit fields, or number strings with whitespace are refused; Python 3.8 and 3.9 are no longer supported by the PC tools; J1939 signed signals at -1/-2 now read as valid.
- Docs: `docs/config.md` (restricted IDs, NVM, watchdog for J1939/plain CAN, 64-bit numbers), `docs/simulation.md`, `docs/trace.md`, the J1939 page, README where user-visible.
