## MODIFIED Requirements

### Requirement: Command names
The PC tools SHALL install `canworks-deploy`, `canworks-config`, `canworks-diag` and `canworks-local-runtime`, with the arguments and behaviour the `openplc-canopen-*` commands had, and SHALL NOT install any `openplc-canopen-*` command.

#### Scenario: Diagnostics command
- **WHEN** a user runs `canworks-diag status --host plc.local`
- **THEN** the output is what `openplc-canopen-diag status --host plc.local` printed with tools 0.40.0

#### Scenario: Old name gone
- **WHEN** a user installs tools 0.42.0 into a fresh environment and runs `openplc-canopen-diag`
- **THEN** the shell reports that the command is not found

### Requirement: Simulator names
Each simulator command SHALL name the protocol it simulates, and no command that is not a device simulator SHALL carry `sim` in its name. The CANopen device simulator binary SHALL be `canworks-canopen-sim` (it also plays the simulation file's plain CAN devices), the J1939 ECU simulator command SHALL be `canworks-j1939-sim`, the switch that forces simulation SHALL be `CANWORKS_FORCE_SIMULATE`, the local runtime command SHALL be `canworks-local-runtime`, its image SHALL be `ghcr.io/tonihoohoo/canworks-local-runtime`, and its container SHALL be `canworks-local-runtime`. The simulation file schemas keep their names (`canworks-sim.v1`, `canworks-sim.v2`), because both the plugin's simulated devices and `canworks-canopen-sim` read that file.

#### Scenario: Local runtime start
- **WHEN** a user runs `canworks-local-runtime start`
- **THEN** a container named `canworks-local-runtime` runs the image `ghcr.io/tonihoohoo/canworks-local-runtime` at the tools' version

#### Scenario: Old simulator names gone
- **WHEN** a user installs the PC tools and the plugin of this release into a fresh environment and runs `canworks-sim` or `canworks-sim-runtime`
- **THEN** the shell reports that the command is not found

## ADDED Requirements

### Requirement: Retired simulator names stay out
The repository's name check SHALL also report `canworks-sim-runtime` and the bare command name `canworks-sim` (not the simulation file schema names `canworks-sim.v1` and `canworks-sim.v2`) outside archived changes, and CI SHALL fail when it finds one. The rename script's mapping from the pre-canworks names SHALL point at the current names (`openplc-canopen-sim-runtime` to `canworks-local-runtime`).

#### Scenario: Old command in a new doc
- **WHEN** a pull request adds a doc line that runs `canworks-sim --eds drive.eds --node 4`
- **THEN** CI fails and names the file and `canworks-sim`

#### Scenario: Schema name is fine
- **WHEN** a pull request adds a link to `schema/canworks-sim.v2.schema.json`
- **THEN** the name check does not report it

### Requirement: One simulation overview
`docs/simulator.md` SHALL be titled "Simulation" and SHALL open with a table that names, for each thing a user may want to simulate, the tool or setting, the protocols it covers, where it runs and its doc. Below the table the page SHALL say why CANopen and J1939 have separate simulators and that J1939 networks do not run on the simulated bus or in the local runtime.

#### Scenario: Reader looks for a J1939 simulator
- **WHEN** a reader opens `docs/simulator.md` to simulate a J1939 engine ECU
- **THEN** the first table names `canworks-j1939-sim`, says it runs on a PC with a SocketCAN interface or a USB adapter, and links `docs/j1939.md#simulator`

#### Scenario: Why two simulators
- **WHEN** a reader wonders why the configurator's Simulation does not play their J1939 ECU
- **THEN** the page says the CANopen simulator builds devices from EDS files on the plugin's virtual bus, while J1939 runs on the kernel's J1939 sockets with ECUs played from a DBC

### Requirement: Simulator wording in the docs
The README SHALL list every simulator command in its one table of commands, each with the protocol it simulates, and SHALL link the simulation overview from its Simulation section. The docs and the configurator SHALL call `canworks-canopen-sim` "the CANopen simulator" and `canworks-local-runtime` "the local runtime", and SHALL NOT use "standalone simulator" or "simulator runtime" for them.

#### Scenario: Reader looks for the local runtime
- **WHEN** a reader scans the README command table for how to run a PLC on the PC without hardware
- **THEN** the row reads `canworks-local-runtime` and does not describe it as a device simulator

#### Scenario: Runtime host commands
- **WHEN** a reader looks for the simulator that runs on the runtime host
- **THEN** the README command table has a `canworks-canopen-sim` row next to `canworks-j1939-sim`, each saying its protocol and where it runs
