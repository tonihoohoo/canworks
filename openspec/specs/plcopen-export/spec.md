# plcopen-export Specification

## Purpose
Export a Modbus bridge config as PLCopen XML for a PLC that imports it and reads the bridge as a Modbus client: the variables, the copy programs and the canworks function blocks in one file, with the target's files that connect it to the bridge.

## Requirements

### Requirement: PLCopen XML export
`canworks-deploy --config FILE --export-plcopen OUT --for generic` SHALL write, for a bridge config with `plc_link`, a folder with `canworks.xml` (TC6 2.01: the canworks ST library unless `--no-library`, the `canworks` globals with one typed variable per located value, `ok`, `link`, `in_w` and `out_w`, and the programs `canworks_in` and `canworks_out`) and the target's files. A config without `bridge`, without `plc_link` or with errors SHALL be refused, naming the fix; so SHALL `--for codesys`. `--for trust` SHALL be refused by the argument parser as an unknown choice: truST is a PLC that imports PLCopen XML and uses `--for generic`.

#### Scenario: Export for truST
- **WHEN** the user runs `canworks-deploy --config cell.json --export-plcopen out --for generic` for a truST PLC on a bridge config with `plc_link`
- **THEN** `out/canworks.xml` holds the library blocks, the `canworks` variables and the two programs, `out` has `README.txt` and `canworks-modbus-map.csv` and no truST files, and the command names the files written

#### Scenario: truST is no longer a target
- **WHEN** the user runs the export with `--for trust`
- **THEN** nothing is written and the usage error lists `generic` and `codesys` as the choices

#### Scenario: Export for CODESYS
- **WHEN** the user runs the export with `--for codesys`
- **THEN** nothing is written and the message says CODESYS runs canworks as the CODESYS target (`--codesys-import`), not as a Modbus client

#### Scenario: No PLC link
- **WHEN** the config has a `bridge` without `plc_link`
- **THEN** nothing is written and the message says to turn on the PLC link and run Pack for Modbus

#### Scenario: Library only
- **WHEN** the user runs `canworks-deploy library --format plcopen --out lib`
- **THEN** `lib/canworks-library.xml` holds only the library POUs, with no variables, programs or configuration

### Requirement: Channel arrays as the boundary
In the exported file, `canworks.in_w[k]` SHALL be input register k of the bridge and `canworks.out_w[k]` holding register k, sized from the highest register the map uses. `canworks_in` and `canworks_out` SHALL do the same conversions, `link` copies, `ok` rule and PLC link header writing as the copy programs `--export-modbus-map OUT.st` writes for the same config. The header SHALL be written last, with the map hash.

#### Scenario: 32-bit value
- **WHEN** a DINT value sits at input registers 20-21 with word order low first
- **THEN** `canworks_in` builds it from `canworks.in_w[20]` (low word) and `canworks.in_w[21]` (high word)

### Requirement: Global variable dialects
The `canworks` variables SHALL be written as standard TC6: a structure type `canworks_values` and one resource global `canworks` of that type in configuration `canworks_config`, resource `canworks_res`, without vendor `addData`. User code SHALL reach the values as `canworks.<name>`.

#### Scenario: Generic file
- **WHEN** a config is exported with `--for generic`
- **THEN** the file has no `addData` elements, declares `canworks` under the resource's `globalVars`, and validates against the TC6 2.01 schema

### Requirement: Tasks in the export
For `--for generic` the resource SHALL hold one cyclic task `canworks_task` whose program instances run `canworks_in`, then `main` when `--with-main` is given, then `canworks_out`, every fifth of the bridge's watchdog time in steps of 5 ms, at least 10 ms. `--with-main` SHALL add an empty `main` program.

#### Scenario: Task order
- **WHEN** a config with `watchdog_ms` 100 is exported with `--for generic --with-main`
- **THEN** the task runs every 20 ms with `canworks_in`, `main` and `canworks_out` in that order

### Requirement: Generic export
`--for generic` SHALL also write the register map as `canworks-modbus-map.csv` and a `README.txt` that lists the client channels (function, registers, target array range) and says that the PLC's Modbus client must fill `canworks.in_w` from input registers and send `canworks.out_w` as holding registers at the task's cycle or faster.

#### Scenario: Other tool
- **WHEN** a config is exported with `--for generic`
- **THEN** the folder has the XML, the CSV map and the README, and no vendor script

### Requirement: Standard globals in the generic dialect
The generic PLCopen XML SHALL use the TC6 2.01 namespace and SHALL declare `canworks` as a VAR_EXTERNAL in every program that reads or writes it.

#### Scenario: Strict importer
- **WHEN** the generic export of a bridge config is checked
- **THEN** it validates against TC6 2.01 and each of `canworks_in`, `canworks_out` and `main` declares `canworks` in its external variables
