## ADDED Requirements

### Requirement: Config target
A config SHALL target one system: the Modbus bridge when it has a top-level `bridge` object, CODESYS when it has a top-level `codesys` object, else OpenPLC. A config with both SHALL be an error. A CODESYS config SHALL be version 2.

#### Scenario: Both markers
- **WHEN** a config has both `bridge` and `codesys`
- **THEN** the check fails saying a config targets one system

### Requirement: CODESYS section in the schema
The version 2 schema SHALL define an optional top-level `codesys` object with `project`, `device`, `create` (`TYPE:ID:VERSION`) and `variables` (boolean), and an optional network `codesys` object with `net_id` (0-255) and `interface` (a name), all optional. In a CODESYS config PDO entries SHALL NOT need `iec_location` and `adapter.interface` SHALL be optional.

#### Scenario: CODESYS config validates
- **WHEN** a version 2 config with `"codesys": {}`, network `field` with `"codesys": {"net_id": 1}` and PDO entries without locations is validated
- **THEN** it is valid

### Requirement: Variable name of a PDO entry
A PDO entry MAY have `name`, an IEC 61131-3 identifier. It SHALL replace the EDS part of the names the declarations, the Modbus register map and the CODESYS channels give that entry, after the same network and node prefixes. Two entries whose names come out equal SHALL be an error naming both paths.

#### Scenario: Named entry
- **WHEN** node `dio` on a one-network config maps 0x6000 sub 1 with `name` `door_open`
- **THEN** its declaration and CODESYS channel are named `dio_door_open`

### Requirement: Settings the target does not use
One relevance table SHALL list, per setting, the targets that use it and why the others do not. The check SHALL warn, with the setting's path and that reason, for every set value its target does not use. Values the target refuses SHALL stay errors.

#### Scenario: Scan watchdog in a CODESYS config
- **WHEN** a CODESYS config has `master.scan_watchdog_ms` 500
- **THEN** the check warns that CODESYS does not use the scan watchdog, naming its path

#### Scenario: Scan watchdog in a bridge config
- **WHEN** a bridge config has `master.scan_watchdog_ms` 500
- **THEN** the check warns that the bridge has no PLC scan and ignores it

### Requirement: CODESYS configs are for CODESYS
The OpenPLC plugin and `canworks-bridge` SHALL refuse a config with a `codesys` object at load with an error saying it is for CODESYS, and the deploy tool SHALL refuse to upload one to a runtime or a bridge.

#### Scenario: CODESYS config uploaded to OpenPLC
- **WHEN** `canworks-deploy --config codesys.json --runtime HOST` is run with a CODESYS config
- **THEN** it stops before uploading with a message pointing to `--codesys-import`
