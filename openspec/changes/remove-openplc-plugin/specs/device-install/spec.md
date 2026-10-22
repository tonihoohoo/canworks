## MODIFIED Requirements

### Requirement: Device probe
Before any change, the configurator SHALL read the device's state with a read-only probe that needs no root and no canworks on the device: `device-probe.sh`, shipped in the PC tools and run on the device from the connection's standard input, printing one JSON object with the system, architecture, systemd, free disk, memory, internet access to the release host, sudo mode, the OpenPLC runtime (none, native, managed Docker or other Docker; version; whether its HTTPS port answers), the bridge (version, prefix, whether its template unit is installed, instances and their state), the remote link and discovery, CAN and vcan interfaces with state and bit rate, serial adapters, the `can-j1939` module and a running or last install job. When the SSH user cannot read the managed runtime's spec or use Docker and sudo needs no password, the probe SHALL read them through `sudo -n`, read-only. An installed native unit that is not running SHALL count only when nothing points to a managed or other Docker runtime. A value the device cannot give SHALL be `null`, never a failed probe. **Check again** SHALL probe again. The probe SHALL NOT look for anything of canworks inside the runtime or its container.

#### Scenario: Fresh device
- **WHEN** the probe runs on a Linux device with no OpenPLC runtime and no canworks
- **THEN** it succeeds and reports `runtime: none`, `bridge: null` and the device's CAN interfaces

#### Scenario: Runtime moved on
- **WHEN** the device's runtime is v4.3.2 while the pin is v4.3.1, and the bridge is current
- **THEN** the runtime row shows the version note of "Tested runtime version", the bridge row says up to date, and no rebuild is offered

#### Scenario: Moved from native to managed Docker
- **WHEN** the device runs the managed Docker runtime v4.3.1, its old native unit is installed but stopped, and the SSH user can read neither the bootloader's folder nor Docker
- **THEN** the runtime row shows managed Docker v4.3.1 (read through password-less sudo, or with no version without it)

### Requirement: One main action
Each device SHALL get at most one main action, chosen from the probe, the project's target (or, with no config open, the role picked on the page) and the newest `deploy-v` release X (found from the `releases/latest` redirect, as the install scripts do): **Install OpenPLC Runtime and the bridge X** (OpenPLC project or role, no runtime), **Install the bridge X** (OpenPLC project or role with a runtime, or Modbus bridge role, no bridge), **Install and start this project's bridge** (project with a config, no bridge), **Update A → X** (bridge older than X), **Switch runtime to vP** (OpenPLC project or role, managed Docker runtime whose version is not the pinned runtime vP), **Start this project's bridge** (bridge current, no instance with this project's saved config), or none with "Up to date". With no config open, a device without the bridge SHALL show **What should this device run?** with **OpenPLC PLC with canworks** (first, picked; runtime and bridge) and **Modbus bridge** (bridge only), and the main action SHALL follow the pick; a device with the bridge SHALL get its main action from what is installed, with no question. The job SHALL install exactly the X the page named (`--version X`). When the canworks on the device has a newer major or minor version than the PC tools, the page SHALL say so in one line with an **Update PC tools…** button that checks for a release and offers the PC tools' own update (or the install command to copy); a patch-only difference SHALL NOT be mentioned. It SHALL NOT block or downgrade. When the newest release cannot be found, the actions SHALL be disabled with that reason. An action the device cannot run SHALL be shown disabled with one sentence why: no systemd, no internet access, under 2 GB free, sudo refused, another install job running. The remote link, discovery and protocol options SHALL be folded under the main action, with the link and discovery on by default.

#### Scenario: PC tools older than the device
- **WHEN** the newest release and the device's bridge are 0.99.0 and the PC tools are 0.98.0
- **THEN** the bridge row says up to date and one line says to update the PC tools, with **Update PC tools…** and no install action

#### Scenario: PC tools older by a patch only
- **WHEN** the device's bridge is 0.111.2 and the PC tools are 0.111.0
- **THEN** no line about the PC tools is shown

#### Scenario: No internet on the device
- **WHEN** the probe reports no access to the release host
- **THEN** the main action is disabled with "The device cannot reach github.com, which the install downloads from."

#### Scenario: Fresh device with no config
- **WHEN** no config is open, the device has no runtime and no bridge, and the newest release is 0.120.0
- **THEN** the page asks What should this device run? with OpenPLC PLC with canworks picked, and the main action is **Install OpenPLC Runtime and the bridge 0.120.0**; picking Modbus bridge changes it to **Install the bridge 0.120.0**

#### Scenario: Old plugin with no config
- **WHEN** no config is open and the device has bridge 0.115.0 while the newest release is 0.120.0
- **THEN** no role question is shown and the main action is **Update 0.115.0 → 0.120.0**

#### Scenario: Runtime updated from the Editor
- **WHEN** the pinned runtime is v4.3.1, a managed Docker device was moved to v4.3.2 from the OpenPLC Editor, and an OpenPLC project is open with its bridge current
- **THEN** the main action is **Switch runtime to v4.3.1**, and its job runs `install-bridge.sh --version X --pinned-runtime`

#### Scenario: Update keeps the device on the pin
- **WHEN** the user runs **Update 0.120.0 → 0.121.0** on a managed Docker device that runs the pinned runtime
- **THEN** the bridge is updated, and the runtime version is unchanged afterwards

### Requirement: Install job on the device
An action SHALL run on the device as a detached systemd unit `canworks-install-<id>` under a lock (`/run/canworks-install.lock`), running the release's `install-bridge.sh` with `--version` and the chosen options, its output in `/var/log/canworks-install/<id>.log`; the last five logs SHALL be kept. The job SHALL go on when the SSH connection drops, the PC sleeps or the configurator stops. The page SHALL show the steps from the script's step lines with their times, the elapsed time, the log folded, and **Stop** (stops the unit, then probes); the status bar SHALL list the job like other jobs. Opening the device's page again, also after a configurator restart, SHALL pick the job up from the probe and the log. An action with this project's config SHALL copy the saved config folder to a temporary folder on the device first and pass it as `--instance <folder name> --config DIR`; the job SHALL remove that folder. A failed job SHALL show its exit status, the last 20 log lines and, for the failures the script names (no internet, disk full, apt locked, runtime install failed), one sentence on what to do.

#### Scenario: Laptop closed during a build
- **WHEN** the PC sleeps for ten minutes during a bridge build on a Linux device and then wakes
- **THEN** the build went on, and the device's page shows the finished or current step and the log since the start

#### Scenario: Second job refused
- **WHEN** another PC starts an install while one runs
- **THEN** the second job ends at once with "Another install is running on this device", and the first goes on

### Requirement: OpenPLC runtime and its first user
**Install OpenPLC Runtime and the bridge** SHALL run `install-bridge.sh --with-openplc` (modbus-bridge "OpenPLC runtime installed with the bridge"). When the job ends and the runtime has no user, the page SHALL ask for the first user's name and password (twice), create the user through the runtime's API and SHALL NOT keep the password. A runtime that has users SHALL be left alone. **Switch runtime to vP** SHALL put a managed Docker runtime on the pinned version with upstream's bootloader, changing nothing else in the runtime.

#### Scenario: Fresh Linux device
- **WHEN** the user runs **Install OpenPLC Runtime and the bridge** on a Linux device with no runtime and enters `admin` and a password afterwards
- **THEN** the managed Docker runtime runs the pinned runtime version with the pinned bootloader and no canworks bind or plugin, the bridge runs next to it, the runtime accepts a login as `admin`, and the configurator's settings hold no password

#### Scenario: Upstream released a newer runtime
- **WHEN** the pin is v4.3.1 and upstream's newest runtime is v4.3.2
- **THEN** a fresh install records v4.3.1 in the bootloader spec and runs the `v4.3.1` image

#### Scenario: Release download fails
- **WHEN** the canworks release cannot be downloaded
- **THEN** the job fails before upstream's installer runs, and no runtime or Docker is installed

### Requirement: Uninstall from the device page
The bridge SHALL have **Uninstall** (`install-bridge.sh --uninstall`), and the device's menu SHALL have **Remove everything** (`--purge`), each confirmed in one sentence and run as an install job. The OpenPLC runtime SHALL NOT be removed from the configurator. **Remove device** SHALL forget the device on this PC only.

#### Scenario: Remove the bridge
- **WHEN** the user uninstalls the bridge
- **THEN** its instances stop, the bridge row says not installed, and the runtime row is unchanged

### Requirement: Runtime install names its version source
The confirmation for **Install OpenPLC Runtime and the bridge** SHALL name upstream's installer and the pinned runtime version it installs, and a test SHALL fail when the PC tools' pinned runtime version differs from `docker/local-runtime/runtime-version` or the bootloader pin differs from `docker/local-runtime/bootloader-version`.

#### Scenario: Install confirmation
- **WHEN** the user starts **Install OpenPLC Runtime and the bridge** with the pin v4.3.1
- **THEN** the confirmation names upstream's installer and says it installs OpenPLC runtime v4.3.1, the version canworks is tested with

### Requirement: Remote link and discovery switches
The device page SHALL give the remote link and the local-network advertisement their own actions, with and without a config open, when the bridge is installed on the device. The **Remote link** row SHALL offer **Turn on…** when the link is not installed, **Turn off…** when it is, and **Start** when it is installed but not running, and SHALL say which bridge instance it serves ("serves the bridge NAME"). A row **Found on the local network** SHALL show whether the advertisement is installed, with **Turn on…** or **Turn off…**. Each action SHALL run as an install job with the release's `install-link.sh` at the newest release X. Turning the link on SHALL serve the open project's instance, else the only bridge instance on the device; with several instances and no open project's instance, the dialog SHALL ask which instance. Turning the link off SHALL keep the link's key and paired PCs, and SHALL leave the advertisement (without the link ID) when discovery is on. In a CODESYS project, and on a device without the bridge, both rows SHALL have no action.

#### Scenario: Turn the link off and on again
- **WHEN** a device's link serves the bridge `line1` and one PC is paired, and the user turns the link off and then on
- **THEN** the link row reads not installed after the first job and "running · serves the bridge line1" after the second, the link ID is the same, and the PC is still paired

#### Scenario: Discovery off
- **WHEN** the user turns **Found on the local network** off on a device with the link running
- **THEN** the Avahi file is removed, the link keeps running, and the row offers **Turn on…**

#### Scenario: Two bridge instances, no config
- **WHEN** a device has two bridge instances `packer` and `line2`, no config is open, and the user turns the link on
- **THEN** the dialog asks which instance the link serves, and the job serves the picked one

#### Scenario: Nothing installed
- **WHEN** a device has no bridge
- **THEN** the Remote link and Found on the local network rows have no action

### Requirement: OpenPLC project on a device
For an OpenPLC project (a config with `bridge.openplc`), the device page SHALL show the OpenPLC runtime row and the bridge row, and the main action SHALL follow "One main action". The runtime SHALL be the pinned version and SHALL get nothing of canworks. The instance SHALL be named after the project folder.

#### Scenario: Fresh device
- **WHEN** an OpenPLC project is open and the device has no runtime and no bridge, and the newest release is 0.120.0
- **THEN** the main action is **Install OpenPLC Runtime and the bridge 0.120.0**, and after the job the device runs the pinned runtime with nothing of canworks inside it and `canworks-bridge@<project>` with the project's config

#### Scenario: Device with the old plugin
- **WHEN** an OpenPLC project is open and the device has the runtime and no bridge
- **THEN** the main action is **Install the bridge X**, and the page says nothing about a plugin

## REMOVED Requirements

### Requirement: Bridge beside the plugin
**Reason**: There is no plugin prefix for a bridge to be mistaken in.
**Migration**: None.

### Requirement: Plugin state before the first upload
**Reason**: The plugin and its `plugins.conf` line are removed.
**Migration**: None.

## ADDED Requirements

### Requirement: Device probe script
The PC tools package SHALL contain `canworks/devices/device-probe.sh`, a POSIX `sh` script that changes nothing, needs no root and no canworks on the device, and prints one JSON object describing the device as "Device probe" requires. It SHALL also be one of each release's assets. A tool the device lacks SHALL give `null` for its values. CI SHALL run `shellcheck` on it and test its output on a fake root with no runtime, a native runtime, a Docker-mode layout, a bridge with two instances and an install job log.

#### Scenario: Read-only
- **WHEN** the probe runs as a user without sudo rights
- **THEN** it exits 0, prints valid JSON, and no file on the device has changed
