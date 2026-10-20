## MODIFIED Requirements

### Requirement: CODESYS settings
A CODESYS project SHALL have a "CODESYS" page in the tree with the project file, the device that gets the bus, the PLC device for a new project and variable names on or off, and each CANopen master network's Bus page SHALL have the CODESYS network number and CAN interface object, all stored in the config's `codesys` objects. The project file SHALL have **Browse…** (Requirement: CODESYS project file dialog), and a project file without an extension SHALL get `.project`. The PLC device for a new project SHALL be a dropdown of the PLC devices installed in CODESYS (Requirement: PLC devices installed in CODESYS) with "Other…" for typing `TYPE:ID:VERSION`, and SHALL be shown only while the project file does not exist; for an existing project the page SHALL say that canworks adds the bus to it.

#### Scenario: Network number
- **WHEN** the user sets the CODESYS network number of network `field` to 0
- **THEN** the config's network `field` gets `codesys.net_id` 0 and the next CODESYS build uses network number 0

#### Scenario: New project file
- **WHEN** the user types `C:\Projects\cell` as the project file and no such file exists
- **THEN** the field shows `C:\Projects\cell.project` and the PLC device dropdown is shown

#### Scenario: Existing project file
- **WHEN** the project file names an existing `.project` file
- **THEN** the PLC device field is hidden and the page says canworks adds the bus to the existing project

### Requirement: CODESYS actions
A CODESYS project SHALL have **Build into CODESYS project…** and **Download for CODESYS** in the header. Build SHALL require a saved config and a project file, run the `--codesys-import` route of `canopen-deploy` with the config's settings, and show CODESYS's report; when CODESYS is not found on this PC it SHALL say so and point to Download. When the project file does not exist and no PLC device for a new project is set, Build SHALL NOT run CODESYS but ask whether to create a new project, with the PLC device dropdown; **Create and build** SHALL set the device, save and build, and Cancel SHALL change nothing. Build failures SHALL be worded in the page's terms (fields and buttons), not command-line options. Download SHALL offer the `codesys-export` folder as `<config folder name>_codesys.zip` and write no file in the project or config folder; on errors it SHALL download nothing and list them in Problems.

#### Scenario: Build
- **WHEN** a saved CODESYS project names `C:\Projects\cell.project` and the user clicks Build into CODESYS project on a PC with CODESYS
- **THEN** the project gets the bus and the page shows CODESYS's report with its result

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

## ADDED Requirements

### Requirement: Placeholder look
Every input's placeholder SHALL look different from a value in both themes (muted colour and italic), so a default or example is never read as a filled-in setting. A placeholder that is an example rather than the value used when the field is empty SHALL start with "e.g.".

#### Scenario: Example placeholder
- **WHEN** the CODESYS page shows an empty project file field
- **THEN** its placeholder reads "e.g. C:\Projects\cell.project" in muted italic, unlike the typed text of other fields

### Requirement: CODESYS project file dialog
**Browse…** next to the CODESYS project file SHALL open the folder dialog (Requirement: Folder dialog) in a file mode that also lists the shown folder's `.project` files after its subfolders; picking one SHALL fill the field with its path. It SHALL start in the field's folder, else its nearest existing parent, else the home folder, and keep the folder dialog's Up, drives, typed path and keyboard use. Cancel SHALL leave the field as it was. Other folder dialogs SHALL NOT list files.

#### Scenario: Pick an existing project
- **WHEN** the user presses Browse…, opens `C:\Projects` and clicks `cell.project`
- **THEN** the dialog closes and the project file field holds `C:\Projects\cell.project`

### Requirement: New project name in the file dialog
The CODESYS project file dialog SHALL have a **New project name** field with **Create here** that fills the project file field with `<shown folder>\<name>.project` without writing a file. A name with slashes, or one whose file exists, SHALL be refused in the dialog.

#### Scenario: Name a new project
- **WHEN** the user opens `C:\Projects` in the dialog, types `line2` as New project name and presses Create here
- **THEN** the field holds `C:\Projects\line2.project`, no file is written and the PLC device dropdown is shown

### Requirement: PLC devices installed in CODESYS
The configurator SHALL list the PLC devices installed in CODESYS on this PC from CODESYS's device repository, each with its name and version, newest version first per name, and SHALL leave out devices that are not PLCs. The list SHALL be read once per configurator start, with a refresh in the dropdown. With no CODESYS or no readable repository the PLC device field SHALL be a text field for `TYPE:ID:VERSION`. A saved device not in the list SHALL be shown as typed.

#### Scenario: Pick the PLC
- **WHEN** CODESYS with CODESYS Control Win V3 x64 3.5.22.40 is installed and the user picks it in the dropdown
- **THEN** the config's `codesys.create` is that device's `TYPE:ID:VERSION`

#### Scenario: No CODESYS
- **WHEN** the configurator runs on a PC without CODESYS
- **THEN** the PLC device field is a text field with an example placeholder
