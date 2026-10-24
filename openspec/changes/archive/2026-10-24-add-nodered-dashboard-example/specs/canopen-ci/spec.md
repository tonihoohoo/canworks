## ADDED Requirements

### Requirement: Node-RED dashboard example check
The tools test shard SHALL check `examples/node-red-dashboard` without Node-RED, node or Docker. The check SHALL confirm that:
- the plant files are byte-identical to `examples/modbus-bridge`;
- the config passes the deploy tool's config check;
- every canworks node in `dashboard.json` uses the bridge node id of `nodered.flow(cfg, "plant")`;
- every topic it reads exists among the export's names and status topics, and every topic sent to **canworks out** is an output;
- `docker-compose.yml` and `start.sh` name files that exist in the folder.

The check SHALL add no job and no measurable CI time.

#### Scenario: Renamed PDO entry
- **WHEN** a change renames the `rtd_temp1` entry in the example config but leaves `dashboard.json` unchanged
- **THEN** the check fails naming the topic `rtd_temp1` and the dashboard node that uses it
