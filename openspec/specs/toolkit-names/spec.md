# toolkit-names Specification

## Purpose
The names of the project and everything it ships (repository, PC tools package and commands, plugin and its files on the PLC, schemas, simulator image, PLC library), the one-time cleanup of an install from before the rename to canworks, and the check that no earlier project name comes back.

## Requirements

### Requirement: Project and package names
The project SHALL be published as the repository `tonihoohoo/canworks`. The PC tools SHALL be the distribution `canworks`, with release wheels `canworks-<version>-py3-none-any.whl` under the existing `deploy-v<version>` tags. In-repository links and JSON Schema `$id` values SHALL use the new repository URL.

#### Scenario: First release after the rename
- **WHEN** version 0.42.0 is released from `main`
- **THEN** the release `deploy-v0.42.0` has the asset `canworks-0.42.0-py3-none-any.whl`

### Requirement: Command names
The PC tools SHALL install `canworks-deploy`, `canworks-config`, `canworks-diag` and `canworks-local-runtime`, with the arguments and behaviour the `openplc-canopen-*` commands had, and SHALL NOT install any `openplc-canopen-*` command.

#### Scenario: Diagnostics command
- **WHEN** a user runs `canworks-diag status --host plc.local`
- **THEN** the output is what `openplc-canopen-diag status --host plc.local` printed with tools 0.40.0

#### Scenario: Old name gone
- **WHEN** a user installs tools 0.42.0 into a fresh environment and runs `openplc-canopen-diag`
- **THEN** the shell reports that the command is not found

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

### Requirement: Schema file names
The JSON Schemas SHALL be published as `schema/canworks.v1.schema.json`, `schema/canworks.v2.schema.json`, `schema/canworks-sim.v1.schema.json` and `schema/canworks-sim.v2.schema.json`, and the `schema_version` values inside config files SHALL keep their meaning.

#### Scenario: Existing example
- **WHEN** `config/pingpong/canopen_config.json` (`schema_version` 2) is checked against `schema/canworks.v2.schema.json`
- **THEN** it validates

#### Scenario: Machine schema
- **WHEN** the repository and the PC tools package are listed
- **THEN** no file named `canworks-sim-machine.v1.schema.json` or `canworks-machine.v1.schema.json` is in either

### Requirement: No old names in the repository
The repository SHALL contain a rename script that applies the old-to-new mapping and can report, without changing anything, any old project-level name left outside archived changes and the CANopen-specific names, including the old `CANOPEN_` environment variable, CMake option and build argument names. CI SHALL fail when that report finds one.

#### Scenario: New file with an old import
- **WHEN** a pull request adds a file that imports `openplc_canopen_deploy`
- **THEN** CI fails and names the file and the old name

#### Scenario: Old variable name
- **WHEN** a pull request adds a test that reads `os.environ.get("CANOPEN_CHROMIUM")`
- **THEN** CI fails and names the file and `CANOPEN_CHROMIUM`

### Requirement: Project logo
The README SHALL open with the canworks logo as a `<picture>` element that shows a light variant in GitHub's light theme and a dark variant in its dark theme, with the alt text "canworks". The logo files SHALL be SVG with the text as outlines (no font needed to render), SHALL be generated by a script in the repository, and SHALL contain no third-party logo or trademark.

#### Scenario: Dark theme reader
- **WHEN** a reader with GitHub set to the dark theme opens the repository
- **THEN** the README shows the dark variant of the logo, readable on the dark background

#### Scenario: Screen reader
- **WHEN** a screen reader reads the top of the README
- **THEN** it reads "canworks" as the page's main heading

#### Scenario: Logo changed
- **WHEN** a developer changes a logo colour in the generator script and runs it
- **THEN** both variants are rewritten with the new colour and no other change

### Requirement: README tool descriptions
The README SHALL keep its PC tools command table to one or two sentences per command, each linking that command's doc, and SHALL describe the configurator in its own section with one bullet per area (Configure, Connect, Commission, Commission a CANopen device, Trace, Exports, Device notes, keyboard and icons), using the labels the page shows.

#### Scenario: New reader looks for the trace
- **WHEN** a reader opens the README and looks for how to decode a bus trace
- **THEN** the Configurator section has a Trace bullet that links `docs/trace.md`, outside the command table

### Requirement: README adapters, skills and export limits
The README SHALL name the USB adapter types the PC tools drive and what each needs per operating system, SHALL name every user-facing Claude skill under `.claude/skills/` (not the OpenSpec workflow skills) with a link to its file, and SHALL list the limits of every export to another vendor's tool under Requirements and limits.

#### Scenario: Claude skill
- **WHEN** a reader looks for how to write device notes from a datasheet
- **THEN** the README has a section naming the `canworks-datasheet-notes` skill with a link to its `SKILL.md`

#### Scenario: Adapter on Windows
- **WHEN** a Windows user reads which USB adapters work
- **THEN** the README says gs_usb adapters need nothing else installed on Windows

### Requirement: App icon
The configurator's app shortcut and its browser tab SHALL use an icon drawn from the project logo: at 48 px and larger the logo's word "can" in the logo's blue over the logo's two-wire bus with terminators and nodes, on a rounded square; at 32 px and smaller the logo's "c" over the two wires. The letters SHALL be the logo's outlined glyphs and the colours the logo's own. The Windows `.ico` SHALL hold both forms at their sizes, and the browser tab icon SHALL be an SVG that uses the logo's dark colours when the operating system is in dark mode. Every icon file SHALL be written by one script in the repository from the same drawing, and SHALL contain no third-party logo or trademark.

#### Scenario: Shortcut matches the logo
- **WHEN** a user installs the PC tools and looks at the canworks configurator shortcut on the desktop, in the Start menu, in `~/Applications` or among the Linux applications
- **THEN** its icon shows the blue "can" over the bus, as in the README logo

#### Scenario: Small sizes
- **WHEN** Windows shows the shortcut at 16 or 24 px (Start menu list, taskbar jump list)
- **THEN** the icon is the "c" over two wires with no blurred detail

#### Scenario: Browser tab
- **WHEN** the configurator page is open in a browser
- **THEN** its tab shows the small form of the app icon, not the earlier blue square

#### Scenario: Dark mode tab
- **WHEN** the operating system is in dark mode
- **THEN** the tab icon uses the logo's dark colours on a dark tile

#### Scenario: Logo colour changed
- **WHEN** a developer changes a colour in the icon script and runs it
- **THEN** the shortcut icons, the favicon and the touch icon are all rewritten with the new colour

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
- **THEN** the page says the CANopen simulator builds devices from EDS files on the bridge's virtual bus, while J1939 runs on the kernel's J1939 sockets with ECUs played from a DBC

### Requirement: Simulator wording in the docs
The README SHALL list every simulator command in its one table of commands, each with the protocol it simulates, and SHALL link the simulation overview from its Simulation section. The docs and the configurator SHALL call `canworks-canopen-sim` "the CANopen simulator" and `canworks-local-runtime` "the local runtime", and SHALL NOT use "standalone simulator" or "simulator runtime" for them.

#### Scenario: Reader looks for the local runtime
- **WHEN** a reader scans the README command table for how to run a PLC on the PC without hardware
- **THEN** the row reads `canworks-local-runtime` and does not describe it as a device simulator

#### Scenario: Runtime host commands
- **WHEN** a reader looks for the simulator that runs on the runtime host
- **THEN** the README command table has a `canworks-canopen-sim` row next to `canworks-j1939-sim`, each saying its protocol and where it runs
