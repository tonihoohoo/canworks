## MODIFIED Requirements

### Requirement: Config target
A config SHALL target one system: OpenPLC through Modbus when it has a top-level `bridge` object holding an `openplc` object, the Modbus bridge when it has a `bridge` object without one, CODESYS when it has a top-level `codesys` object, else the OpenPLC plugin. A config with both `bridge` and `codesys` SHALL be an error. A CODESYS config SHALL be version 2. The configurator SHALL NOT offer the OpenPLC plugin as a target for new configs.

#### Scenario: Both markers
- **WHEN** a config has both `bridge` and `codesys`
- **THEN** the check fails saying a config targets one system

#### Scenario: OpenPLC through Modbus
- **WHEN** a config has `"bridge": {"openplc": {}, "writers": ["127.0.0.1"]}`
- **THEN** its target is OpenPLC through Modbus and `canworks-bridge` runs it
