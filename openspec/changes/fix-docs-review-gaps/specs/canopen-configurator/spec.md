## MODIFIED Requirements

### Requirement: Choose what to edit
Started without arguments, the configurator SHALL open a start page with one line saying what the tool is for (configuring CANopen and J1939 networks for OpenPLC Runtime v4, and commissioning CANopen devices from the PC) and four choices: open an OpenPLC Editor project, open a standalone config folder, create a new standalone config, or commission a CANopen device. Each choice SHALL say in one or two short sentences what it opens and how it relates to OpenPLC: the project choice edits the `canworks/` folder of an OpenPLC Editor project and checks addresses against its program; a standalone config is used before an OpenPLC Editor project exists and can be moved into one later; commissioning needs no OpenPLC runtime. The choices SHALL sit in a grid with no lone card on a row of its own at desktop widths. The page SHALL let the user browse local folders and SHALL list recently opened ones. A path given on the command line SHALL open directly, as a project when the folder has `project.json` and as a standalone config otherwise. The current mode SHALL always be visible.

#### Scenario: Start page
- **WHEN** `canworks-config` runs without arguments in a 1280 px wide window
- **THEN** the browser shows the purpose line, the four choices in two rows of two, and the recent folders, and the project choice is titled "Open OpenPLC Editor project"

#### Scenario: Open a project from the start page
- **WHEN** the user chooses "Open OpenPLC Editor project" and picks `~/Documents/workspace/rtd-monitor`, which has `canworks/canworks.json`
- **THEN** the page shows that config with the mode "project rtd-monitor"

#### Scenario: Project without a config
- **WHEN** the user opens an OpenPLC Editor project that has no `canworks/` folder
- **THEN** the page shows an empty config and the project folder is unchanged until the user saves

#### Scenario: Not an editor project
- **WHEN** the user picks a folder without `project.json` under "Open OpenPLC Editor project"
- **THEN** the page says it is not an OpenPLC Editor project and offers to open it as a standalone config instead
