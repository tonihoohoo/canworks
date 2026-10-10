# Proposal: fix-security-audit-findings

## Why

A code audit of main looked for security holes and for bugs that could disturb a CAN bus or the PLC. It covered the runtime plugin, the Modbus TCP bridge, the diagnostics channel, the simulator and the PC tools. It found 9 high, 21 medium and about 15 low issues. None of them lets a stranger run code on the PLC, and the diagnostics login, the configurator's HTTP guards and the Modbus request parser held up well.

The findings fall into five groups:
- **Inputs that crash or exhaust a process.**
  - A raw CAN location outside the I/O image crashes the runtime.
  - A deeply nested simulator expression overflows the stack.
  - A Modbus client that never reads its replies grows the bridge's memory without limit.
  - A diagnostics client that has not logged in can grow the runtime's memory during the login backoff.
- **Outputs that are wrong or stale on the bus.**
  - Event-driven outputs are not sent again after a device reboots.
  - The first SYNC after a node recovers carries pre-outage values.
  - Nothing reaches the devices when the PLC stops or its scan hangs.
  - A failed on-change send is recorded as sent.
- **Open or loose guards.**
  - The Modbus bridge lets every host write outputs and send NMT when `writers` is left out.
  - Diagnostics SDO writes and NMT do not need `force` on a running node.
  - A looping replay gets around the frame-rate limit.
  - Simulator "power on" brings back a node that a real device already holds.
  - The configurator's lone-device sweep skips the CLI's guards.
- **Silent failures.**
  - The editor hook drops every version 2 config, so the PLC runs with CAN off.
  - A node with no heartbeat and no guarding is never seen as lost.
- **Concurrency.** The PLC CAN frame blocks are not safe when two PLC tasks use them at once.

The full list with evidence is in design.md.

## What Changes

**Runtime plugin**
- Every raw CAN location is checked against the I/O image, as CANopen and J1939 locations already are.
- Byte-address checks no longer overflow.
- When a node comes back up or the outputs gate opens again, the master writes the current outputs to the node and sends its event-driven PDOs once.
- New master option `on_plc_stop`:
  - `"preop"` (default): every node gets ENTER PRE-OPERATIONAL before the network closes.
  - `"stop"`: NMT STOP.
  - `"keep"`: today's behaviour.
- New master option `scan_watchdog_ms` (default 1000, 0 off): when the PLC scan stops advancing, outputs stop until it advances again.
- A node with no heartbeat and no guarding is refused at config load unless the config says `"heartbeat_ms": 0` on purpose, which then logs a warning.
- A failed on-change send (raw and J1939) is retried instead of being recorded as sent.
- PLC SDO transfers to a node that keeps failing its boot end with `ERROR_ID` 3 instead of waiting forever.
- The PLC CAN frame blocks claim slots atomically and work from several PLC tasks.
- `dcfgen` and the EDS lint get a time limit and run isolated from the current directory.
- Smaller items:
  - interface names are checked;
  - the bus thread drops real-time priority while shutting down;
  - the bus-info read is bounded;
  - J1939 Request replies are rate-limited and Cannot Claim gets its random delay.

**Diagnostics channel**
- The request-line limit applies before login, also during the login backoff.
- The large line limit applies only to `put_config`, and line scanning is linear.
- A looping replay is rate-checked as a whole and at run time.
- SDO writes, NMT commands and the network scan need `force` while the target or any node is OPERATIONAL.
- The owned-identifier guard covers 29-bit COB-IDs, a slave's own PDO COB-IDs and the master's SDO server.
- Bit rate detection has a total time limit and a `detect_bitrate_stop` operation, and always restores the configured bit rate.
- Smaller items:
  - per-frame log lines are rate-limited;
  - the login time limit is shorter;
  - the failed-login records are pruned.

**Modbus TCP bridge**
- `writers` is required. An open bridge must say so with `["0.0.0.0/0", "::/0"]`.
- Each client's pending replies are capped. The bridge stops reading from a client that does not read its replies.
- The idle timer counts only complete requests, a partial request times out, there is a per-address connection limit, and a writer can take the slot of a reader when all slots are full.
- With `on_client_loss: "stop"`, the output image is cleared on entering outputs off, so a later write cannot bring back pre-loss values.
- An allowlist entry that fails to parse stops the bridge from starting.
- The systemd unit gets a memory limit.

**Simulator**
- Expressions have a nesting and length limit.
- A node found taken on the real bus stays off until the session restarts, whatever `power on` or `clear` says.
- Extra devices from `simulation.json` get the same free node ID check as config nodes.
- CSV sources only read regular files under the config folder, with size and line limits.
- `delay()` handles NaN delays and time going backwards, and keeps a bounded history.
- A `repeat` that loops without waiting yields until the next tick.
- The standalone simulator's control socket requires `hello` before any other request and closes on a line that is not JSON.
- `CANWORKS_FORCE_SIMULATE` warns about values other than `1`.
- Small leak and undefined-behaviour fixes.

**PC tools**
- The editor hook accepts version 2 configs.
- The configurator's lone-device sweep applies the same guards as the CLI.
- The configurator retries a timed-out request only for read-only operations.
- `canworks-deploy` leaves a PLC that was stopped before the upload stopped, unless `--start` is given.
- On Windows, editor paths with cmd.exe special characters are refused.
- The local runtime refuses a changed certificate unless it just created the container itself, and no longer prints the password.
- The configurator's start URL carries a one-time code instead of the session token.

## Capabilities

### New Capabilities
None.

### Modified Capabilities
- `can-raw-messages`: location bounds and on-change retry.
- `can-plc-frames`: blocks safe across PLC tasks.
- `canopen-pdo-io`: outputs re-sent when a node comes up or the gate opens; scan watchdog.
- `canopen-node-supervision`: refuse unsupervised nodes; outputs on PLC stop.
- `canopen-plc-sdo`: bounded wait for a node that fails its boot.
- `canopen-master-bringup`: time limit and isolation for dcfgen and the lint; interface name check.
- `canopen-online-diagnostics`: pre-login limits, replay loop rate, `force` for SDO write, NMT and scan on a running network, complete owned-identifier guard, bounded bit rate detection.
- `modbus-bridge`: required writers, bounded replies, connection limits, watchdog stop clears the image.
- `j1939-ecu`: on-change retry, rate-limited Request replies, Cannot Claim delay.
- `canopen-device-simulator`: expression limits, taken node IDs stay off, CSV file rules, `delay()` and `repeat` limits, control socket hello.
- `canopen-editor-upload`: version 2 configs.
- `canopen-configurator`: lone-device guards, no retry of changes, one-time start code.
- `canopen-deploy`: keep a stopped PLC stopped.
- `canopen-local-runtime`: certificate change refused, no password on screen.
- `canopen-ci`: CI time kept.

## Impact

- **Plugin:**
  - `plugin/src/can/` (config, diag, frame_tx, raw/*, image_io, plugin);
  - `plugin/src/canopen/` (network, network_plc, bus, dcf_gen, eds_lint, sim/*);
  - `plugin/src/j1939/`;
  - `plugin/src/bridge/`.
- **Standalone simulator:** `tools/sim/control.cpp`.
- **PC tools:**
  - `tools/editor-hook/canworks_hook/snapshot.py`;
  - `tools/deploy/canworks/` (configurator server and online, cli, runtime, localruntime, editorproject, contract);
  - `scripts/install-bridge.sh`.
- **Config contract:**
  - new master keys `on_plc_stop` and `scan_watchdog_ms`;
  - `bridge.writers` becomes required;
  - an unsupervised node is refused.

  These are breaking changes to configs. The project is not in real use, so there is no compatibility layer. The bench template project needs `heartbeat_ms` if its node lacks one.
- **Docs:** `docs/config.md`, `docs/diagnostics.md`, `docs/modbus-bridge.md`, `docs/simulator.md`, `docs/deploy.md`, README where a listed behaviour changes.
- **Version:** PC tools minor version bump.
