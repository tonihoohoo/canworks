## ADDED Requirements

### Requirement: Node-RED flow tests
The Node-RED flow tests (golden flow, function-node code run under `node`, round trip against a Modbus server stub) SHALL run in the existing tools test shard and SHALL skip with a message where `node` is missing. No Node-RED installation and no new pull request job SHALL be added.

#### Scenario: No new job
- **WHEN** a pull request changes only `tools/deploy/canworks/nodered.py`
- **THEN** the flow tests run in the existing tools shard and the pull request's job list is the same as before
