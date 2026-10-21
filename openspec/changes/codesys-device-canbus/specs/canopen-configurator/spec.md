## MODIFIED Requirements

### Requirement: CODESYS actions
A CODESYS project SHALL have **Build into CODESYS project…** and **Download for CODESYS** in the header. Build SHALL require a saved config and a project file, run the `--codesys-import` route of `canopen-deploy` with the config's settings, and show CODESYS's report, its first sentence naming the device the bus went to and why (from the report's device line); when CODESYS is not found on this PC it SHALL say so and point to Download. When the project file does not exist and no PLC device for a new project is set, Build SHALL NOT run CODESYS but ask whether to create a new project, with the PLC device dropdown; **Create and build** SHALL set the device, save and build, and Cancel SHALL change nothing. Build failures SHALL be worded in the page's terms (fields and buttons), not command-line options. Download SHALL offer the `codesys-export` folder as `<config folder name>_codesys.zip` and write no file in the project or config folder; on errors it SHALL download nothing and list them in Problems.

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
