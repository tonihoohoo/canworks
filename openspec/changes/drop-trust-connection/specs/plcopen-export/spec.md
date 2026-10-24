## MODIFIED Requirements

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

### Requirement: Tasks in the export
For `--for generic` the resource SHALL hold one cyclic task `canworks_task` whose program instances run `canworks_in`, then `main` when `--with-main` is given, then `canworks_out`, every fifth of the bridge's watchdog time in steps of 5 ms, at least 10 ms. `--with-main` SHALL add an empty `main` program.

#### Scenario: Task order
- **WHEN** a config with `watchdog_ms` 100 is exported with `--for generic --with-main`
- **THEN** the task runs every 20 ms with `canworks_in`, `main` and `canworks_out` in that order

## REMOVED Requirements

### Requirement: truST transport
**Reason**: truST is no longer its own Modbus target (Toni, 2026-10-24). It imports the generic export like any other PLC that reads PLCopen XML; its I/O image file, `io.toml` part, byte copy loops, one-request size check and 500 ms watchdog floor go.
**Migration**: None (not in real use). A truST user exports `--for generic` and wires truST's Modbus driver by hand.

### Requirement: truST trim offered only when it fits
**Reason**: The one-request limit it guards belonged to the truST transport, which is removed.
**Migration**: None.
