## ADDED Requirements

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
Each adapter action SHALL run as an install job with the release's `install-adapter.sh` at the newest release X, which installs the PC tools in `/opt/canworks/venv` when `canworks-diag` is not there and installs the server as a service of the SSH user. A root SSH login SHALL be refused with one sentence to log in as a user with sudo. The first server SHALL use port 7536, a server on another interface the next free port from 7537.

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
The dialog SHALL let a SocketCAN interface that a bridge instance uses be served, with the bit rate locked to this project's bridge's when it is on that interface, and one line: "The bridge NAME is the master on IF: PCs with this project's config connect through the bridge; a PC's changes on this adapter need force while the bridge runs." A serial adapter that a running bridge instance or another adapter server uses SHALL be refused with one sentence why.

#### Scenario: Shared can0
- **WHEN** this project's bridge runs on can0 at 250 kbit/s and the user turns the remote CAN adapter on for can0
- **THEN** the bit rate shows 250 kbit/s and cannot be changed, the master line is shown, and after the job a PC scan through the adapter lists the bridge's nodes while the bridge keeps running
## MODIFIED Requirements

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

### Requirement: Uninstall from the device page
The bridge SHALL have **Uninstall** (`install-bridge.sh --uninstall`), and the device's menu SHALL have **Remove everything** (`--purge`, and every adapter server with `install-adapter.sh --uninstall`), each confirmed in one sentence and run as an install job. Neither SHALL touch anything on the device that is not canworks. **Remove device** SHALL forget the device on this PC only.

#### Scenario: Remove the bridge
- **WHEN** the user uninstalls the bridge on a device that also runs an OpenPLC runtime
- **THEN** its instances stop, the bridge row says not installed, and the runtime is unchanged

#### Scenario: Remove everything with an adapter server
- **WHEN** the user picks **Remove everything** on a device with the bridge and an adapter server on can0
- **THEN** the bridge, its configs, the remote link and `canworks-adapter-can0.service` with its Avahi file are gone, and the device's other programs are unchanged

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

### Requirement: Device probe script
The PC tools package SHALL contain `canworks/devices/device-probe.sh`, a POSIX `sh` script that changes nothing, needs no root and no canworks on the device, and prints one JSON object describing the device as "Device probe" requires. It SHALL also be one of each release's assets. A tool the device lacks SHALL give `null` for its values. CI SHALL run `shellcheck` on it and test its output on a fake root with nothing installed, a bridge with two instances and a backup folder next to them, an adapter server unit with its status file, and an install job log.

#### Scenario: Read-only
- **WHEN** the probe runs as a user without sudo rights
- **THEN** it exits 0, prints valid JSON, and no file on the device has changed
