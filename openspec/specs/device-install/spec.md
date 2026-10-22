# device-install Specification

## Purpose
Installing what a project needs on a Linux device from the configurator over SSH: the Devices workspace, the read-only device probe, the one main action per device, and install jobs that run on the device by themselves, with no password ever kept.

## Requirements

### Requirement: Devices workspace
The configurator SHALL have a **Devices** workspace. It SHALL list this PC's devices, remembered in `devices.json` in the settings folder by host and port, the same list for every project and with no config open (host, port, SSH user, key choice, trusted host key, last probe result and its time; never a password), with **Add device…** and the devices runtime discovery finds that are not in the list yet. Each device in the list SHALL say what it is to which project, derived from the PC's settings and the last probe and not stored: **Runtime of** a project whose Online access runtime host is that device, and **Bridge of** a bridge instance the probe lists. With a config open, that project's devices SHALL be listed first and the others muted but selectable. Selecting a device SHALL show its page: a header line with the SSH user, host, system, architecture, free disk and internet access, then one row per part (OpenPLC runtime, canworks plugin, Modbus bridge, remote link, CAN interfaces) with what the device has and that row's action. With a config open each row SHALL also show what this project needs, and parts the project's target does not use SHALL be shown muted with no action; a CODESYS project SHALL show one line that CODESYS installs its runtime itself and offer no action. The page and its hints SHALL call the device a Linux device and SHALL NOT name a board brand.

#### Scenario: OpenPLC project with an old plugin
- **WHEN** an OpenPLC project's device has plugin 0.93.4 and the newest release is 0.98.0
- **THEN** the plugin row says `0.93.4`, the project column says `newest 0.98.0`, and the main action is **Update 0.93.4 → 0.98.0**

#### Scenario: Bridge row in an OpenPLC project
- **WHEN** an OpenPLC project's device has no bridge
- **THEN** the Modbus bridge row is muted and has no action

#### Scenario: Remembered without a password
- **WHEN** a device was added with a password login and the configurator is restarted
- **THEN** the device is still listed with its host, user and host key, and `devices.json` holds no password

#### Scenario: Same list in every project
- **WHEN** the user adds `line4.local` with no config open, then opens the config `line3`
- **THEN** Devices in `line3` lists `line4.local`, after `line3`'s own devices

#### Scenario: Project tags
- **WHEN** the config `line3`'s runtime host is `line3.local` and the last probe of `packer.local` lists a running bridge instance `packer`
- **THEN** the list shows `line3.local` with "Runtime of line3" and `packer.local` with "Bridge of packer"

#### Scenario: No board brand
- **WHEN** the Devices page shows its empty list, or a device that does not answer
- **THEN** its hints say "Linux device" and "SSH is on in the device", and name no board brand

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
Before any change, the configurator SHALL read the device's state with a read-only probe that needs no root and no canworks on the device: `device-probe.sh`, shipped in the PC tools and run on the device from the connection's standard input, printing one JSON object with the system, architecture, systemd, free disk, memory, internet access to the release host, sudo mode, the OpenPLC runtime (none, native, managed Docker or other Docker; version; whether its HTTPS port answers), the plugin (version, the runtime version it was built for, enabled in `plugins.conf` or not), the bridge (version, prefix, instances and their state), the remote link and discovery, CAN and vcan interfaces with state and bit rate, serial adapters, the `can-j1939` module and a running or last install job. When the SSH user cannot read the managed runtime's spec or use Docker and sudo needs no password, the probe SHALL read them through `sudo -n`, read-only. An installed native unit that is not running SHALL count only when nothing points to a managed or other Docker runtime. A value the device cannot give SHALL be `null`, never a failed probe. **Check again** SHALL probe again.

#### Scenario: Fresh device
- **WHEN** the probe runs on a Linux device with no OpenPLC runtime and no canworks
- **THEN** it succeeds and reports `runtime: none`, `plugin: null` and the device's CAN interfaces

#### Scenario: Runtime moved on
- **WHEN** the runtime is v4.2.5 and the plugin was built for v4.2.4
- **THEN** the plugin row says it is off because it was built for v4.2.4, and the main action is **Rebuild for runtime v4.2.5**

#### Scenario: Moved from native to managed Docker
- **WHEN** the device runs the managed Docker runtime v4.2.4, its old native unit is installed but stopped, and the SSH user can read neither the bootloader's folder nor Docker
- **THEN** the runtime row shows managed Docker v4.2.4 (read through password-less sudo, or with no version without it), the plugin's state comes from the Docker line, and no **Rebuild** is offered

### Requirement: One main action
Each device SHALL get at most one main action, chosen from the probe, the project's target (or, with no config open, the role picked on the page) and the newest `deploy-v` release X (found from the `releases/latest` redirect, as the install scripts do): **Install OpenPLC Runtime and canworks** (OpenPLC project or role, no runtime), **Install canworks X** (runtime, no plugin), **Update A → X** (plugin older than X), **Switch runtime to vP** (managed Docker runtime whose version is not the pinned runtime vP), **Rebuild for runtime vN** (plugin built for another runtime version, runtime not on managed Docker), **Install and start this project's bridge** (bridge project, no bridge), **Install the bridge X** (Modbus bridge role with no config, no bridge), **Update A → X** (bridge older than X), **Start this project's bridge** (bridge project, bridge current, no instance with this project's saved config), or none with "Up to date". With no config open, a device with neither the plugin nor the bridge SHALL show **What should this device run?** with **OpenPLC PLC with canworks** (first, picked) and **Modbus bridge**, and the main action SHALL follow the pick; a device that has the plugin or the bridge SHALL get its main action from what is installed, with no question, and the part it lacks (the bridge next to the plugin, the plugin next to the bridge) SHALL have Install… in its row, whose confirmation says the PLC and the bridge cannot share a CAN interface. The job SHALL install exactly the X the page named (`--version X`), and every plugin install, update, rebuild or switch on a managed Docker runtime SHALL put the runtime on the version that release is pinned to (`--pinned-runtime`). When the canworks on the device has a newer major or minor version than the PC tools, the page SHALL say so in one line with an **Update PC tools…** button that checks for a release and offers the PC tools' own update (or the install command to copy); a patch-only difference SHALL NOT be mentioned. It SHALL NOT block or downgrade. When the newest release cannot be found, the actions SHALL be disabled with that reason. An action the device cannot run SHALL be shown disabled with one sentence why: no systemd, no internet access, under 2 GB free, sudo refused, another install job running. The remote link, discovery and protocol options SHALL be folded under the main action, with the link and discovery on by default.

#### Scenario: PC tools older than the device
- **WHEN** the newest release and the device's plugin are 0.99.0 and the PC tools are 0.98.0
- **THEN** the plugin row says up to date and one line says to update the PC tools, with **Update PC tools…** and no install action

#### Scenario: PC tools older by a patch only
- **WHEN** the device's plugin is 0.111.2 and the PC tools are 0.111.0
- **THEN** no line about the PC tools is shown

#### Scenario: No internet on the device
- **WHEN** the probe reports no access to the release host
- **THEN** the main action is disabled with "The device cannot reach github.com, which the install downloads from."

#### Scenario: Fresh device with no config
- **WHEN** no config is open, the device has no runtime, no plugin and no bridge, and the newest release is 0.110.0
- **THEN** the page asks What should this device run? with OpenPLC PLC with canworks picked, and the main action is **Install OpenPLC Runtime and canworks 0.110.0**; picking Modbus bridge changes it to **Install the bridge 0.110.0**

#### Scenario: Old plugin with no config
- **WHEN** no config is open and the device has plugin 0.105.0 while the newest release is 0.110.0
- **THEN** no role question is shown and the main action is **Update 0.105.0 → 0.110.0**

#### Scenario: Runtime updated from the Editor
- **WHEN** the pinned runtime is v4.3.1, a managed Docker device was moved to v4.3.2 from the OpenPLC Editor, and its plugin is current and built for v4.3.1
- **THEN** the main action is **Switch runtime to v4.3.1**, not **Rebuild for runtime v4.3.2**, and its job runs `install-runtime.sh --version X --pinned-runtime`, which passes `--runtime-version v4.3.1` to `install-stock.sh`

#### Scenario: Update keeps the device on the pin
- **WHEN** the user runs **Update 0.110.0 → 0.111.0** on a managed Docker device that runs the pinned runtime
- **THEN** the job passes `--pinned-runtime`, and the runtime version is unchanged afterwards

### Requirement: Confirm destructive effects only
Starting an action SHALL ask once, in one sentence per effect, only for effects that stop or lose something: a Docker-mode plugin install, update or runtime switch ("The PLC stops and comes back without a program; upload it again afterwards."), a bridge update ("Running bridges restart."), installing the OpenPLC runtime (names upstream's installer URL, that it installs Docker, and the runtime version it installs), and uninstalling. The same dialog SHALL take the sudo password when the probe says one is needed. An action with no such effect on a device with password-less sudo SHALL start without a dialog.

#### Scenario: Docker-mode update
- **WHEN** the user starts an update on a device with the managed Docker runtime
- **THEN** the dialog says the PLC stops and comes back without a program before anything runs

#### Scenario: Runtime switch
- **WHEN** the user starts **Switch runtime to v4.3.1**
- **THEN** the dialog says the runtime goes back to v4.3.1, the version canworks is tested with, and that the PLC stops and comes back without a program

### Requirement: Install job on the device
An action SHALL run on the device as a detached systemd unit `canworks-install-<id>` under a lock (`/run/canworks-install.lock`), running the release's `install-runtime.sh` or `install-bridge.sh` with `--version` and the chosen options, its output in `/var/log/canworks-install/<id>.log`; the last five logs SHALL be kept. The job SHALL go on when the SSH connection drops, the PC sleeps or the configurator stops. The page SHALL show the steps from the scripts' step lines with their times, the elapsed time, the log folded, and **Stop** (stops the unit, then probes); the status bar SHALL list the job like other jobs. Opening the device's page again, also after a configurator restart, SHALL pick the job up from the probe and the log. A bridge action with this project's config SHALL copy the saved config folder to a temporary folder on the device first and pass it as `--instance <folder name> --config DIR`; the job SHALL remove that folder. A failed job SHALL show its exit status, the last 20 log lines and, for the failures the scripts name (no internet, disk full, apt locked, runtime not found, runtime image changed), one sentence on what to do.

#### Scenario: Laptop closed during a build
- **WHEN** the PC sleeps for ten minutes during a plugin build on a Linux device and then wakes
- **THEN** the build went on, and the device's page shows the finished or current step and the log since the start

#### Scenario: Second job refused
- **WHEN** another PC starts an install while one runs
- **THEN** the second job ends at once with "Another install is running on this device", and the first goes on

### Requirement: OpenPLC runtime and its first user
**Install OpenPLC Runtime and canworks** SHALL run `install-runtime.sh --with-openplc`, which SHALL download the canworks release before changing anything and SHALL then run upstream's installer with the release's pinned runtime and bootloader versions (`--runtime-version`, `--bootloader-version`). When the job ends and the runtime has no user, the page SHALL ask for the first user's name and password (twice), create the user through the runtime's API and SHALL NOT keep the password. A runtime that has users SHALL be left alone.

#### Scenario: Fresh Linux device
- **WHEN** the user runs **Install OpenPLC Runtime and canworks** on a Linux device with no runtime and enters `admin` and a password afterwards
- **THEN** the managed Docker runtime runs the pinned runtime version with the pinned bootloader, the plugin is installed for that version, the runtime accepts a login as `admin`, and the configurator's settings hold no password

#### Scenario: Upstream released a newer runtime
- **WHEN** the pin is v4.3.1 and upstream's newest runtime is v4.3.2
- **THEN** a fresh install records v4.3.1 in the bootloader spec and runs the `v4.3.1` image

#### Scenario: Release download fails
- **WHEN** the canworks release cannot be downloaded
- **THEN** the job fails before upstream's installer runs, and no runtime or Docker is installed

### Requirement: After the job
When a job ends the configurator SHALL probe again and show the next step: for the plugin that canworks switches on with the next upload (the editor's Build and upload or `canworks-deploy`), and in Docker mode that the PLC has no program until then; for a project's bridge that it runs this project's config, with **Open in Commission**; for a bridge installed with no config, that it starts with a config when that config's Devices page installs it there. With a config open, the project's Online access runtime host SHALL be set to the device when it was empty; with no config open, no project setting SHALL change.

#### Scenario: Bridge started
- **WHEN** **Install and start this project's bridge** ends without error
- **THEN** the bridge row shows the instance named after the project folder running, and the page offers **Open in Commission**

#### Scenario: Runtime installed with no config
- **WHEN** **Install OpenPLC Runtime and canworks** ends without error with no config open
- **THEN** the page asks for the runtime's first user as it does with a config, says canworks switches on with the next upload, and no project's runtime host changes

### Requirement: Uninstall from the device page
Each installed part SHALL have **Uninstall** (plugin: `install-runtime.sh --uninstall`; bridge: `install-bridge.sh --uninstall`), and the device's menu SHALL have **Remove everything** (both with `--purge`), each confirmed in one sentence and run as an install job. The OpenPLC runtime SHALL NOT be removed from the configurator. **Remove device** SHALL forget the device on this PC only.

#### Scenario: Remove the bridge
- **WHEN** the user uninstalls the bridge
- **THEN** its instances stop, the bridge row says not installed, and the runtime and plugin rows are unchanged

### Requirement: Bridge beside the plugin
The probe SHALL NOT report the `canworks-bridge` command in the plugin's own prefix (`/opt/canworks` with the plugin library) as a bridge when the bridge's template unit `canworks-bridge@.service` is not installed. The bridge object SHALL say whether that unit is installed. For a bridge project, a bridge without its unit SHALL get **Install and start this project's bridge**, and a bridge whose version is not a release version SHALL get **Update A → X**. The start job SHALL check for the unit first and, without it, end with a message that says to install the bridge.

#### Scenario: Plugin device, no bridge yet
- **WHEN** a device runs the canworks plugin under the managed Docker runtime, its `/opt/canworks/bin` has an old `canworks-bridge`, and no bridge unit is installed
- **THEN** the bridge row says not installed and the main action is **Install and start this project's bridge**

### Requirement: Bridge install and the device's remote link
The probe SHALL report the config the remote link serves. For a bridge install on a device whose remote link serves another config, the page SHALL grey the **Remote link** option with a hint that the link stays, and the job SHALL NOT pass `--with-link`.

#### Scenario: Bridge on a PLC device
- **WHEN** the device's remote link serves the PLC's config and the project is a bridge project
- **THEN** **Options** shows **Remote link** greyed with "The device's remote link serves another config (the PLC's) and stays as it is.", and the install leaves the link alone

### Requirement: Plugin state before the first upload
On a managed Docker runtime, when the plugin is installed and no upload has recorded its `plugins.conf` line yet (no `<prefix>/lib/plugins-line`), the probe SHALL report the plugin as not enabled, because the editor hook adds the line disabled until an upload. The plugin row SHALL then say "waiting for an upload". A recorded line that cannot be read SHALL stay unknown.

#### Scenario: Right after a fresh install
- **WHEN** **Install OpenPLC Runtime and canworks** has just finished and no program was uploaded yet
- **THEN** the plugin row reads "<version> · built for <runtime> · waiting for an upload"

### Requirement: Tested runtime version
The PC tools SHALL know the pinned OpenPLC runtime version, equal to `docker/local-runtime/runtime-version`. When the probe reports a runtime version other than the pin, newer or older, the runtime row SHALL say in one muted line that canworks runs on the pinned version and name the device's version. The note SHALL NOT block the main action. An equal or unknown runtime version SHALL show no note.

#### Scenario: Newer runtime
- **WHEN** the pin is v4.3.1 and the device runs v4.3.2
- **THEN** the runtime row says "canworks runs on runtime v4.3.1; this device runs v4.3.2."

#### Scenario: Older runtime
- **WHEN** the pin is v4.3.1 and the device runs v4.2.4
- **THEN** the runtime row says "canworks runs on runtime v4.3.1; this device runs v4.2.4."

#### Scenario: Tested runtime
- **WHEN** the device runs v4.3.1
- **THEN** the runtime row has no note

### Requirement: Runtime install names its version source
The confirmation for **Install OpenPLC Runtime and canworks** SHALL name upstream's installer and the pinned runtime version it installs, and a test SHALL fail when the PC tools' pinned runtime version differs from `docker/local-runtime/runtime-version` or the bootloader pin differs from `docker/local-runtime/bootloader-version`.

#### Scenario: Install confirmation
- **WHEN** the user starts **Install OpenPLC Runtime and canworks** with the pin v4.3.1
- **THEN** the confirmation names upstream's installer and says it installs OpenPLC runtime v4.3.1, the version canworks is tested with

### Requirement: Remote link and discovery switches
The device page SHALL give the remote link and the local-network advertisement their own actions, with and without a config open, when the canworks plugin or the bridge is installed on the device. The **Remote link** row SHALL offer **Turn on…** when the link is not installed, **Turn off…** when it is, and **Start** when it is installed but not running, and SHALL say which config it serves ("serves the PLC" for the plugin's config, "serves the bridge NAME" for a bridge instance). A row **Found on the local network** SHALL show whether the advertisement is installed, with **Turn on…** or **Turn off…**. Each action SHALL run as an install job with the release's `install-link.sh` at the newest release X. Turning the link on SHALL serve the plugin's config when the plugin is installed, else the open bridge project's instance, else the only bridge instance on the device; with several instances and none of these, the dialog SHALL ask which instance. Turning the link off SHALL keep the link's key and paired PCs, and SHALL leave the advertisement (without the link ID) when discovery is on. In a CODESYS project, and on a device with neither the plugin nor the bridge, both rows SHALL have no action.

#### Scenario: Turn the link off and on again
- **WHEN** a device's link serves the PLC and one PC is paired, and the user turns the link off and then on
- **THEN** the link row reads not installed after the first job and "running · serves the PLC" after the second, the link ID is the same, and the PC is still paired

#### Scenario: Discovery off
- **WHEN** the user turns **Found on the local network** off on a device with the link running
- **THEN** the Avahi file is removed, the link keeps running, and the row offers **Turn on…**

#### Scenario: Two bridge instances, no config
- **WHEN** a device has no plugin and two bridge instances `packer` and `line2`, no config is open, and the user turns the link on
- **THEN** the dialog asks which instance the link serves, and the job serves the picked one

#### Scenario: Nothing installed
- **WHEN** a device has neither the plugin nor the bridge
- **THEN** the Remote link and Found on the local network rows have no action

### Requirement: OpenPLC project on a device
For an OpenPLC project (a config with `bridge.openplc`), the device page SHALL show the OpenPLC runtime row and the bridge row, and the main action SHALL be **Install OpenPLC Runtime and this project's bridge** (no runtime), **Install and start this project's bridge** (runtime, no bridge), **Update A → X** (bridge older than X), **Start this project's bridge** (bridge current, no instance with this project's saved config), or none with "Up to date". The runtime SHALL be the pinned version and SHALL get no canworks plugin (`install-runtime.sh --with-openplc --bridge`). A device that still has the canworks plugin SHALL show in its row that the plugin is no longer used for this project, with Uninstall. The instance SHALL be named after the project folder.

#### Scenario: Fresh device
- **WHEN** an OpenPLC project is open and the device has no runtime and no bridge, and the newest release is 0.120.0
- **THEN** the main action is **Install OpenPLC Runtime and this project's bridge** for 0.120.0, and after the job the device runs the pinned runtime with no canworks plugin and `canworks-bridge@<project>` with the project's config

#### Scenario: Device with the old plugin
- **WHEN** an OpenPLC project is open and the device has the runtime with the canworks plugin and no bridge
- **THEN** the main action is **Install and start this project's bridge**, and the plugin row says it is no longer used and offers Uninstall
