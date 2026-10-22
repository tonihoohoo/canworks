## MODIFIED Requirements

### Requirement: Folders the configurator cannot use
Opening a folder the configurator cannot read, or saving where it cannot write, SHALL end with a message naming the folder and the reason in plain words, and the configurator SHALL stay where it was (the start page or the open config), usable without a restart. A folder is added to Recent only after it opened. Open… SHALL refuse a folder that does not exist. New config… SHALL refuse a folder that already has a `canworks.json` or `project.json`, offering to open it instead. With "Also create an OpenPLC Editor project" it SHALL accept an existing folder that the editor project rules allow (`canopen-editor-project`, Never overwrite) and refuse any other, naming the file in the way. When Windows refuses to replace a file because another program holds it open, Save and Create SHALL try again for about 5 seconds before failing. The message SHALL then name the file and say that another program, often antivirus or a sync client, kept it open, and that trying again may work.

#### Scenario: Unreadable folder
- **WHEN** the user opens a folder without read permission
- **THEN** the page says it cannot read the folder, stays on the start page, Recent does not list it, and the next request works

#### Scenario: Mistyped standalone path
- **WHEN** the user types a path that does not exist in the Open… dialog and uses it
- **THEN** the page says the folder does not exist and nothing opens

#### Scenario: New config where one exists
- **WHEN** the user creates a new config in a folder that already has `canworks.json`
- **THEN** nothing is written and the page offers to open that config

#### Scenario: New config with an editor project in an existing empty folder
- **WHEN** `openplc-cli` is found, `~/plc/cell` exists and is empty, and the user creates a new OpenPLC config named `cell` in `~/plc` with the editor-project tick on
- **THEN** `~/plc/cell` becomes an OpenPLC Editor project with an empty config in its `canworks/` folder, and the page opens it as a project

#### Scenario: File held open on Save
- **WHEN** another program holds `canworks.json` open for 2 seconds while the user saves
- **THEN** the save succeeds after the program lets go

#### Scenario: File held open too long
- **WHEN** another program keeps `canworks.json` open for longer than the retry
- **THEN** Save fails with a message naming `canworks.json` and the held-open reason, the draft stays, and Save is offered again

### Requirement: Target of a new config
New config… SHALL be one dialog that asks first what will run the networks, with three choices and one sentence each: OpenPLC Runtime (the canworks plugin runs the networks), Modbus bridge (no PLC; the values are served as Modbus TCP registers, naming Node-RED, HMIs and other Modbus TCP clients) and CODESYS (a CODESYS PLC runs the CANopen master). OpenPLC SHALL be preselected. The dialog SHALL then ask for a name (the folder, new or existing and empty) and its location, with Choose… opening the folder dialog. For OpenPLC it SHALL offer "Also create an OpenPLC Editor project here", ticked by default when the editor's `openplc-cli` is found and disabled with the reason when it is not; ticked, the folder SHALL become a new OpenPLC Editor project, opened as a project, and while the project is created the dialog SHALL show "Creating the editor project…" with Create disabled. Otherwise the folder SHALL become a config folder. In both cases Create SHALL write the target's empty config to disk (the project's `canworks/` folder, or the config folder) before the page opens it, so a reload shows the new config with its target.

#### Scenario: New CODESYS config
- **WHEN** the user creates a new config with target CODESYS
- **THEN** the config is version 2 with a `codesys` object, it is on disk, and the page shows the CODESYS target

#### Scenario: New Modbus bridge config
- **WHEN** the user creates a new config with target Modbus bridge and reloads the page
- **THEN** the folder holds a config with a `bridge` object, and the page shows it with the Modbus bridge target and "Saved"

#### Scenario: New OpenPLC config with an editor project
- **WHEN** `openplc-cli` is found and the user creates a new OpenPLC config in `~/plc/new-machine` with the editor-project tick on
- **THEN** the dialog shows "Creating the editor project…" until `~/plc/new-machine` is an OpenPLC Editor project with an empty config in its `canworks/` folder, and the page shows the mode "project new-machine"

#### Scenario: No editor command-line tool
- **WHEN** `openplc-cli` is not found and the user picks OpenPLC
- **THEN** the editor-project tick is off and disabled with the reason, and Create makes a config folder
