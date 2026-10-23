## MODIFIED Requirements

### Requirement: Export DCF files from the command line
The deploy tool SHALL accept `--export-dcf DIR` as an alternative to `--check`, `--bridge`, `--into-project` and the other exports. With it, the tool SHALL run the checks before upload on `--config`, export every node as `canopen-dcf-export` describes into DIR (created if missing, existing `node_<id>.dcf` files replaced), print one line per written file, and SHALL NOT upload anything. On any check or validation failure it SHALL exit non-zero, print every message and write no DCF.

#### Scenario: Export
- **WHEN** `canworks-deploy --config canworks/canworks.json --export-dcf out` runs on a valid config with nodes 2 and 23
- **THEN** it writes `out/node_2.dcf` and `out/node_23.dcf`, exits 0 and contacts no bridge

#### Scenario: Failure
- **WHEN** one node's DCF fails validation
- **THEN** the tool exits non-zero naming the node, section and key, and `out/` gets no new DCF

### Requirement: Export a DBC file from the command line
The deploy tool SHALL accept `--export-dbc FILE` as an alternative to `--check`, `--bridge`, `--into-project` and the other exports. With it, the tool SHALL run the checks before upload on `--config`, write the DBC as `canopen-dbc-export` describes to FILE (replacing it, through a temporary file and rename), print the file name and any export warnings, and SHALL NOT upload anything. `--dbc-sdo none|config|all` SHALL set the export's SDO option (default `none`) and SHALL be refused without `--export-dbc`. When `--config` is the `canworks/canworks.json` of an editor project, the project's located variables SHALL be used for signal names. On any check failure it SHALL exit non-zero, print every message and leave FILE untouched.

#### Scenario: Export
- **WHEN** `canworks-deploy --config canworks/canworks.json --export-dbc bus.dbc` runs on a valid config
- **THEN** it writes `bus.dbc`, exits 0 and contacts no bridge

#### Scenario: Failure
- **WHEN** the config has an error
- **THEN** the tool exits non-zero with the error and `bus.dbc` is not written

#### Scenario: With SDO frames
- **WHEN** the same command runs with `--dbc-sdo all`
- **THEN** `bus.dbc` also has each node's SDO request and response messages

#### Scenario: Runtime option refused
- **WHEN** `--export-dbc` is given together with `--runtime`
- **THEN** the tool fails as for any unknown option, before checking anything

#### Scenario: Two modes refused
- **WHEN** `--export-dbc` is given together with `--bridge`
- **THEN** the tool refuses the combination before checking anything

### Requirement: Create an editor project from the command line
The deploy tool SHALL accept `--new-project DIR` as an alternative to `--check`, `--bridge`, `--into-project` and the exports. With it, the tool SHALL run the `--into-project` checks on `--config`, create the editor project in DIR as `canopen-editor-project` describes, print the project folder and the number of declared variables, and SHALL NOT upload anything. `--task-interval` SHALL set the task interval (default `T#20ms`) and SHALL be refused without `--new-project`. On any failure it SHALL exit non-zero, print every message and leave DIR as it was.

#### Scenario: Create
- **WHEN** `canworks-deploy --config config/rtd-sensor/canopen_config.json --new-project ~/workspace/rtd-monitor` runs on a valid config
- **THEN** the project is created, the tool exits 0 and contacts no bridge

#### Scenario: Existing folder
- **WHEN** `~/workspace/rtd-monitor` already exists
- **THEN** the tool exits non-zero naming the folder and changes nothing in it

#### Scenario: Interval without a project
- **WHEN** `--task-interval T#10ms` is given without `--new-project`
- **THEN** the tool exits non-zero saying `--task-interval` needs `--new-project`

### Requirement: Export network documentation from the command line
The deploy tool SHALL accept `--export-html FILE` as an alternative to `--check`, `--bridge`, `--into-project` and the other exports. With it, the tool SHALL run the checks before upload on `--config`, write the document as `canopen-network-docs` describes to FILE (replacing it, through a temporary file and rename), print the file name and any warnings, and SHALL NOT upload anything. `--network NAME` SHALL limit the document to one network. `--doc-title TEXT` SHALL set the title, `--doc-od used|all` the object dictionary extract (default `used`), and `--doc-embed-eds` SHALL embed the EDS files; these options SHALL be refused without `--export-html`. When `--config` is the `canworks/canworks.json` of an editor project, the project's located variables SHALL be used for PLC variable names. On any check failure it SHALL exit non-zero, print every message and leave FILE untouched.

#### Scenario: Export
- **WHEN** `canworks-deploy --config canworks/canworks.json --export-html network.html` runs on a valid config
- **THEN** it writes `network.html`, exits 0 and contacts no bridge

#### Scenario: Failure
- **WHEN** the config has an error
- **THEN** the tool exits non-zero with the error and `network.html` is not written

#### Scenario: Option without export
- **WHEN** `--doc-od all` is given without `--export-html`
- **THEN** the tool exits non-zero saying the option needs `--export-html`

### Requirement: CODESYS export from the command line
The deploy tool SHALL accept `--export-codesys DIR` as an alternative to `--check`, `--bridge`, `--into-project` and the other exports. It SHALL run the checks before upload, write the folder `codesys-export` describes into DIR (created if missing, the files it writes replaced), print one line per written file and contact no bridge. On a failed check or DCF validation it SHALL exit non-zero, print every message and write nothing.

#### Scenario: Export
- **WHEN** `canworks-deploy --config canworks/canworks.json --export-codesys out` runs on a valid config with network `field`
- **THEN** it writes `out/field/node_<id>.dcf`, `out/canworks-codesys.json`, `out/import_canworks.py` and `out/README.txt` and exits 0
