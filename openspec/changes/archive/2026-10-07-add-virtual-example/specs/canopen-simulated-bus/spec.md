## MODIFIED Requirements

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

## ADDED Requirements

### Requirement: Fastscan finds only devices without a node ID
A simulated device that has a node ID SHALL NOT answer LSS Fastscan (CiA 305); a device without one SHALL answer it by its 0x1018 identity. The plugin's own slave SHALL behave the same.

#### Scenario: Search on a bus with configured LSS devices
- **WHEN** a simulated network has configured DIO-16 modules with node IDs and serial number 0, and an extra device without a node ID with serial number 7099, and a client runs the LSS search
- **THEN** the search finds the extra device, serial number 7099, without a node ID
