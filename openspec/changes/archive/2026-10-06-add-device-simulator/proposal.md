## Why

Nobody can try the plugin, the configurator, the online view or a PLC program without real CANopen devices on a real bus, and now that the repository is public that is the first wall every new user hits. The repository already runs Lely slaves built from EDS files in its own tests (`test/sensor/sensor_slave`, the LSS, fixed-mapping and config-check slaves), but none of that is installable, configurable or controllable by a user. Commercial commissioning tools simulate a node from its EDS so a project can be built and tested before the hardware arrives; this change brings that to the project, both as a one-switch "run my config on simulated devices" and as a scriptable test bench for PLC programs.

## What Changes

- **New simulator engine**: a simulated CANopen device built from any EDS or DCF (including a parameter backup made with `openplc-canopen-diag backup`), with its own object dictionary, NMT, heartbeat or node guarding, SDO server, PDOs, EMCY, store/restore (0x1010/0x1011), configuration date (0x1020), LSS and program download objects, all as the EDS describes them.
- **Easy start, no setup**:
  - Simulate any mix, with two switches: the network (`adapter.simulate`: real or simulated) and each device (`simulate` per node, with **Simulate all** and **Simulate none** in the configurator). One device, some or all can be simulated, on the real network next to real devices or on a simulated network.
  - A simulated network runs the master against simulated copies of the configured nodes on an in-process virtual bus inside the plugin: no CAN adapter, no vcan, no root, works in the Docker install and on any Linux host. The real adapter settings stay in the file, so switching back is one switch. A node switched off there is absent, as an unplugged device.
  - On the real network, the plugin runs the simulated devices itself on the same interface, so real devices on the wire and the master both see them. A simulated device starts only when its node ID is free on the bus, and powers off if a real device with its node ID shows up.
  - `openplc-canopen-sim canopen/canopen.json` runs every node (or `--nodes 5,7`) of a config as simulated devices on a SocketCAN interface (default `vcan0`, created with `--setup-vcan`), for a plugin on the same host or another master on the bus; `openplc-canopen-sim --eds X.eds --node 5` runs one device.
  - Sensible behaviour with no simulation file at all: devices boot with their EDS (or DCF) values, CiA 401 I/O modules loop outputs back to inputs, CiA 404 measuring devices produce slowly moving values, CiA 402 drives run a drive model.
- **Advanced behaviour** in an optional `canopen/simulation.json` (own JSON Schema, versioned):
  - Per object value sources: constant, sine, triangle, square, sawtooth, ramp, step sequence, random walk and noise, counter, CSV time series playback, and expressions over time and other objects (`lag`, `delay`, `rate_limit`, `if`, bit functions) to model a plant, for example a temperature that follows a heater output with a time constant.
  - Built-in device models: CiA 401 loopback, CiA 404 measuring channels with sensor break, and a CiA 402 drive (power state machine, profile position, profile velocity, homing, cyclic synchronous position and velocity, following error, limit switches, faults).
  - Fault injection: EMCY (once, periodic or on a condition), heartbeat stop, power off and on, self reset, NMT state change, SDO abort or delay rules per object, refusing writes while OPERATIONAL, a TPDO that stops, wrong identity, a device without node ID (LSS).
  - Scenarios: named timelines of steps (set, wait for a condition, fault, expect) started from the CLI, the configurator or at start-up, with an expect step that turns a scenario into a test of the PLC program.
  - Extra devices that are not in the config, for trying scan, LSS commissioning and identity checks.
- **Control while running**: live values, overrides, faults and scenarios from `openplc-canopen-sim` subcommands, from `openplc-canopen-diag sim ...` (both the in-plugin and the standalone simulator) and from a new **Simulation** view in the configurator (live values, sliders and switches for inputs, fault buttons, scenario runner).
- **Test mode**: `openplc-canopen-sim test` runs scenarios, exits non-zero when an expect fails and writes a JUnit XML report, so users can test PLC programs in CI.
- Plugin status, logs, the online view and trace show clearly what is simulated (the network, or which nodes); the deploy tool warns before uploading a config with simulated parts.
- `scripts/install-stock.sh` installs `openplc-canopen-sim` next to the plugin.

## Capabilities

### New Capabilities
- `canopen-device-simulator`: the simulated device itself (built from EDS/DCF, default behaviour per device profile, value sources, device models, fault injection, scenarios and expects, persistence of stored values) and its control protocol.
- `canopen-simulated-bus`: running the plugin's master against any subset of simulated devices, on a simulated network (`adapter.simulate`) or on the real network next to real devices (`simulate` per node), and the standalone `openplc-canopen-sim` runner and test mode on a SocketCAN interface, with the node ID safety checks for all of them.

### Modified Capabilities
- `canopen-config-contract`: `adapter.simulate` and per-node `simulate` in `canopen.json`, and the new `simulation.json` contract with its own schema and version.
- `canopen-online-diagnostics`: simulator operations on the diagnostics channel, simulated flags in status, trace on the virtual bus and of simulated devices on a real network, and `openplc-canopen-diag sim` commands.
- `canopen-configurator`: the network choice, the per-node **Simulated** switch and the Simulation view (values, faults, behaviour editor, scenarios).
- `canopen-deploy`: carries `simulation.json` in the bundle and warns about a config with simulated parts.
- `canopen-stock-install`: installs the `openplc-canopen-sim` binary.

## Impact

- New C++ library `plugin/sim/` (simulator engine on Lely's `BasicSlave`, expression evaluator, device models) linked into the plugin and into the new `openplc-canopen-sim` executable; no new third-party dependency.
- `plugin/src`: virtual bus path next to `can_adapter`, simulated devices on the real interface with the free node ID check and conflict guard, trace capture on the virtual bus, simulator ops in `diag.cpp`, status flags.
- `schema/`: `canopen.v1.schema.json` (`adapter.simulate`, node `simulate`), new `canopen-sim.v1.schema.json`.
- `tools/deploy`: bundle, `--check`, configurator Simulation view, `openplc-canopen-diag sim`; deploy tool version bump.
- `scripts/install-stock.sh`, docs (`docs/simulator.md`, config, configurator, diagnostics, deploy, README), CI (simulator unit tests, sim tests, a vcan run).
- The existing test slaves stay as they are; moving them onto the engine is optional later work.
