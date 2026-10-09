## ADDED Requirements

### Requirement: Project and package names
The project SHALL be published as the repository `tonihoohoo/canworks`. The PC tools SHALL be the distribution `canworks`, with release wheels named `canworks-<version>-py3-none-any.whl` under the existing `deploy-v<version>` tags. In-repository links and the JSON Schema `$id` values SHALL use the new repository URL.

#### Scenario: First release after the rename
- **WHEN** version 0.41.0 is released from `main`
- **THEN** the release `deploy-v0.41.0` has the asset `canworks-0.41.0-py3-none-any.whl`

#### Scenario: Old repository URL
- **WHEN** a user clones `https://github.com/tonihoohoo/openplc-canopen` after the rename
- **THEN** the clone succeeds through GitHub's redirect and contains the renamed tree

### Requirement: Command names
The PC tools SHALL install the commands `canworks-deploy`, `canworks-config`, `canworks-diag` and `canworks-sim-runtime`. They SHALL have the same arguments, output and exit status as the commands they replace.

#### Scenario: New diagnostics command
- **WHEN** a user runs `canworks-diag status --host plc.local`
- **THEN** the output is what `openplc-canopen-diag status --host plc.local` printed with tools 0.40.0

### Requirement: Earlier command names keep working
The PC tools SHALL also install `openplc-canopen-deploy`, `openplc-canopen-config`, `openplc-canopen-diag`, `openplc-canopen-sim-runtime` and `openplc-canopen-runtime`. Each SHALL print one line to stderr naming the command that replaces it, then behave exactly like that command with the same arguments.

#### Scenario: Old command in a script
- **WHEN** a script runs `openplc-canopen-deploy --check project/`
- **THEN** it gets the same stdout and exit status as `canworks-deploy --check project/`, plus one line on stderr saying the command is now `canworks-deploy`

### Requirement: Environment variable names
Every environment variable the PC tools read with the prefix `OPENPLC_CANOPEN_` SHALL also be read as the same name with the prefix `CANWORKS_`. When both are set, the `CANWORKS_` value SHALL be used.

#### Scenario: Token from the old variable
- **WHEN** only `OPENPLC_CANOPEN_TOKEN` is set and the user runs `canworks-diag status`
- **THEN** the client uses that token

#### Scenario: Both set
- **WHEN** `CANWORKS_TOKEN` and `OPENPLC_CANOPEN_TOKEN` are both set to different values
- **THEN** the client uses the `CANWORKS_TOKEN` value

### Requirement: Settings folder carried over
The PC tools SHALL keep per-user settings in a folder named `canworks` in the operating system's settings location. When that folder does not exist and an `openplc-canopen` folder does, the tools SHALL copy the old folder's contents to the new one on first use, say so in one line, and leave the old folder unchanged.

#### Scenario: Upgrade on macOS
- **WHEN** `~/Library/Application Support/openplc-canopen` holds a saved runtime and token and the user runs `canworks-config` for the first time
- **THEN** the saved runtime and token are available, `~/Library/Application Support/canworks` exists, and the old folder is still there

### Requirement: Simulator runtime image and container names
The simulator runtime image SHALL be published as `ghcr.io/tonihoohoo/canworks-sim-runtime`, and the local runtime container SHALL be named `canworks-sim-runtime`. When `start` or `update` finds no `canworks-sim-runtime` container but one with an earlier name (`openplc-canopen-sim-runtime`, then `openplc-canopen-runtime`), it SHALL take that container over on its data volume as for the earlier rename, keeping the saved credentials and certificate fingerprint.

#### Scenario: Update after upgrading from 0.40.0
- **WHEN** a local runtime was started with tools 0.40.0 and the user upgrades and runs `canworks-sim-runtime update`
- **THEN** `openplc-canopen-sim-runtime` is gone, `canworks-sim-runtime` runs the new image on the old data volume, and the saved credentials log in with the same fingerprint

### Requirement: On-device names unchanged
The rename SHALL NOT change any name on an installed runtime: the plugin stays `canopen` in `plugins.conf` with library `libcanopen_plugin.so`, files install under `/opt/openplc-canopen`, the uploaded config stays `conf/canopen.json`, the editor project folder stays `canopen/`, and the editor hook module and the diagnostics port stay as they are.

#### Scenario: Upgrade of a running PLC
- **WHEN** a PLC installed with 0.40.0 is redeployed with `canworks-deploy` 0.41.0
- **THEN** the runtime keeps the same `plugins.conf` line and install path, and the configurator connects on the same port with the same token

### Requirement: Rename check in CI
The repository SHALL contain a rename script that applies the old-to-new name mapping and can report, without changing anything, whether any old name is left outside archived changes, the on-device names and the alias definitions. CI SHALL fail when that report finds a leftover old name.

#### Scenario: Branch that missed the rename
- **WHEN** a pull request adds a new file that imports `openplc_canopen_deploy`
- **THEN** CI fails and names the file and the old name
