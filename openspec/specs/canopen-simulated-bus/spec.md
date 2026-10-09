# canopen-simulated-bus Specification

## Purpose
Running the CANopen master against simulated devices, any subset of them, on a simulated network or on the real network next to real devices: inside the plugin from config switches, or as a standalone simulator process on a SocketCAN interface, with a test mode for PLC programs and the safety checks that keep simulated devices off a real machine's bus.

## Requirements

### Requirement: Simulated network or real network
The config SHALL choose the network with `adapter.simulate`: false (default) runs the master on the real adapter as today; true runs the master on an in-process virtual network, for which the plugin SHALL open no CAN interface or serial device, change no link and need no privileges. The other adapter fields SHALL be kept and checked as usual but not used on a simulated network, so switching back needs only the one field.

#### Scenario: Config switched to a simulated network
- **WHEN** the ping-pong config with `adapter.simulate: true` is uploaded to a runtime whose host has no CAN interface
- **THEN** the PLC starts, node 2 boots and reaches OPERATIONAL, its status bit is TRUE and the ping-pong values move in the PLC image

#### Scenario: Docker install
- **WHEN** a config with a simulated network runs in the managed Docker install
- **THEN** it works without vcan, extra container capabilities or host changes

#### Scenario: Switching back
- **WHEN** the user sets `adapter.simulate` to false again
- **THEN** the plugin uses the kept `interface` and `bitrate` as before

### Requirement: Which devices are simulated
Each node SHALL have an optional `simulate`. On a simulated network a node SHALL be simulated unless its `simulate` is false; such a node SHALL be absent from the network, as an unplugged device would be. On a real network a node SHALL be simulated only when its `simulate` is true. A simulated node SHALL be a simulated device built from that node's EDS, node ID, identity and LSS settings, run by the plugin; the extra devices of the simulation file SHALL be simulated in both cases. Apart from where the device lives, the master SHALL treat a simulated node exactly like a real one: the same boot, configuration, PDO exchange, status locations, SDO variables, NMT commands and diagnostics.

#### Scenario: All devices simulated
- **WHEN** a config with three nodes has `adapter.simulate: true` and no node sets `simulate`
- **THEN** all three nodes are simulated and boot

#### Scenario: One device absent on a simulated network
- **WHEN** a config with `adapter.simulate: true` has node 7 with `simulate: false`
- **THEN** nodes other than 7 boot, node 7's status bit stays FALSE and its boot retries as for a missing device

#### Scenario: One device simulated on a real network
- **WHEN** a config on `can0` has real node 23 and node 5 with `simulate: true`
- **THEN** the master boots real node 23 over the wire and simulated node 5 inside the plugin, both reach OPERATIONAL, and real devices on the wire see node 5's frames

#### Scenario: All devices simulated on a real network
- **WHEN** a config on `can0` sets `simulate: true` on every node
- **THEN** every node is simulated on `can0` and its frames go out on the wire

### Requirement: Simulated devices on a real network need a free node ID
Before it starts a simulated device on a real network, the plugin SHALL listen on the interface for 1 second and SHALL NOT start a simulated device whose node ID sends heartbeats, boot-up messages, EMCY or SDO answers there; it SHALL log an error naming the node ID, leave the node to the real device, and report the node in the diagnostics status as not simulated with `sim_conflict` true. While a simulated device runs on a real network, a heartbeat, boot-up or EMCY with its node ID that it did not send itself SHALL make it power off and log the conflict, so it never competes with a real device.

#### Scenario: Real device already there
- **WHEN** node 23 has `simulate: true` on `can0` and a real node 23 sends heartbeats
- **THEN** the simulated node 23 is not started, the log names the conflict, the master treats the real device as node 23, and the diagnostics status shows node 23 with `simulated` false and `sim_conflict` true

#### Scenario: Real device plugged in later
- **WHEN** a simulated node 5 runs on `can0` and a real device with node ID 5 is plugged in and sends its boot-up
- **THEN** the simulated node 5 powers off and the log names the conflict

### Requirement: Simulation with several networks
In a config with several networks (version 2), `adapter.simulate` and each node's `simulate` SHALL apply to their own network, so one network can be simulated while another runs on its real interface, each with its own trace and `sim_` operations selected by the request's `network`. A simulation file of version 2 SHALL give each network's behaviour in its own section, matched by network name; the plugin SHALL apply each section to the simulated devices of that network only, and a network without a section SHALL run its simulated devices with their default behaviour. Node IDs, extra devices, expressions and scenario conditions in a section SHALL refer to that network only. A version 1 simulation file SHALL keep serving a config with one network; with several networks the plugin SHALL log a warning that a version 1 file is not used and run the simulated devices with their default behaviour, and the deploy tool's check SHALL say the same and name version 2.

#### Scenario: One simulated network next to a real one
- **WHEN** a version 2 config has network `io` on `can0` and network `test` with `adapter.simulate: true`
- **THEN** `io` runs on `can0`, every node of `test` is simulated, and `sim_status` with `network: "test"` lists them

#### Scenario: Per-network simulation file
- **WHEN** a project with networks `io` and `motion` has a version 2 simulation file with a sine on node 5 of `io` and drive settings for node 4 of `motion`
- **THEN** node 5 of `io` follows the sine, node 4 of `motion` uses the drive settings, and a node 5 on `motion`, if there were one, would not get the sine

#### Scenario: Extra device on one network
- **WHEN** the `io` section adds an extra device without a node ID
- **THEN** an LSS scan on `io` finds it and an LSS scan on `motion` does not

#### Scenario: Autostart scenario per network
- **WHEN** the `io` section has a scenario with `"autostart": true`
- **THEN** it starts with the simulation and `sim_scenario_list` with `network: "io"` lists it as running

#### Scenario: Simulation file with two networks
- **WHEN** a project with two networks has a version 1 `simulation.json`
- **THEN** the plugin logs that the file is not used and that version 2 has per-network sections, and the simulated devices run with their defaults

### Requirement: Simulation is always visible
When the network is simulated or any node is simulated, the plugin SHALL log a warning at every PLC start naming the simulated network and the simulated node IDs, the diagnostics status SHALL say `simulated_network` (true or false) and per node `simulated`, a simulated network SHALL report error-active bus state as a healthy bus does, and the configurator, the diagnostics client, the trace and the deploy tool SHALL each say what is simulated.

#### Scenario: Log at start
- **WHEN** the PLC starts with node 5 simulated on `can0`
- **THEN** the log has a warning that node 5 is a simulated device on the real network `can0`

### Requirement: Simulated network timing
On a simulated network, frames SHALL be delivered in order and without loss, timers (SYNC, heartbeats, event timers, SDO timeouts) SHALL run on the host's monotonic clock as on a real bus, and the bus load figures shown by the trace SHALL be computed for the configured bit rate.

#### Scenario: SYNC period
- **WHEN** a simulated config has `sync_period_us: 10000`
- **THEN** the trace shows SYNC frames 10 ms apart within the host's timer jitter

### Requirement: Standalone simulator on a SocketCAN interface
The `canworks-sim` command SHALL simulate devices on a SocketCAN interface: the nodes of a `canworks.json` (all of them, or only those `--nodes 5,7` lists; with `canworks/simulation.json` next to it, or `--sim FILE`), or one device from `--eds FILE --node ID`, or both. It SHALL use `vcan0` unless `--iface` names another interface, and with `--setup-vcan` SHALL create and bring up a missing vcan interface (which needs root). It SHALL print one line per device when it starts and a line for each NMT state change, power change, fault and scenario result, and SHALL stop all devices cleanly on SIGINT or SIGTERM.

#### Scenario: One command for a project
- **WHEN** a user runs `canworks-sim canworks/canworks.json` on a host with `vcan0` up
- **THEN** every configured node is simulated on `vcan0` and a plugin configured for `vcan0` on the same host boots all of them

#### Scenario: Some nodes of a config
- **WHEN** a user runs `canworks-sim canworks/canworks.json --nodes 5` for a config with nodes 5 and 23
- **THEN** only node 5 is simulated

#### Scenario: One device
- **WHEN** a user runs `canworks-sim --eds drive.eds --node 4`
- **THEN** one device is simulated as node 4 on `vcan0`

#### Scenario: vcan missing
- **WHEN** `vcan0` does not exist and `--setup-vcan` is not given
- **THEN** the command exits with an error that names `--setup-vcan` and the `ip link` commands that create it

### Requirement: Real buses need consent and a free node ID
The standalone simulator SHALL refuse an interface that is not a vcan interface unless `--real-bus` is given. On a real interface it SHALL apply the same free node ID check and conflict guard as simulated devices in the plugin on a real network.

#### Scenario: Real interface without consent
- **WHEN** a user runs `canworks-sim canworks.json --iface can0`
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
- **WHEN** a simulator runs with default options and a user runs `canworks-sim set 5 0x7130:1 450`
- **THEN** 0x7130:1 of node 5 reads 450

#### Scenario: Remote bind without token
- **WHEN** a user starts the simulator with `--bind 0.0.0.0` and no token
- **THEN** the simulator refuses to start and says a token is needed

#### Scenario: Remote control is encrypted
- **WHEN** a simulator runs with `--bind 0.0.0.0 --token-file token` and a user runs `canworks-diag sim --sim host status --token-file token`
- **THEN** the client connects over TLS, logs in without sending the token, and prints the status

### Requirement: Test mode
`canworks-sim test` SHALL start the simulation, run the named scenarios (or all scenarios marked `test`) one after another or together as asked, stop when they are done or after `--timeout`, print a result line per scenario, write a JUnit XML report with `--junit FILE`, and exit 0 only when every scenario passed. It SHALL work both with its own devices on a SocketCAN interface and against the plugin's simulated devices through the diagnostics channel (`--runtime`).

#### Scenario: Failing expect
- **WHEN** one of two test scenarios fails an expect
- **THEN** the command prints the failed step, the condition and the value seen, writes both results to the JUnit file and exits 1

#### Scenario: Test against the plugin
- **WHEN** a user runs `canworks-sim test --runtime plc.local --token-file token --scenario alarm` against a runtime that simulates node 5
- **THEN** the scenario runs in the plugin's simulator and its result is reported as for local devices

### Requirement: Simulation forced by the runtime environment
When the plugin's environment has `CANWORKS_FORCE_SIMULATE` set to exactly `1`, the plugin SHALL run every network of the loaded config as a simulated network, whatever its `adapter.simulate`, and SHALL apply the simulated-network rules to its nodes (simulated unless `simulate` is false). It SHALL open no CAN interface or serial device and change no link. Any other value, or no value, SHALL leave the config in charge. The config file itself SHALL NOT be changed. The plugin SHALL log at every PLC start a warning, for each network it forced, that simulation is forced by the runtime environment, and the diagnostics status SHALL report `simulation_forced: true` next to `simulated_network`. `canworks-diag status` and the configurator's online view SHALL say so when the status reports it.

#### Scenario: Real adapter config in the simulator runtime
- **WHEN** the ping-pong config with `adapter.interface: can0` and `adapter.simulate` unset runs with `CANWORKS_FORCE_SIMULATE=1` on a host without `can0`
- **THEN** node 2 boots on the simulated network, no interface is opened, the log has the forced-simulation warning, and the status reports `simulated_network: true` and `simulation_forced: true`

#### Scenario: Absent node stays absent
- **WHEN** a config has node 7 with `simulate: false` and simulation is forced
- **THEN** node 7 is absent and its boot retries, as on any simulated network

#### Scenario: Variable not set
- **WHEN** `CANWORKS_FORCE_SIMULATE` is unset or `0`
- **THEN** the plugin uses `adapter.simulate` from the config as before and the status reports `simulation_forced: false`

### Requirement: Fastscan finds only devices without a node ID
A simulated device that has a node ID SHALL NOT answer LSS Fastscan (CiA 305); a device without one SHALL answer it by its 0x1018 identity. The plugin's own slave SHALL behave the same.

#### Scenario: Search on a bus with configured LSS devices
- **WHEN** a simulated network has configured DIO-16 modules with node IDs and serial number 0, and an extra device without a node ID with serial number 7099, and a client runs the LSS search
- **THEN** the search finds the extra device, serial number 7099, without a node ID
