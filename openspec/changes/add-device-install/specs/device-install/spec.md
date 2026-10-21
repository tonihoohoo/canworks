## ADDED Requirements

### Requirement: Devices workspace
The configurator SHALL have a **Devices** workspace next to Configure and Commission. It SHALL list the open project's devices, remembered on the PC per project folder in `devices.json` in the settings folder (host, port, SSH user, key choice, trusted host key, last probe result and its time; never a password), with **Add device…** and the devices runtime discovery finds that are not in the list yet. Selecting a device SHALL show its page: a header line with the SSH user, host, system, architecture, free disk and internet access, then one row per part (OpenPLC runtime, canworks plugin, Modbus bridge, remote link, CAN interfaces) with what the device has, what this project needs and that row's action. Parts the project's target does not use SHALL be shown muted with no action. A CODESYS project SHALL show one line that CODESYS installs its runtime itself and offer no action.

#### Scenario: OpenPLC project with an old plugin
- **WHEN** an OpenPLC project's device has plugin 0.93.4 and the newest release is 0.98.0
- **THEN** the plugin row says `0.93.4`, the project column says `newest 0.98.0`, and the main action is **Update 0.93.4 → 0.98.0**

#### Scenario: Bridge row in an OpenPLC project
- **WHEN** an OpenPLC project's device has no bridge
- **THEN** the Modbus bridge row is muted and has no action

#### Scenario: Remembered without a password
- **WHEN** a device was added with a password login and the configurator is restarted
- **THEN** the device is still listed with its host, user and host key, and `devices.json` holds no password

### Requirement: SSH connection and host key
The configurator SHALL connect to a device over SSH from its own process, the same way on Windows, macOS and Linux, using the user's SSH agent and default keys and the host, user and port from `~/.ssh/config` when the host is an alias there. On first contact it SHALL show the host key's SHA256 fingerprint and connect only after **Trust and connect**, and SHALL keep trusted keys in its own `known_hosts` in the settings folder. When a device answers with a different key it SHALL refuse to connect, say that the key changed and that a reinstalled device needs **Forget key**, and SHALL NOT replace the key by itself. When no key logs in it SHALL ask for the SSH password in a dialog. After a password login it SHALL offer **Use key login from now on**, which creates the PC's `canworks_ed25519` key in the settings folder once (readable by the user only) and adds its public key to the device user's `~/.ssh/authorized_keys` unless it is there already.

#### Scenario: New device
- **WHEN** the user adds `line4.local` for the first time
- **THEN** a dialog shows the key's fingerprint, and nothing is sent to the device before **Trust and connect**

#### Scenario: Reinstalled device
- **WHEN** a trusted device answers with another host key
- **THEN** the connection is refused with the changed-key message and **Forget key**, and the stored key is unchanged

#### Scenario: Key login set up
- **WHEN** the user logs in with a password and picks **Use key login from now on**
- **THEN** the next connection to that device logs in with the canworks key and asks no password, and `authorized_keys` has the key once

### Requirement: Passwords are never stored
The SSH password, the sudo password and the OpenPLC runtime's first user's password SHALL be used only for the request that needs them and SHALL NOT be written to any file, log, job log, browser storage or answer to the page. The sudo password SHALL reach the device only on the standard input of `sudo -S`. A device whose user is root or has password-less sudo SHALL not be asked for one.

#### Scenario: sudo with a password
- **WHEN** a job is started on a device whose user needs a sudo password
- **THEN** the confirmation asks for it, the job starts, and neither the settings folder, the configurator's log nor the device's job log contains it

### Requirement: Device probe
Before any change, the configurator SHALL read the device's state with a read-only probe that needs no root and no canworks on the device: `scripts/device-probe.sh`, shipped in the PC tools and run on the device from the connection's standard input, printing one JSON object with the system, architecture, systemd, free disk, memory, internet access to the release host, sudo mode, the OpenPLC runtime (none, native, managed Docker or other Docker; version; PLC state), the plugin (version, the runtime version it was built for, enabled in `plugins.conf` or not), the bridge (version, prefix, instances and their state), the remote link and discovery, CAN and vcan interfaces with state and bit rate, serial adapters, the `can-j1939` module and a running or last install job. A value the device cannot give SHALL be `null`, never a failed probe. **Check again** SHALL probe again.

#### Scenario: Fresh device
- **WHEN** the probe runs on a Linux device with no OpenPLC runtime and no canworks
- **THEN** it succeeds and reports `runtime: none`, `plugin: null` and the device's CAN interfaces

#### Scenario: Runtime moved on
- **WHEN** the runtime is v4.2.5 and the plugin was built for v4.2.4
- **THEN** the plugin row says it is off because it was built for v4.2.4, and the main action is **Rebuild for runtime v4.2.5**

### Requirement: One main action
Each device SHALL get at most one main action, chosen from the probe, the project's target and the newest `deploy-v` release X (found from the `releases/latest` redirect, as the install scripts do): **Install OpenPLC Runtime and canworks** (OpenPLC project, no runtime), **Install canworks X** (runtime, no plugin), **Update A → X** (plugin older than X), **Rebuild for runtime vN** (plugin built for another runtime version), **Install and start this project's bridge** (bridge project, no bridge), **Update A → X** (bridge older than X), **Start this project's bridge** (bridge current, no instance with this project's saved config), or none with "Up to date". The job SHALL install exactly the X the page named (`--version X`). When the PC tools are older than the canworks on the device, the page SHALL say so in one line with how to update the PC tools; it SHALL NOT block or downgrade. When the newest release cannot be found, the actions SHALL be disabled with that reason. An action the device cannot run SHALL be shown disabled with one sentence why: no systemd, no internet access, under 2 GB free, sudo refused, another install job running. The remote link, discovery and protocol options SHALL be folded under the main action, with the link and discovery on by default.

#### Scenario: PC tools older than the device
- **WHEN** the newest release and the device's plugin are 0.99.0 and the PC tools are 0.98.0
- **THEN** the plugin row says up to date and one line says to update the PC tools, with no install action

#### Scenario: No internet on the device
- **WHEN** the probe reports no access to the release host
- **THEN** the main action is disabled with "The device cannot reach github.com, which the install downloads from."

### Requirement: Confirm destructive effects only
Starting an action SHALL ask once, in one sentence per effect, only for effects that stop or lose something: a Docker-mode plugin install or update ("The PLC stops and comes back without a program; upload it again afterwards."), a bridge update ("Running bridges restart."), installing the OpenPLC runtime (names upstream's installer URL and that it installs Docker), and uninstalling. The same dialog SHALL take the sudo password when the probe says one is needed. An action with no such effect on a device with password-less sudo SHALL start without a dialog.

#### Scenario: Docker-mode update
- **WHEN** the user starts an update on a device with the managed Docker runtime
- **THEN** the dialog says the PLC stops and comes back without a program before anything runs

### Requirement: Install job on the device
An action SHALL run on the device as a detached systemd unit `canworks-install-<id>` under a lock (`/run/canworks-install.lock`), running the release's `install-runtime.sh` or `install-bridge.sh` with `--version` and the chosen options, its output in `/var/log/canworks-install/<id>.log`; the last five logs SHALL be kept. The job SHALL go on when the SSH connection drops, the PC sleeps or the configurator stops. The page SHALL show the steps from the scripts' step lines with their times, the elapsed time, the log folded, and **Stop** (stops the unit, then probes); the status bar SHALL list the job like other jobs. Opening the device's page again, also after a configurator restart, SHALL pick the job up from the probe and the log. A bridge action with this project's config SHALL copy the saved config folder to a temporary folder on the device first and pass it as `--instance <folder name> --config DIR`; the job SHALL remove that folder. A failed job SHALL show its exit status, the last 20 log lines and, for the failures the scripts name (no internet, disk full, apt locked, runtime not found, runtime image changed), one sentence on what to do.

#### Scenario: Laptop closed during a build
- **WHEN** the PC sleeps for ten minutes during a plugin build on a Raspberry Pi and then wakes
- **THEN** the build went on, and the device's page shows the finished or current step and the log since the start

#### Scenario: Second job refused
- **WHEN** another PC starts an install while one runs
- **THEN** the second job ends at once with "Another install is running on this device", and the first goes on

### Requirement: OpenPLC runtime and its first user
**Install OpenPLC Runtime and canworks** SHALL run `install-runtime.sh --with-openplc`. When the job ends and the runtime has no user, the page SHALL ask for the first user's name and password (twice), create the user through the runtime's API and SHALL NOT keep the password. A runtime that has users SHALL be left alone.

#### Scenario: Fresh Raspberry Pi
- **WHEN** the user runs **Install OpenPLC Runtime and canworks** on a Pi with no runtime and enters `admin` and a password afterwards
- **THEN** the managed Docker runtime runs, the plugin is installed for its version, the runtime accepts a login as `admin`, and the configurator's settings hold no password

### Requirement: After the job
When a job ends the configurator SHALL probe again and show the next step: for the plugin that canworks switches on with the next upload (the editor's Build and upload or `canworks-deploy`), and in Docker mode that the PLC has no program until then; for the bridge that it runs this project's config, with **Open in Commission**. The project's Online access runtime host SHALL be set to the device when it was empty.

#### Scenario: Bridge started
- **WHEN** **Install and start this project's bridge** ends without error
- **THEN** the bridge row shows the instance named after the project folder running, and the page offers **Open in Commission**

### Requirement: Uninstall from the device page
Each installed part SHALL have **Uninstall** (plugin: `install-runtime.sh --uninstall`; bridge: `install-bridge.sh --uninstall`), and the device's menu SHALL have **Remove everything** (both with `--purge`), each confirmed in one sentence and run as an install job. The OpenPLC runtime SHALL NOT be removed from the configurator. **Remove device** SHALL forget the device on this PC only.

#### Scenario: Remove the bridge
- **WHEN** the user uninstalls the bridge
- **THEN** its instances stop, the bridge row says not installed, and the runtime and plugin rows are unchanged
