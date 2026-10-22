## MODIFIED Requirements

### Requirement: Standalone simulator on a SocketCAN interface
The `canworks-canopen-sim` command SHALL simulate devices on a SocketCAN interface: the nodes of a `canworks.json` (all of them, or only those `--nodes 5,7` lists; with `canworks/simulation.json` next to it, or `--sim FILE`), or one device from `--eds FILE --node ID`, or both. It SHALL use `vcan0` unless `--iface` names another interface, and with `--setup-vcan` SHALL create and bring up a missing vcan interface (which needs root). It SHALL print one line per device when it starts and a line for each NMT state change, power change, fault and scenario result, and SHALL stop all devices cleanly on SIGINT or SIGTERM.

#### Scenario: One command for a project
- **WHEN** a user runs `canworks-canopen-sim canworks/canworks.json` on a host with `vcan0` up
- **THEN** every configured node is simulated on `vcan0` and a plugin configured for `vcan0` on the same host boots all of them

#### Scenario: Some nodes of a config
- **WHEN** a user runs `canworks-canopen-sim canworks/canworks.json --nodes 5` for a config with nodes 5 and 23
- **THEN** only node 5 is simulated

#### Scenario: One device
- **WHEN** a user runs `canworks-canopen-sim --eds drive.eds --node 4`
- **THEN** one device is simulated as node 4 on `vcan0`

#### Scenario: vcan missing
- **WHEN** `vcan0` does not exist and `--setup-vcan` is not given
- **THEN** the command exits with an error that names `--setup-vcan` and the `ip link` commands that create it

### Requirement: Real buses need consent and a free node ID
The standalone simulator SHALL refuse an interface that is not a vcan interface unless `--real-bus` is given. On a real interface it SHALL apply the same free node ID check and conflict guard as simulated devices in the plugin on a real network.

#### Scenario: Real interface without consent
- **WHEN** a user runs `canworks-canopen-sim canworks.json --iface can0`
- **THEN** the command refuses and says that `--real-bus` is needed to put simulated devices on a real bus

#### Scenario: Node ID taken
- **WHEN** a user runs the simulator with `--real-bus` on `can0` for node 23 while a real node 23 sends heartbeats
- **THEN** the simulator refuses to start node 23, names it, and starts the other devices

#### Scenario: Next to the plugin on the same interface
- **WHEN** the simulator runs with `--real-bus` on `can0` on the runtime host for node 40, and the plugin uses `can0`
- **THEN** the plugin and the real devices on the wire both see node 40

#### Scenario: Conflict while running
- **WHEN** a real device with the simulated device's node ID sends a heartbeat on the bus
- **THEN** the simulated device powers off and the simulator prints the conflict

### Requirement: Standalone control channel
The standalone simulator SHALL offer its live control on a TCP port (default 7532) with the same one-JSON-object-per-line framing as the diagnostics channel. It SHALL listen on 127.0.0.1 unless `--bind` names another address; on any other address it SHALL require a token (`--token` or `--token-file`). With a token, the channel SHALL use the same TLS and SCRAM-SHA-256 login as the plugin's diagnostics channel, with a verifier the simulator computes from the token at start, and SHALL refuse plain connections with "this simulator needs an encrypted connection". Without a token it SHALL stay plain. Its subcommands `status`, `get`, `set`, `override`, `release`, `source`, `fault`, `clear`, `scenario start|stop|list` SHALL use this channel.

#### Scenario: Local control
- **WHEN** a simulator runs with default options and a user runs `canworks-canopen-sim set 5 0x7130:1 450`
- **THEN** 0x7130:1 of node 5 reads 450

#### Scenario: Remote bind without token
- **WHEN** a user starts the simulator with `--bind 0.0.0.0` and no token
- **THEN** the simulator refuses to start and says a token is needed

#### Scenario: Remote control is encrypted
- **WHEN** a simulator runs with `--bind 0.0.0.0 --token-file token` and a user runs `canworks-diag sim --sim host status --token-file token`
- **THEN** the client connects over TLS, logs in without sending the token, and prints the status

### Requirement: Test mode
`canworks-canopen-sim test` SHALL start the simulation, run the named scenarios (or all scenarios marked `test`) one after another or together as asked, stop when they are done or after `--timeout`, print a result line per scenario, write a JUnit XML report with `--junit FILE`, and exit 0 only when every scenario passed. It SHALL work both with its own devices on a SocketCAN interface and against the plugin's simulated devices through the diagnostics channel (`--runtime`).

#### Scenario: Failing expect
- **WHEN** one of two test scenarios fails an expect
- **THEN** the command prints the failed step, the condition and the value seen, writes both results to the JUnit file and exits 1

#### Scenario: Test against the plugin
- **WHEN** a user runs `canworks-canopen-sim test --runtime plc.local --token-file token --scenario alarm` against a runtime that simulates node 5
- **THEN** the scenario runs in the plugin's simulator and its result is reported as for local devices
