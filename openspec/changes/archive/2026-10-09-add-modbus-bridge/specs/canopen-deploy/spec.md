## ADDED Requirements

### Requirement: Deploy to a bridge
`canworks-deploy --config FILE --bridge HOST[:PORT]` SHALL run the same checks as an OpenPLC deploy, assemble the config and every file it names, and upload them with `put_config` over the diagnostics channel, with the same TLS options and token as `canworks-diag`. It SHALL print the bridge's answer and exit non-zero when the bridge rejected the config or restored the previous one. `--check-only` SHALL stop before uploading. A config that is not a bridge config SHALL be refused with a message pointing to `--runtime`.

#### Scenario: Successful bridge deploy
- **WHEN** a valid bridge config with two EDS files is deployed with `--bridge pi.local`
- **THEN** the bridge restarts with it and the tool prints the networks the bridge started

### Requirement: Export the Modbus map from the command line
`canworks-deploy --config FILE --export-modbus-map OUT` SHALL write the bridge config's register map in the format given by the extension of OUT (`.csv`, `.json`, `.st`) without contacting any device.

#### Scenario: CSV map
- **WHEN** the example bridge config is exported to `map.csv`
- **THEN** the file has one row per location with its Modbus table and address
