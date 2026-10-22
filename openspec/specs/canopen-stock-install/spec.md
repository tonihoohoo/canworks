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
`scripts/install-stock.sh` SHALL build and install `canworks-canopen-sim` with the plugin, under the plugin's prefix, with a link in `/usr/local/bin` on native installs, and the uninstall SHALL remove both. In Docker mode the simulator SHALL be installed inside the runtime container and be runnable with `docker exec`. An install SHALL also remove the earlier `canworks-sim` binary under the plugin's prefix and its `/usr/local/bin/canworks-sim` link when that link points into this install, printing one line, so a bench device updated from an older install keeps no dangling link.

#### Scenario: Native install
- **WHEN** `install-stock.sh` finishes on a native runtime
- **THEN** `canworks-canopen-sim --version` prints the same version as the plugin

#### Scenario: Update from an install with the old name
- **WHEN** `install-stock.sh` runs on a native runtime that has `/usr/local/bin/canworks-sim` linking into `/opt/canworks`
- **THEN** afterwards that link and the old binary are gone, `canworks-canopen-sim` is installed, and the output names the removal

### Requirement: J1939 kernel module loaded
The install script SHALL load the `can-j1939` kernel module on the host and make it load at boot, in native and in Docker mode. When the module is not available in the running kernel, the install SHALL succeed and say that J1939 networks will not start on this device.

#### Scenario: Debian-based device install
- **WHEN** the script runs on a Debian-based host
- **THEN** `lsmod` lists `can_j1939` and `/etc/modules-load.d/` holds an entry for it

#### Scenario: Kernel without J1939
- **WHEN** the script runs on a kernel without `can-j1939`
- **THEN** the install finishes, CANopen works, and the output says J1939 networks need a kernel with the can-j1939 module

### Requirement: Link and discovery install options
`scripts/install-stock.sh` and `scripts/install-bridge.sh` SHALL install the Avahi advertisement by default (skipped with `--without-discovery`) and, with `--with-link`, the link service: a Python virtual environment with the pinned `iroh` package under the install prefix, the `canworks-link` command, `canworks-link.service` (enabled and started, watching the deployed config), and `/etc/canworks-link/` with no paired PCs. No other step on the device SHALL be needed. `--uninstall` SHALL remove the service, the command and the Avahi file and keep `/etc/canworks-link/` unless `--purge` is given.

#### Scenario: Fresh install with the link
- **WHEN** `install-stock.sh --with-link` runs on a device with no internet route
- **THEN** the service starts, makes no outside connection, appears in discovery with its link ID, and the first PC that logs in with the right token on the LAN gets paired

### Requirement: One-line install and update on the device

The repository SHALL provide `scripts/install-runtime.sh`, and `docs/install-stock.md` and the README SHALL give, first among the install routes, the one line that runs it straight from the repository on GitHub as root (`curl -LsSf <url> | sudo bash`, options after `-s --`). It SHALL download the source of the newest `deploy-v` release (or of `--version <version>`), found from the `releases/latest` redirect without the GitHub API, and run that release's `scripts/install-stock.sh` with every other option given, without a git checkout on the device. Running the same line again SHALL install the newer release over the existing one as `install-stock.sh` re-runs do; `--uninstall` and the other `install-stock.sh` options SHALL pass through unchanged. It SHALL never install code from `main`. Without root it SHALL exit non-zero and say how to run it. It SHALL remove its downloaded source afterwards. The documentation SHALL keep the git checkout route and show the script pinned to a release.

The same install SHALL be possible from a Windows, macOS or Linux PC onto a remote Linux device over SSH: `scripts/install-runtime.sh --ssh USER@HOST` (macOS, Linux) and `scripts/install-runtime.ps1 -Ssh USER@HOST` (Windows, PowerShell 5.1 with the built-in OpenSSH client), each runnable with one documented line straight from GitHub. The PC side SHALL need no root, no Python and no canworks tools; it SHALL resolve the release once and run the device side over `ssh -t` with that exact `--version`, so a `sudo` password prompt works and both sides agree on the release. Options other than the PC side's own (`--ssh`, `--port`, `--identity`, `--dry-run`) SHALL pass through to the device. The PC side SHALL exit with the device side's exit status, and SHALL say so before connecting when `ssh` is missing.

CI SHALL run `shellcheck` on the script and test its release lookup, option pass-through and the SSH command line it builds (for both scripts) without network access.

#### Scenario: Install on a fresh device
- **WHEN** an operator pastes the documented line on a Linux device with a stock OpenPLC Runtime v4 and no canworks checkout
- **THEN** the newest release's `install-stock.sh` runs, the plugin is installed as in Requirement: Install on a stock runtime, and no source folder of the release is left behind

#### Scenario: Update
- **WHEN** the line is run again on a device that has the plugin of an older release
- **THEN** the newest release is built and installed, `canworks-canopen-sim --version` prints its version and `plugins.conf` still has exactly one `canworks` line

#### Scenario: Options pass through
- **WHEN** the operator runs the line with `-s -- --with-link`
- **THEN** `install-stock.sh` of the release runs with `--with-link`

#### Scenario: Install from a Windows PC
- **WHEN** a user on Windows runs the documented PowerShell line with `-Ssh admin@plc.local` against a device with a stock runtime
- **THEN** an SSH session to `admin@plc.local` asks for the `sudo` password when needed, the newest release's `install-stock.sh` runs on the device, and the PowerShell command ends with its exit status

#### Scenario: Remote update from a Mac with options
- **WHEN** a Mac user runs `install-runtime.sh --ssh admin@plc.local --with-link`
- **THEN** the device runs the newest release's `install-stock.sh --with-link`, and the release named on the Mac and on the device is the same

#### Scenario: Not root
- **WHEN** the line is run without `sudo`
- **THEN** the script exits non-zero before downloading anything and shows the line with `sudo`

### Requirement: Release install reports its version

When `scripts/install-runtime.sh` installs a release, the plugin and `canworks-canopen-sim` SHALL be built with that release's version, so the diagnostics channel and `canworks-canopen-sim --version` report it, although the downloaded source has no git history.

#### Scenario: Version after a one-line install
- **WHEN** the one-line install installs release `0.84.0` on a device
- **THEN** `canworks-canopen-sim --version` prints `0.84.0`, not `unknown`

### Requirement: Installed version on the device
`install-stock.sh` SHALL write the plugin's version (the release version, or `git describe` of a checkout) to `<prefix>/VERSION` on every install and update, native and Docker mode, so the version can be read on the host without the runtime container. `--uninstall` SHALL remove it with `<prefix>/lib/`.

#### Scenario: Docker-mode device
- **WHEN** release 0.98.0 is installed on a managed Docker runtime
- **THEN** `/opt/canworks/VERSION` on the host holds `0.98.0`

### Requirement: Install step lines
`install-stock.sh` and `install-runtime.sh` SHALL print one line `::canworks-step N/M text` when each step starts (download, build tools, Lely, plugin and editor hook, runtime restart or container recreate, discovery and link), with M the number of steps this run takes (`?` in the lines `install-runtime.sh` prints before `install-stock.sh` runs, which does not know it yet), and SHALL keep their other output unchanged. The text SHALL be a short sentence for people.

#### Scenario: Steps of a Docker-mode update
- **WHEN** an update runs in Docker mode
- **THEN** the output has step lines from `1/M` to `M/M` in order, and the last names the runtime container restart

### Requirement: Install the OpenPLC runtime when none is found
`install-runtime.sh --with-openplc` SHALL, when no OpenPLC runtime is found (no `openplc-runtime` service and no bootloader runtime spec), run upstream's installer (`https://runtime.getedge.me`) as root, wait up to 10 minutes until the runtime answers on its local HTTPS port, and then install the plugin as without the option. When a runtime is found it SHALL install the plugin only. A failed upstream install SHALL end the script non-zero with the upstream output and SHALL NOT try the plugin. `--with-openplc` SHALL pass over `--ssh` like the other options, and `docs/install-stock.md` SHALL describe it.

#### Scenario: Fresh device
- **WHEN** `install-runtime.sh --with-openplc` runs on a Linux device without a runtime
- **THEN** upstream's managed Docker runtime is installed and answers, and the plugin is installed for its version

#### Scenario: Runtime present
- **WHEN** the same command runs on a device with a runtime
- **THEN** upstream's installer is not run

### Requirement: Device probe script
The PC tools package SHALL contain `canworks/devices/device-probe.sh`, a POSIX `sh` script that changes nothing, needs no root and no canworks on the device, and prints one JSON object describing the device as the `device-install` capability's probe requires. It SHALL also be one of each release's assets. A tool the device lacks SHALL give `null` for its values. CI SHALL run `shellcheck` on it and test its output on a fake root with no runtime, a native runtime with the plugin, a Docker-mode layout, a bridge with two instances and an install job log.

#### Scenario: Read-only
- **WHEN** the probe runs as a user without sudo rights
- **THEN** it exits 0, prints valid JSON, and no file on the device has changed

### Requirement: Locked dependency versions on the device
`install-stock.sh` SHALL take `--constraints FILE` and install the tools into `<prefix>/venv` with it. `install-runtime.sh` and `install-runtime.ps1` SHALL download the release's `canworks-<version>-constraints.txt` and pass it on. When no file is given and `uv` is on PATH, `install-stock.sh` SHALL export the constraints from the checkout's `tools/deploy/uv.lock`. Otherwise it SHALL say in one line that the dependency versions are not locked and install as before.

#### Scenario: Release install on the device
- **WHEN** release 0.110.0 is installed with `install-runtime.sh`
- **THEN** `pip freeze` in `/opt/canworks/venv` lists the versions of `canworks-0.110.0-constraints.txt` for every package that file names

#### Scenario: Checkout without uv
- **WHEN** `install-stock.sh` runs from a checkout with no `--constraints` and no `uv`
- **THEN** it says the dependency versions are not locked and installs as before

### Requirement: dcf-tools venv pinned
`build-lely.sh` SHALL install dcf-tools with the exact versions in `scripts/dcf-tools-constraints.txt`. That file SHALL name the Lely commit it was made for, and a test SHALL fail when the Lely commit changes without it.

#### Scenario: Lely commit bumped alone
- **WHEN** a change updates `_lely_dcf/VERSION` and not `scripts/dcf-tools-constraints.txt`
- **THEN** the test fails, naming both files
