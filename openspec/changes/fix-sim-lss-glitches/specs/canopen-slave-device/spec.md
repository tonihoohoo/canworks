## MODIFIED Requirements

### Requirement: LSS slave
With `node_id: null` the slave SHALL start without a node ID and wait for LSS. It SHALL answer LSS switch, identify and fastscan by its 0x1018 identity, take a node ID from the LSS master, and keep it on LSS store in the state file. An LSS bit timing change SHALL be answered as not supported.

`node_id: null` SHALL be rejected by the plugin and the deploy tool when the slave's EDS does not say `LSS_Supported=1` (left out or 0), with "slave: node_id null needs an EDS with LSS_Supported=1; its EDS has no LSS", since the slave could never get a node ID.

#### Scenario: Node ID assigned by LSS
- **WHEN** the slave has `node_id: null` and the LSS master assigns 12 and stores it
- **THEN** the slave boots as node 12, and after a PLC restart boots as node 12 again

#### Scenario: Bit rate change
- **WHEN** the LSS master asks to configure bit timing
- **THEN** the slave answers with error code 1 (not supported) and keeps the adapter's bit rate

#### Scenario: No LSS in the slave's EDS
- **WHEN** the slave has `node_id: null` and its EDS says `LSS_Supported=0`
- **THEN** the plugin and the deploy tool reject the configuration with that message
