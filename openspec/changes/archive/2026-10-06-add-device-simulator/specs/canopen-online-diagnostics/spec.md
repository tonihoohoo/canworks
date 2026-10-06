## ADDED Requirements

### Requirement: Simulator operations
When the plugin simulates at least one device, the diagnostics channel SHALL offer the simulator's live control for those devices as `sim_` operations: `sim_status`, `sim_get` and `sim_scenario_list` with the token alone, and the operations that change values, sources, faults or scenarios only with `allow_changes: true`. When the plugin simulates no device every `sim_` operation SHALL answer `nothing simulated`, and an operation naming a node that is not simulated SHALL answer `node N is not simulated`. The `status` answer SHALL carry `simulated_network` and, per node, `simulated`.

#### Scenario: Read-only access
- **WHEN** a client with the token but `allow_changes` false calls `sim_get` and then `sim_fault`
- **THEN** `sim_get` returns the value and `sim_fault` answers `changes not allowed`

#### Scenario: Nothing simulated
- **WHEN** a client calls `sim_status` on a runtime whose config simulates nothing
- **THEN** the answer is `nothing simulated`

#### Scenario: Mixed network
- **WHEN** node 5 is simulated and node 23 is real on `can0`, and a client calls `sim_fault` for node 23
- **THEN** the answer is `node 23 is not simulated`, and `status` shows node 5 with `simulated: true` and node 23 with `simulated: false`

### Requirement: Trace with simulated devices
Bus trace SHALL work on a simulated network with the same operations, filters and records as on a SocketCAN interface, with time stamps from the host's clock when the frame is delivered and the interface reported as `simulated`. On a real network the trace SHALL also record the frames of devices the plugin simulates there.

#### Scenario: Trace a simulated network
- **WHEN** a user starts a trace on a runtime with a simulated network
- **THEN** the trace records the SYNC, PDO, heartbeat and SDO frames of the simulated network, and the trace header says the interface is simulated

#### Scenario: Trace a mixed network
- **WHEN** node 5 is simulated on `can0` next to real node 23 and a user traces `can0`
- **THEN** the trace has the frames of both nodes

### Requirement: Simulator commands in the command-line client
`openplc-canopen-diag` SHALL have `sim` subcommands (`status`, `get`, `set`, `override`, `release`, `source`, `fault`, `clear`, `scenario start|stop|list`) that talk to the plugin's simulated devices with `--runtime` or to a standalone simulator with `--sim HOST[:PORT]`, with the same arguments and output as `openplc-canopen-sim`'s own subcommands.

#### Scenario: Fault from the PC
- **WHEN** a user runs `openplc-canopen-diag sim fault 5 emcy 0x5000 --register 1 --runtime plc.local` against a runtime that simulates node 5, with `allow_changes`
- **THEN** simulated node 5 sends EMCY 0x5000 and the online view shows it in node 5's EMCY history
