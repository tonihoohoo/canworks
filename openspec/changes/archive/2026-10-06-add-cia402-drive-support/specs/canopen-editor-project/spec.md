## MODIFIED Requirements

### Requirement: CANopen I/O declared in main
The program `main` SHALL declare, in one `VAR` block, a located variable for every location the config uses: mapped PDO entries, master and node diagnostic inputs, NMT command bytes and SDO variable locations, with the names and IEC types of the configurator's located variable declarations. Declarations SHALL use the editor's own form `name : TYPE AT location;`. For every axis node `main` SHALL also declare the axis, named after the node, of the library's axis type, and one drive bridge instance named `<node>_bridge`. The program body SHALL hold a comment saying the block came from `canopen/canopen.json`; when the config has axis nodes, the body SHALL start with generated lines that, for each axis in config order, set the axis's three scaling fields from the config and call its bridge with the axis, the node's mapped standard objects (only those mapped) and its status bit, and say they must stay first. Entries without a location SHALL be left out.

#### Scenario: RTD sensor
- **WHEN** a project is created from a config whose node `rtd` maps four INTEGER16 inputs at `%IW100` to `%IW103` and has status bit `%IX10.0`
- **THEN** `main` declares `rtd_ok : BOOL AT %IX10.0;` and four `INT` variables at `%IW100` to `%IW103`, and nothing else in its VAR block

#### Scenario: No locations
- **WHEN** the config has nodes but no locations at all
- **THEN** `main` has an empty `VAR` ... `END_VAR` block and the project is still created

#### Scenario: Axis node
- **WHEN** a project is created from a config whose node `drive` has `axis` with scale numerator 10 and maps 0x6040 at `%QW100` and 0x6041 at `%IW100`, with status bit `%IX10.0`
- **THEN** `main` declares `drive : AXIS_REF_SM3;` and `drive_bridge : SM_Drive_GenericDS402;` next to the located variables, and its body starts with lines setting `drive.iRatioTechUnitsNum` to 10 and calling `drive_bridge` with `Axis := drive`, the statusword variable, `bOnline :=` the status bit variable and `wControlWord =>` the controlword variable

#### Scenario: Axis project builds
- **WHEN** the example CiA 402 config's project is opened in OpenPLC Editor 4.3.2 and a program line `MC_Power(Axis := drive, Enable := TRUE)` is added
- **THEN** Build only succeeds for the target OpenPLC Runtime v4
