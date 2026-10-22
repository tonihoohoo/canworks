## MODIFIED Requirements

### Requirement: Choose what to edit
Started without arguments, the configurator SHALL open a start page with one line saying what the tool is for (setting up CANopen and J1939 networks for a PLC, working on a CANopen device directly from the PC, and installing canworks on a Linux device), two buttons, **Open…** and **New config…**, two links, **Commission a device without a config** and **Install on a device**, and the **Recent** list as the page's main content. The page SHALL NOT show a folder browser of its own; Open… and New config… SHALL pick folders in the configurator's folder dialog.

Open… SHALL open the picked folder as an OpenPLC Editor project when it has `project.json` (editing its `canworks/` folder and checking addresses against its program), else as a config folder when it has `canworks.json`. A folder with neither SHALL get one question offering to start a new config there, which opens New config… with that folder filled in.

Each Recent entry SHALL show the folder's name, its path, a tag with the config's target (OpenPLC, Modbus bridge or CODESYS; none when the config cannot be read) and whether it is an editor project or a config folder, and when it was last opened when known. One click or Enter SHALL open it, and each entry SHALL have a Remove button that takes it off the list and leaves the folder alone. With nothing in Recent, the page SHALL show four short starting choices in its place, each in one sentence of plain words: open an OpenPLC project (Open…), start something new (New config…), talk to a device with a USB CAN adapter (Commission), and set up a Linux device (Install on a device). The start page SHALL NOT use the words "standalone", "canworks.json", "LSS" or "object dictionary", and SHALL NOT name a board brand.

A path given on the command line SHALL open directly, as a project when the folder has `project.json` and as a config folder otherwise. The current mode SHALL always be visible.

#### Scenario: Start page
- **WHEN** `canworks-config` runs without arguments in a 1280 px wide window and Recent has entries
- **THEN** the browser shows the purpose line, Open… and New config…, the Commission and Install on a device links and the Recent list, with no folder browser and no clipped text

#### Scenario: First run
- **WHEN** `canworks-config` runs with an empty Recent
- **THEN** the page shows the four starting choices instead of the list, and each runs the same action as Open…, New config…, the Commission link or the Install on a device link

#### Scenario: Open a project from the start page
- **WHEN** the user chooses Open… and picks `~/Documents/workspace/rtd-monitor`, which has `project.json` and `canworks/canworks.json`
- **THEN** the page shows that config with the mode "project rtd-monitor"

#### Scenario: Open a config folder
- **WHEN** the user chooses Open… and picks `~/canworks/rtd`, which has `canworks.json` and no `project.json`
- **THEN** the page shows that config as a config folder

#### Scenario: Project without a config
- **WHEN** the user opens an OpenPLC Editor project that has no `canworks/` folder
- **THEN** the page shows an empty config and the project folder is unchanged until the user saves

#### Scenario: Not an editor project
- **WHEN** the user chooses Open… and picks a folder with neither `project.json` nor `canworks.json`
- **THEN** the page asks whether to start a new config there, and Yes opens New config… with that folder

#### Scenario: Recent shows the target
- **WHEN** Recent holds a Modbus bridge config folder and a CODESYS config
- **THEN** their entries are tagged "Modbus bridge" and "CODESYS", and one click on either opens it

### Requirement: Devices in the header and from other pages
The header's workspace switch SHALL read **Configure | Commission | Devices** while a config is open, with Devices as described by the `device-install` capability. The start page's **Install on a device** SHALL open Devices with no config: the header SHALL show the mode "Devices · no config" and no workspace switch, Save, Export or Project menus, and **Close** SHALL return to the start page. While a project is open, its devices SHALL also be reachable from the pages that need them: Online access's **Runtime host** SHALL show the state of the device with that host (for example `canworks 0.93.4, off`) with **Open in Devices**; the Modbus bridge page SHALL show where the bridge runs and its state, with **Install on device…** when no device runs it; Commission's connect panel, when it lists no runtime, SHALL offer **Install canworks on a device…**; the status bar SHALL list a running install job with **Show**. Commission a CANopen device (no config) SHALL show no Devices workspace.

#### Scenario: Host with an old plugin
- **WHEN** Online access's runtime host is a device of the project whose last probe found plugin 0.93.4 off
- **THEN** the field shows `canworks 0.93.4, off` and **Open in Devices** opens that device's page

#### Scenario: Bridge not installed
- **WHEN** a bridge project has no device running its bridge
- **THEN** the Modbus bridge page shows **Install on device…**, which opens Devices with Add device or the project's device selected

#### Scenario: Devices from the start page
- **WHEN** the user presses Install on a device on the start page
- **THEN** Devices opens with the PC's device list, the mode reads "Devices · no config", and Close returns to the start page
