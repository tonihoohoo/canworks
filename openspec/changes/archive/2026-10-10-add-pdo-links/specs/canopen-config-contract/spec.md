## ADDED Requirements

### Requirement: Links and heartbeat watch in the schema
The JSON Schemas for version 1 and version 2 SHALL describe `links` (on a version 1 file's top level and on a version 2 CANopen master network) and the node field `heartbeat_watch`, through one shared definition each. Both fields SHALL be optional, so every file an earlier release accepted SHALL still validate and mean the same. The checks the schema cannot express (layout against both EDS files, COB-ID rules, nodes of the same network, heartbeat watch capacity) SHALL be listed with the other such checks in docs/config.md, and the shared config fixtures SHALL hold cases for them that the schema, the plugin and the deploy tool judge alike.

#### Scenario: Example with a link validates
- **WHEN** the schema is applied to an example config with a link and a heartbeat watch
- **THEN** it validates without errors in both versions

#### Scenario: Consumer entry with a location
- **WHEN** a link consumer entry gives `iec_location`
- **THEN** the schema, the plugin and the deploy tool reject it, naming `links[0].to[0].entries[0].iec_location`

#### Scenario: Older plugin
- **WHEN** a plugin from before this change loads a version 1 file with `links`
- **THEN** it logs that `links` is an unknown field and loads the rest of the config
