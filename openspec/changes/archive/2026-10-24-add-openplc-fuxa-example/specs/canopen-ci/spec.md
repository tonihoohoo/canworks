## ADDED Requirements

### Requirement: OpenPLC FUXA example config check
The tools test shard SHALL check, without the editor, runtime, FUXA or Docker, that:
- the plant files of `examples/openplc-fuxa` are byte-identical to `examples/modbus-bridge`;
- its networks equal those of `examples/node-red-dashboard`;
- the config passes the config check;
- its committed canworks-owned editor files equal what `--into-project` writes on a copy.

The check SHALL add no job and no measurable CI time.

#### Scenario: Stale generated file
- **WHEN** `canworks_in.st` in the example differs from what `--into-project` writes
- **THEN** the check fails naming `canworks_in.st`

### Requirement: OpenPLC FUXA example HMI check
The tools test shard SHALL check that:
- every FUXA tag's node id is published by the example's OPC UA server entry;
- every tag a FUXA view writes is writable for `operator`;
- every OPC UA node of `main` names a variable declared in `main`.

#### Scenario: HMI writes a read-only node
- **WHEN** a change makes a FUXA view write `PLC.main.temp1`, which the OPC UA entry publishes read-only
- **THEN** the check fails naming the tag and the node

### Requirement: OpenPLC FUXA example compose check
The tools test shard SHALL check that the runtime image tag in the example's `docker-compose.yml` equals the local runtime's pinned version, and that `docker-compose.yml` and `fuxa/start.sh` name files that exist in the folder.

#### Scenario: Runtime pin moves
- **WHEN** the local runtime's pinned version changes and the example's compose file still names the old tag
- **THEN** the check fails naming both versions
