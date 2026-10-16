## ADDED Requirements

### Requirement: EMCY and heartbeat consumer fields need their EDS objects
A slave entry whose EDS has no object 0x1014 SHALL NOT give `emcy_code_location`, `error_register_location` or `emcy_cob_id`; the plugin and the deploy tool's check SHALL reject each one given, naming the node, the field and that the EDS has no EMCY COB-ID (0x1014). A slave entry whose EDS has no object 0x1016 with a writable sub-index SHALL NOT give `heartbeat_consumer`, true or false; it SHALL be rejected naming the node, the field and that the EDS has no consumer heartbeat time (0x1016).

#### Scenario: EMCY COB-ID on a device without EMCY
- **WHEN** node 7's EDS has no 0x1014 and node 7 has `"emcy_cob_id": "eds"`
- **THEN** the configuration is rejected naming node 7, `emcy_cob_id` and 0x1014

#### Scenario: Heartbeat consumer on a device without 0x1016
- **WHEN** node 7's EDS has no 0x1016 and node 7 has `"heartbeat_consumer": false`
- **THEN** the configuration is rejected naming node 7, `heartbeat_consumer` and 0x1016

#### Scenario: Fields left out
- **WHEN** node 7's EDS has neither 0x1014 nor 0x1016 and node 7 gives none of these fields
- **THEN** the configuration is accepted and the generated configuration writes nothing to 0x1014 or 0x1016
