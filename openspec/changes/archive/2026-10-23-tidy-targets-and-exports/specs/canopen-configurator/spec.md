## ADDED Requirements

### Requirement: Where things are
The configurator SHALL place its parts by one rule. The Project page holds the target and actions on the whole project. The header's primary target button puts the config onto the target. Export ▾ holds every file written for download, apart from one item's export on its own page (slave EDS, device notes). A target page holds that target's settings. Copy as ST call stays on its item. `docs/configurator.md` SHALL state this rule.

#### Scenario: Node-RED flow
- **WHEN** a user of a Modbus bridge config looks for the Node-RED flow
- **THEN** it is in Export ▾ under For the program, and the Modbus bridge page has no export buttons

### Requirement: Export menu groups
Export ▾ SHALL have two labelled groups. **Network files** SHALL hold All DCFs, This node's DCF, DBC and Documentation. **For the program** SHALL hold the target's own files, and a group with no item SHALL be hidden: Modbus bridge gets Register map (CSV), Register map (JSON), ST variables and Node-RED flow; OpenPLC gets the two register map files and ST for another PLC (the PLC link file); CODESYS gets Download for CODESYS.

#### Scenario: OpenPLC config
- **WHEN** the user opens Export ▾ on an OpenPLC config
- **THEN** For the program lists Register map (CSV), Register map (JSON) and ST for another PLC, and no Node-RED flow

#### Scenario: Node-RED flow from the menu
- **WHEN** the user picks Node-RED flow in Export ▾ on a Modbus bridge config with a valid map
- **THEN** the browser downloads `<config name>-node-red.json`, equal to the command-line export of the same config

#### Scenario: CODESYS download from the menu
- **WHEN** the user picks Download for CODESYS in Export ▾ on a CODESYS config
- **THEN** the browser downloads `<config folder name>_codesys.zip` as Download on the CODESYS page does

### Requirement: Same files from the menu
Each For the program item SHALL download the same file as before: the `canworks-deploy --export-modbus-map` formats, `--export-nodered` with default host and period, and the `codesys-export` zip. When the register map or the export cannot be computed, it SHALL show the reason instead of a file.

#### Scenario: Map cannot be computed
- **WHEN** the register map of a Modbus bridge config has an error and the user picks Register map (CSV)
- **THEN** nothing downloads and the reason is shown as "Exports report progress and keep Problems clean" says

### Requirement: Editor project on the Project page
The Project page of an OpenPLC config SHALL have an **Editor project** section under the target, and other targets SHALL NOT have it. In project mode it SHALL name the project, its folder and the files Save writes into it. In standalone mode it SHALL say there is no editor project, so PLC addresses are not checked, and offer **Move into project…** and **New editor project…** with their existing dialogs.

#### Scenario: Standalone OpenPLC config
- **WHEN** a standalone OpenPLC config's Project page is open
- **THEN** the Editor project section offers Move into project… and New editor project…, and the header has no Project menu

#### Scenario: Modbus bridge config
- **WHEN** a Modbus bridge config's Project page is open
- **THEN** it has no Editor project section

### Requirement: Header menus stay inside the window
A header menu's panel SHALL open fully inside the window. It SHALL be right-aligned under its button unless that would cross the window's left edge, and then left-aligned.

When the header would not fit one row, the simulation chip SHALL show only its mark and "Simulated", with the full text in its tooltip and in Details.

#### Scenario: Export with the simulation chip
- **WHEN** an OpenPLC config with simulated nodes is open at 1440 px and the user opens Export ▾
- **THEN** the header is one row and the whole Export panel is inside the window

#### Scenario: Narrow window
- **WHEN** the window is 1280 px wide with a simulated network and the user opens Export ▾
- **THEN** the chip reads "Simulated", and the Export panel is inside the window

### Requirement: Copy as ST call only where the blocks run
Copy as ST call (object dictionary entry, NMT command, CAN message, J1939 PGN) SHALL be offered only on Modbus bridge and OpenPLC configs, not on a CODESYS config and not when commissioning a device without a config.

#### Scenario: CODESYS config
- **WHEN** the user opens a node's object dictionary in Commission on a CODESYS config
- **THEN** no entry offers ST, and NMT offers no Copy as ST call

### Requirement: Copy as ST call names the missing part
When the config lacks the bridge part a copied block needs, the button SHALL stay enabled, and its tooltip and the copied text's first comment SHALL name the setting and its page: SDO bridge registers for `CO_SDO_READ`/`CO_SDO_WRITE`, the control block for `CO_NMT`, a request mailbox for the other SDO, send and request blocks, the receive mailbox for the receive blocks.

#### Scenario: Receive mailbox off
- **WHEN** a Modbus bridge config has the Function blocks section on without the receive mailbox, and the user copies the ST call of a received J1939 PGN
- **THEN** the copied text starts with a comment saying it needs the Function blocks' receive mailbox on the Modbus bridge page

## MODIFIED Requirements

### Requirement: Only what the target uses is shown
The page SHALL hide every field, table column, choice option, fieldset, node tab, tree entry, menu item, page and start-page action that the project's target does not use, as the relevance table of `canopen-config-contract` lists them, whether or not the config has a value for it, and SHALL NOT list, mark or ask about such values (Requirement: Settings the target does not use are left out on save). Hints, labels and page texts that differ between targets SHALL use the project target's wording: a bridge or CODESYS project SHALL NOT be told about the Linux device, the PLC scan or PLC locations where they do not apply. The editor project's address scan line SHALL be shown for OpenPLC only. A section SHALL be hidden only when none of its controls is left, and a section whose settings the target does not use (the Emergency section for CODESYS) SHALL not be drawn. A node tab left with nothing SHALL say in one line that the target does not use its settings instead of staying blank. The same rules SHALL apply to all three targets. No target SHALL show a CiA 402 axis setting, a scan watchdog, SYNC from the PLC cycle or a Variable declarations page: they no longer exist.

#### Scenario: CODESYS project
- **WHEN** the project's target is CODESYS
- **THEN** the page shows no IEC location fields or column, status locations, SDO variables, EDS lint, simulated devices, raw CAN messages, gateway, Online access, Emergency section or OpenPLC Editor project actions, and the protocol choice offers only CANopen master

#### Scenario: Bridge project
- **WHEN** the project's target is Modbus bridge
- **THEN** the Project page has no Editor project section and the Bus page's role hint says the bridge is the network's master

#### Scenario: OpenPLC project
- **WHEN** the project's target is OpenPLC
- **THEN** no CODESYS page, field or action is shown, and the Modbus bridge page shows none of the listen, port, writers, readers, word order or client limit fields

#### Scenario: Leftover value
- **WHEN** a CODESYS project still has `on_plc_stop` set to `keep`
- **THEN** the field is hidden, nothing on the page or in Problems mentions it, and the next save leaves it out

#### Scenario: Leftover location in a CODESYS project
- **WHEN** a CODESYS project's node `dio` has one TPDO entry with `iec_location` `%IW100`
- **THEN** the node's PDO table has no PLC location column and the PDOs tab shows nothing about it

#### Scenario: Leftover simulate in a CODESYS project
- **WHEN** a CODESYS project's node has `simulate` set
- **THEN** the node has no Simulation tab and no simulated mark

#### Scenario: Supervision with the EDS's own settings in a CODESYS project
- **WHEN** a CODESYS project's node has no heartbeat or guarding settings (Method "EDS default") and the user opens its Supervision tab
- **THEN** the Method choice is shown, there is no Emergency section, and the tab is not blank

#### Scenario: Wording guard
- **WHEN** the browser tests open every page and node tab of a config with every setting set, once per target
- **THEN** no field the target does not use is visible, no node tab is blank, and no visible text uses another target's words (for CODESYS: the bridge, the Linux device, PLC location, an IEC address, OpenPLC), apart from the Project target field's help

### Requirement: Header menus
The header SHALL show, left to right:
- the title;
- the workspace switch (see "Workspaces");
- the config's folder name with an unsaved mark;
- a settings menu with the theme choice;
- Reload from disk;
- Close;
- an Export menu (see "Export menu groups");
- the target's primary button (see "Header target action");
- Save.

The header SHALL have no Project menu; the editor project's actions are on the Project page (see "Editor project on the Project page").

The tool tabs SHALL be on a row under it. Menus SHALL open on click or Enter, close on Escape or a click elsewhere, and SHALL be navigable with the arrow keys. The header SHALL fit on one line at 1000 px. In Commission a device the header SHALL show only the title, the settings menu and Close.

#### Scenario: Export a DBC from the menu
- **WHEN** the user opens Export, picks "SDO: configured objects" and clicks DBC
- **THEN** the DBC file downloads as before and the menu closes

#### Scenario: One line
- **WHEN** the window is 1000 px wide in standalone mode
- **THEN** the header's actions are on one line

#### Scenario: Theme from the settings menu
- **WHEN** the user opens the settings menu and picks Dark
- **THEN** the page turns dark and the choice is kept in `ui.json`

### Requirement: Register map preview and export
The bridge page SHALL show:
- the register map as a table (Modbus table, address, size, type, name, source) with a filter;
- the suggested client channels;
- "Pack for Modbus";
- one line saying that Export ▾ → For the program has the register map files.

The page SHALL have no export buttons; the CSV, JSON and ST variable exports are in Export ▾ (see "Export menu groups").

#### Scenario: Export the ST list
- **WHEN** the user picks ST variables in Export ▾ on a Modbus bridge config
- **THEN** the browser downloads the same file `canworks-deploy --export-modbus-map map.st` writes for this config

### Requirement: Header target action
The header SHALL hold the target's hand-off action as one primary button with no menu: **Build into CODESYS project…** for CODESYS, **Install on device…** for Modbus bridge and OpenPLC. Download for CODESYS SHALL be in Export ▾ (see "Export menu groups").

At 1280 px and wider the header SHALL be one row for every target, also while the simulation chip is shown (see "Header menus stay inside the window").

Under 1500 px with a config open, Reload from disk, Close, Settings and Quit SHALL be in one "⋯" menu. With no config open (start page, Devices without a config) they SHALL stay buttons in the header.

#### Scenario: CODESYS at 1366 px
- **WHEN** a CODESYS config is open at 1366 px wide
- **THEN** the header is one row with one Build button and no ▾ next to it

#### Scenario: OpenPLC with simulated nodes at 1280 px
- **WHEN** an OpenPLC config with simulated nodes is open at 1280 px wide
- **THEN** the header is one row with Install on device…

### Requirement: CODESYS actions
A CODESYS project SHALL have **Build into CODESYS project…** in the header and on the CODESYS page, and **Download for CODESYS** in Export ▾ and on the CODESYS page.

Build SHALL:
- require a saved config and a project file;
- run the `--codesys-import` route of `canopen-deploy` with the config's settings;
- show CODESYS's report, its first sentence naming the device the bus went to and why (from the report's device line);
- when CODESYS is not found on this PC, say so and point to Download.

When the project file does not exist and no PLC device for a new project is set, Build SHALL NOT run CODESYS. It SHALL ask whether to create a new project, with the PLC device dropdown. **Create and build** SHALL set the device, save and build, and Cancel SHALL change nothing. Build failures SHALL be worded in the page's terms (fields and buttons), not command-line options.

Download SHALL offer the `codesys-export` folder as `<config folder name>_codesys.zip` and write no file in the project or config folder. On errors it SHALL download nothing and list them in Problems.

#### Scenario: Build
- **WHEN** a saved CODESYS project names `C:\Projects\cell.project` and the user clicks Build into CODESYS project on a PC with CODESYS
- **THEN** the project gets the bus and the page shows CODESYS's report with its result

#### Scenario: Build names the device
- **WHEN** the build's report says the bus went to `ExampleApp (active application)`
- **THEN** the dialog's first sentence names `ExampleApp` and that it is the active application's device

#### Scenario: Build a new project
- **WHEN** the project file `C:\Projects\new.project` does not exist, no PLC device is set and the user clicks Build
- **THEN** a dialog asks to create a new CODESYS project with a PLC device dropdown, and Create and build saves the device and builds `C:\Projects\new.project` with it

#### Scenario: Cancel the new project
- **WHEN** the create dialog is open and the user presses Cancel
- **THEN** the config is unchanged and CODESYS does not run

#### Scenario: Project open in CODESYS
- **WHEN** the build fails because the project is open in the CODESYS window
- **THEN** the page shows the failure with the hint to close the project in CODESYS first

#### Scenario: No CODESYS
- **WHEN** the user clicks Build on a PC without CODESYS
- **THEN** the page says CODESYS was not found and offers Download for CODESYS

### Requirement: OpenPLC project page
The Project page of an OpenPLC project SHALL show the target and the Editor project section (see "Editor project on the Project page").

The Modbus bridge page of such a project SHALL be headed "Modbus bridge", with one line saying OpenPLC's Modbus master reads and writes these registers on 127.0.0.1. Its OpenPLC box SHALL start with these facts from the saved config:
- the remote device and its port;
- the poll period with the number of Modbus requests per poll, and the warning above 40;
- the writer-loss time;
- the map hash;
- the first editor `%IW`/`%QW`.

The box SHALL also hold the poll period (`poll_ms`, placeholder 10), the remote device name, the first editor location, the unit ID, the watchdog and the loss action. The page SHALL show the status block as fixed `%IB4`, and no listen, port, writers, readers, word order or client limit fields; those follow `bridge.openplc`.

#### Scenario: Requests per poll
- **WHEN** an OpenPLC project has 30 nodes with two TPDOs and two RPDOs each, none contiguous
- **THEN** the Modbus bridge page's OpenPLC box shows the request count above 40 with the warning, and Problems lists it as a warning

### Requirement: Project target
A project SHALL have one target: "OpenPLC" (default; OpenPLC Runtime through its Modbus master and the bridge), "Modbus bridge" or "CODESYS".

The target SHALL be chosen in a "Project target" field on the Project page (see "Network tree") and shown in the header, where the badge opens the Project page. No network's Bus page and no Modbus bridge page SHALL have the field. The page, its messages and the check's warnings SHALL use these three names and no other name for a target, apart from the removed plugin's message and its button.

The target SHALL come from the config:
- a `bridge` object holding `openplc` makes it OpenPLC;
- any other `bridge` object makes it Modbus bridge;
- a `codesys` object makes it CODESYS.

A config with neither (a config of the removed OpenPLC plugin) SHALL open read-only, with one message saying the plugin is no longer supported and **Switch to OpenPLC through Modbus**. As one undo step, the switch SHALL:
- repack the locations for the bridge;
- add `"bridge": {"openplc": {}, "writers": ["127.0.0.1"]}`;
- remove what the bridge does not use, including `axis`, `sync_source`, `sync_cycles` and `scan_watchdog_ms`.

Until the switch the page SHALL NOT save the config.

#### Scenario: Target shown
- **WHEN** the user opens a config with a `codesys` object
- **THEN** the Project page's Project target field and the header show CODESYS

#### Scenario: Plugin config opened
- **WHEN** the user opens a config with no `bridge` and no `codesys` object, whose master has `"sync_source": "plc_cycle"` and whose node `drive` has `axis`
- **THEN** the message offers Switch to OpenPLC through Modbus and Save is disabled; after the switch the config has `bridge.openplc`, no `sync_source` and no `axis`, timer SYNC is asked for in Problems, and one Undo restores the config as it was opened

#### Scenario: One name
- **WHEN** the user switches an OpenPLC config to Modbus bridge and back
- **THEN** the banner, the header badge, the target field and the bridge page heading say "OpenPLC" and "Modbus bridge", never "OpenPLC through Modbus" or "OpenPLC Runtime"

### Requirement: Target of a new config
New config… SHALL be one dialog that asks first what will run the networks. It SHALL offer three choices with one sentence each:
- **OpenPLC**: the canworks bridge runs the networks next to the OpenPLC Runtime, and OpenPLC reads and writes them over Modbus, set up for you;
- **Modbus bridge**: no OpenPLC; the values are served as Modbus TCP registers, naming Node-RED, HMIs and another PLC;
- **CODESYS**: a CODESYS PLC runs the CANopen master.

OpenPLC SHALL be preselected and SHALL write a config with `bridge.openplc`.

The dialog SHALL then ask for a name (the folder, new or existing and empty) and its location, with Choose… opening the folder dialog.

For OpenPLC it SHALL offer "Also create an OpenPLC Editor project here":
- ticked by default when the editor's `openplc-cli` is found;
- disabled with the reason when it is not.

Ticked, the folder SHALL become a new OpenPLC Editor project, opened as a project. While the project is created, the dialog SHALL show "Creating the editor project…" with Create disabled. Otherwise the folder SHALL become a config folder.

In both cases Create SHALL write the target's empty config to disk (the project's `canworks/` folder, or the config folder) before the page opens it, so a reload shows the new config with its target.

#### Scenario: New CODESYS config
- **WHEN** the user creates a new config with target CODESYS
- **THEN** the config is version 2 with a `codesys` object, it is on disk, and the page shows the CODESYS target

#### Scenario: New Modbus bridge config
- **WHEN** the user creates a new config with target Modbus bridge and reloads the page
- **THEN** the folder holds a config with a `bridge` object, and the page shows it with the Modbus bridge target and "Saved"

#### Scenario: New OpenPLC config with an editor project
- **WHEN** `openplc-cli` is found and the user creates a new OpenPLC config in `~/plc/new-machine` with the editor-project tick on
- **THEN** the dialog shows "Creating the editor project…" until `~/plc/new-machine` is an OpenPLC Editor project with a config holding `bridge.openplc` in its `canworks/` folder and `devices/remote/canworks.json`, and the page shows the mode "project new-machine"

#### Scenario: No editor command-line tool
- **WHEN** `openplc-cli` is not found and the user picks OpenPLC
- **THEN** the editor-project tick is off and disabled with the reason, and Create makes a config folder

## REMOVED Requirements

### Requirement: Node-RED flow export on the bridge page
**Reason**: The bridge page no longer has export buttons; every download is in Export ▾.
**Migration**: Export ▾ → For the program → Node-RED flow on a Modbus bridge config (see "Export menu groups").
