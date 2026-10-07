# canopen-deploy Specification

## Purpose
A command-line tool on the engineering PC that adds the CANopen config and EDS files to an editor-built program bundle, checks it, and uploads it to an OpenPLC Runtime v4 through the runtime's REST API.

## Requirements

### Requirement: Bundle assembly
The deploy tool SHALL take a program bundle produced by the OpenPLC editor ("Build only" output directory, or a build it runs with `openplc-cli`), a CANopen config file, and the EDS files the config names. It SHALL add the config as `conf/canopen.json` and each EDS file under `conf/canopen/eds/`, rewriting each node's `eds` path to `canopen/eds/<file name>`. Each EDS SHALL be stored as UTF-8, converted from CP1252 when it is not valid UTF-8, and the tool SHALL print the names of converted files. It SHALL leave every other file of the bundle unchanged, including other plugins' configs in `conf/`.

#### Scenario: Bundle with EtherCAT config
- **WHEN** the editor's build output contains `conf/ethercat.json` and the user deploys a CANopen config with one EDS file
- **THEN** the uploaded zip contains `conf/ethercat.json` unchanged, `conf/canopen.json`, and `conf/canopen/eds/<file>.eds`, and the node's `eds` field reads `canopen/eds/<file>.eds`

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
- **WHEN** `conf/ethercat.json` maps `%ID100` and `conf/canopen.json` maps `%ID100`
- **THEN** the tool exits non-zero naming both files, both JSON paths, and the overlapping location range, and uploads nothing

#### Scenario: Different sizes do not clash
- **WHEN** `conf/ethercat.json` maps `%IW100` and `conf/canopen.json` maps `%ID100`
- **THEN** the tool reports no clash, since they are different variables

#### Scenario: Output shared with Modbus master
- **WHEN** `conf/modbus_master.json` and `conf/canopen.json` both map `%QW10`
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
The deploy tool SHALL log in with `POST /api/login`, upload the zip with `POST /api/upload-file`, and follow `compilation-status` until the build ends, printing the runtime's build log. After a successful build it SHALL start the PLC with `/api/start-plc` and wait until `/api/status` reports it running, unless the user passes `--no-start`. It SHALL exit zero only when the runtime reports a successful build and the PLC runs (or `--no-start` was given). It SHALL read the password from an environment variable or an interactive prompt, never from the command line or the config, and SHALL verify the runtime's TLS certificate against a CA file or a pinned SHA-256 fingerprint unless the user passes an explicit `--insecure`.

#### Scenario: Successful deploy
- **WHEN** the user deploys the ping-pong program and config to a reachable runtime with valid credentials
- **THEN** the runtime compiles the program, its log shows the `canopen` plugin enabled, the PLC is started and running, and the tool exits zero

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
The deploy tool's documentation and its success message SHALL state that uploading from the editor's own "Build and upload" sends no `conf/canopen.json`, so the runtime switches CANopen off until the next deploy.

#### Scenario: Success message
- **WHEN** a deploy succeeds
- **THEN** the tool's last output lines include that warning

### Requirement: Export DCF files from the command line
The deploy tool SHALL accept `--export-dcf DIR` as an alternative to `--bundle`, `--project` and `--into-project`. With it, the tool SHALL run the checks before upload on `--config`, export every node as `canopen-dcf-export` describes into DIR (created if missing, existing `node_<id>.dcf` files replaced), print one line per written file, and SHALL NOT build, assemble or upload anything. On any check or validation failure it SHALL exit non-zero, print every message and write no DCF.

#### Scenario: Export
- **WHEN** `openplc-canopen-deploy --config canopen/canopen.json --export-dcf out` runs on a valid config with nodes 2 and 23
- **THEN** it writes `out/node_2.dcf` and `out/node_23.dcf`, exits 0 and contacts no runtime

#### Scenario: Failure
- **WHEN** one node's DCF fails validation
- **THEN** the tool exits non-zero naming the node, section and key, and `out/` gets no new DCF

### Requirement: Export a DBC file from the command line
The deploy tool SHALL accept `--export-dbc FILE` as an alternative to `--bundle`, `--project`, `--into-project` and `--export-dcf`. With it, the tool SHALL run the checks before upload on `--config`, write the DBC as `canopen-dbc-export` describes to FILE (replacing it, through a temporary file and rename), print the file name and any export warnings, and SHALL NOT build, assemble or upload anything. `--dbc-sdo none|config|all` SHALL set the export's SDO option (default `none`) and SHALL be refused without `--export-dbc`. When `--config` is the `canopen/canopen.json` of an editor project, the project's located variables SHALL be used for signal names. On any check failure it SHALL exit non-zero, print every message and leave FILE untouched.

#### Scenario: Export
- **WHEN** `openplc-canopen-deploy --config canopen/canopen.json --export-dbc bus.dbc` runs on a valid config
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
- **WHEN** `openplc-canopen-deploy --config config/rtd-sensor/canopen_config.json --new-project ~/workspace/rtd-monitor` runs on a valid config
- **THEN** the project is created, the tool exits 0 and contacts no runtime

#### Scenario: Existing folder
- **WHEN** `~/workspace/rtd-monitor` already exists
- **THEN** the tool exits non-zero naming the folder and changes nothing in it

#### Scenario: Interval without a project
- **WHEN** `--task-interval T#10ms` is given without `--new-project`
- **THEN** the tool exits non-zero saying `--task-interval` needs `--new-project`

### Requirement: Simulation file in the bundle
When a `simulation.json` lies next to the config, the deploy tool SHALL check it and add it to the bundle as `conf/canopen/simulation.json`, together with the EDS or DCF files its extra devices and CSV files its value sources name, rewriting their paths as it does for node EDS files. `--into-project` and `--new-project` SHALL copy it into the project's `canopen/` folder the same way.

#### Scenario: Simulation file uploaded
- **WHEN** a user deploys a project whose `canopen/` folder has `simulation.json` naming `data/temp.csv`
- **THEN** the bundle has `conf/canopen/simulation.json` and the CSV, and the simulated devices use the CSV on the runtime

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
- **WHEN** a slave binds an `rww` object to a `%Q` location and the user runs `openplc-canopen-deploy --check`
- **THEN** the check fails with the same message the plugin would log, before anything is uploaded

### Requirement: Slave EDS command
The deploy tool SHALL provide `openplc-canopen-deploy slave-eds <description.json> -o <file.eds>` (canopen-slave-eds), exiting non-zero with the reason when the description is invalid.

#### Scenario: Invalid description
- **WHEN** the description has an object without a type
- **THEN** the command exits non-zero naming the object
