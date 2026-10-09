## ADDED Requirements

### Requirement: Note editor
Wherever an object's note is shown in a project (object dictionary view, startup SDO editor and picker, PDO entry picker), a "Note" button SHALL open an editor for that object or sub-object with text, details, unit, scale, a values table, a bits table and manual. For an object with a built-in note the editor SHALL start from the built-in fields and SHALL save only the fields the user changed into the device notes file.

#### Scenario: Write a note while commissioning
- **WHEN** the user opens the Note editor of 0x2010 of node 7, types "Opening ramp of the valve", unit ms, and saves the project
- **THEN** `0x2010` in the EDS's notes file has that text and unit, and the object dictionary view shows them

#### Scenario: Override a built-in note
- **WHEN** the user adds the value -1 "vendor jog mode" to the values of 0x6060 in the Note editor and saves
- **THEN** the device notes file has only a `values` entry for 0x6060 and the built-in text is not copied

### Requirement: Note edits are draft edits
A note edit SHALL mark the draft as changed, SHALL be written with Save, and SHALL be undoable like other draft edits.

#### Scenario: Undo a note
- **WHEN** the user changes the text of 0x2010 in the Note editor and presses Ctrl+Z
- **THEN** the earlier text is back and the draft is clean again if nothing else changed

### Requirement: Notes read-only without a config
In "Commission a device" without a config, notes SHALL be shown but not editable.

#### Scenario: Read-only when commissioning
- **WHEN** the user opens the object dictionary view in "Commission a device" without a config
- **THEN** notes are shown and no Note button is offered

### Requirement: Notes in the other node lists
The PDO entry picker and the Parameters compare and restore lists SHALL show each object's note `text` under its name and the meaning and unit of each value from its merged note.

#### Scenario: Compare with meanings
- **WHEN** the user compares node 4 against a backup and 0x6060 differs (3 on the device, 1 in the backup)
- **THEN** the compare list shows `3 (profile velocity)` and `1 (profile position)`

## MODIFIED Requirements

### Requirement: Import an EDS
Adding a node SHALL start from an EDS file the user picks. The configurator SHALL check that it is a CiA 306 EDS the deploy tool accepts, store it under `canworks/` as UTF-8 (converting from Latin-1/CP1252 when it is not valid UTF-8) and refer to it by a path relative to `canworks/`. A different file with the same name SHALL NOT be overwritten silently. When "keep both" gives the new EDS another name, it SHALL get its own notes file (see `canopen-device-notes`), and replacing an EDS SHALL keep its notes file.

At import, the configurator SHALL also run the checks the PLC runs before dcfgen, on the same prepared copy (see `canopen-master-bringup`, "Prepared EDS copy"): dcfgen's EDS read and lint, and Lely's EDS parse rules, sorting the lint findings as the plugin does (see `canopen-master-bringup`, "EDS lint scope") under the config's `eds_lint` setting. The import SHALL show:
- that the file is readable, when nothing below applies;
- the corrections the PLC will make (UTF-8 conversion, REAL rewrite, cleared OCTET_STRING values);
- findings that do not stop the PLC, as a collapsed list with each finding's object, saying they are accepted.

The import SHALL be refused, showing the reason, and no node SHALL be added, when dcfgen or Lely cannot read the file even after the corrections, or when the lint has findings that would stop the PLC.

#### Scenario: Latin-1 vendor EDS
- **WHEN** the user imports `vendor.eds`, encoded in Latin-1 with `°C` in a ParameterName
- **THEN** on save `canworks/vendor.eds` is valid UTF-8 with the same text and the node's `eds` is `vendor.eds`

#### Scenario: Not an EDS
- **WHEN** the user picks a file without objects 0x1000 and 0x1018
- **THEN** the import is refused with the reason and no node is added

#### Scenario: Same name, different content
- **WHEN** an imported EDS has the same name as a different EDS already in `canworks/`
- **THEN** the user is asked to replace it or keep both under a new name, and nothing is overwritten without that choice

#### Scenario: Vendor EDS with findings in profile objects
- **WHEN** the user imports a drive EDS with signed limits written as unsigned hex in its profile objects
- **THEN** the node is added and the import shows its findings as accepted, listed collapsed with their objects

#### Scenario: Finding in a communication object
- **WHEN** the user imports an EDS whose 0x1A00 sub 0 has the data type UNSIGNED16, and `eds_lint` is unset
- **THEN** the import is refused, the finding in 0x1A00 sub 0 is shown, and no node is added

#### Scenario: Notes file for a new EDS
- **WHEN** the user imports `valve.eds`, which has no notes file, adds the node and saves
- **THEN** `canworks/valve.eds.notes.json` is written with the valve's identity and an entry for each manufacturer object

### Requirement: Save only the project's canopen folder
Saving SHALL write `canworks/canworks.json`, the imported EDS files and their notes files (`<eds file name>.notes.json`, see `canopen-device-notes`) under `canworks/`, and no other file. `canworks.json` SHALL be replaced atomically, carry `schema_version` 1 and keep fields the configurator does not know. The saved folder SHALL be accepted unchanged by the deploy tool's `--config` and by the editor-upload hook.

#### Scenario: Unknown field kept
- **WHEN** a loaded config has a field the configurator does not know and the user changes a heartbeat and saves
- **THEN** the unknown field is still in the saved file with its value

#### Scenario: Only canopen is touched
- **WHEN** the user saves
- **THEN** no file outside `canworks/` is created or modified

#### Scenario: Deploy tool reads the result
- **WHEN** `canworks-deploy --config <project>/canworks/canworks.json` runs on a saved config
- **THEN** its checks pass with no change to the file

### Requirement: Value formats in the object dictionary view
Each numeric entry SHALL be shown in decimal by default and SHALL let the user switch it to hex or binary, the choice kept for that entry while the page is open. INTEGER entries in hex or binary SHALL show their two's-complement bits. For an object whose merged note has `bits` (see `canopen-device-notes`; built in at least for 0x1001 error register, 0x1002 manufacturer status register, 0x6040 controlword and 0x6041 statusword of CiA 402; an empty `bits` marks a bit field without names) the entry SHALL offer a bit view naming each set bit from those notes; a set bit without a name SHALL be shown by its number. An entry whose merged note has `values` SHALL show the meaning after the value, as `3 (profile velocity)`, and a value without a meaning as the number alone. An entry whose note has `unit` SHALL show it after the value, and with `scale` the scaled value too, as `1234 (12.34 bar)`. An entry's note `text` SHALL be shown under its name, with `details` and `manual` on hover.

#### Scenario: Hex view
- **WHEN** 0x6110 subindex 1 reads 30 and the user switches it to hex
- **THEN** it shows `0x001E`

#### Scenario: Statusword bits
- **WHEN** 0x6041 of a CiA 402 drive reads 0x0237 and the user opens its bit view
- **THEN** the bits ready to switch on, switched on, operation enabled, voltage enabled, quick stop and remote are shown as set

#### Scenario: Vendor bit field
- **WHEN** the notes of `valve.eds` give 0x2100 the bits 0 "coil A open" and 7 "overtemperature", and 0x2100 reads 0x81
- **THEN** its bit view shows "coil A open" and "overtemperature" as set

#### Scenario: Scaled value with unit
- **WHEN** the notes give 0x2200:1 the unit bar and scale 0.01, and it reads 1234
- **THEN** the entry shows `1234 (12.34 bar)`

### Requirement: Editing values in the object dictionary view
When the runtime allows changes, writable entries in the object dictionary tab SHALL be editable in place, using the SDO panel's write with its range check and its warnings for entries the configuration writes or an SDO variable owns. The editor SHALL show the entry's EDS LowLimit and HighLimit when the EDS has them, and a value outside them SHALL need a confirmation before it is written. When the entry's merged note has `values`, the editor SHALL offer them as a list with their meanings plus "Other value…" for any value in range. The value shown SHALL be read back after the write. When changes are not allowed, entries SHALL be read-only with the reason shown.

#### Scenario: Edit a parameter
- **WHEN** the runtime allows changes and the user changes 0x6110 subindex 1 of node 3 to 30
- **THEN** the value is written, read back and shown as 30

#### Scenario: Value outside the EDS limits
- **WHEN** the EDS gives 0x2010 subindex 1 a HighLimit of 100 and the user enters 150
- **THEN** the editor says the EDS allows 0 to 100 and writes only after the user confirms

#### Scenario: Read-only runtime
- **WHEN** the runtime's `allow_changes` is false
- **THEN** no entry is editable and the tab says online changes are not allowed

#### Scenario: Pick a mode by name
- **WHEN** the runtime allows changes and the user edits 0x6060 of a CiA 402 drive
- **THEN** the editor lists the modes of operation by name, and picking "profile velocity" writes 3

### Requirement: Startup SDO writes
For each node the configurator SHALL edit an ordered list of startup SDO writes, which the plugin performs every time the node is configured at boot. The user SHALL pick the object from the node's EDS or type an index and subindex, and the type SHALL come from the EDS. Objects the EDS does not define, or marks read-only or const, SHALL be refused, and each value SHALL be checked against its type's range. The picker and the list SHALL show each object's note `text` under its name; the value field SHALL show the value's meaning and unit from the merged note, and SHALL offer the note's `values` as a list with "Other value…" when it has them.

#### Scenario: Set the RTD sensor type
- **WHEN** the user adds a write to 0x6110 subindex 1 (`AI0_Sensor_Type`, `rw`, UNSIGNED16, EDS default 0x1E), enters `0x1E`, and moves it to the top of the list
- **THEN** the saved node's `sdo` list starts with `{"index": "0x6110", "subindex": 1, "type": "UNSIGNED16", "value": "0x1E"}`, and the plugin writes it before the other startup SDOs

#### Scenario: Read-only object
- **WHEN** the user picks object 0x1018 subindex 1 (const)
- **THEN** the write is refused with the reason

#### Scenario: Value out of range
- **WHEN** the user enters 300 for an UNSIGNED8 object
- **THEN** the field shows the range error and the save is refused

#### Scenario: Object not in the EDS
- **WHEN** the user types index 0x2100 subindex 0 that the EDS does not list
- **THEN** the write is refused, because the plugin only writes startup SDOs to objects the node's EDS defines

#### Scenario: Startup SDO with a value meaning
- **WHEN** the notes give 0x2011:2 the values 0 "hold position" and 1 "close" and the user adds a startup SDO for it
- **THEN** the value field lists "0 hold position" and "1 close", and the saved write has the number the user picked
