## ADDED Requirements

### Requirement: Export network documentation from the command line
The deploy tool SHALL accept `--export-html FILE` as an alternative to `--bundle`, `--project`, `--into-project`, `--export-dcf` and `--export-dbc`. With it, the tool SHALL run the checks before upload on `--config`, write the document as `canopen-network-docs` describes to FILE (replacing it, through a temporary file and rename), print the file name and any warnings, and SHALL NOT build, assemble or upload anything. `--network NAME` SHALL limit the document to one network. `--doc-title TEXT` SHALL set the title, `--doc-od used|all` the object dictionary extract (default `used`), `--doc-embed-eds` SHALL embed the EDS files, and `--doc-cycle-ms MS` SHALL give the PLC cycle for the bus-load estimate; these options SHALL be refused without `--export-html`. When `--config` is the `canopen/canopen.json` of an editor project, the project's located variables SHALL be used for PLC variable names and, without `--doc-cycle-ms`, the project's task interval for the PLC cycle. On any check failure it SHALL exit non-zero, print every message and leave FILE untouched.

#### Scenario: Export
- **WHEN** `openplc-canopen-deploy --config canopen/canopen.json --export-html network.html` runs on a valid config
- **THEN** it writes `network.html`, exits 0 and contacts no runtime

#### Scenario: Failure
- **WHEN** the config has an error
- **THEN** the tool exits non-zero with the error and `network.html` is not written

#### Scenario: Option without export
- **WHEN** `--doc-od all` is given without `--export-html`
- **THEN** the tool exits non-zero saying the option needs `--export-html`
