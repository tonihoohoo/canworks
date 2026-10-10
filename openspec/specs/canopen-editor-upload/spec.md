# canopen-editor-upload Specification

## Purpose
Keeps the CANopen plugin enabled on a stock OpenPLC Runtime v4 when the OpenPLC Editor's own "Build and upload" is used, by carrying the CANopen config inside the editor project and applying it on the runtime from the upload's project snapshot.

## Requirements

### Requirement: CANopen config in the editor project
An editor project SHALL be able to carry its config as `canworks/canworks.json` at the project root, with every EDS file it names next to it or in a subfolder of `canworks/`. The file SHALL follow the same contract as the deploy tool's input, `schema_version` 1 or 2 (several networks, slave, gateway, J1939 and raw messages included), with `eds` paths relative to `canworks/`.

#### Scenario: Project layout
- **WHEN** a project folder contains `canworks/canworks.json` naming `eds: "rtd8.eds"` and `canworks/rtd8.eds` exists
- **THEN** the project carries a complete CANopen config

#### Scenario: Version 2 config
- **WHEN** a project's `canworks/canworks.json` is a version 2 config with two networks and a slave network, and it is sent with the editor's "Build and upload"
- **THEN** the runtime enables the plugin with that config and both networks run

### Requirement: Editor upload enables CANopen from the project
On a stock runtime with the hook installed, a successful build from an upload that carries no `conf/canworks.json`, but whose project snapshot carries `canworks/canworks.json`, SHALL end with the runtime enabling `canopen` using that config and its EDS files, before the runtime reports the build successful. The runtime log SHALL say the config came from the project snapshot.

#### Scenario: Build and upload from the editor
- **WHEN** a project with `canworks/canworks.json` is sent with the editor's "Build and upload" and the build succeeds
- **THEN** `plugins.conf` shows `canopen` enabled before the compilation status reads SUCCESS, the PLC started afterwards runs with CANopen, and the build log names the snapshot as the config's source

#### Scenario: Build fails
- **WHEN** the same upload's build fails
- **THEN** the hook changes nothing and the runtime's own failure handling applies

### Requirement: Deployed config takes precedence
When an upload carries `conf/canworks.json` (as the deploy tool's uploads do), the hook SHALL leave that config and its EDS files untouched and ignore any CANopen config in the project snapshot.

#### Scenario: Deploy tool upload
- **WHEN** a bundle made by `canworks-deploy` is uploaded
- **THEN** the runtime enables `canopen` with the uploaded `conf/canworks.json`, exactly as without the hook

### Requirement: No config means CANopen off
When neither the upload nor its project snapshot carries a CANopen config, or the upload has no snapshot at all, the runtime SHALL disable `canopen` exactly as it does without the hook.

#### Scenario: Project without CANopen
- **WHEN** a project with no `canworks/` folder is sent with "Build and upload"
- **THEN** the runtime disables `canopen` and logs that no config was found

#### Scenario: Upload without a snapshot
- **WHEN** an older editor or `openplc-cli` uploads a program without a snapshot
- **THEN** the runtime disables `canopen`

### Requirement: Fail closed on a bad project config
If the snapshot's `canworks/canworks.json` is not valid JSON, fails the contract's schema, or names an EDS file the snapshot does not contain, the hook SHALL apply nothing from the snapshot, so the runtime disables `canopen`. The build log SHALL name the file and the problem. The build result SHALL not change because of it.

#### Scenario: Missing EDS
- **WHEN** the project's `canworks.json` names `drive.eds` and the snapshot has no such file
- **THEN** the build still succeeds, `canopen` is disabled, and the build log says `canworks/drive.eds` is missing from the project

### Requirement: EDS text encoding
The editor reads every project file as UTF-8 text when it builds the snapshot, so an EDS in another encoding arrives with its non-ASCII bytes replaced. The hook SHALL treat an EDS from the snapshot that contains the Unicode replacement character (bytes EF BF BD) as invalid and fail closed, naming the file. Putting a config into a project SHALL store every EDS as UTF-8, converting from Latin-1/CP1252 when the file is not valid UTF-8.

#### Scenario: Latin-1 EDS copied into a project
- **WHEN** `--into-project` copies an EDS whose `ParameterName` contains `°C` encoded in Latin-1
- **THEN** the project's copy is valid UTF-8 with the same text, and the next Build and upload enables CANopen

#### Scenario: Corrupted EDS in the snapshot
- **WHEN** an EDS that was put into the project in Latin-1 by hand arrives in the snapshot with replacement characters
- **THEN** nothing is extracted, `canopen` is disabled, and the build log names the EDS and says it must be UTF-8 (`--into-project` converts it)

### Requirement: Safe extraction from the snapshot
The hook SHALL read only `canworks/canworks.json` and the EDS files it names from the snapshot. It SHALL reject absolute paths, `..` components and links, and it SHALL bound the total size it extracts. It SHALL never write outside the upload's `conf/` directory.

#### Scenario: Path traversal
- **WHEN** the project's config names `eds: "../../etc/passwd"`
- **THEN** nothing is extracted, `canopen` is disabled, and the build log reports an invalid EDS path

### Requirement: Runtime compatibility self-check
At webserver start, the hook SHALL check that the runtime still provides the post-compile plugin-configuration step and the staged snapshot it relies on. If either is missing, it SHALL disable itself and log one error naming what is missing. The runtime SHALL then behave exactly as without the hook.

#### Scenario: Runtime renamed an internal
- **WHEN** a runtime update removes the function the hook wraps
- **THEN** the runtime starts normally, the log has one error from the CANopen editor hook saying it is inactive and why, and editor uploads switch CANopen off as without the hook

### Requirement: Install and uninstall the hook
`scripts/install-stock.sh` SHALL install the hook into the runtime's webserver Python environment and SHALL change no runtime source file. `--uninstall` SHALL remove it. Re-running the script SHALL leave exactly one copy of the hook installed. A flag SHALL allow installing the plugin without the hook.

#### Scenario: Install then uninstall
- **WHEN** the install script runs and then runs with `--uninstall`
- **THEN** after install the runtime log shows the hook active at start and `git status` in the runtime shows no modified tracked files; after uninstall the hook is gone and the runtime log no longer mentions it

#### Scenario: Runtime venv rebuilt
- **WHEN** a runtime reinstall recreates the webserver environment and the install script is run again
- **THEN** the hook is active again

### Requirement: Put a config into an editor project
The deploy tool SHALL be able to copy a config and its EDS files into an editor project's `canworks/` folder, after the same checks it runs before a deploy, rewriting each node's `eds` to a path relative to `canworks/`. It SHALL refuse to overwrite an existing `canworks/` folder unless asked to.

#### Scenario: Prepare a project
- **WHEN** `canworks-deploy --config config/rtd-sensor/canopen_config.json --into-project ~/Documents/workspace/rtd-monitor` runs
- **THEN** the project has `canworks/canworks.json` and `canworks/rtd8.eds`, and the next "Build and upload" from the editor leaves CANopen enabled
