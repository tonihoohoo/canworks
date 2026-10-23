## MODIFIED Requirements

### Requirement: Settings and environment names
The PC tools SHALL keep per-user settings in a folder named `canworks` in the operating system's settings location. Every environment variable, CMake option or cache variable and Docker build argument that the bridge, the simulator, the PC tools, the install script, the build or the tests read SHALL have the prefix `CANWORKS_`; none SHALL have the prefix `CANOPEN_` or `OPENPLC_CANOPEN_`. Names only code sees (header guards, the C SDO API `CANOPEN_PLC_*`, Python constants) are not settings and MAY keep a CANopen name.

#### Scenario: Token from the environment
- **WHEN** `CANWORKS_TOKEN` is set and the user runs `canworks-diag status`
- **THEN** the client uses that token

#### Scenario: Slave state folder
- **WHEN** the bridge runs a slave network with `CANWORKS_STATE_DIR=/tmp/state`
- **THEN** a store to 0x1010 writes the state file under `/tmp/state`, and `CANOPEN_STATE_DIR` has no effect

#### Scenario: Build without tests
- **WHEN** a user configures the build with `-DCANWORKS_BUILD_TESTS=OFF`
- **THEN** `canopen_check`, the tests and the ping-pong slave are not built

### Requirement: Simulator names
Each simulator command SHALL name the protocol it simulates, and no command that is not a device simulator SHALL carry `sim` in its name. The CANopen device simulator binary SHALL be `canworks-canopen-sim` (it also plays the simulation file's plain CAN devices), the J1939 ECU simulator command SHALL be `canworks-j1939-sim`, the switch that forces simulation SHALL be `CANWORKS_FORCE_SIMULATE`, the local runtime command SHALL be `canworks-local-runtime`, its image SHALL be `ghcr.io/tonihoohoo/canworks-local-runtime`, and its container SHALL be `canworks-local-runtime`. The simulation file schemas keep their names (`canworks-sim.v1`, `canworks-sim.v2`), because both the bridge's simulated devices and `canworks-canopen-sim` read that file.

#### Scenario: Local runtime start
- **WHEN** a user runs `canworks-local-runtime start`
- **THEN** a container named `canworks-local-runtime` runs the image `ghcr.io/tonihoohoo/canworks-local-runtime` at the tools' version

#### Scenario: Old simulator names gone
- **WHEN** a user installs the PC tools and the bridge of this release into a fresh environment and runs `canworks-sim` or `canworks-sim-runtime`
- **THEN** the shell reports that the command is not found

### Requirement: One simulation overview
`docs/simulator.md` SHALL be titled "Simulation" and SHALL open with a table that names, for each thing a user may want to simulate, the tool or setting, the protocols it covers, where it runs and its doc. Below the table the page SHALL say why CANopen and J1939 have separate simulators and that J1939 networks do not run on the simulated bus or in the local runtime.

#### Scenario: Reader looks for a J1939 simulator
- **WHEN** a reader opens `docs/simulator.md` to simulate a J1939 engine ECU
- **THEN** the first table names `canworks-j1939-sim`, says it runs on a PC with a SocketCAN interface or a USB adapter, and links `docs/j1939.md#simulator`

#### Scenario: Why two simulators
- **WHEN** a reader wonders why the configurator's Simulation does not play their J1939 ECU
- **THEN** the page says the CANopen simulator builds devices from EDS files on the bridge's virtual bus, while J1939 runs on the kernel's J1939 sockets with ECUs played from a DBC

### Requirement: Schema file names
The JSON Schemas SHALL be published as `schema/canworks.v1.schema.json`, `schema/canworks.v2.schema.json`, `schema/canworks-sim.v1.schema.json` and `schema/canworks-sim.v2.schema.json`, and the `schema_version` values inside config files SHALL keep their meaning.

#### Scenario: Existing example
- **WHEN** `config/pingpong/canopen_config.json` (`schema_version` 2) is checked against `schema/canworks.v2.schema.json`
- **THEN** it validates

#### Scenario: Machine schema
- **WHEN** the repository and the PC tools package are listed
- **THEN** no file named `canworks-sim-machine.v1.schema.json` or `canworks-machine.v1.schema.json` is in either

## REMOVED Requirements

### Requirement: Names on the PLC
**Reason**: The `canworks` plugin line in `plugins.conf`, `libcanworks_plugin.so`, the uploaded `conf/canworks.json` and the editor hook went with the OpenPLC plugin.
**Migration**: The bridge keeps its configs in `/etc/canworks-bridge/<name>/canworks.json` (modbus-bridge); the editor project keeps its config in `canworks/`.

### Requirement: Older install cleaned up
**Reason**: `install-stock.sh`, which cleaned up the old plugin names in `plugins.conf` and `/opt/openplc-canopen`, is deleted with the plugin.
**Migration**: None; the bench cleanup removes plugin installs by hand (remove-openplc-plugin task 11.1).
