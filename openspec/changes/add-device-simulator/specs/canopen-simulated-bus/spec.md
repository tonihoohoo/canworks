## Purpose
Running the CANopen master against simulated devices: inside the plugin on an in-process virtual bus with one config switch, or as a standalone simulator process on a SocketCAN interface, with a test mode for PLC programs and the safety checks that keep simulated devices off a real machine's bus.

## ADDED Requirements

### Requirement: Simulated bus inside the plugin
When the config's `adapter.simulate` is true, the plugin SHALL open no CAN interface or serial device, change no link and need no privileges for the bus. It SHALL run its master on an in-process virtual bus together with one simulated device per configured node (from that node's EDS, node ID, identity settings and LSS settings) and the extra devices of the simulation file, and SHALL otherwise behave exactly as with a real bus: the same boot, configuration, PDO exchange, status locations, SDO variables, NMT commands and diagnostics. The other adapter fields SHALL be kept and checked as usual, but not used.

#### Scenario: Config switched to simulation
- **WHEN** the ping-pong config with `adapter.simulate: true` is uploaded to a runtime whose host has no CAN interface
- **THEN** the PLC starts, node 2 boots and reaches OPERATIONAL, its status bit is TRUE and the ping-pong values move in the PLC image

#### Scenario: Docker install
- **WHEN** a simulated config runs in the managed Docker install
- **THEN** it works without vcan, extra container capabilities or host changes

#### Scenario: Switching back
- **WHEN** the user sets `adapter.simulate` to false again
- **THEN** the plugin uses the kept `interface` and `bitrate` as before

### Requirement: A simulated bus is always visible
With `adapter.simulate` true, the plugin SHALL log a warning naming the simulated bus at every PLC start, the diagnostics status SHALL say `simulated: true`, the bus state location SHALL report error-active as on a healthy bus, and the configurator, the diagnostics client, the trace and the deploy tool SHALL each say that the bus is simulated.

#### Scenario: Log at start
- **WHEN** the PLC starts with a simulated config
- **THEN** the log has a warning that CANopen runs on simulated devices and no CAN interface is used

### Requirement: Simulated bus timing
On the simulated bus, frames SHALL be delivered in order and without loss, timers (SYNC, heartbeats, event timers, SDO timeouts) SHALL run on the host's monotonic clock as on a real bus, and the bus load figures shown by the trace SHALL be computed for the configured bit rate.

#### Scenario: SYNC period
- **WHEN** a simulated config has `sync_period_us: 10000`
- **THEN** the trace shows SYNC frames 10 ms apart within the host's timer jitter

### Requirement: Standalone simulator on a SocketCAN interface
The `openplc-canopen-sim` command SHALL simulate devices on a SocketCAN interface: every node of a `canopen.json` (with `canopen/simulation.json` next to it, or `--sim FILE`), or one device from `--eds FILE --node ID`, or both. It SHALL use `vcan0` unless `--iface` names another interface, and with `--setup-vcan` SHALL create and bring up a missing vcan interface (which needs root). It SHALL print one line per device when it starts and a line for each NMT state change, power change, fault and scenario result, and SHALL stop all devices cleanly on SIGINT or SIGTERM.

#### Scenario: One command for a project
- **WHEN** a user runs `openplc-canopen-sim canopen/canopen.json` on a host with `vcan0` up
- **THEN** every configured node is simulated on `vcan0` and a plugin configured for `vcan0` on the same host boots all of them

#### Scenario: One device
- **WHEN** a user runs `openplc-canopen-sim --eds drive.eds --node 4`
- **THEN** one device is simulated as node 4 on `vcan0`

#### Scenario: vcan missing
- **WHEN** `vcan0` does not exist and `--setup-vcan` is not given
- **THEN** the command exits with an error that names `--setup-vcan` and the `ip link` commands that create it

### Requirement: Real buses need consent and a free node ID
The standalone simulator SHALL refuse an interface that is not a vcan interface unless `--real-bus` is given. On a real interface it SHALL listen for 1 second before starting and SHALL refuse to start a device whose node ID already sends heartbeats, boot-up messages or SDO answers on the bus, naming the node ID.

#### Scenario: Real interface without consent
- **WHEN** a user runs `openplc-canopen-sim canopen.json --iface can0`
- **THEN** the command refuses and says that `--real-bus` is needed to put simulated devices on a real bus

#### Scenario: Node ID taken
- **WHEN** a user runs the simulator with `--real-bus` on `can0` for node 23 while a real node 23 sends heartbeats
- **THEN** the simulator refuses to start node 23, names it, and starts the other devices

### Requirement: Standalone control channel
The standalone simulator SHALL offer its live control on a TCP port (default 7532) with the same one-JSON-object-per-line framing as the diagnostics channel. It SHALL listen on 127.0.0.1 unless `--bind` names another address; on any other address it SHALL require a token (`--token` or `--token-file`) in the first request. Its subcommands `status`, `get`, `set`, `override`, `release`, `source`, `fault`, `clear`, `scenario start|stop|list` SHALL use this channel.

#### Scenario: Local control
- **WHEN** a simulator runs with default options and a user runs `openplc-canopen-sim set 5 0x7130:1 450`
- **THEN** 0x7130:1 of node 5 reads 450

#### Scenario: Remote bind without token
- **WHEN** a user starts the simulator with `--bind 0.0.0.0` and no token
- **THEN** the simulator refuses to start and says a token is needed

### Requirement: Test mode
`openplc-canopen-sim test` SHALL start the simulation, run the named scenarios (or all scenarios marked `test`) one after another or together as asked, stop when they are done or after `--timeout`, print a result line per scenario, write a JUnit XML report with `--junit FILE`, and exit 0 only when every scenario passed. It SHALL work both with its own devices on a SocketCAN interface and against a plugin's simulated bus through the diagnostics channel (`--runtime`).

#### Scenario: Failing expect
- **WHEN** one of two test scenarios fails an expect
- **THEN** the command prints the failed step, the condition and the value seen, writes both results to the JUnit file and exits 1

#### Scenario: Test against the plugin
- **WHEN** a user runs `openplc-canopen-sim test --runtime plc.local --token-file token --scenario alarm` against a runtime with a simulated config
- **THEN** the scenario runs in the plugin's simulator and its result is reported as for local devices
