## MODIFIED Requirements

### Requirement: Project target
A project SHALL have one target: "OpenPLC" (default; OpenPLC Runtime through its Modbus master and the bridge), "Modbus bridge" or "CODESYS", chosen in a "Project target" field on the Project page (see "Network tree") and shown in the header, where the badge opens the Project page. No network's Bus page and no Modbus bridge page SHALL have the field. The target SHALL come from the config: a `bridge` object holding `openplc` makes it OpenPLC, any other `bridge` object Modbus bridge, a `codesys` object CODESYS. A config with neither (an OpenPLC plugin config) SHALL open with the OpenPLC target shown and one message saying the plugin route is being retired, with **Switch to OpenPLC through Modbus**, which repacks the locations for the bridge, adds `"bridge": {"openplc": {}, "writers": ["127.0.0.1"]}` and removes what the bridge does not use, as one undo step.

#### Scenario: Target shown
- **WHEN** the user opens a config with a `codesys` object
- **THEN** the Project page's Project target field and the header show CODESYS

#### Scenario: Plugin config opened
- **WHEN** the user opens a config with no `bridge` and no `codesys` object, whose master has `"sync_source": "plc_cycle"`
- **THEN** the message offers Switch to OpenPLC through Modbus, and after it the config has `bridge.openplc`, timer SYNC is asked for in Problems, and one Undo restores the plugin config

### Requirement: Target of a new config
New config… SHALL be one dialog that asks first what will run the networks, with three choices and one sentence each: OpenPLC Runtime (the canworks bridge runs the networks next to the runtime and OpenPLC reads and writes them over Modbus, set up for you), Modbus bridge (no PLC; the values are served as Modbus TCP registers, naming Node-RED, HMIs and other Modbus TCP clients) and CODESYS (a CODESYS PLC runs the CANopen master). OpenPLC SHALL be preselected and SHALL write a config with `"bridge": {"openplc": {}, "writers": ["127.0.0.1"]}`. The dialog SHALL then ask for a name (the folder, new or existing and empty) and its location, with Choose… opening the folder dialog. For OpenPLC it SHALL offer "Also create an OpenPLC Editor project here", ticked by default when the editor's `openplc-cli` is found and disabled with the reason when it is not; ticked, the folder SHALL become a new OpenPLC Editor project, opened as a project, and while the project is created the dialog SHALL show "Creating the editor project…" with Create disabled. Otherwise the folder SHALL become a config folder. In both cases Create SHALL write the target's empty config to disk (the project's `canworks/` folder, or the config folder) before the page opens it, so a reload shows the new config with its target.

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

## ADDED Requirements

### Requirement: OpenPLC remote device on save
Saving an OpenPLC project (target OpenPLC, inside an editor project) SHALL also write the remote device file of `modbus-bridge-map` into the editor project and SHALL touch no other editor file. When that file changed on disk since canworks last wrote it, Save SHALL ask before replacing it, naming the file. After writing it the message SHALL say that an OpenPLC Editor with this project open must reopen it before Build. A standalone OpenPLC config folder SHALL write no remote device and SHALL say so on its Project page, with **Move into project…**.

#### Scenario: Save writes the device
- **WHEN** the user adds a TPDO entry in an OpenPLC project and saves
- **THEN** `devices/remote/canworks.json` gains a read group for it, and `project.json` and the POU files are unchanged

#### Scenario: Device edited in the editor
- **WHEN** the user changed `devices/remote/canworks.json` in OpenPLC Editor and then saves in the configurator
- **THEN** Save asks whether to replace it, naming the file, and Cancel leaves it as it is

### Requirement: OpenPLC project page
The Project page of an OpenPLC project SHALL show the poll period (`poll_ms`, placeholder 10 ms), the Modbus port, the map hash, the number of Modbus requests per poll with the warning above 40, and **Update declarations**, which rewrites the `canworks` variable list and the `canworks_in` and `canworks_out` programs of `canopen-editor-project`. It SHALL show no listen, writers or word order fields; those follow `bridge.openplc`.

#### Scenario: Requests per poll
- **WHEN** an OpenPLC project has 30 nodes with two TPDOs and two RPDOs each, none contiguous
- **THEN** the Project page shows the request count above 40 with the warning, and Problems lists it as a warning
