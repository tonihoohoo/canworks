## ADDED Requirements

### Requirement: Modbus register map
For a bridge config, the document SHALL have a "Modbus register map" section with the bridge settings (listen address, unit ID, word order, watchdog, client-loss action, allowlists), the register map table from the shared map module, and the suggested client channels.

#### Scenario: Bridge document
- **WHEN** the HTML document is generated for the example bridge config
- **THEN** it has a Modbus register map section whose rows match `--export-modbus-map map.csv`
