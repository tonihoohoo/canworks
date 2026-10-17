# canopen-deploy Specification

## Purpose
A command-line tool on the engineering PC that adds the CANopen config and EDS files to an editor-built program bundle, checks it, and uploads it to an OpenPLC Runtime v4 through the runtime's REST API.

## Requirements

### Requirement: Bundle assembly
The deploy tool SHALL take a program bundle produced by the OpenPLC editor ("Build only" output directory, or a build it runs with `openplc-cli`), a CANopen config file, and the EDS files the config names. It SHALL add the config as `conf/canworks.json` and each EDS file under `conf/canworks/eds/`, rewriting each node's `eds` path to `canworks/eds/<file name>`. Each EDS SHALL be stored as UTF-8, converted from CP1252 when it is not valid UTF-8, and the tool SHALL print the names of converted files. It SHALL leave every other file of the bundle unchanged, including other plugins' configs in `conf/`.

#### Scenario: Bundle with EtherCAT config
- **WHEN** the editor's build output contains `conf/ethercat.json` and the user deploys a CANopen config with one EDS file
- **THEN** the uploaded zip contains `conf/ethercat.json` unchanged, `conf/canworks.json`, and `conf/canworks/eds/<file>.eds`, and the node's `eds` field reads `canworks/eds/<file>.eds`

#### Scenario: CP1252 EDS in a bundle
- **WHEN** the config names an EDS containing the CP1252 byte 0x94
- **THEN** the bundle's copy is valid UTF-8 with the same text, the source file on the PC is unchanged, and the tool prints that it converted that file

#### Scenario: EDS file missing on the PC
- **WHEN** the config names an EDS file the tool cannot find
- **THEN** the tool exits non-zero naming the node ID and the file, and uploads nothing

#### Scenario: Not an editor bundle
- **WHEN** the given directory has no program sources the runtime can compile
- **THEN** the tool exits non-zero saying the directory is not an editor build output, and uploads nothing

### Requirement: Checks before upload
Before uploading, the deploy tool SHALL validate the config against the published JSON Schema for its `schema_version`, and SHALL run the same EDS checks the plugin runs at load (PDO-mappable, data type, access type, startup SDO value range, and the EDS lint with the plugin's rule and `eds_lint` setting, on the same prepared copy). Any failure SHALL stop the deploy with a non-zero exit, naming the file and the JSON path of the problem, and nothing SHALL be uploaded. Lint findings that do not stop the PLC SHALL be printed as warnings.

#### Scenario: Schema violation
- **WHEN** the config has a node ID of 200
- **THEN** the tool exits non-zero naming `nodes[0].node_id` and the allowed range, and uploads nothing

#### Scenario: EDS check fails
- **WHEN** an `rx_pdos` entry targets a read-only object in the EDS
- **THEN** the tool exits non-zero with the same message the plugin would log, and uploads nothing

#### Scenario: Blocking lint finding
- **WHEN** a node's EDS gives 0x1A00 sub 0 the data type UNSIGNED16, and `eds_lint` is unset
- **THEN** the tool exits non-zero with the same lint error the plugin would log, and uploads nothing

### Requirement: Address clash check across plugins
Before uploading, the deploy tool SHALL collect the IEC locations used by every plugin config in the bundle's `conf/*.json` (CANopen `iec_location` and `status_location`, and `iec_location` fields in other plugins' configs), and compare their ranges. Since each size letter is a separate table in the OpenPLC image, only locations of the same area and size can overlap. Two plugins mapping overlapping input locations (`%I`) SHALL be an error, since both would write the same input. Two plugins mapping overlapping output locations (`%Q`) SHALL be a warning, since both only read it. An `--allow-clash` option SHALL turn the errors into warnings. A plugin config that is empty or holds only whitespace SHALL count as a config with no locations and SHALL be skipped without a warning; a config with other content that is not valid JSON SHALL be reported as a warning saying its locations are not checked.

#### Scenario: Input clash with EtherCAT
- **WHEN** `conf/ethercat.json` maps `%ID100` and `conf/canworks.json` maps `%ID100`
- **THEN** the tool exits non-zero naming both files, both JSON paths, and the overlapping location range, and uploads nothing

#### Scenario: Different sizes do not clash
- **WHEN** `conf/ethercat.json` maps `%IW100` and `conf/canworks.json` maps `%ID100`
- **THEN** the tool reports no clash, since they are different variables

#### Scenario: Output shared with Modbus master
- **WHEN** `conf/modbus_master.json` and `conf/canworks.json` both map `%QW10`
- **THEN** the tool prints a warning naming both entries and continues

#### Scenario: Clash allowed
- **WHEN** the input clash above is deployed with `--allow-clash`
- **THEN** the tool prints it as a warning and uploads

#### Scenario: Empty plugin config from the editor
- **WHEN** the editor's build contains a zero-byte `conf/ethercat.json`
- **THEN** the tool prints nothing about that file and checks the other configs as usual

#### Scenario: Broken plugin config
- **WHEN** `conf/ethercat.json` holds text that is not valid JSON
- **THEN** the tool prints a warning that the file is not readable JSON and its locations are not checked, and continues

### Requirement: Upload through the runtime API
The deploy tool SHALL log in with `POST /api/login`, read the PLC's state with `/api/status`, upload the zip with `POST /api/upload-file`, and follow `compilation-status` until the build ends, printing the runtime's build log. After a successful build it SHALL start the PLC with `/api/start-plc` and wait until `/api/status` reports it running when the PLC was running before the upload or had no program, or when the user passes `--start`; it SHALL leave the PLC stopped, saying so, when it was stopped before the upload, when the build log does not show whether the plugin was enabled, or when the user passes `--no-start`. It SHALL exit zero only when the runtime reports a successful build and the PLC is in the state the tool said it would leave it in. It SHALL read the password from an environment variable or an interactive prompt, never from the command line or the config, and SHALL verify the runtime's TLS certificate against a CA file or a pinned SHA-256 fingerprint unless the user passes an explicit `--insecure`.

#### Scenario: Successful deploy
- **WHEN** the user deploys the ping-pong program and config to a reachable runtime whose PLC is running, with valid credentials
- **THEN** the runtime compiles the program, its log shows the `canopen` plugin enabled, the PLC is started and running, and the tool exits zero

#### Scenario: PLC stopped for maintenance
- **WHEN** the PLC was stopped before the upload and the user deploys without `--start`
- **THEN** the build runs, the PLC stays stopped, and the tool says it left the PLC stopped and names `--start`

#### Scenario: Leave the PLC stopped
- **WHEN** the user deploys with `--no-start`
- **THEN** the tool does not start the PLC and says it is stopped

#### Scenario: Start refused
- **WHEN** the runtime refuses the start because the device's run/stop switch is at STOP
- **THEN** the tool exits non-zero after the build and says the switch is at STOP

#### Scenario: Wrong credentials
- **WHEN** login fails
- **THEN** the tool exits non-zero with the runtime's error and uploads nothing

#### Scenario: Compile fails
- **WHEN** the runtime reports a failed build
- **THEN** the tool prints the build log and exits non-zero

#### Scenario: Unknown certificate
- **WHEN** the runtime's certificate matches neither the CA file nor the pinned fingerprint and `--insecure` is not given
- **THEN** the tool exits non-zero before sending credentials

### Requirement: Warning about the editor's upload button
The deploy tool's documentation and its success message SHALL state that uploading from the editor's own "Build and upload" sends no `conf/canworks.json`, so the runtime switches CANopen off until the next deploy.

#### Scenario: Success message
- **WHEN** a deploy succeeds
- **THEN** the tool's last output lines include that warning

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
When a `simulation.json` lies next to the config, the deploy tool SHALL check it and add it to the bundle as `conf/canworks/simulation.json`, together with the EDS or DCF files its extra devices and CSV files its value sources name, rewriting their paths as it does for node EDS files. `--into-project` and `--new-project` SHALL copy it into the project's `canworks/` folder the same way.

#### Scenario: Simulation file uploaded
- **WHEN** a user deploys a project whose `canworks/` folder has `simulation.json` naming `data/temp.csv`
- **THEN** the bundle has `conf/canworks/simulation.json` and the CSV, and the simulated devices use the CSV on the runtime

### Requirement: Warning before uploading a config with simulated parts
When the config has a simulated network or any simulated node, the deploy tool SHALL say before uploading what is simulated (the network and no CAN interface used, or the simulated node IDs on the real network), and SHALL ask for confirmation unless `--yes` or `--simulated` is given. `--check-only` SHALL report it as a warning.

#### Scenario: Upload refused without confirmation
- **WHEN** a user deploys a config with a simulated network non-interactively without `--yes` or `--simulated`
- **THEN** the deploy tool stops before uploading and says which option uploads it anyway

#### Scenario: One simulated node
- **WHEN** a user deploys interactively a config on `can0` with node 5 simulated
- **THEN** the deploy tool says that node 5 will be a simulated device on the real network `can0` and asks before uploading

### Requirement: Slave networks in the bundle and checks
The deploy tool SHALL bundle each slave network's EDS with the config, and `--check` and every upload SHALL run the same EDS lint, object and binding checks the plugin runs, including the direction and location checks.

#### Scenario: Binding error found on the PC
- **WHEN** a slave binds an `rww` object to a `%Q` location and the user runs `canworks-deploy --check`
- **THEN** the check fails with the same message the plugin would log, before anything is uploaded

### Requirement: Slave EDS command
The deploy tool SHALL provide `canworks-deploy slave-eds <description.json> -o <file.eds>` (canopen-slave-eds), exiting non-zero with the reason when the description is invalid.

#### Scenario: Invalid description
- **WHEN** the description has an object without a type
- **THEN** the command exits non-zero naming the object

### Requirement: Uploading to the local simulator runtime
With `--runtime local`, the deploy tool SHALL take the target and credentials from the local runtime's saved settings (canopen-local-runtime), SHALL NOT ask the simulated-config confirmation, and SHALL print once before uploading that the local simulator runtime runs every network simulated. All other checks SHALL run as for any runtime.

#### Scenario: Real config to the local runtime
- **WHEN** a user deploys a config on `can0` with no simulated parts to `--runtime local` non-interactively
- **THEN** the upload goes ahead without `--yes` or `--simulated`, and the output says that every network runs simulated there

#### Scenario: Simulated config to the local runtime
- **WHEN** a user deploys a config with `adapter.simulate: true` to `--runtime local` non-interactively
- **THEN** the upload goes ahead without asking

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
`canworks-deploy --config FILE --bridge HOST[:PORT]` SHALL run the same checks as an OpenPLC deploy, assemble the config and every file it names, and upload them with `put_config` over the diagnostics channel, with the same TLS options and token as `canworks-diag`. It SHALL print the bridge's answer and exit non-zero when the bridge rejected the config or restored the previous one. `--check-only` SHALL stop before uploading. A config that is not a bridge config SHALL be refused with a message pointing to `--runtime`.

#### Scenario: Successful bridge deploy
- **WHEN** a valid bridge config with two EDS files is deployed with `--bridge pi.local`
- **THEN** the bridge restarts with it and the tool prints the networks the bridge started

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

### Requirement: Deploy to a remembered runtime
`canworks-deploy --runtime NAME` SHALL accept a remembered runtime and reach its HTTPS port by the automatic path choice (`link:NAME` forces the link), with the same login and certificate fingerprint check as a direct deploy.

#### Scenario: Fingerprint unchanged over the link
- **WHEN** a deploy runs over the link with `--fingerprint`
- **THEN** the runtime's certificate is checked against the fingerprint exactly as on a direct connection, and a mismatch stops the deploy before the password is sent

### Requirement: Link checks before upload
Before uploading, the deploy tool SHALL run the link and heartbeat watch checks the plugin runs at load (producer TPDO configured, consumer RPDO free and present in the EDS, layout against both EDS files, COB-ID rules, SYNC need, heartbeat watch capacity and timeouts) with the same messages, and SHALL stop with a non-zero exit, uploading nothing, on any error. Warnings (types that differ at one size, kept links that stop with SYNC or watch the master) SHALL be printed and SHALL NOT stop the deploy. The deploy tool's model of each node's download (the one the DCF export uses) SHALL match `canopen_check --dump-writes` for the fixture configs with links.

#### Scenario: Layout mismatch
- **WHEN** a link consumer maps 16 bits for a 32-bit producer TPDO
- **THEN** the tool exits non-zero with the plugin's message and uploads nothing

#### Scenario: Warning only
- **WHEN** a kept link's producer TPDO is synchronous
- **THEN** the tool prints the warning and uploads the bundle

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
With the CODESYS export the deploy tool SHALL accept `--network NAME` (one network), `--codesys-net NAME=N` (repeatable, a network's CODESYS network number), `--codesys-plc NAME` (the device to use instead of the project's active application's device), `--codesys-can NETWORK=OBJECT` (repeatable, the CAN interface object in that device that gets the network's bus) and `--codesys-no-variables`. A name that matches no network SHALL fail with a message naming it.

#### Scenario: Unknown network in an override
- **WHEN** `--codesys-net drives=1` names no network in the config
- **THEN** the tool exits non-zero naming `drives` and writes nothing

#### Scenario: Device override
- **WHEN** `--codesys-plc PLC` is given with `--export-codesys out`
- **THEN** the plan's `plc` is `PLC`

#### Scenario: CAN interface override
- **WHEN** `--codesys-can field=CAN2` is given with `--export-codesys out`
- **THEN** the plan's `field` network has interface `CAN2`

### Requirement: Import into a CODESYS project from the command line
`canworks-deploy --config FILE --codesys-import PROJECT` SHALL write the CODESYS export (into `--codesys-dir DIR` when given, else a temporary folder removed after a run without errors), set the plan to open PROJECT, or to create it when `--codesys-new TYPE:ID:VERSION` gives the PLC device, run CODESYS headless on the script, print the script's report, and exit non-zero when the report has an error.

#### Scenario: Existing project
- **WHEN** `canworks-deploy --config canworks.json --codesys-import "C:\Projects\Line 2\cell.project"` runs on a PC with CODESYS installed
- **THEN** CODESYS runs headless, the project gets the bus and is saved, and the report is printed

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
