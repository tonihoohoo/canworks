## MODIFIED Requirements

### Requirement: Choose what to edit
Started without arguments, the configurator SHALL open a start page with one line saying what the tool is for (setting up CANopen and J1939 networks for a PLC, and working on a CANopen device directly from the PC), two buttons, **Open…** and **New config…**, a link **Commission a device without a config**, and the **Recent** list as the page's main content. The page SHALL NOT show a folder browser of its own; Open… and New config… SHALL pick folders in the configurator's folder dialog.

Open… SHALL open the picked folder as an OpenPLC Editor project when it has `project.json` (editing its `canworks/` folder and checking addresses against its program), else as a config folder when it has `canworks.json`. A folder with neither SHALL get one question offering to start a new config there, which opens New config… with that folder filled in.

Each Recent entry SHALL show the folder's name, its path, a tag with the config's target (OpenPLC, Modbus bridge or CODESYS; none when the config cannot be read) and whether it is an editor project or a config folder, and when it was last opened when known. One click or Enter SHALL open it, and each entry SHALL have a Remove button that takes it off the list and leaves the folder alone. With nothing in Recent, the page SHALL show three short starting choices in its place, each in one sentence of plain words: open an OpenPLC project (Open…), start something new (New config…), and talk to a device with a USB CAN adapter (Commission). The start page SHALL NOT use the words "standalone", "canworks.json", "LSS" or "object dictionary".

A path given on the command line SHALL open directly, as a project when the folder has `project.json` and as a config folder otherwise. The current mode SHALL always be visible.

#### Scenario: Start page
- **WHEN** `canworks-config` runs without arguments in a 1280 px wide window and Recent has entries
- **THEN** the browser shows the purpose line, Open… and New config…, the Commission link and the Recent list, with no folder browser and no clipped text

#### Scenario: First run
- **WHEN** `canworks-config` runs with an empty Recent
- **THEN** the page shows the three starting choices instead of the list, and each runs the same action as Open…, New config… or the Commission link

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

### Requirement: Folders the configurator cannot use
Opening a folder the configurator cannot read, or saving where it cannot write, SHALL end with a message naming the folder and the reason in plain words, and the configurator SHALL stay where it was (the start page or the open config), usable without a restart. A folder is added to Recent only after it opened. Open… SHALL refuse a folder that does not exist. New config… SHALL refuse a folder that already has a `canworks.json` or `project.json`, offering to open it instead, and with "Also create an OpenPLC Editor project" SHALL refuse a folder that already exists.

#### Scenario: Unreadable folder
- **WHEN** the user opens a folder without read permission
- **THEN** the page says it cannot read the folder, stays on the start page, Recent does not list it, and the next request works

#### Scenario: Mistyped standalone path
- **WHEN** the user types a path that does not exist in the Open… dialog and uses it
- **THEN** the page says the folder does not exist and nothing opens

#### Scenario: New config where one exists
- **WHEN** the user creates a new config in a folder that already has `canworks.json`
- **THEN** nothing is written and the page offers to open that config

### Requirement: Target of a new config
New config… SHALL be one dialog that asks first what will run the networks, with three choices and one sentence each: OpenPLC Runtime (the canworks plugin runs the networks), Modbus bridge (no PLC; the values are served as Modbus TCP registers, naming Node-RED, HMIs and other Modbus TCP clients) and CODESYS (a CODESYS PLC runs the CANopen master). OpenPLC SHALL be preselected. The dialog SHALL then ask for a name (the new folder) and its location, with Choose… opening the folder dialog. For OpenPLC it SHALL offer "Also create an OpenPLC Editor project here", ticked by default when the editor's `openplc-cli` is found and disabled with the reason when it is not; ticked, the folder SHALL become a new OpenPLC Editor project, opened as a project with an empty config that is written to its `canworks/` folder on the first save. Otherwise the folder SHALL become a config folder with the target's empty config.

#### Scenario: New CODESYS config
- **WHEN** the user creates a new config with target CODESYS
- **THEN** the config is version 2 with a `codesys` object and the page shows the CODESYS target

#### Scenario: New Modbus bridge config
- **WHEN** the user creates a new config with target Modbus bridge
- **THEN** the config has a `bridge` object and the page shows the Modbus bridge target

#### Scenario: New OpenPLC config with an editor project
- **WHEN** `openplc-cli` is found and the user creates a new OpenPLC config in `~/plc/new-machine` with the editor-project tick on
- **THEN** `~/plc/new-machine` is an OpenPLC Editor project, and the page shows its empty config with the mode "project new-machine"

#### Scenario: No editor command-line tool
- **WHEN** `openplc-cli` is not found and the user picks OpenPLC
- **THEN** the editor-project tick is off and disabled with the reason, and Create makes a config folder
