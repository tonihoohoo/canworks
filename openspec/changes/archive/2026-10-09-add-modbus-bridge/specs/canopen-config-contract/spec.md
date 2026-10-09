## ADDED Requirements

### Requirement: Bridge section in the schema
The version 2 schema SHALL define an optional top-level `bridge` object with:
- `listen` (required)
- `unit_id`, `word_order` (`high_first` or `low_first`), `max_clients`
- `writers` and `readers` (lists of addresses or prefixes)
- `watchdog_ms`, `on_client_loss` (`stop`, `zero` or `hold`)
- `status_location`, `control_location`, `live_lists`
- `sdo_bridge_location` (`request`, `response`) and `sdo_bridge_write`

The schema SHALL also define the `diagnostics.allow_config_upload` flag. A writer SHALL save a config with `bridge` as version 2.

#### Scenario: Bridge config validates
- **WHEN** `examples/modbus-bridge/canworks.json` is validated against the published version 2 schema
- **THEN** it is valid

### Requirement: Bridge configs are byte-addressed
A config with a `bridge` object SHALL be a bridge config. Its locations SHALL be byte-addressed and checked as the modbus-bridge capability describes. The OpenPLC plugin SHALL refuse a bridge config at load with an error saying it is meant for `canworks-bridge`, and the deploy tool SHALL refuse to upload one to an OpenPLC runtime.

#### Scenario: Bridge config uploaded to OpenPLC
- **WHEN** `canworks-deploy --config bridge.json --runtime HOST` is run with a bridge config
- **THEN** it stops before uploading with a message pointing to `--bridge`
