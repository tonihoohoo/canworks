## ADDED Requirements

### Requirement: Simulation forced by the runtime environment
When the plugin's environment has `CANOPEN_FORCE_SIMULATE` set to exactly `1`, the plugin SHALL run every network of the loaded config as a simulated network, whatever its `adapter.simulate`, and SHALL apply the simulated-network rules to its nodes (simulated unless `simulate` is false). It SHALL open no CAN interface or serial device and change no link. Any other value, or no value, SHALL leave the config in charge. The config file itself SHALL NOT be changed. The plugin SHALL log at every PLC start a warning, for each network it forced, that simulation is forced by the runtime environment, and the diagnostics status SHALL report `simulation_forced: true` next to `simulated_network`. `openplc-canopen-diag status` and the configurator's online view SHALL say so when the status reports it.

#### Scenario: Real adapter config in the simulator runtime
- **WHEN** the ping-pong config with `adapter.interface: can0` and `adapter.simulate` unset runs with `CANOPEN_FORCE_SIMULATE=1` on a host without `can0`
- **THEN** node 2 boots on the simulated network, no interface is opened, the log has the forced-simulation warning, and the status reports `simulated_network: true` and `simulation_forced: true`

#### Scenario: Absent node stays absent
- **WHEN** a config has node 7 with `simulate: false` and simulation is forced
- **THEN** node 7 is absent and its boot retries, as on any simulated network

#### Scenario: Variable not set
- **WHEN** `CANOPEN_FORCE_SIMULATE` is unset or `0`
- **THEN** the plugin uses `adapter.simulate` from the config as before and the status reports `simulation_forced: false`
