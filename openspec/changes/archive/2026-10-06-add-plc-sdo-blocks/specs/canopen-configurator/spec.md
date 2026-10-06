## MODIFIED Requirements

### Requirement: New editor project from a standalone config
In standalone mode the page SHALL offer "New editor project" next to "move into project". It SHALL ask for a parent folder (prefilled with the home folder, as "move into project" does), a project name, the task interval (default `T#20ms`) and whether to enable the CANopen SDO blocks (unchecked by default), create the project as `canopen-editor-project` describes, and then switch to project mode on the new project. It SHALL require the config to be saved first and SHALL show the reason when creation is refused. The standalone folder SHALL be left unchanged.

#### Scenario: Create and switch
- **WHEN** the user has saved a standalone config in `~/canopen/rtd`, chooses "New editor project", picks `~/workspace` and the name `rtd-monitor`
- **THEN** `~/workspace/rtd-monitor` is created with the config in its `canopen/` folder and `main` declaring its I/O, and the page shows mode "project rtd-monitor" with every CANopen entry marked as declared

#### Scenario: SDO blocks enabled
- **WHEN** the user ticks "Enable CANopen SDO blocks" in the dialog
- **THEN** the project is created as with `--sdo-blocks`, and the page shows how to install the library when the creation output says it is missing

#### Scenario: Unsaved changes
- **WHEN** the config has unsaved changes
- **THEN** the page asks the user to save first and creates nothing

#### Scenario: Name taken
- **WHEN** `~/workspace/rtd-monitor` already exists
- **THEN** the dialog says the folder exists and stays open, nothing is written and the page stays in standalone mode

## ADDED Requirements

### Requirement: Copy as ST call
The object dictionary tab SHALL offer "Copy as ST call" for a selected entry. It SHALL copy Structured Text that declares an instance of the matching block and calls it with the node ID, index and subindex filled in: `CO_SDO_READ_REAL`/`CO_SDO_WRITE_REAL` for REAL32 and REAL64, `CO_SDO_READ_STRING`/`CO_SDO_WRITE_STRING` for VISIBLE_STRING, `CO_SDO_READ_BYTES`/`CO_SDO_WRITE_BYTES` for OCTET_STRING and DOMAIN, and `CO_SDO_READ`/`CO_SDO_WRITE` for every other type, with the `LWORD_TO_<type>` conversion for the entry's IEC type in a comment. It SHALL offer the read call for readable entries and the write call for writable ones, and both when both apply. The entry row for any index and subindex SHALL offer the same, using `CO_SDO_READ`/`CO_SDO_WRITE` when no type is given.

#### Scenario: INTEGER16 entry
- **WHEN** the user picks "Copy as ST call", read, on node 5's 0x6401 subindex 1 (INTEGER16, `ro`)
- **THEN** the clipboard holds a declaration of a `CO_SDO_READ` instance, a call with `NODE := 5, INDEX := 16#6401, SUBINDEX := 1`, and a comment showing `LWORD_TO_INT(...DATA)`

#### Scenario: Device name
- **WHEN** the user picks "Copy as ST call" on 0x1008 subindex 0 (VISIBLE_STRING, `const`)
- **THEN** only the read is offered and it uses `CO_SDO_READ_STRING`
