## MODIFIED Requirements

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

### Requirement: One main action
Each device SHALL get at most one main action, chosen from the probe, the project's target (or, with no config open, the role picked on the page) and the newest `deploy-v` release X (found from the `releases/latest` redirect, as the install scripts do): **Install OpenPLC Runtime and canworks** (OpenPLC project or role, no runtime), **Install canworks X** (runtime, no plugin), **Update A → X** (plugin older than X), **Rebuild for runtime vN** (plugin built for another runtime version), **Install and start this project's bridge** (bridge project, no bridge), **Install the bridge X** (Modbus bridge role with no config, no bridge), **Update A → X** (bridge older than X), **Start this project's bridge** (bridge project, bridge current, no instance with this project's saved config), or none with "Up to date". With no config open, a device with neither the plugin nor the bridge SHALL show **What should this device run?** with **OpenPLC PLC with canworks** (first, picked) and **Modbus bridge**, and the main action SHALL follow the pick; a device that has the plugin or the bridge SHALL get its main action from what is installed, with no question. The job SHALL install exactly the X the page named (`--version X`). When the PC tools are older than the canworks on the device, the page SHALL say so in one line with how to update the PC tools; it SHALL NOT block or downgrade. When the newest release cannot be found, the actions SHALL be disabled with that reason. An action the device cannot run SHALL be shown disabled with one sentence why: no systemd, no internet access, under 2 GB free, sudo refused, another install job running. The remote link, discovery and protocol options SHALL be folded under the main action, with the link and discovery on by default.

#### Scenario: PC tools older than the device
- **WHEN** the newest release and the device's plugin are 0.99.0 and the PC tools are 0.98.0
- **THEN** the plugin row says up to date and one line says to update the PC tools, with no install action

#### Scenario: No internet on the device
- **WHEN** the probe reports no access to the release host
- **THEN** the main action is disabled with "The device cannot reach github.com, which the install downloads from."

#### Scenario: Fresh device with no config
- **WHEN** no config is open, the device has no runtime, no plugin and no bridge, and the newest release is 0.110.0
- **THEN** the page asks What should this device run? with OpenPLC PLC with canworks picked, and the main action is **Install OpenPLC Runtime and canworks 0.110.0**; picking Modbus bridge changes it to **Install the bridge 0.110.0**

#### Scenario: Old plugin with no config
- **WHEN** no config is open and the device has plugin 0.105.0 while the newest release is 0.110.0
- **THEN** no role question is shown and the main action is **Update 0.105.0 → 0.110.0**

### Requirement: After the job
When a job ends the configurator SHALL probe again and show the next step: for the plugin that canworks switches on with the next upload (the editor's Build and upload or `canworks-deploy`), and in Docker mode that the PLC has no program until then; for a project's bridge that it runs this project's config, with **Open in Commission**; for a bridge installed with no config, that it starts with a config when that config's Devices page installs it there. With a config open, the project's Online access runtime host SHALL be set to the device when it was empty; with no config open, no project setting SHALL change.

#### Scenario: Bridge started
- **WHEN** **Install and start this project's bridge** ends without error
- **THEN** the bridge row shows the instance named after the project folder running, and the page offers **Open in Commission**

#### Scenario: Runtime installed with no config
- **WHEN** **Install OpenPLC Runtime and canworks** ends without error with no config open
- **THEN** the page asks for the runtime's first user as it does with a config, says canworks switches on with the next upload, and no project's runtime host changes
