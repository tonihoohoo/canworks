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

### Requirement: Commission a device without a config
The configurator's start page SHALL offer "Commission a device", which opens the online pages on a USB adapter without any project or config: scan, object dictionary view (EDS from the scan match in the EDS library, or picked by the user), LSS, Parameters (backup, compare, restore, store) and Trace. "Add as node" SHALL be offered only when a config is open; instead the mode SHALL offer "Add to a config…", which picks a project or standalone config folder and opens it with the device added as an unsaved node (node ID, EDS imported, serial number, and LSS assignment ticked when the node ID was set by LSS in this session). The mode SHALL show a Steps panel listing Bit rate, Find the device, Node ID and bit rate, Identity and EDS, Write configuration, PDO test, Store, Verify after power cycle and Back up; each step SHALL open its panel and show done or skipped with a one-line result, steps SHALL be possible in any order or skipped, and none SHALL run by itself. In this mode the page SHALL show no config editing: no Project or Export menu, no Save, no Problems pane, and a side bar with only the online pages (Online, Scan the bus, Trace, Frame lab), so nothing suggests a config is being edited. This mode SHALL connect only through a USB adapter on this PC: the Connect form SHALL show the adapter form with no Runtime choice, whatever target the settings last held, and no text in this mode SHALL link to a page the mode does not show.

#### Scenario: New device on the desk
- **WHEN** the user opens "Commission a device", connects to a CANable at 250 kbit/s with "Allow changes" on, finds an unconfigured device with LSS and gives it node ID 12
- **THEN** a scan lists node 12, and nothing was stored on the device unless the user ticked "store"

#### Scenario: Nothing to save
- **WHEN** the user opens "Commission a device"
- **THEN** the header shows the mode badge, the theme choice and Close only, the side bar lists Online, Scan the bus, Trace and Frame lab, and no problem is reported

#### Scenario: Guided commissioning
- **WHEN** the user detects the bit rate, gives the device node ID 12 by LSS, writes a configuration from a DCF and backs it up
- **THEN** the Steps panel marks Bit rate, Node ID and bit rate, Write configuration and Back up as done with their results, and Store as not done

#### Scenario: Carry the device into a config
- **WHEN** the user presses "Add to a config…" after setting node ID 12 by LSS and picks a standalone config folder
- **THEN** that config opens with node 12 added as an unsaved node with the device's EDS, serial number and LSS assignment ticked

#### Scenario: Runtime choice not offered
- **WHEN** the user opens "Commission a device" on a PC whose online settings last used the Runtime target
- **THEN** the Online page shows the USB adapter form, with no Runtime choice and no "Online access is off for this config" text
