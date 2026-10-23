## ADDED Requirements

### Requirement: PLCopen XML export
`canworks-deploy --config FILE --export-plcopen OUT --for codesys|trust|generic` SHALL write, for a bridge config with the PLC link (`plc_link`, or `openplc`), a folder with one PLCopen XML (TC6 2.01) file `canworks.xml` and the target's other files. `canworks.xml` SHALL hold: the whole canworks ST library (the blocks over the bridge with their helpers, the mailbox blocks, `CW_LINK_SERVICE`, the CAN and J1939 helper functions and the REAL word helpers), unless `--no-library` is given; the global variables `canworks` with one typed variable per located value of the map (named as in an OpenPLC project), `ok`, `link`, and the channel arrays `in_w` and `out_w`; and the programs `canworks_in` and `canworks_out`. Each typed variable SHALL carry its network, node, PDO and object, unit and scale as documentation. A config without a `bridge`, without the PLC link, or with errors SHALL be refused with nothing written, and the refusal SHALL name the fix. Options that need another `--for` (`--codesys-plc`, `--codesys-ethernet` without codesys, `--with-main` with codesys) SHALL be refused.

#### Scenario: Export for CODESYS
- **WHEN** the user runs `canworks-deploy --config cell.json --export-plcopen out --for codesys --bridge-host 192.168.10.5` on a bridge config with `plc_link` and mailboxes
- **THEN** `out/canworks.xml` holds the library blocks, the `canworks` variables and the two programs, and the command names the files written and the README with the next steps

#### Scenario: No PLC link
- **WHEN** the config has a `bridge` without `plc_link` or `openplc`
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
For `--for codesys` the `canworks` variables SHALL be written as a CODESYS global variable list (vendor `addData`, `{attribute 'qualified_only'}`) and the file SHALL hold no configuration. For `--for trust` and `--for generic` they SHALL be written as standard TC6: a structure type `canworks_values` and one resource global `canworks` of that type in configuration `canworks_config`, resource `canworks_res`, without vendor `addData`. In every dialect, user code SHALL reach the values as `canworks.<name>`.

#### Scenario: Generic file
- **WHEN** a config is exported with `--for generic`
- **THEN** the file has no `addData` elements, declares `canworks` under the resource's `globalVars`, and validates against the TC6 2.01 schema

### Requirement: Tasks in the export
For `--for trust` and `--for generic` the resource SHALL hold one cyclic task `canworks_task` whose program instances run `canworks_in`, then `main` when `--with-main` is given, then `canworks_out`, every fifth of the bridge's watchdog time in steps of 5 ms, at least 10 ms. `--with-main` SHALL add an empty `main` program.

#### Scenario: Task order
- **WHEN** a config with `watchdog_ms` 100 is exported with `--for trust --with-main`
- **THEN** the task runs every 20 ms with `canworks_in`, `main` and `canworks_out` in that order

### Requirement: CODESYS transport
`--for codesys` SHALL also write the plan `canworks-codesys-modbus.json` (bridge host, port, unit ID, channels, cycle, map hash, optional PLC and Ethernet device names), the script `import_canworks_modbus.py`, the shared `import_canworks.py` and `README.txt`. The bridge host SHALL be `--bridge-host`, else `listen` when it is neither a wildcard nor a loopback address; otherwise the export SHALL be refused. Run in CODESYS on the open project, the script SHALL find the PLC with the rule of `codesys-export` "Uses the project's PLC", import `canworks.xml` into the PLC's application (replacing objects of the same name), reuse or add an Ethernet adapter, a Modbus TCP Master and a Modbus TCP Slave `canworks_bridge`, set the slave's address, port and unit ID, put `canworks_in` first and `canworks_out` last in the task that runs the application's programs, build, and write `import_report.txt`. What the script engine cannot set (the slave's channels until checked on a real CODESYS, a task among several, the network interface) SHALL be listed in the report as "by hand" with the values to enter. The script SHALL not save the project. Run again, it SHALL reuse what it added. It SHALL run on IronPython 2.7 and CPython 3.

#### Scenario: First import
- **WHEN** the user runs the script on a project with one PLC, one task and no Ethernet device
- **THEN** the application has the canworks list, programs and library POUs, the PLC has an Ethernet adapter with a Modbus TCP Master and the slave `canworks_bridge` at the plan's address, the task calls `canworks_in` first and `canworks_out` last, and the report lists the channels to enter by hand

#### Scenario: Several tasks
- **WHEN** the application has two tasks and neither or both call `PLC_PRG`
- **THEN** the script changes no task and the report names both tasks and the calls to add by hand

### Requirement: truST transport
`--for trust` SHALL also write `canworks_io.st` (the byte arrays `cw_in AT %IB0` and `cw_out AT %QB0`, because truST's PLCopen import drops AT addresses), `io.toml.part` (the `modbus-tcp` driver with the bridge's address and unit ID, reading the input registers from 0 and writing the holding registers from 0 every cycle, `on_error = "warn"`) and `README.txt` with the import command, the VS Code command, the copy and merge steps and the resource name `canworks_res`. `canworks_in` SHALL first copy `cw_in` into `canworks.in_w` and `canworks_out` SHALL last copy `canworks.out_w` into `cw_out`, high byte first. Because truST's driver moves one request each way, a map with more than 125 input or 123 holding registers SHALL be refused; for a config with mailboxes the refusal SHALL name the trimmed mailboxes that fit (one request mailbox, no receive mailbox, network info or cyclic jobs) and the blocks that then need the receive mailbox (`CAN_RECEIVE`, `J1939_RECEIVE`, `CO_RECV_EMCY`). The truST documentation SHALL say which blocks work on truST and which do not. The bridge host defaults to 127.0.0.1 when `listen` is a wildcard.

#### Scenario: Run on truST
- **WHEN** the folder is imported into a new truST project, `canworks_io.st` is copied, the driver is set and the runtime runs against a bridge with that config
- **THEN** `canworks.ok` is TRUE, input values follow the bridge, outputs written by `main` reach the bridge, and `CO_SDO_READ` reads 0x1018:1 of a node

#### Scenario: Default mailboxes on truST
- **WHEN** a config with the default mailboxes is exported with `--for trust`
- **THEN** nothing is written and the message says truST's driver moves one request each way and how to trim the mailboxes

#### Scenario: Trimmed mailboxes on truST
- **WHEN** a config with `"mailboxes": {"requests": 1, "receive": false, "network_info": false, "cyclic_jobs": 0}` is exported with `--for trust` and run against the bridge
- **THEN** the export is written, and `CO_SDO_READ_STRING` reads 0x1008 of a node through the request mailbox

### Requirement: Generic export
`--for generic` SHALL also write the register map as `canworks-modbus-map.csv` and a `README.txt` that lists the client channels (function, registers, target array range) and says that the PLC's Modbus client must fill `canworks.in_w` from input registers and send `canworks.out_w` as holding registers at the task's cycle or faster.

#### Scenario: Other tool
- **WHEN** a config is exported with `--for generic`
- **THEN** the folder has the XML, the CSV map and the README, and no vendor script
