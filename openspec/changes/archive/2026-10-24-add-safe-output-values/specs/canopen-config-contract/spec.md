## MODIFIED Requirements

### Requirement: Bridge section in the schema
The version 2 schema SHALL define an optional top-level `bridge` object with:
- `listen` (required)
- `unit_id`, `word_order` (`high_first` or `low_first`), `max_clients`
- `writers` and `readers` (lists of addresses or prefixes)
- `watchdog_ms`, `on_client_loss` (`stop`, `zero`, `hold`, `preop` or `safe`)
- `safe_values`: an object whose keys are `%Q` locations and whose values are booleans, numbers or decimal strings
- `status_location`, `control_location`, `live_lists`
- `sdo_bridge_location` (`request`, `response`) and `sdo_bridge_write`

The schema SHALL also define the `diagnostics.allow_config_upload` flag. A writer SHALL save a config with `bridge` as version 2.

#### Scenario: Bridge config validates
- **WHEN** `examples/modbus-bridge/canworks.json` is validated against the published version 2 schema
- **THEN** it is valid

#### Scenario: Safe values in the schema
- **WHEN** a bridge config with `"on_client_loss": "safe"` and `"safe_values": { "%QW10": 500, "%QX12.0": true }` is validated against the published schema
- **THEN** it is valid, and a key `%IW10` in `safe_values` is not
