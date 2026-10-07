# canopen-stock-install Specification

## Purpose
Installing the CANopen plugin on an unmodified native OpenPLC Runtime v4, so that the runtime's own upload rules switch it on when an upload carries `conf/canopen.json`.

## Requirements

### Requirement: Install on a stock runtime
The repository SHALL provide an install script for native installs of OpenPLC Runtime v4. It SHALL install the Lely CANopen libraries and `dcfgen`, build the plugin library against the runtime's headers, place it outside the runtime's build tree (default `/opt/openplc-canopen/lib/`), and add exactly one `canopen` line of type 1 to the runtime's `plugins.conf`, disabled. It SHALL change no runtime source file. Running it again SHALL leave exactly one `canopen` line and rebuild the library. On a device where the runtime runs in Docker, the same script SHALL install in Docker mode as specified in `canopen-docker-install`.

#### Scenario: Fresh install
- **WHEN** the script runs against a stock runtime checkout at its default path
- **THEN** `plugins.conf` has one `canopen` line pointing at the installed library, `git status` in the runtime shows no modified tracked files, and the runtime starts with the plugin loaded but not started

#### Scenario: Re-run
- **WHEN** the script runs a second time
- **THEN** `plugins.conf` still has exactly one `canopen` line

#### Scenario: Docker install detected
- **WHEN** the script finds the runtime runs under the managed Docker install
- **THEN** it installs in Docker mode (`canopen-docker-install`) and changes nothing on the host outside `/opt/openplc-canopen` and the bootloader's runtime spec

#### Scenario: Unmanaged Docker container detected
- **WHEN** the script finds a container named `openplc-runtime` but no bootloader runtime spec, and no `--docker-image` was given
- **THEN** it exits non-zero, changes nothing, and says to re-run with `--docker-image <the container's image>` and add the printed flags to the container

### Requirement: Enabled by uploads
With the plugin installed, an upload carrying `conf/canopen.json` SHALL make the stock runtime enable the plugin and copy the config next to the library. An upload without it SHALL make the runtime disable the plugin, unless the editor hook is installed and the upload's project snapshot carries a CANopen config (see `canopen-editor-upload`). The plugin SHALL work with whatever config path the runtime gives it.

#### Scenario: Deploy enables CANopen
- **WHEN** a bundle made by the deploy tool is uploaded
- **THEN** the runtime's `plugins.conf` shows `canopen` enabled with its config path next to the library, and the plugin starts when the PLC starts

#### Scenario: Editor upload disables CANopen
- **WHEN** a program from a project without a `canopen/` folder, or on a runtime without the editor hook, is uploaded from the editor's own "Build and upload"
- **THEN** the runtime disables `canopen`, the PLC runs without it, and the runtime log says the plugin was disabled because no config was found

#### Scenario: Editor upload with a project config
- **WHEN** a program from a project with `canopen/canopen.json` is uploaded from the editor's own "Build and upload" on a runtime with the editor hook installed
- **THEN** the runtime enables `canopen` with that config, as specified in `canopen-editor-upload`

### Requirement: EDS files from the upload
The plugin SHALL resolve a relative `eds` path first against the directory of the config file it was given, then against the runtime's `core/generated/conf/` directory, where the stock runtime extracts the uploaded `conf/` tree. It SHALL log which path it used. If neither exists, it SHALL report the EDS file as missing.

#### Scenario: EDS from a deployed bundle
- **WHEN** the config names `canopen/eds/cpp-slave.eds` and the runtime extracted the upload to `core/generated/conf/canopen/eds/cpp-slave.eds`
- **THEN** the plugin loads that EDS and logs the resolved path

### Requirement: Uninstall
The install script SHALL have an uninstall mode that removes the `canopen` line from `plugins.conf` and the installed library, and changes nothing else in the runtime.

#### Scenario: Uninstall
- **WHEN** the uninstall mode runs
- **THEN** `plugins.conf` has no `canopen` line, the library is gone, and the runtime starts normally

### Requirement: Simulator installed with the plugin
`scripts/install-stock.sh` SHALL build and install `openplc-canopen-sim` with the plugin, under the plugin's prefix, with a link in `/usr/local/bin` on native installs, and the uninstall SHALL remove both. In Docker mode the simulator SHALL be installed inside the runtime container and be runnable with `docker exec`.

#### Scenario: Native install
- **WHEN** `install-stock.sh` finishes on a native runtime
- **THEN** `openplc-canopen-sim --version` prints the same version as the plugin
