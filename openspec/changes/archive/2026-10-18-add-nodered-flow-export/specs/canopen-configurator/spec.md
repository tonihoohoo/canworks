## ADDED Requirements

### Requirement: Node-RED flow export on the bridge page
The bridge page SHALL offer **Export Node-RED flow** next to the register map exports. It SHALL download the same file `canworks-deploy --export-nodered` writes for the draft with default host and period, and SHALL show the reason instead when the register map cannot be computed.

#### Scenario: Export
- **WHEN** the user presses Export Node-RED flow on a bridge project with a valid map
- **THEN** the browser downloads `<config name>-node-red.json`, equal to the command-line export of the same config
