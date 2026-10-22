## MODIFIED Requirements

### Requirement: Validate before save
Before and after saving, the configurator SHALL run the deploy tool's checks: contract schema, EDS type and access checks, node ID uniqueness, overlapping locations and SDO value ranges. It SHALL show every error next to the field it concerns and in Problems. Save SHALL write the draft even when it has errors, and SHALL then show a message bar saying how many errors the saved config has and that the runtime refuses it until they are fixed. The steps that hand the config over SHALL refuse it while it has errors (see "Hand-off steps need a config without errors"). An overlap with the editor project MAY be handed over only when the user explicitly allows it, as the deploy tool's `--allow-clash` does. The control that allows it SHALL be shown in the Problems pane together with the editor-project overlap errors, and only while there are such errors; it SHALL NOT be shown in the page header or in standalone mode.

#### Scenario: Duplicate node ID
- **WHEN** two nodes have node ID 5 and the user presses Save
- **THEN** the config is written, both node ID fields show the error, and a message bar says the saved config has 1 error that the runtime refuses

#### Scenario: No overlap, no override
- **WHEN** a project config has no location that overlaps the editor project
- **THEN** neither the header nor the Problems pane shows an "Allow overlap" control

#### Scenario: Save despite an overlap
- **WHEN** node 2's TPDO entry uses `%ID100`, which the editor project's EtherCAT config also uses, and the user ticks "Allow overlap" under that error in the Problems pane
- **THEN** saving writes the config, the overlap no longer blocks the hand-off steps, and the Problems pane says overlaps are allowed

### Requirement: Busy states and the Save button
Save, every export, Move into project, New editor project and Add node from EDS SHALL disable their control and show what is running ("Saving…", "Exporting…", "Adding…") until the request completes, and a second click meanwhile SHALL do nothing. The Save button SHALL read "Save" and be enabled whenever the draft differs from the file, with or without errors. It SHALL read "Saved" and be disabled when the draft equals the file and has no problems, and "Saved, N problems" (disabled) when it equals the file and has problems. The error count SHALL be shown in the Problems pane.

#### Scenario: Double click on Save
- **WHEN** the user clicks Save twice while the first save is still running
- **THEN** one save request is made and the button reads "Saving…" until it returns

#### Scenario: Clean draft
- **WHEN** the file on disk equals the draft and the check has no problems
- **THEN** the button reads "Saved" and is disabled

#### Scenario: Dirty draft with an error
- **WHEN** the draft has one error and differs from the file
- **THEN** the button reads "Save" and is enabled

### Requirement: Target of a new config
New config… SHALL be one dialog that asks first what will run the networks, with three choices and one sentence each: OpenPLC Runtime (the canworks plugin runs the networks), Modbus bridge (no PLC; the values are served as Modbus TCP registers, naming Node-RED, HMIs and other Modbus TCP clients) and CODESYS (a CODESYS PLC runs the CANopen master). OpenPLC SHALL be preselected. The dialog SHALL then ask for a name (the new folder) and its location, with Choose… opening the folder dialog. For OpenPLC it SHALL offer "Also create an OpenPLC Editor project here", ticked by default when the editor's `openplc-cli` is found and disabled with the reason when it is not; ticked, the folder SHALL become a new OpenPLC Editor project, opened as a project. Otherwise the folder SHALL become a config folder. In both cases Create SHALL write the target's empty config to disk (the project's `canworks/` folder, or the config folder) before the page opens it, so a reload shows the new config with its target.

#### Scenario: New CODESYS config
- **WHEN** the user creates a new config with target CODESYS
- **THEN** the config is version 2 with a `codesys` object, it is on disk, and the page shows the CODESYS target

#### Scenario: New Modbus bridge config
- **WHEN** the user creates a new config with target Modbus bridge and reloads the page
- **THEN** the folder holds a config with a `bridge` object, and the page shows it with the Modbus bridge target and "Saved"

#### Scenario: New OpenPLC config with an editor project
- **WHEN** `openplc-cli` is found and the user creates a new OpenPLC config in `~/plc/new-machine` with the editor-project tick on
- **THEN** `~/plc/new-machine` is an OpenPLC Editor project with an empty config in its `canworks/` folder, and the page shows the mode "project new-machine"

#### Scenario: No editor command-line tool
- **WHEN** `openplc-cli` is not found and the user picks OpenPLC
- **THEN** the editor-project tick is off and disabled with the reason, and Create makes a config folder

## ADDED Requirements

### Requirement: Hand-off steps need a config without errors
Build into CODESYS project, Download for CODESYS, and installing or updating the bridge config on a device SHALL use the saved config. They SHALL refuse while it has errors. A refusal SHALL be shown next to the control in one line naming the error count, with a link that opens Problems. Allowed overlaps SHALL NOT count. Exports of DCF, DBC and documentation SHALL keep their own rules.

#### Scenario: Build with an error
- **WHEN** a CODESYS config is saved with one error and the user presses Build into CODESYS project…
- **THEN** nothing runs, and the page says the saved config has 1 error, with a link to Problems

### Requirement: Empty network is a warning
A CANopen master network without nodes SHALL be one warning in Problems, not an error. The tree and the network's Bus page SHALL show the empty state: "No nodes yet", with **Add node…** and a pointer to finding devices in Commission. The hand-off steps SHALL still refuse a network without nodes.

#### Scenario: Fresh config
- **WHEN** the user creates a new OpenPLC config
- **THEN** Problems shows one warning about the empty network and no error, and Save is not blocked

### Requirement: Supervision of a new node
When a node is added from an EDS whose heartbeat producer default (0x1017) is 0, the configurator SHALL give it supervision:
- `heartbeat_ms: 1000` when 0x1017 is writable;
- else node guarding at 1000 ms with life time factor 3, when the EDS supports guarding;
- else none, leaving the supervision problem.

Supervision SHALL say the value was set when the node was added.

#### Scenario: Node with a writable heartbeat
- **WHEN** the user adds a node from an EDS with 0x1017 writable and default 0
- **THEN** the node has a 1000 ms heartbeat and Problems shows nothing for it

### Requirement: Quick fixes in Problems
A problem MAY carry actions that fix it. Each action SHALL be one undo step. The supervision problem SHALL offer **Use heartbeat 1000 ms**, or **Use guarding** when the EDS only supports guarding, and **Accept no supervision**, which saves `heartbeat_ms: 0`. Its text SHALL name the field in the page's words (Supervision tab, heartbeat period) and SHALL NOT quote config keys.

#### Scenario: Fix from Problems
- **WHEN** node 2 has the supervision problem and the user presses Use heartbeat 1000 ms in Problems
- **THEN** node 2's heartbeat period is 1000 ms, the problem is gone, and Ctrl+Z brings it back

### Requirement: Errors in the New config dialog
The New config dialog SHALL show an error under the field it concerns, mark that field and move focus to it. The dialog's title SHALL stay.

#### Scenario: Empty name
- **WHEN** the user presses Create with an empty name
- **THEN** the Name field is marked with "Give the new config a name: it becomes its folder." under it and has focus, and the dialog's title still reads "New config"
