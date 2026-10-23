# canopen-deploy Specification

## Purpose
A command-line tool on the engineering PC that checks a canworks config, uploads it with its files to canworks-bridge over the diagnostics channel, writes it into OpenPLC Editor projects and exports it (DCF, DBC, HTML, Modbus map, CODESYS, PLCopen, Node-RED).

## Requirements

### Requirement: Checks before upload
Before uploading to a bridge, and for `--check`, the exports and `--into-project`, the deploy tool SHALL validate the config against the published JSON Schema for its `schema_version`, and SHALL run the same EDS checks the bridge runs at load (PDO-mappable, data type, access type, startup SDO value range, and the EDS lint with the bridge's rule and `eds_lint` setting, on the same prepared copy). Any failure SHALL stop with a non-zero exit, naming the file and the JSON path of the problem, and nothing SHALL be uploaded or written. Lint findings that do not stop the bridge SHALL be printed as warnings. A config with neither `bridge` nor `codesys` SHALL be refused as canopen-config-contract's "Config target" says.

#### Scenario: Schema violation
- **WHEN** the config has a node ID of 200
- **THEN** the tool exits non-zero naming `nodes[0].node_id` and the allowed range, and uploads nothing

#### Scenario: EDS check fails
- **WHEN** an `rx_pdos` entry targets a read-only object in the EDS and the user runs `canworks-deploy --config c.json --bridge plc.local`
- **THEN** the tool exits non-zero with the same message the bridge would log, and uploads nothing

#### Scenario: Blocking lint finding
- **WHEN** a node's EDS gives 0x1A00 sub 0 the data type UNSIGNED16, and `eds_lint` is unset
- **THEN** the tool exits non-zero with the same lint error the bridge would log, and uploads nothing

#### Scenario: Old plugin config
- **WHEN** the user runs `canworks-deploy --config old.json --check` on a config with neither `bridge` nor `codesys`
- **THEN** the tool exits non-zero with the message naming the configurator's **Use with canworks-bridge**

### Requirement: Export DCF files from the command line
The deploy tool SHALL accept `--export-dcf DIR` as an alternative to `--bundle`, `--project` and `--into-project`. With it, the tool SHALL run the checks before upload on `--config`, export every node as `canopen-dcf-export` describes into DIR (created if missing, existing `node_<id>.dcf` files replaced), print one line per written file, and SHALL NOT build, assemble or upload anything. On any check or validation failure it SHALL exit non-zero, print every message and write no DCF.

#### Scenario: Export
- **WHEN** `canworks-deploy --config canworks/canworks.json --export-dcf out` runs on a valid config with nodes 2 and 23
- **THEN** it writes `out/node_2.dcf` and `out/node_23.dcf`, exits 0 and contacts no runtime

#### Scenario: Failure
- **WHEN** one node's DCF fails validation
- **THEN** the tool exits non-zero naming the node, section and key, and `out/` gets no new DCF

### Requirement: Export a DBC file from the command line
The deploy tool SHALL accept `--export-dbc FILE` as an alternative to `--bundle`, `--project`, `--into-project` and `--export-dcf`. With it, the tool SHALL run the checks before upload on `--config`, write the DBC as `canopen-dbc-export` describes to FILE (replacing it, through a temporary file and rename), print the file name and any export warnings, and SHALL NOT build, assemble or upload anything. `--dbc-sdo none|config|all` SHALL set the export's SDO option (default `none`) and SHALL be refused without `--export-dbc`. When `--config` is the `canworks/canworks.json` of an editor project, the project's located variables SHALL be used for signal names. On any check failure it SHALL exit non-zero, print every message and leave FILE untouched.

#### Scenario: Export
- **WHEN** `canworks-deploy --config canworks/canworks.json --export-dbc bus.dbc` runs on a valid config
- **THEN** it writes `bus.dbc`, exits 0 and contacts no runtime

#### Scenario: Failure
- **WHEN** the config has an error
- **THEN** the tool exits non-zero with the error and `bus.dbc` is not written

#### Scenario: With SDO frames
- **WHEN** the same command runs with `--dbc-sdo all`
- **THEN** `bus.dbc` also has each node's SDO request and response messages

#### Scenario: Runtime option refused
- **WHEN** `--export-dbc` is given together with `--runtime`
- **THEN** the tool refuses the combination before checking anything

### Requirement: Create an editor project from the command line
The deploy tool SHALL accept `--new-project DIR` as an alternative to `--bundle`, `--project`, `--into-project`, `--export-dcf` and `--export-dbc`. With it, the tool SHALL run the `--into-project` checks on `--config`, create the editor project in DIR as `canopen-editor-project` describes, print the project folder and the number of declared variables, and SHALL NOT build, assemble or upload anything. `--task-interval` SHALL set the task interval (default `T#20ms`) and SHALL be refused without `--new-project`. On any failure it SHALL exit non-zero, print every message and leave DIR as it was.

#### Scenario: Create
- **WHEN** `canworks-deploy --config config/rtd-sensor/canopen_config.json --new-project ~/workspace/rtd-monitor` runs on a valid config
- **THEN** the project is created, the tool exits 0 and contacts no runtime

#### Scenario: Existing folder
- **WHEN** `~/workspace/rtd-monitor` already exists
- **THEN** the tool exits non-zero naming the folder and changes nothing in it

#### Scenario: Interval without a project
- **WHEN** `--task-interval T#10ms` is given without `--new-project`
- **THEN** the tool exits non-zero saying `--task-interval` needs `--new-project`

### Requirement: Simulation file in the bundle
When a `simulation.json` lies next to the config, the deploy tool SHALL check it and upload it with the config to the bridge, together with the EDS or DCF files its extra devices and CSV files its value sources name. `--into-project` and `--new-project` SHALL copy it into the project's `canworks/` folder the same way.

#### Scenario: Simulation file uploaded
- **WHEN** a user deploys a config whose folder has `simulation.json` naming `data/temp.csv` with `--bridge plc.local`
- **THEN** the bridge receives the simulation file and the CSV, and its simulated devices use the CSV

### Requirement: Warning before uploading a config with simulated parts
When the config has a simulated network or any simulated node, `--bridge` SHALL say before uploading what is simulated (the network and no CAN interface used, or the simulated node IDs on the real network), and SHALL ask for confirmation unless `--yes` or `--simulated` is given, or the target is the local bridge (`--bridge local`), which runs every network simulated. `--check-only` SHALL report it as a warning.

#### Scenario: Upload refused without confirmation
- **WHEN** a user deploys a config with a simulated network to `--bridge plc.local` non-interactively without `--yes` or `--simulated`
- **THEN** the deploy tool stops before uploading and says which option uploads it anyway

#### Scenario: One simulated node
- **WHEN** a user deploys interactively a config on `can0` with node 5 simulated
- **THEN** the deploy tool says that node 5 will be a simulated device on the real network `can0` and asks before uploading

#### Scenario: Local bridge
- **WHEN** a user deploys a config on `can0` to `--bridge local` non-interactively
- **THEN** the upload goes ahead without asking, and the output says once that every network runs simulated there

### Requirement: Slave networks in the bundle and checks
The deploy tool SHALL upload each slave network's EDS with the config, and `--check` and every upload SHALL run the same EDS lint, object and binding checks the bridge runs, including the direction and location checks.

#### Scenario: Binding error found on the PC
- **WHEN** a slave binds an `rww` object to a `%QB` location and the user runs `canworks-deploy --check`
- **THEN** the check fails with the same message the bridge would log, before anything is uploaded

### Requirement: Slave EDS command
The deploy tool SHALL provide `canworks-deploy slave-eds <description.json> -o <file.eds>` (canopen-slave-eds), exiting non-zero with the reason when the description is invalid.

#### Scenario: Invalid description
- **WHEN** the description has an object without a type
- **THEN** the command exits non-zero naming the object

### Requirement: Export network documentation from the command line
The deploy tool SHALL accept `--export-html FILE` as an alternative to `--bundle`, `--project`, `--into-project`, `--export-dcf` and `--export-dbc`. With it, the tool SHALL run the checks before upload on `--config`, write the document as `canopen-network-docs` describes to FILE (replacing it, through a temporary file and rename), print the file name and any warnings, and SHALL NOT build, assemble or upload anything. `--network NAME` SHALL limit the document to one network. `--doc-title TEXT` SHALL set the title, `--doc-od used|all` the object dictionary extract (default `used`), `--doc-embed-eds` SHALL embed the EDS files, and `--doc-cycle-ms MS` SHALL give the PLC cycle for the bus-load estimate; these options SHALL be refused without `--export-html`. When `--config` is the `canworks/canworks.json` of an editor project, the project's located variables SHALL be used for PLC variable names and, without `--doc-cycle-ms`, the project's task interval for the PLC cycle. On any check failure it SHALL exit non-zero, print every message and leave FILE untouched.

#### Scenario: Export
- **WHEN** `canworks-deploy --config canworks/canworks.json --export-html network.html` runs on a valid config
- **THEN** it writes `network.html`, exits 0 and contacts no runtime

#### Scenario: Failure
- **WHEN** the config has an error
- **THEN** the tool exits non-zero with the error and `network.html` is not written

#### Scenario: Option without export
- **WHEN** `--doc-od all` is given without `--export-html`
- **THEN** the tool exits non-zero saying the option needs `--export-html`

### Requirement: Deploy to a bridge
`canworks-deploy --config FILE --bridge TARGET` SHALL run the checks before upload, assemble the config and every file it names, and upload them with `put_config` over the diagnostics channel, with the same TLS options and token as `canworks-diag`. `TARGET` SHALL be `HOST[:PORT]`, a remembered runtime name reached by the automatic path choice (`link:NAME` forces the remote link), or `local` for the local bridge of canopen-local-runtime (`127.0.0.1` at its saved diagnostics port). It SHALL print the bridge's answer and exit non-zero when the bridge rejected the config or restored the previous one. `--check-only` SHALL stop before uploading. The deploy tool SHALL NOT upload anything to an OpenPLC runtime: the editor's own Build and upload sends the program and its Modbus master config.

#### Scenario: Successful bridge deploy
- **WHEN** a valid bridge config with two EDS files is deployed with `--bridge plc.local`
- **THEN** the bridge restarts with it and the tool prints the networks the bridge started

#### Scenario: Remembered device over the link
- **WHEN** the PC has paired with device `line1` and the user runs `canworks-deploy --config c.json --bridge line1`
- **THEN** the upload goes over the LAN when the device answers there, else over the remote link, with the same token

#### Scenario: Old runtime option
- **WHEN** the user runs `canworks-deploy --config c.json --runtime plc.local`
- **THEN** the command fails as for any unknown option

### Requirement: Export the Modbus map from the command line
`canworks-deploy --config FILE --export-modbus-map OUT` SHALL write the bridge config's register map in the format given by the extension of OUT (`.csv`, `.json`, `.st`) without contacting any device.

#### Scenario: CSV map
- **WHEN** the example bridge config is exported to `map.csv`
- **THEN** the file has one row per location with its Modbus table and address

### Requirement: Paths safe for the editor's command on Windows
On Windows, the deploy tool SHALL refuse a project or editor path that contains `&`, `|`, `^`, `%`, `<`, `>` or `"` before running the editor's command-line tool, naming the character.

#### Scenario: Ampersand in a folder name
- **WHEN** the project is in `C:\R&D\pump` on Windows
- **THEN** the tool refuses, naming `&`, and runs nothing

### Requirement: Link checks before upload
Before uploading, the deploy tool SHALL run the link and heartbeat watch checks the bridge runs at load (producer TPDO configured, consumer RPDO free and present in the EDS, layout against both EDS files, COB-ID rules, SYNC need, heartbeat watch capacity and timeouts) with the same messages, and SHALL stop with a non-zero exit, uploading nothing, on any error. Warnings (types that differ at one size, kept links that stop with SYNC or watch the master) SHALL be printed and SHALL NOT stop the deploy. The deploy tool's model of each node's download (the one the DCF export uses) SHALL match `canopen_check --dump-writes` for the fixture configs with links.

#### Scenario: Layout mismatch
- **WHEN** a link consumer maps 16 bits for a 32-bit producer TPDO
- **THEN** the tool exits non-zero with the bridge's message and uploads nothing

#### Scenario: Warning only
- **WHEN** a kept link's producer TPDO is synchronous
- **THEN** the tool prints the warning and uploads the config

### Requirement: Notes skeleton command
The deploy tool SHALL provide `canworks-deploy notes skeleton <eds>` (canopen-device-notes), printing a `canworks-notes.v1` document with the EDS identity and an entry per manufacturer object and sub-object (0x2000-0x5FFF), each with its EDS name, data type (`x-type`) and access (`x-access`). With `--all` it SHALL have an entry for every object and sub-object of the EDS, each also with the EDS default (`x-default`), limits (`x-low`, `x-high`) and PDO mapping (`x-pdo`, true or false), each value as the EDS writes it and left out when the EDS has none, and an entry with only the name for each ARRAY and RECORD object itself. `--index LOW-HIGH` SHALL keep only the entries of objects in that index range. Data types SHALL be named, UNSIGNED24-56 and INTEGER24-56 included. When the EDS lacks the vendor ID, product code or revision, the identity SHALL leave it out and a line on stderr SHALL name it. `--output FILE` SHALL write the document to a file instead. An EDS that cannot be read SHALL exit non-zero with the reason, naming the line for a syntax error and the section for a missing or wrong entry.

#### Scenario: Skeleton of a device
- **WHEN** the user runs `canworks-deploy notes skeleton valve.eds` for an EDS with VAR 0x2010 (UNSIGNED8, rw) and RECORD 0x2011 with subs 0-2
- **THEN** the output has `"format": "canworks-notes.v1"`, the EDS identity, `0x2010` with its name, `x-type` UNSIGNED8 and `x-access` rw, and `0x2011:0`, `0x2011:1` and `0x2011:2`

#### Scenario: Every object with its EDS values
- **WHEN** the user runs `canworks-deploy notes skeleton --all valve.eds` and the EDS gives 0x2010 the default 100 and no limits
- **THEN** the output also has `0x1000`, `0x1018:1` and `0x2011` with the RECORD's name, and `0x2010` has `x-default` "100", `x-pdo` false and no `x-low` or `x-high`

#### Scenario: One range of a large EDS
- **WHEN** the user runs `canworks-deploy notes skeleton --all --index 0x3000-0x30FF drive.eds` for an EDS with 600 manufacturer objects
- **THEN** the output has only the entries of objects 0x3000 to 0x30FF

#### Scenario: EDS without a product code
- **WHEN** the EDS's `[DeviceInfo]` has no `ProductNumber`
- **THEN** the identity has no `product_code` and stderr says the EDS gives no product code

#### Scenario: Syntax error in the EDS
- **WHEN** line 1843 of the EDS reads `ObjectType0x7`
- **THEN** the command exits non-zero and the reason names line 1843 and its text

### Requirement: Built-in notes command
The deploy tool SHALL provide `canworks-deploy notes builtin <eds>`, printing the built-in notes that apply to the EDS as a `canworks-notes.v1` document, with `--output FILE` as for `skeleton`. A line on stderr SHALL name the built-in sets used and, when the EDS's 0x1000 default names a device profile without built-in notes or has no default, say so.

#### Scenario: Built-in notes of a drive
- **WHEN** the EDS's 0x1000 default has device profile 402
- **THEN** `canworks-deploy notes builtin` prints the CiA 301 and CiA 402 notes for the objects that EDS has, including the controlword bit names

#### Scenario: Encoder profile
- **WHEN** the EDS's 0x1000 default has device profile 406
- **THEN** the output has the CiA 301 notes only and stderr says that there are no built-in notes for profile 406

### Requirement: Notes check command
The deploy tool SHALL provide `canworks-deploy notes check <eds> <notes file>`, printing the findings the configurator shows for that notes file, one per line, and exiting with status 1 when there is any finding and 0 when there is none. An EDS or notes file that cannot be read SHALL exit non-zero with the reason, naming the line or section as for `skeleton`.

#### Scenario: Check a notes file
- **WHEN** a notes file has a note for 0x2012, which the EDS does not have
- **THEN** `canworks-deploy notes check` prints that the notes file has a note for 0x2012, which the EDS does not have, and exits with status 1

#### Scenario: Object count wrong in the EDS
- **WHEN** the EDS's `[ManufacturerObjects]` says `SupportedObjects=7` and lists six objects
- **THEN** the command exits non-zero and the reason names `[ManufacturerObjects]` and the missing entry 7

### Requirement: CODESYS export from the command line
The deploy tool SHALL accept `--export-codesys DIR` as an alternative to `--bundle`, `--project` and `--into-project`. It SHALL run the checks before upload, write the folder `codesys-export` describes into DIR (created if missing, the files it writes replaced), print one line per written file and contact no runtime. On a failed check or DCF validation it SHALL exit non-zero, print every message and write nothing.

#### Scenario: Export
- **WHEN** `canworks-deploy --config canworks/canworks.json --export-codesys out` runs on a valid config with network `field`
- **THEN** it writes `out/field/node_<id>.dcf`, `out/canworks-codesys.json`, `out/import_canworks.py` and `out/README.txt` and exits 0

### Requirement: CODESYS export options
With the CODESYS export the deploy tool SHALL take the plan's settings from the config's `codesys` objects and SHALL accept, overriding them, `--codesys-net NAME=N` (repeatable, a network's CODESYS network number), `--codesys-plc NAME` (the device to use instead of the project's active application's device), `--codesys-can NETWORK=OBJECT` (repeatable, the CAN interface object in that device that gets the network's bus) and `--codesys-no-variables`, and `--network NAME` (one network). A name that matches no network SHALL fail with a message naming it.

#### Scenario: Unknown network in an override
- **WHEN** `--codesys-net drives=1` names no network in the config
- **THEN** the tool exits non-zero naming `drives` and writes nothing

#### Scenario: Device override
- **WHEN** the config has `codesys.device` `HMI` and `--codesys-plc PLC` is given with `--export-codesys out`
- **THEN** the plan's `plc` is `PLC`

#### Scenario: Settings from the config
- **WHEN** the config has `codesys.device` `PLC` and network `field` has `codesys.interface` `CAN2`, and no flag is given
- **THEN** the plan's `plc` is `PLC` and the `field` network has interface `CAN2`

#### Scenario: CAN interface override
- **WHEN** `--codesys-can field=CAN2` is given with `--export-codesys out`
- **THEN** the plan's `field` network has interface `CAN2`

### Requirement: Import into a CODESYS project from the command line
`canworks-deploy --config FILE --codesys-import [PROJECT]` SHALL write the CODESYS export (into `--codesys-dir DIR` when given, else a temporary folder removed after a run without errors), set the plan to open PROJECT, else the config's `codesys.project`, or to create it when `--codesys-new TYPE:ID:VERSION` or `codesys.create` gives the PLC device, run CODESYS headless on the script, print the script's report, and exit non-zero when the report has an error. A project path without an extension SHALL get `.project` before it is opened or created. With no project given and none in the config it SHALL exit non-zero saying so.

#### Scenario: Existing project
- **WHEN** `canworks-deploy --config canworks.json --codesys-import "C:\Projects\Line 2\cell.project"` runs on a PC with CODESYS installed
- **THEN** CODESYS runs headless, the project gets the bus and is saved, and the report is printed

#### Scenario: Project from the config
- **WHEN** the config has `codesys.project` `C:\Projects\cell.project` and `canworks-deploy --config canworks.json --codesys-import` runs
- **THEN** that project gets the bus

#### Scenario: Project without extension
- **WHEN** the config has `codesys.project` `C:\Projects\cell` and `codesys.create` set, and no `C:\Projects\cell.project` exists
- **THEN** CODESYS creates `C:\Projects\cell.project`

#### Scenario: No project anywhere
- **WHEN** `--codesys-import` is given without a project and the config has no `codesys.project`
- **THEN** the tool exits non-zero saying which project to give, and runs no CODESYS

### Requirement: Finding CODESYS
For `--codesys-import`, CODESYS SHALL come from `--codesys-exe`, else the newest CODESYS install in the standard program folders, and the profile from `--codesys-profile`, else the newest profile of that install. When none is found the tool SHALL exit non-zero saying so.

#### Scenario: CODESYS missing
- **WHEN** no CODESYS install is found and `--codesys-exe` is not given
- **THEN** the tool exits non-zero saying so, after writing nothing outside the temporary folder

### Requirement: Into-project keeps the config's files
`--into-project` SHALL copy every DBC file the config names and each EDS's notes file, and with `--force` SHALL keep the old `canworks/` folder as a dated backup instead of deleting it.

#### Scenario: J1939 config
- **WHEN** a J1939 config naming `machine.dbc` is moved into a project
- **THEN** the project's `canworks/` folder has `machine.dbc`

#### Scenario: Refresh with force
- **WHEN** the project's own config is moved again with `--force`
- **THEN** the old folder is kept as `canworks.bak-<time>`

### Requirement: Export a Node-RED flow from the command line
`canworks-deploy --config FILE --export-nodered OUT` SHALL write the Node-RED flow of a bridge config without contacting any device. `--nodered-host HOST[:PORT]` SHALL set the bridge address the flow connects to (default: the bridge's listen address, `127.0.0.1` for an all-addresses listen) and `--nodered-poll-ms N` the poll period (default 10, kept between 10 and a third of `watchdog_ms`, with a note when changed). The tool SHALL print the number of values in and out, the mailboxes the flow's block nodes can use, and that the flow needs the `node-red-canworks` package of this tools version. A config that is not a bridge config SHALL be refused with a message saying so, and the option SHALL not combine with an upload. `canworks-deploy --export-nodered-package OUT` SHALL write the package `.tgz` of the installed tools (nodered-blocks) and needs no config.

#### Scenario: Defaults
- **WHEN** `canworks-deploy --config examples/modbus-bridge/canworks.json --export-nodered flow.json` runs
- **THEN** `flow.json` connects to `127.0.0.1` on the bridge's port, polls every 10 ms, and the tool prints the number of values in and out and the package it needs

#### Scenario: Package
- **WHEN** `canworks-deploy --export-nodered-package node-red-canworks.tgz` runs with tools 0.120.0
- **THEN** the file is a package `node-red-canworks` version 0.120.0, the same bytes on every run
