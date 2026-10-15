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
The PC tools SHALL install `canworks-deploy`, `canworks-config`, `canworks-diag` and `canworks-sim-runtime`, with the arguments and behaviour the `openplc-canopen-*` commands had, and SHALL NOT install any `openplc-canopen-*` command.

#### Scenario: Diagnostics command
- **WHEN** a user runs `canworks-diag status --host plc.local`
- **THEN** the output is what `openplc-canopen-diag status --host plc.local` printed with tools 0.40.0

#### Scenario: Old name gone
- **WHEN** a user installs tools 0.42.0 into a fresh environment and runs `openplc-canopen-diag`
- **THEN** the shell reports that the command is not found

### Requirement: Settings and environment names
The PC tools SHALL keep per-user settings in a folder named `canworks` in the operating system's settings location. Every environment variable, CMake option or cache variable and Docker build argument that the plugin, the simulator, the PC tools, the install script, the build or the tests read SHALL have the prefix `CANWORKS_`; none SHALL have the prefix `CANOPEN_` or `OPENPLC_CANOPEN_`. Names only code sees (header guards, the C SDO API `CANOPEN_PLC_*`, Python constants) are not settings and MAY keep a CANopen name.

#### Scenario: Token from the environment
- **WHEN** `CANWORKS_TOKEN` is set and the user runs `canworks-diag status`
- **THEN** the client uses that token

#### Scenario: Slave state folder
- **WHEN** the plugin runs a slave network with `CANWORKS_STATE_DIR=/tmp/state`
- **THEN** a store to 0x1010 writes the state file under `/tmp/state`, and `CANOPEN_STATE_DIR` has no effect

#### Scenario: Build without tests
- **WHEN** a user configures the build with `-DCANWORKS_BUILD_TESTS=OFF`
- **THEN** `canopen_check`, the tests and the ping-pong slave are not built

### Requirement: Names on the PLC
The plugin SHALL register as `canworks` in `plugins.conf` with library `libcanworks_plugin.so` installed under `/opt/canworks`, SHALL read the uploaded config `conf/canworks.json` with its files in `conf/canworks/`, and SHALL write generated files to `.canworks/` next to the config. The editor hook SHALL take the config from the project folder `canworks/` (`canworks/canworks.json`). The diagnostics port and protocol version SHALL stay as they are.

#### Scenario: Deploy after the rename
- **WHEN** a project is deployed with `canworks-deploy` 0.42.0 to a runtime installed with that version
- **THEN** `plugins.conf` has one enabled `canworks` line, the runtime holds `conf/canworks.json`, and the configurator connects on port 7531

#### Scenario: Editor upload
- **WHEN** the editor's Build and Upload sends a project with a `canworks/` folder to a runtime with the editor hook installed
- **THEN** the runtime enables `canworks` with that config

### Requirement: Simulator names
The device simulator binary SHALL be `canworks-sim`, the switch that forces simulation SHALL be `CANWORKS_FORCE_SIMULATE`, the simulator runtime image SHALL be `ghcr.io/tonihoohoo/canworks-sim-runtime`, and the local runtime container SHALL be `canworks-sim-runtime`.

#### Scenario: Local runtime start
- **WHEN** a user runs `canworks-sim-runtime start`
- **THEN** a container named `canworks-sim-runtime` runs the image `ghcr.io/tonihoohoo/canworks-sim-runtime` at the tools' version

### Requirement: Schema file names
The JSON Schemas SHALL be published as `schema/canworks.v1.schema.json`, `schema/canworks.v2.schema.json`, `schema/canworks-sim.v1.schema.json`, `schema/canworks-sim.v2.schema.json` and `schema/canworks-sim-machine.v1.schema.json`, and the `schema_version` values inside config files SHALL keep their meaning.

#### Scenario: Existing example
- **WHEN** `config/pingpong/canopen_config.json` (`schema_version` 1) is checked against `schema/canworks.v1.schema.json`
- **THEN** it validates

#### Scenario: Machine schema
- **WHEN** `examples/gantry-cell/canworks/machine.json` is checked against `schema/canworks-sim-machine.v1.schema.json`
- **THEN** it validates, and no file named `canworks-machine.v1.schema.json` is in the repository or the PC tools

### Requirement: Older install cleaned up
When `install-stock.sh` finds a `canopen` line in `plugins.conf`, a `/opt/openplc-canopen` folder, or runtime-spec entries that refer to `/opt/openplc-canopen`, it SHALL remove them before installing and print one line for each.

#### Scenario: Bench PLC upgrade
- **WHEN** the script runs on a runtime that has the 0.40.0 install
- **THEN** afterwards `plugins.conf` has a `canworks` line and no `canopen` line, `/opt/openplc-canopen` is gone, and the output names both removals

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
