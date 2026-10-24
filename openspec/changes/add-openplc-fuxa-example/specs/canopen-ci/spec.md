## ADDED Requirements

### Requirement: OpenPLC FUXA example check
The tools test shard SHALL check `examples/openplc-fuxa` without the OpenPLC Editor, runtime, FUXA, node or Docker. The check SHALL confirm that:
- the plant files are byte-identical to `examples/modbus-bridge`, and the networks of `canworks/canworks.json` equal those of `examples/node-red-dashboard`;
- the config passes the deploy tool's config check;
- the committed canworks-owned editor files equal what `--into-project` writes on a copy of the project;
- every FUXA tag's node id is published by the project's OPC UA server entry, and every tag a FUXA view writes is writable for `operator` there;
- every OPC UA node of `main` names a variable declared in `main`;
- the runtime image tag in `docker-compose.yml` equals the local runtime's pinned version;
- `docker-compose.yml` and `fuxa/start.sh` name files that exist in the folder.

The check SHALL add no job and no measurable CI time.

#### Scenario: HMI writes a read-only node
- **WHEN** a change makes a FUXA view write `PLC.main.temp1`, which the OPC UA entry publishes read-only
- **THEN** the check fails naming the tag and the node

#### Scenario: Runtime pin moves
- **WHEN** the local runtime's pinned version changes and the example's compose file still names the old tag
- **THEN** the check fails naming both versions
