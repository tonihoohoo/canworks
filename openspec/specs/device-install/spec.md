# device-install Specification

## Purpose
Installing what a project needs on a Linux device from the configurator over SSH: the Devices workspace, the read-only device probe, the one main action per device, and install jobs that run on the device by themselves, with no password ever kept.

## Requirements

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
The SSH password and the sudo password SHALL be used only for the request that needs them and SHALL NOT be written to any file, log, job log, browser storage or answer to the page. The sudo password SHALL reach the device only on the standard input of `sudo -S`. A device whose user is root or has password-less sudo SHALL not be asked for one.

#### Scenario: sudo with a password
- **WHEN** a job is started on a device whose user needs a sudo password
- **THEN** the confirmation asks for it, the job starts, and neither the settings folder, the configurator's log nor the device's job log contains it

### Requirement: Device probe
Before any change, the configurator SHALL read the device's state with a read-only probe that needs no root and no canworks on the device: `device-probe.sh`, shipped in the PC tools and run on the device from the connection's standard input, printing one JSON object with the system, architecture, systemd, free disk, memory, internet access to the release host, sudo mode, the bridge (version, prefix, whether its template unit is installed, instances and their state), the remote link and discovery, CAN and vcan interfaces with state and bit rate, serial adapters, the `can-j1939` module, the adapter servers (each `canworks-adapter-*.service` unit with its state, adapter, bit rate, port, whether it allows changes and, when the SSH user can read the service user's status file, the connected PCs) and a running or last install job. A bridge instance SHALL be a folder under `/etc/canworks-bridge/` whose name the installer accepts as an instance name (letters, digits, `-` and `_` only) and that holds `canworks.json`; other folders, such as backup copies, SHALL be ignored. The probe SHALL NOT look for the OpenPLC runtime, Docker or any other program that is not canworks, and its JSON SHALL have no `runtime` key. A value the device cannot give SHALL be `null`, never a failed probe. **Check again** SHALL probe again.

#### Scenario: Fresh device
- **WHEN** the probe runs on a Linux device with no canworks
- **THEN** it succeeds and reports `bridge: null` and the device's CAN interfaces, and runs neither `docker` nor `sudo`

#### Scenario: Backup folders
- **WHEN** `/etc/canworks-bridge/` holds `line1/`, `line1.bak-271/` and `line1.trimmed/`, each with a `canworks.json`
- **THEN** the probe lists one instance, `line1`

#### Scenario: Device with an OpenPLC runtime
- **WHEN** the device also runs an OpenPLC runtime
- **THEN** the probe's JSON says nothing about it, and the device page shows no row for it

#### Scenario: Runtime moved on
- **WHEN** the device's OpenPLC runtime was moved to another version and the bridge is current
- **THEN** the device page shows no runtime row and no runtime note, and the bridge row says up to date

#### Scenario: Moved from native to managed Docker
- **WHEN** the device has an old native OpenPLC unit next to the managed Docker runtime, and the SSH user can use neither Docker nor the bootloader's folder
- **THEN** the probe runs no `sudo` and no `docker`, and its JSON has no `runtime` key

#### Scenario: Adapter server installed by hand
- **WHEN** a device has `canworks-adapter-can0.service` running `adapter-serve --adapter socketcan:can0 --bitrate 500 --port 7536 --allow-changes` as the SSH user, and one PC is connected
- **THEN** the probe lists one adapter server with adapter `socketcan:can0`, 500 kbit/s, port 7536, active, changes allowed and one connected PC, without sudo

### Requirement: One main action
Each device SHALL get at most one main action, chosen from the probe, the project's target and the newest `deploy-v` release X (found from the `releases/latest` redirect, as the install scripts do): **Install and start this project's bridge** (a bridge project, OpenPLC connection or not, and no bridge), **Install the bridge X** (no config open, no bridge), **Update A → X** (bridge older than X), **Start this project's bridge** (bridge current, no running instance with this project's saved config), or none with "Up to date". With no config open, a device without the bridge SHALL show **Install the bridge X** with one line that a config's own Devices page starts the bridge with that config, and SHALL ask no question about what the device runs; a device with the bridge SHALL get its main action from what is installed. The configurator SHALL NOT install, update, switch or remove the OpenPLC runtime or any other program that is not canworks. The job SHALL install exactly the X the page named (`--version X`). When the canworks on the device has a newer major or minor version than the PC tools, the page SHALL say so in one line with an **Update PC tools…** button that checks for a release and offers the PC tools' own update (or the install command to copy); a patch-only difference SHALL NOT be mentioned. It SHALL NOT block or downgrade. When the newest release cannot be found, the actions SHALL be disabled with that reason. An action the device cannot run SHALL be shown disabled with one sentence why: no systemd, no internet access, under 2 GB free, sudo refused, another install job running. The remote link, discovery and protocol options SHALL be folded under the main action, with the link and discovery on by default.

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
- **WHEN** no config is open, the device has no bridge, and the newest release is 0.120.0
- **THEN** the main action is **Install the bridge 0.120.0**, and no question about what the device runs is shown

#### Scenario: Old plugin with no config
- **WHEN** no config is open and the device has bridge 0.115.0 while the newest release is 0.120.0
- **THEN** the main action is **Update 0.115.0 → 0.120.0**

#### Scenario: OpenPLC project on a fresh device
- **WHEN** a config with an OpenPLC connection is open, the device has no bridge, and the newest release is 0.120.0
- **THEN** the main action is **Install and start this project's bridge**, and no action installs or changes the OpenPLC runtime

#### Scenario: Runtime updated from the Editor
- **WHEN** a config with an OpenPLC connection is open, its bridge is current and running its saved config, and the device's runtime was moved to another version from the OpenPLC Editor
- **THEN** the device is "Up to date", and no action switches the runtime

#### Scenario: Update keeps the device on the pin
- **WHEN** the user runs **Update 0.120.0 → 0.121.0** on a device with the managed Docker OpenPLC runtime
- **THEN** the bridge is updated, and the runtime's version and containers are unchanged afterwards

### Requirement: Confirm destructive effects only
Starting an action SHALL ask once, in one sentence per effect, only for effects that stop or lose something: a bridge update ("Running bridges restart.") and uninstalling. The same dialog SHALL take the sudo password when the probe says one is needed. An action with no such effect on a device with password-less sudo SHALL start without a dialog.

#### Scenario: Docker-mode update
- **WHEN** the user starts an update on a device with a running bridge instance and the managed Docker OpenPLC runtime
- **THEN** the dialog says only that running bridges restart, and nothing about the PLC

#### Scenario: Runtime switch
- **WHEN** the user starts any action on any device
- **THEN** no dialog names a runtime version, upstream's runtime installer or Docker

#### Scenario: First install
- **WHEN** the user starts **Install the bridge X** on a device with password-less sudo
- **THEN** the job starts without a dialog

### Requirement: Install job on the device
An action SHALL run on the device as a detached systemd unit `canworks-install-<id>` under a lock (`/run/canworks-install.lock`), running the release's `install-bridge.sh` with `--version` and the chosen options, its output in `/var/log/canworks-install/<id>.log`; the last five logs SHALL be kept. The job SHALL go on when the SSH connection drops, the PC sleeps or the configurator stops. The page SHALL show the steps from the script's step lines with their times, the elapsed time, the log folded, and **Stop** (stops the unit, then probes); the status bar SHALL list the job like other jobs. Opening the device's page again, also after a configurator restart, SHALL pick the job up from the probe and the log. An action with this project's config SHALL copy the saved config folder to a temporary folder on the device first and pass it as `--instance <folder name> --config DIR`; the job SHALL remove that folder. A failed job SHALL show its exit status, the last 20 log lines and, for the failures the script names (no internet, disk full, apt locked), one sentence on what to do.

#### Scenario: Laptop closed during a build
- **WHEN** the PC sleeps for ten minutes during a bridge build on a Linux device and then wakes
- **THEN** the build went on, and the device's page shows the finished or current step and the log since the start

#### Scenario: Second job refused
- **WHEN** another PC starts an install while one runs
- **THEN** the second job ends at once with "Another install is running on this device", and the first goes on

### Requirement: After the job
When a job ends the configurator SHALL probe again and show the next step: for a project's bridge that it runs this project's config, with **Open in Commission**; for a bridge installed with no config, that it starts with a config when that config's Devices page installs it there. With a config open, the project's Online access runtime host SHALL be set to the device when it was empty; with no config open, no project setting SHALL change.

#### Scenario: Bridge started
- **WHEN** **Install and start this project's bridge** ends without error
- **THEN** the bridge row shows the instance named after the project folder running, and the page offers **Open in Commission**

#### Scenario: Bridge installed with no config
- **WHEN** **Install the bridge X** ends without error with no config open
- **THEN** the page says the bridge starts with a config when that config's Devices page installs it, asks for nothing more, and no project's runtime host changes

#### Scenario: Runtime installed with no config
- **WHEN** a job ends with no config open on a device that has an OpenPLC runtime with no user
- **THEN** the page asks for no runtime user, and no project's runtime host changes

### Requirement: Uninstall from the device page
The bridge SHALL have **Uninstall** (`install-bridge.sh --uninstall`), and the device's menu SHALL have **Remove everything** (`--purge`, and every adapter server with `install-adapter.sh --uninstall`), each confirmed in one sentence and run as an install job. Neither SHALL touch anything on the device that is not canworks. **Remove device** SHALL forget the device on this PC only.

#### Scenario: Remove the bridge
- **WHEN** the user uninstalls the bridge on a device that also runs an OpenPLC runtime
- **THEN** its instances stop, the bridge row says not installed, and the runtime is unchanged

#### Scenario: Remove everything with an adapter server
- **WHEN** the user picks **Remove everything** on a device with the bridge and an adapter server on can0
- **THEN** the bridge, its configs, the remote link and `canworks-adapter-can0.service` with its Avahi file are gone, and the device's other programs are unchanged

### Requirement: Bridge install and the device's remote link
The probe SHALL report the config the remote link serves. For a bridge install on a device whose remote link serves another config, the page SHALL grey the **Remote link** option with a hint that the link stays, and the job SHALL NOT pass `--with-link`.

#### Scenario: Bridge on a PLC device
- **WHEN** the device's remote link serves the PLC's config and the project is a bridge project
- **THEN** **Options** shows **Remote link** greyed with "The device's remote link serves another config (the PLC's) and stays as it is.", and the install leaves the link alone

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

### Requirement: Device probe script
The PC tools package SHALL contain `canworks/devices/device-probe.sh`, a POSIX `sh` script that changes nothing, needs no root and no canworks on the device, and prints one JSON object describing the device as "Device probe" requires. It SHALL also be one of each release's assets. A tool the device lacks SHALL give `null` for its values. CI SHALL run `shellcheck` on it and test its output on a fake root with nothing installed, a bridge with two instances and a backup folder next to them, an adapter server unit with its status file, and an install job log.

#### Scenario: Read-only
- **WHEN** the probe runs as a user without sudo rights
- **THEN** it exits 0, prints valid JSON, and no file on the device has changed

### Requirement: Devices workspace for the bridge
The configurator SHALL have a **Devices** workspace for the canworks parts of a Linux device. It SHALL list this PC's devices, remembered in `devices.json` in the settings folder by host and port, the same list for every project and with no config open (host, port, SSH user, key choice, trusted host key, last probe result and its time; never a password), with **Add device…** and the devices runtime discovery finds that are not in the list yet. Each device in the list SHALL show its status (the main action's label, "Up to date", "Nothing installed yet" or why it was not reached) and one summary line of its bridge instances, derived from the last probe and not stored: **This project's bridge** when the open project's instance is on the device; otherwise the running instances by name followed by `running`, then `N stopped` for the other instances; `N bridges stopped` when none runs; nothing without the bridge. The list SHALL NOT tag devices by other projects' Online access settings. With a config open, that project's devices (its Online access runtime host or its bridge instance) SHALL be listed first and the others muted but selectable. Selecting a device SHALL show its page: a header line with the SSH user, host, system, architecture, free disk and internet access, then one row per canworks part (Modbus bridge, remote link, found on the local network, CAN interfaces, remote CAN adapter) with what the device has and that row's action, and no row for the OpenPLC runtime or another program. With a config open each row SHALL also show what this project needs, and parts the project's target does not use SHALL be shown muted with no action; a CODESYS project SHALL show one line that CODESYS installs its runtime itself and offer no action. The workspace's intro and the start page's entries SHALL describe installing the Modbus bridge, its remote link and local network discovery, and turning on the remote CAN adapter, and SHALL NOT offer to install the OpenPLC runtime. The page and its hints SHALL call the device a Linux device and SHALL NOT name a board brand.

#### Scenario: OpenPLC project with an old bridge
- **WHEN** a project with an OpenPLC connection has a device with bridge 0.93.4 and the newest release is 0.98.0
- **THEN** the bridge row says `0.93.4`, the project column says `newest 0.98.0`, and the main action is **Update 0.93.4 → 0.98.0**

#### Scenario: Bridge row in an OpenPLC project
- **WHEN** a project with an OpenPLC connection has a device with no bridge
- **THEN** the Modbus bridge row says it is needed with this project's config, and the main action is **Install and start this project's bridge**

#### Scenario: Remembered without a password
- **WHEN** a device was added with a password login and the configurator is restarted
- **THEN** the device is still listed with its host, user and host key, and `devices.json` holds no password

#### Scenario: Same list in every project
- **WHEN** the user adds `line4.local` with no config open, then opens the config `line3`
- **THEN** Devices in `line3` lists `line4.local`, after `line3`'s own devices

#### Scenario: Summary line
- **WHEN** no config is open and the last probe of `packer.local` lists the running instance `packer` and the stopped instance `test`
- **THEN** the list shows `packer.local` with "packer running · 1 stopped", and no "Runtime of" or "Bridge of" tags

#### Scenario: Own project's device
- **WHEN** the config `packer` is open and its instance `packer` is on `packer.local`
- **THEN** `packer.local` is listed first with "This project's bridge"

#### Scenario: Project tags
- **WHEN** the config `line3` is open with the runtime host `line3.local`, and the last probe of `packer.local` lists the running instance `packer`
- **THEN** `line3.local` is listed first with no "Runtime of" tag, and `packer.local` shows "packer running"

#### Scenario: No board brand
- **WHEN** the Devices page shows its empty list, or a device that does not answer
- **THEN** its hints say "Linux device" and "SSH is on in the device", and name no board brand

### Requirement: Remote CAN adapter row
The device page SHALL have a row **Remote CAN adapter**, also with no config and no bridge, listing each adapter server found (interface, bit rate, port, running, changes allowed, PCs connected when known), or `off`. A device with a CAN interface or serial adapter and no server SHALL offer **Turn on…**; a server **Change…**, **Connect from this PC** while running and **Turn off…**; a free interface **Add…**. In a CODESYS project the row SHALL be muted with no action.

#### Scenario: Turn off
- **WHEN** the user turns the remote CAN adapter off
- **THEN** the service and its Avahi file are removed, the row reads `off`, and `canworks-diag --adapter socketcan:can0` on the device can open the interface

### Requirement: Remote CAN adapter dialog
**Turn on…**, **Add…** and **Change…** SHALL ask in one screen for the interface (the probe's CAN interfaces and serial adapters), the bit rate (required, never guessed; prefilled from this project's bridge on that interface, else the interface's current rate when up, else the open config's network), **Allow changes from PCs** (ticked by default; unticked, the server refuses changes for every PC) and **Advertise on the local network** (ticked by default).

#### Scenario: Change to read-only
- **WHEN** the user unticks **Allow changes from PCs** with **Change…** on a running server
- **THEN** the service restarts read-only, the row says `read-only`, and this PC connects with the token it already had

### Requirement: Remote CAN adapter job
Each adapter action SHALL run as an install job with the release's `install-adapter.sh` at the newest release X, which installs the release's PC tools in `/opt/canworks-adapter/venv` when they are not there and installs the server as a service of the SSH user. A root SSH login SHALL be refused with one sentence to log in as a user with sudo. The first server SHALL use port 7536, a server on another interface the next free port from 7537.

#### Scenario: Turn on with no config
- **WHEN** no config is open, the device has can0 up at 500 kbit/s and no bridge, and the user turns the remote CAN adapter on with the defaults
- **THEN** the job installs the PC tools and the service, and the row reads `can0 · 500 kbit/s · running · changes allowed`

### Requirement: Remote CAN adapter token
Turning a server on from the device page SHALL make the token on the PC, keep it in `online.json` under that server's host and port as **Adapter on another machine** does, and upload only its verifier (`--token-verifier-file`). The plain token SHALL NOT reach the device or its job log. **Change…** SHALL keep the server's token.

#### Scenario: No token in the job log
- **WHEN** the user turns the remote CAN adapter on
- **THEN** neither the job log nor any file on the device contains the token, `adapter-serve.json` of the SSH user holds its verifier, and this PC's `online.json` holds the token for that host

### Requirement: New token and Copy token
On a PC without the token of a running server the row SHALL offer **New token…**, confirmed with "Every other PC must enter the new token", which uploads a new verifier and restarts the server. A PC that has the token SHALL get **Copy token**, the only answer of the page that carries it.

#### Scenario: Another PC
- **WHEN** a second PC opens the device page of a server another PC turned on
- **THEN** the row offers **New token…** and no **Copy token**, and after **New token…** the first PC's next connect asks for the token

### Requirement: Connect from the device page
**Connect from this PC** on the row, and in the notice after a job that turned a server on, SHALL open the connect panel on **Adapter on another machine** with the device's host and the server's port filled in; with no config open it SHALL open **Commission a CANopen device** first. Connecting SHALL then work as with a USB adapter: the server's bit rate check, read-only unless **Allow changes** is ticked in the panel or **Unlock…** is pressed later.

#### Scenario: One click after turning on
- **WHEN** a job that turned the server on ends and the user presses **Connect from this PC**, then **Connect**
- **THEN** the PC connects to the server without asking for a token, read-only, and the connection bar shows `socketcan:can0 on HOST`

### Requirement: Remote CAN adapter next to the bridge
The dialog SHALL let a SocketCAN interface that a bridge instance uses be served, with the bit rate locked to this project's bridge's when it is on that interface, and one line: "The bridge NAME is the master on IF: PCs with this project's config connect through the bridge; a PC's changes on this adapter need force while the bridge runs." A serial adapter that this project's running bridge uses SHALL be refused with one sentence why, and a served one SHALL NOT be offered again.

#### Scenario: Shared can0
- **WHEN** this project's bridge runs on can0 at 250 kbit/s and the user turns the remote CAN adapter on for can0
- **THEN** the bit rate shows 250 kbit/s and cannot be changed, the master line is shown, and after the job a PC scan through the adapter lists the bridge's nodes while the bridge keeps running
