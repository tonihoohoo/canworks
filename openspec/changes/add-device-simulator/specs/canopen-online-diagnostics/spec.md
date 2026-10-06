## ADDED Requirements

### Requirement: Simulator operations
When the bus is simulated, the diagnostics channel SHALL offer the simulator's live control as `sim_` operations: `sim_status`, `sim_get` and `sim_scenario_list` with the token alone, and the operations that change values, sources, faults or scenarios only with `allow_changes: true`. With a real bus every `sim_` operation SHALL answer `not simulated`. The `status` answer SHALL carry `simulated` (true or false).

#### Scenario: Read-only access
- **WHEN** a client with the token but `allow_changes` false calls `sim_get` and then `sim_fault`
- **THEN** `sim_get` returns the value and `sim_fault` answers `changes not allowed`

#### Scenario: Real bus
- **WHEN** a client calls `sim_status` on a runtime whose config does not simulate
- **THEN** the answer is `not simulated`

### Requirement: Trace on the simulated bus
Bus trace SHALL work on the simulated bus with the same operations, filters and records as on a SocketCAN interface. Time stamps SHALL come from the host's clock when the frame is delivered, and `trace_start` SHALL report the interface as `simulated`.

#### Scenario: Trace a simulated network
- **WHEN** a user starts a trace on a runtime with a simulated config
- **THEN** the trace records the SYNC, PDO, heartbeat and SDO frames of the simulated network, and the trace header says the interface is simulated

### Requirement: Simulator commands in the command-line client
`openplc-canopen-diag` SHALL have `sim` subcommands (`status`, `get`, `set`, `override`, `release`, `source`, `fault`, `clear`, `scenario start|stop|list`) that talk to a plugin's simulated bus with `--runtime` or to a standalone simulator with `--sim HOST[:PORT]`, with the same arguments and output as `openplc-canopen-sim`'s own subcommands.

#### Scenario: Fault from the PC
- **WHEN** a user runs `openplc-canopen-diag sim fault 5 emcy 0x5000 --register 1 --runtime plc.local` against a simulated runtime with `allow_changes`
- **THEN** simulated node 5 sends EMCY 0x5000 and the online view shows it in node 5's EMCY history
