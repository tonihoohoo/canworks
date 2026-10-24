## ADDED Requirements

### Requirement: Safe values in the map
The register map SHALL carry each output value's safe value when `on_client_loss` is `"safe"`: the value from `safe_values`, or 0 when it has none. The CSV and JSON exports SHALL have it as a `safe_value` column, the ST list in each output's comment, and the HTML document's register map table as a column. With another action the column SHALL be left out.

#### Scenario: CSV with safe values
- **WHEN** a bridge config with `"safe"` and `"%QW10": 500` is exported with `--export-modbus-map map.csv`
- **THEN** the row of the entry at `%QW10` has `safe_value` 500, and the other output rows have 0
