## ADDED Requirements

### Requirement: New editor project in standalone mode
In standalone mode the page SHALL offer "New editor project" next to "move into project". It SHALL ask for a parent folder (prefilled with the home folder, as "move into project" does), a project name, the task interval (default `T#20ms`) and whether to enable the canworks function blocks (unchecked by default), create the project as `canopen-editor-project` describes, and then switch to project mode on the new project. It SHALL require the config to be saved first and SHALL show the reason when creation is refused. The standalone folder SHALL be left unchanged.

#### Scenario: Create and switch
- **WHEN** the user has saved a standalone config in `~/canworks/rtd`, chooses "New editor project", picks `~/workspace` and the name `rtd-monitor`
- **THEN** `~/workspace/rtd-monitor` is created with the config in its `canworks/` folder and `main` declaring its I/O, and the page shows mode "project rtd-monitor" with every CANopen entry marked as declared

#### Scenario: Function blocks enabled
- **WHEN** the user ticks "Enable the canworks function blocks" in the dialog
- **THEN** the project is created as with `--blocks`, and the page shows how to install the library when the creation output says it is missing

#### Scenario: Unsaved changes
- **WHEN** the config has unsaved changes
- **THEN** the page asks the user to save first and creates nothing

#### Scenario: Name taken
- **WHEN** `~/workspace/rtd-monitor` already exists
- **THEN** the dialog says the folder exists and stays open, nothing is written and the page stays in standalone mode

## REMOVED Requirements

### Requirement: New editor project from a standalone config
**Reason**: Its scenario named the option "CANopen SDO blocks"; the library is a general function block library.
**Migration**: Replaced by "New editor project in standalone mode", the same behaviour with the dialog's "Enable the canworks function blocks" option.
