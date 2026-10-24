## ADDED Requirements

### Requirement: FUXA Node-RED example check
The tools test shard SHALL check `examples/fuxa-node-red` without FUXA, Node-RED, node or Docker. It SHALL confirm that:
- the plant files match `examples/node-red-dashboard`;
- the plant logic code matches `dashboard.json`;
- every canworks node uses the `plant` export's bridge id;
- every topic it reads exists in the export, and every topic written is an output.

The check SHALL add no job and no measurable CI time.

#### Scenario: Renamed PDO entry
- **WHEN** a change renames the `temp1` entry in the example config but leaves `plant.json` unchanged
- **THEN** the check fails naming the topic and the node that uses it

### Requirement: FUXA tag ids checked
The FUXA Node-RED example check SHALL confirm that every tag id used in `plant.json` and in the views of `fuxa/project.json` is a Server tag of that project. It SHALL also confirm that `docker-compose.yml` and `start.sh` name files that exist in the folder.

#### Scenario: Tag missing
- **WHEN** a view binds a tag id that is not among the project's Server tags
- **THEN** the check fails naming the view and the tag id
