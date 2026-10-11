## MODIFIED Requirements

### Requirement: LSS configuration checks
`lss.assign` SHALL be rejected for a node with `reset_communication: false`, since the new node ID only becomes active on a communication reset. Two nodes with `lss.assign` and the same vendor ID, product code and serial number (and the same revision, or either revision left out or 0) SHALL be rejected, naming both nodes. A node whose EDS does not say `LSS_Supported=1` in `[DeviceInfo]` (left out or 0) does not support LSS. An `lss` object on such a node, whatever it holds, SHALL be rejected by the plugin and the deploy tool, real or simulated (`simulate`), with one message: "node N (name): 'lss' needs an EDS with LSS_Supported=1; this node's EDS has no LSS".

#### Scenario: Reset communication off
- **WHEN** node 12 has `lss.assign` and `"reset_communication": false`
- **THEN** the plugin and the deploy tool reject the configuration, naming node 12 and both settings

#### Scenario: Same device twice
- **WHEN** nodes 12 and 13 both have `lss.assign` with the same vendor ID, product code and serial number
- **THEN** the configuration is rejected, naming nodes 12 and 13

#### Scenario: EDS says no LSS
- **WHEN** node 12 (valve) has `"lss": {"assign": true}` and its EDS does not say `LSS_Supported=1`
- **THEN** the plugin and the deploy tool reject the configuration with "node 12 (valve): 'lss' needs an EDS with LSS_Supported=1; this node's EDS has no LSS"

#### Scenario: Empty lss object on an EDS without LSS
- **WHEN** node 12 has `"lss": {}` and its EDS has `LSS_Supported=0`
- **THEN** the configuration is rejected with the same message
