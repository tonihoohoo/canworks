## ADDED Requirements

### Requirement: Link checks before upload
Before uploading, the deploy tool SHALL run the link and heartbeat watch checks the plugin runs at load (producer TPDO configured, consumer RPDO free and present in the EDS, layout against both EDS files, COB-ID rules, SYNC need, heartbeat watch capacity and timeouts) with the same messages, and SHALL stop with a non-zero exit, uploading nothing, on any error. Warnings (types that differ at one size, kept links that stop with SYNC or watch the master) SHALL be printed and SHALL NOT stop the deploy. The deploy tool's model of each node's download (the one the DCF export uses) SHALL match `canopen_check --dump-writes` for the fixture configs with links.

#### Scenario: Layout mismatch
- **WHEN** a link consumer maps 16 bits for a 32-bit producer TPDO
- **THEN** the tool exits non-zero with the plugin's message and uploads nothing

#### Scenario: Warning only
- **WHEN** a kept link's producer TPDO is synchronous
- **THEN** the tool prints the warning and uploads the bundle
