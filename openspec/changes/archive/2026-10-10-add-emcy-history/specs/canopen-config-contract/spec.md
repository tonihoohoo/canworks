## ADDED Requirements

### Requirement: EMCY COB-ID in the schema
The JSON Schema SHALL describe the optional node field `emcy_cob_id` as `"device"`, `"eds"`, or an integer from 0x001 to 0x7FF, in the node definition shared by `schema_version` 1 and 2. `contract.py` SHALL apply the same checks as the plugin (restricted CAN-IDs and clashes with the network's other identifiers), and the shared config fixtures SHALL cover a valid number, each rejected kind and the default.

#### Scenario: Valid config without the field
- **WHEN** a version 1 config written before this change is checked by the schema, the plugin and the deploy tool
- **THEN** all three accept it

#### Scenario: Restricted COB-ID
- **WHEN** a node has `"emcy_cob_id": 1537` (0x601)
- **THEN** the plugin and the deploy tool reject it with the same message naming the node and `emcy_cob_id`
