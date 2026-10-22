## MODIFIED Requirements

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
