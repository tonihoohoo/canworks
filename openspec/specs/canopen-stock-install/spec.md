# canopen-stock-install Specification

## Purpose
Installing the CANopen plugin on an unmodified native OpenPLC Runtime v4, so that the runtime's own upload rules switch it on when an upload carries `conf/canworks.json`.

## Requirements

### Requirement: Install on a stock runtime
The repository SHALL provide an install script for native installs of OpenPLC Runtime v4. It SHALL install the Lely CANopen libraries and `dcfgen`, build the plugin library against the runtime's headers, place it outside the runtime's build tree (default `/opt/canworks/lib/`), and add exactly one `canopen` line of type 1 to the runtime's `plugins.conf`, disabled. It SHALL change no runtime source file. Running it again SHALL leave exactly one `canopen` line and rebuild the library. On a device where the runtime runs in Docker, the same script SHALL install in Docker mode as specified in `canopen-docker-install`.

#### Scenario: Fresh install
- **WHEN** the script runs against a stock runtime checkout at its default path
- **THEN** `plugins.conf` has one `canopen` line pointing at the installed library, `git status` in the runtime shows no modified tracked files, and the runtime starts with the plugin loaded but not started

#### Scenario: Re-run
- **WHEN** the script runs a second time
- **THEN** `plugins.conf` still has exactly one `canopen` line

#### Scenario: Docker install detected
- **WHEN** the script finds the runtime runs under the managed Docker install
- **THEN** it installs in Docker mode (`canopen-docker-install`) and changes nothing on the host outside `/opt/canworks` and the bootloader's runtime spec

#### Scenario: Unmanaged Docker container detected
- **WHEN** the script finds a container named `openplc-runtime` but no bootloader runtime spec, and no `--docker-image` was given
- **THEN** it exits non-zero, changes nothing, and says to re-run with `--docker-image <the container's image>` and add the printed flags to the container

### Requirement: Enabled by uploads
With the plugin installed, an upload carrying `conf/canworks.json` SHALL make the stock runtime enable the plugin and copy the config next to the library. An upload without it SHALL make the runtime disable the plugin, unless the editor hook is installed and the upload's project snapshot carries a CANopen config (see `canopen-editor-upload`). The plugin SHALL work with whatever config path the runtime gives it.

#### Scenario: Deploy enables CANopen
- **WHEN** a bundle made by the deploy tool is uploaded
- **THEN** the runtime's `plugins.conf` shows `canopen` enabled with its config path next to the library, and the plugin starts when the PLC starts

#### Scenario: Editor upload disables CANopen
- **WHEN** a program from a project without a `canworks/` folder, or on a runtime without the editor hook, is uploaded from the editor's own "Build and upload"
- **THEN** the runtime disables `canopen`, the PLC runs without it, and the runtime log says the plugin was disabled because no config was found

#### Scenario: Editor upload with a project config
- **WHEN** a program from a project with `canworks/canworks.json` is uploaded from the editor's own "Build and upload" on a runtime with the editor hook installed
- **THEN** the runtime enables `canopen` with that config, as specified in `canopen-editor-upload`

### Requirement: EDS files from the upload
The plugin SHALL resolve a relative `eds` path first against the directory of the config file it was given, then against the runtime's `core/generated/conf/` directory, where the stock runtime extracts the uploaded `conf/` tree. It SHALL log which path it used. If neither exists, it SHALL report the EDS file as missing.

#### Scenario: EDS from a deployed bundle
- **WHEN** the config names `canworks/eds/cpp-slave.eds` and the runtime extracted the upload to `core/generated/conf/canworks/eds/cpp-slave.eds`
- **THEN** the plugin loads that EDS and logs the resolved path

### Requirement: Uninstall
The install script SHALL have an uninstall mode that removes the `canopen` line from `plugins.conf` and the installed library, and changes nothing else in the runtime.

#### Scenario: Uninstall
- **WHEN** the uninstall mode runs
- **THEN** `plugins.conf` has no `canopen` line, the library is gone, and the runtime starts normally

### Requirement: Simulator installed with the plugin
`scripts/install-stock.sh` SHALL build and install `canworks-sim` with the plugin, under the plugin's prefix, with a link in `/usr/local/bin` on native installs, and the uninstall SHALL remove both. In Docker mode the simulator SHALL be installed inside the runtime container and be runnable with `docker exec`.

#### Scenario: Native install
- **WHEN** `install-stock.sh` finishes on a native runtime
- **THEN** `canworks-sim --version` prints the same version as the plugin

### Requirement: J1939 kernel module loaded
The install script SHALL load the `can-j1939` kernel module on the host and make it load at boot, in native and in Docker mode. When the module is not available in the running kernel, the install SHALL succeed and say that J1939 networks will not start on this device.

#### Scenario: Raspberry Pi install
- **WHEN** the script runs on a Raspberry Pi OS host
- **THEN** `lsmod` lists `can_j1939` and `/etc/modules-load.d/` holds an entry for it

#### Scenario: Kernel without J1939
- **WHEN** the script runs on a kernel without `can-j1939`
- **THEN** the install finishes, CANopen works, and the output says J1939 networks need a kernel with the can-j1939 module

### Requirement: Link and discovery install options
`scripts/install-stock.sh` and `scripts/install-bridge.sh` SHALL install the Avahi advertisement by default (skipped with `--without-discovery`) and, with `--with-link`, the link service: a Python virtual environment with the pinned `iroh` package under the install prefix, the `canworks-link` command, `canworks-link.service` (enabled and started, watching the deployed config), and `/etc/canworks-link/` with no paired PCs. No other step on the device SHALL be needed. `--uninstall` SHALL remove the service, the command and the Avahi file and keep `/etc/canworks-link/` unless `--purge` is given.

#### Scenario: Fresh install with the link
- **WHEN** `install-stock.sh --with-link` runs on a device with no internet route
- **THEN** the service starts, makes no outside connection, appears in discovery with its link ID, and the first PC that logs in with the right token on the LAN gets paired
