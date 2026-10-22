## ADDED Requirements

### Requirement: PLCopen XML export
`canworks-deploy --config FILE --export-plcopen OUT --for codesys|trust|generic` SHALL write, for a bridge config with `plc_link`, one PLCopen XML (TC6) file holding: the canworks ST library (the blocks over the bridge, `CW_LINK_SERVICE`, the pure ST helpers and REAL word helpers), unless `--no-library` is given; the global variable list `canworks` with one typed variable per located value of the map (named as in an OpenPLC project), `ok`, `link`, `raw_in` and `raw_out`; the constant list `canworks_const` with `MAP_HASH`, `INPUT_REGISTERS`, `HOLDING_REGISTERS` and `WORD_ORDER_LOW_FIRST`; and the programs `canworks_in` and `canworks_out`. Each typed variable SHALL carry its network, node, PDO and object, unit and scale as documentation. A config without `plc_link`, or with errors, SHALL be refused with nothing written, and the refusal SHALL name the fix.

#### Scenario: Export for truST
- **WHEN** the user runs `canworks-deploy --config cell.json --export-plcopen out --for trust` on a bridge config with `plc_link` and mailboxes
- **THEN** `out/canworks.xml` holds the library blocks, the lists `canworks` and `canworks_const` and the two programs, and the command prints the map hash and the register counts

#### Scenario: No PLC link
- **WHEN** the config has a `bridge` without `plc_link`
- **THEN** nothing is written and the message says to turn on the PLC link and run Pack for Modbus

#### Scenario: Library only
- **WHEN** the user runs `canworks-deploy library --format plcopen --out canworks-lib.xml`
- **THEN** the file holds only the library POUs and no variable lists or programs

### Requirement: Raw register arrays
In the exported file, `canworks.raw_in[k]` SHALL be input register k of the bridge and `canworks.raw_out[k]` holding register k, sized from the map's register counts. `canworks_in` and `canworks_out` SHALL do the same conversions, `link` copies, `ok` rule and PLC link header writing as the programs of an OpenPLC project for the same config, reading and writing the arrays instead of located words. The header SHALL be written last, with `canworks_const.MAP_HASH`.

#### Scenario: Same code as OpenPLC
- **WHEN** the same config is exported for OpenPLC and with `--export-plcopen`
- **THEN** the two `canworks_in` bodies differ only in the raw word expressions (`i12` against `canworks.raw_in[12]`)

#### Scenario: 32-bit value
- **WHEN** a DINT value sits at input registers 20-21 with word order low first
- **THEN** `canworks_in` builds it from `canworks.raw_in[20]` (low word) and `canworks.raw_in[21]` (high word)

### Requirement: Global variable dialects
For `--for codesys` and `--for trust` the variable lists SHALL be written as CODESYS-style named global variable lists (`canworks` qualified-only), and for `--for generic` as standard TC6 resource global variables without vendor `addData`. In every dialect, user code SHALL reach the values as `canworks.<name>` and the constants as `canworks_const.<name>`.

#### Scenario: Generic file
- **WHEN** a config is exported with `--for generic`
- **THEN** the file has no `addData` elements and declares the globals under `instances/configurations/configuration/resource/globalVars`

### Requirement: Tasks in the export
For `--for trust` and `--for generic` the file SHALL hold one configuration with one cyclic task whose program instances run `canworks_in`, `main` and `canworks_out` in that order, with the interval from the bridge's watchdog divided by five, at least 10 ms. `--with-main` SHALL add an empty `main` program. For `--for codesys` the file SHALL hold no configuration.

#### Scenario: Task order
- **WHEN** a config with `watchdog_ms` 100 is exported with `--for trust`
- **THEN** the task runs every 20 ms with `canworks_in` first and `canworks_out` last

### Requirement: CODESYS transport
`--for codesys` SHALL write a folder with `canworks.xml`, the plan `canworks-codesys-modbus.json` (bridge host, port, unit ID, channels, cycle, optional PLC and Ethernet interface names) and the script `import_canworks_modbus.py`. Run in CODESYS (from the script menu on the open project, or headless as the CODESYS export script runs), the script SHALL find the PLC with the rule of `codesys-export` "Uses the project's PLC", import the XML into the PLC's application (replacing objects canworks wrote before), reuse or add an Ethernet adapter, a Modbus TCP Master and a Modbus TCP Slave `canworks_bridge` with the plan's address, set the slave's channels to the plan's (FC 4 reads and FC 16 writes, cyclic at the plan's cycle) mapped onto `canworks.raw_in`/`raw_out` at the channels' start registers, put `canworks_in` first and `canworks_out` last in the application's task, and write `import_report.txt`. Run again, it SHALL leave the project as after the first run. It SHALL run on IronPython 2.7 and CPython 3.

#### Scenario: First import
- **WHEN** the user runs the script on a project with one PLC, its MainTask and no Ethernet device
- **THEN** the project has the canworks lists, programs and library POUs, an Ethernet adapter with a Modbus TCP Master and the slave `canworks_bridge` with the plan's channels, and MainTask calls `canworks_in`, the main program, then `canworks_out`

#### Scenario: Run again after a config change
- **WHEN** the config gains a PDO and the export and script are run again on the same project
- **THEN** the slave's channels and the canworks objects are replaced, the user's own POUs are unchanged, and the report lists what was replaced

#### Scenario: Several tasks
- **WHEN** the application has two cyclic tasks and the plan names none
- **THEN** the script stops before changing anything, names both tasks and says how to name one in the plan

### Requirement: truST transport
`--for trust` SHALL write a folder with `canworks.xml`, `io.toml.part` and `README.txt`. `io.toml.part` SHALL be one `modbus-tcp` driver entry for `io.drivers` with the bridge's address and unit ID whose points make `canworks.raw_in[k]` hold input register k and send `canworks.raw_out[k]` as holding register k every cycle. `README.txt` SHALL give the truST import command and the VS Code command, and say how to merge the driver entry into the project's `io.toml`.

#### Scenario: Run on truST
- **WHEN** the folder is imported into a new truST project, the driver entry is merged and the runtime runs against a bridge with that config
- **THEN** `canworks.ok` is TRUE, input values follow the bridge, and outputs written by `main` reach the bridge's output image

### Requirement: Generic export
`--for generic` SHALL write `canworks.xml` and the register map as `canworks-map.csv` with the suggested client channels, and a `README.txt` saying that the PLC's Modbus client must fill `canworks.raw_in` from input registers and send `canworks.raw_out` as holding registers every cycle, below the bridge's watchdog time.

#### Scenario: Other tool
- **WHEN** a config is exported with `--for generic`
- **THEN** the folder has the XML, the CSV map and the README, and no vendor script
