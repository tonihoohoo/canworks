## ADDED Requirements

### Requirement: Project and package names
The project SHALL be published as the repository `tonihoohoo/canworks`. The PC tools SHALL be the distribution `canworks`, with release wheels `canworks-<version>-py3-none-any.whl` under the existing `deploy-v<version>` tags. In-repository links and JSON Schema `$id` values SHALL use the new repository URL.

#### Scenario: First release after the rename
- **WHEN** version 0.41.0 is released from `main`
- **THEN** the release `deploy-v0.41.0` has the asset `canworks-0.41.0-py3-none-any.whl`

### Requirement: Command names
The PC tools SHALL install `canworks-deploy`, `canworks-config`, `canworks-diag` and `canworks-sim-runtime`, with the arguments and behaviour the `openplc-canopen-*` commands had, and SHALL NOT install any `openplc-canopen-*` command.

#### Scenario: Diagnostics command
- **WHEN** a user runs `canworks-diag status --host plc.local`
- **THEN** the output is what `openplc-canopen-diag status --host plc.local` printed with tools 0.40.0

#### Scenario: Old name gone
- **WHEN** a user installs tools 0.41.0 into a fresh environment and runs `openplc-canopen-diag`
- **THEN** the shell reports that the command is not found

### Requirement: Settings and environment names
The PC tools SHALL keep per-user settings in a folder named `canworks` in the operating system's settings location, and SHALL read environment variables with the prefix `CANWORKS_` where they read `OPENPLC_CANOPEN_` before.

#### Scenario: Token from the environment
- **WHEN** `CANWORKS_TOKEN` is set and the user runs `canworks-diag status`
- **THEN** the client uses that token

### Requirement: Names on the PLC
The plugin SHALL register as `canworks` in `plugins.conf` with library `libcanworks_plugin.so` installed under `/opt/canworks`, SHALL read the uploaded config `conf/canworks.json` with its files in `conf/canworks/`, and SHALL write generated files to `.canworks/` next to the config. The editor hook SHALL take the config from the project folder `canworks/` (`canworks/canworks.json`). The diagnostics port and protocol version SHALL stay as they are.

#### Scenario: Deploy after the rename
- **WHEN** a project is deployed with `canworks-deploy` 0.41.0 to a runtime installed with that version
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
The JSON Schemas SHALL be published as `schema/canworks.v1.schema.json`, `schema/canworks.v2.schema.json`, `schema/canworks-sim.v1.schema.json` and `schema/canworks-sim.v2.schema.json`, and the `schema_version` values inside config files SHALL keep their meaning.

#### Scenario: Existing example
- **WHEN** `config/pingpong/canopen_config.json` (`schema_version` 1) is checked against `schema/canworks.v1.schema.json`
- **THEN** it validates

### Requirement: Older install cleaned up
When `install-stock.sh` finds a `canopen` line in `plugins.conf`, a `/opt/openplc-canopen` folder, or runtime-spec entries that refer to `/opt/openplc-canopen`, it SHALL remove them before installing and print one line for each.

#### Scenario: Bench PLC upgrade
- **WHEN** the script runs on a runtime that has the 0.40.0 install
- **THEN** afterwards `plugins.conf` has a `canworks` line and no `canopen` line, `/opt/openplc-canopen` is gone, and the output names both removals

### Requirement: No old names in the repository
The repository SHALL contain a rename script that applies the old-to-new mapping and can report, without changing anything, any old project-level name left outside archived changes and the CANopen-specific names. CI SHALL fail when that report finds one.

#### Scenario: New file with an old import
- **WHEN** a pull request adds a file that imports `openplc_canopen_deploy`
- **THEN** CI fails and names the file and the old name
