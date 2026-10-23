# plcopen-export Specification

## Purpose
Export a Modbus bridge config as PLCopen XML for a PLC that imports it and reads the bridge as a Modbus client (truST, others): the variables, the copy programs and the canworks function blocks in one file, with the target's files that connect it to the bridge.

## Requirements

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
For `--for trust` and `--for generic` the resource SHALL hold one cyclic task `canworks_task` whose program instances run `canworks_in`, then `main` when `--with-main` is given, then `canworks_out`, every fifth of the bridge's watchdog time in steps of 5 ms, at least 10 ms. `--with-main` SHALL add an empty `main` program.

#### Scenario: Task order
- **WHEN** a config with `watchdog_ms` 100 is exported with `--for trust --with-main`
- **THEN** the task runs every 20 ms with `canworks_in`, `main` and `canworks_out` in that order

### Requirement: truST transport
`--for trust` SHALL also write `canworks_io.st` (the byte arrays `cw_in AT %IB0` and `cw_out AT %QB0`, because truST's PLCopen import drops AT addresses), `io.toml.part` (the `modbus-tcp` driver with the bridge's address and unit ID, reading the input registers from 0 and writing the holding registers from 0 every cycle, `on_error = "warn"`) and `README.txt` with the import command, the VS Code command, the copy and merge steps and the resource name `canworks_res`. `canworks_in` SHALL first copy `cw_in` into `canworks.in_w` and `canworks_out` SHALL last copy `canworks.out_w` into `cw_out`, high byte first. Because truST's driver moves one request each way, a map with more than 125 input or 123 holding registers SHALL be refused; for a config with mailboxes the refusal SHALL name the trimmed mailboxes that fit (one request mailbox, no receive mailbox, network info or cyclic jobs) and the blocks that then need the receive mailbox (`CAN_RECEIVE`, `J1939_RECEIVE`, `CO_RECV_EMCY`). Because a truST scan with the library takes about 100–125 ms, a bridge watchdog (the effective `watchdog_ms`, including OpenPLC's default of five polls) of more than 0 and less than 500 ms SHALL be refused, and the refusal SHALL name `"watchdog_ms": 500` or more as the fix. The truST documentation SHALL say which blocks work on truST and which do not, the scan time and the watchdog floor. The bridge host defaults to 127.0.0.1 when `listen` is a wildcard.

#### Scenario: Run on truST
- **WHEN** the folder is imported into a new truST project, `canworks_io.st` is copied, the driver is set and the runtime runs against a bridge with that config
- **THEN** `canworks.ok` is TRUE, input values follow the bridge, outputs written by `main` reach the bridge, and `CO_SDO_READ` reads 0x1018:1 of a node

#### Scenario: Default mailboxes on truST
- **WHEN** a config with the default mailboxes is exported with `--for trust`
- **THEN** nothing is written and the message says truST's driver moves one request each way and how to trim the mailboxes

#### Scenario: Trimmed mailboxes on truST
- **WHEN** a config with `"mailboxes": {"requests": 1, "receive": false, "network_info": false, "cyclic_jobs": 0}` is exported with `--for trust` and run against the bridge
- **THEN** the export is written, and `CO_SDO_READ_STRING` reads 0x1008 of a node through the request mailbox

#### Scenario: Watchdog too short for truST
- **WHEN** a config with `bridge.openplc` and no `watchdog_ms` (50 ms with the default 10 ms poll), or with `"watchdog_ms": 499`, is exported with `--for trust`
- **THEN** nothing is written and the message says a truST scan takes about 100–125 ms and to set `"watchdog_ms": 500` or more

#### Scenario: Watchdog long enough or off
- **WHEN** a config with `"watchdog_ms": 500`, with the PLC link's default of 1000 ms, or with `"watchdog_ms": 0` is exported with `--for trust`
- **THEN** the export is written

#### Scenario: Steady outputs on truST
- **WHEN** truST runs the export for 60 s against a bridge with `"watchdog_ms": 500`
- **THEN** the bridge log has no watchdog off and on lines while truST runs, and one outputs-off line when truST stops

### Requirement: Generic export
`--for generic` SHALL also write the register map as `canworks-modbus-map.csv` and a `README.txt` that lists the client channels (function, registers, target array range) and says that the PLC's Modbus client must fill `canworks.in_w` from input registers and send `canworks.out_w` as holding registers at the task's cycle or faster.

#### Scenario: Other tool
- **WHEN** a config is exported with `--for generic`
- **THEN** the folder has the XML, the CSV map and the README, and no vendor script
