## MODIFIED Requirements

### Requirement: PLCopen XML export
`canworks-deploy --config FILE --export-plcopen OUT --for trust|generic` SHALL write, for a bridge config with `plc_link`, a folder with `canworks.xml` (TC6 2.01: the canworks ST library unless `--no-library`, the `canworks` globals with one typed variable per located value, `ok`, `link`, `in_w` and `out_w`, and the programs `canworks_in` and `canworks_out`) and the target's files. A config without `bridge`, without `plc_link` or with errors SHALL be refused, naming the fix; so SHALL `--for codesys`.

#### Scenario: Export for truST
- **WHEN** the user runs `canworks-deploy --config cell.json --export-plcopen out --for trust` on a bridge config with `plc_link` and trimmed mailboxes
- **THEN** `out/canworks.xml` holds the library blocks, the `canworks` variables and the two programs, and the command names the files written

#### Scenario: Export for CODESYS
- **WHEN** the user runs the export with `--for codesys`
- **THEN** nothing is written and the message says CODESYS runs canworks as the CODESYS target (`--codesys-import`), not as a Modbus client

#### Scenario: No PLC link
- **WHEN** the config has a `bridge` without `plc_link`
- **THEN** nothing is written and the message says to turn on the PLC link and run Pack for Modbus

#### Scenario: Library only
- **WHEN** the user runs `canworks-deploy library --format plcopen --out lib`
- **THEN** `lib/canworks-library.xml` holds only the library POUs, with no variables, programs or configuration

### Requirement: Global variable dialects
The `canworks` variables SHALL be written as standard TC6: a structure type `canworks_values` and one resource global `canworks` of that type in configuration `canworks_config`, resource `canworks_res`, without vendor `addData`. User code SHALL reach the values as `canworks.<name>`.

#### Scenario: Generic file
- **WHEN** a config is exported with `--for generic`
- **THEN** the file has no `addData` elements, declares `canworks` under the resource's `globalVars`, and validates against the TC6 2.01 schema

## REMOVED Requirements

### Requirement: CODESYS transport
**Reason**: CODESYS as a Modbus client of the bridge is not a supported use (Toni 2026-10-23).
**Migration**: Use the CODESYS target, where CODESYS runs the CANopen master (`--codesys-import`).
