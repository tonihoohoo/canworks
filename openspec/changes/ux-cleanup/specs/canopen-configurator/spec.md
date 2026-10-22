## MODIFIED Requirements

### Requirement: Startup SDO picker shows settings
The startup SDO picker SHALL by default list only writable objects that are not PDO-mappable, are not communication objects the plugin writes itself (0x1005-0x1007, 0x100C, 0x100D, 0x1014-0x1017, 0x1400-0x1BFF, 0x1F80), and are not already in the node's list. It SHALL say how many objects are hidden, and a "Show all writable objects" switch SHALL list every writable object. Saving SHALL accept any writable object except the store and restore commands 0x1010 and 0x1011, which SHALL NOT be listed even with the switch on and SHALL be refused when typed, with a reason pointing to Store on device and Restore defaults in Commission. A startup SDO that writes a PDO parameter, or a supervision object with a value other than the node's setting, SHALL get a warning.

#### Scenario: Valve with non-mappable settings
- **WHEN** the picker opens for a node whose EDS has PDO-mappable outputs 0x2010 sub 1-4 and a non-mappable setting 0x2020 sub 1-4
- **THEN** 0x2020 sub 1-4 are listed, 0x2010 is not, and the hidden count includes the four outputs

#### Scenario: Show all
- **WHEN** the user turns on "Show all writable objects"
- **THEN** 0x2010 sub 1-4 and the writable communication objects are listed too, and adding one works as today

#### Scenario: Startup SDO overlaps a plugin setting
- **WHEN** a node's startup SDO list writes 200 to 0x1017 sub 0 and the node also sets `heartbeat_ms` to 100
- **THEN** the configurator and the deploy tool warn that the startup SDO runs last and overrides the heartbeat setting, and the save still succeeds

#### Scenario: Store command refused
- **WHEN** the user turns on "Show all writable objects" on a node whose EDS has 0x1010 and 0x1011
- **THEN** neither is listed, and typing 0x1010 sub 1 by hand is refused with the reason

## ADDED Requirements

### Requirement: Bus page of a simulated network
On a network set to Simulated, the CAN adapter section SHALL be folded to one line saying the adapter settings are kept for switching back, with **Show**. Its fields SHALL NOT be marked Required while folded. A choice that has one possible value for the target SHALL be shown as text, not as a dropdown.

#### Scenario: Simulated io
- **WHEN** the user opens Bus and master of the virtual plant's simulated `io` network
- **THEN** the CAN adapter section is one folded line with Show, and no field on the page says Required for the interface

#### Scenario: CODESYS role
- **WHEN** a CODESYS config's Bus and master page is open
- **THEN** Protocol reads "CANopen" and Role reads "Master" as text, without dropdowns

### Requirement: No empty message bars
No message bar or notice SHALL be shown without text. A notice whose text depends on a connection SHALL be hidden until it has text.

#### Scenario: Simulation without a connection
- **WHEN** the user opens Simulation while not connected
- **THEN** no warning bar without text is shown

### Requirement: Save to simulation file state
**Save to simulation file** SHALL be disabled, reading "Saved", while the simulation draft equals the file, and enabled only when it differs.

#### Scenario: Nothing changed
- **WHEN** the user opens a node's simulation tab without changing anything
- **THEN** the button reads "Saved" and is disabled

### Requirement: Parameters names and file buttons
On the Parameters tab, restoring a backup SHALL be named **Restore from backup…** and restoring factory values **Factory defaults (0x1011)…**, the latter in a section marked as changing the device. File choices SHALL use the page's button style with the chosen file's name next to it, not the browser's unstyled file input.

#### Scenario: Two restores
- **WHEN** the user opens node 6's Parameters tab
- **THEN** one button reads "Restore from backup…" and another "Factory defaults (0x1011)…", and no "Choose File / No file chosen" control is shown

### Requirement: Simulated value control range
The slider of a simulated value SHALL span the value source's range when the object has one, else the EDS limits of the object, else its type's range. **Set** and **Override** SHALL each have a tooltip saying that Set changes the value once and the source moves it again, while Override holds it until Release.

#### Scenario: Sine source
- **WHEN** node 5's 0x7130:1 has a sine source from 200 to 260 and the user opens Simulation live values
- **THEN** its slider spans 200 to 260

### Requirement: Device messages
The Add device dialog SHALL show a check message under the field it concerns, starting with a capital letter. A device that is not reached SHALL show one sentence without the SSH library's text ("Can't reach 192.0.2.10 on SSH port 22.") and a short list of what to check: SSH on the device, the same network, the address, the port. The device's action menu SHALL be named **Actions**.

#### Scenario: Unreachable
- **WHEN** the user adds 192.0.2.10 and nothing answers on port 22
- **THEN** the device reads "Not reached" with one sentence and the checklist, and no "[Errno" text is shown

### Requirement: Folder dialog marks projects
The folder dialog SHALL mark each listed folder that is an OpenPLC Editor project or holds a canworks config, with a tag ("OpenPLC project", "canworks config") before the user enters it. A single click SHALL select a folder, and double-click or Enter SHALL open it; **Use this folder** SHALL use the selected folder, or the current one when none is selected. The EDS count line SHALL be shown only when the dialog is picking an EDS folder.

#### Scenario: Pick the example
- **WHEN** the user opens Open… in a folder holding `virtual-plant` and clicks it once
- **THEN** `virtual-plant` is tagged "OpenPLC project" and selected, and Use this folder opens it

### Requirement: Network menu anchored
A network's ⋯ menu SHALL open as a menu anchored to its button, listing Rename…, Role and Remove… one per line, and SHALL close on Escape or a click outside.

#### Scenario: Open the menu
- **WHEN** the user presses ⋯ on network `io`
- **THEN** a menu opens next to the button, not a centred dialog

### Requirement: PDO headings per target
The PDOs tab headings and column titles SHALL use the target's words: "Inputs (TPDOs, device to PLC)" and "PLC location" for OpenPLC, "Inputs (TPDOs, device to Modbus)" and "Register" for the Modbus bridge, and "Inputs (TPDOs, device to CODESYS)" without a location column for CODESYS.

#### Scenario: Bridge headings
- **WHEN** a Modbus bridge config's node PDOs tab is open
- **THEN** no heading or column title says "PLC"

### Requirement: Small fixes on node tabs
- The SDOs tab SHALL title each table once.
- A startup write's value SHALL be shown in the same notation as its EDS default (both hex, or both decimal).
- The Notes tab SHALL show **Add note…** and **Import notes…** once.
- The Supervision tab SHALL group its PLC signal fields under "PLC signals", with **Suggest all** filling every empty one.

#### Scenario: Startup write notation
- **WHEN** a startup write to 0x6110:1 holds 0x1E and the EDS default is 0x1E
- **THEN** both read 0x1E

#### Scenario: Suggest all
- **WHEN** node 2 has no status bit, state byte, NMT command or boot error byte and the user presses Suggest all
- **THEN** each gets a free location

### Requirement: Declarations at a glance
The Variable declarations table SHALL mark an entry the project already declares under the same name with a check mark rather than repeating the name, and SHALL show the name only when it differs. A filter SHALL show only the entries still to be declared. The task interval field SHALL be under the block it changes. The page SHALL NOT show a network picker, because it covers every network.

#### Scenario: All declared
- **WHEN** the virtual plant's project declares every entry under its own name
- **THEN** each row shows a check mark, and the filter "Only missing" shows an empty table that says so

### Requirement: Graph series names
The Trace graph's series list SHALL show each series' whole name on hover and focus, and SHALL start with the first PDO signal ticked when no series was ticked before for the network.

#### Scenario: First graph
- **WHEN** the user opens Graph on a new trace of `io`
- **THEN** one series is drawn, and hovering a cut name shows it whole

### Requirement: Disabled and selected look different
A disabled primary button SHALL NOT share the fill of a selected tab or segment in either theme.

#### Scenario: Dark header
- **WHEN** the dark theme is on, the draft is saved and Configure is selected
- **THEN** the Saved button and the Configure segment have clearly different fills

### Requirement: Mode badge names the folder
The header's mode badge SHALL show the folder's name for both projects and config folders, with the full path in its tooltip.

#### Scenario: Config folder
- **WHEN** the config folder `/home/user/work/cs-machine` is open
- **THEN** the badge reads "cs-machine" and its tooltip the full path
