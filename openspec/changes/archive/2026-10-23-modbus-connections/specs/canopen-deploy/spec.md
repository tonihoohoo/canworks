## MODIFIED Requirements

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
