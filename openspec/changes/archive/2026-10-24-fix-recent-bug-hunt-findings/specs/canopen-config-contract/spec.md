## MODIFIED Requirements

### Requirement: CODESYS configs are for CODESYS
canworks-bridge and `canworks-bridge` SHALL refuse a config with a `codesys` object at load with an error saying it is for CODESYS, and the deploy tool SHALL refuse to upload one to a runtime or a bridge.

#### Scenario: CODESYS config uploaded to OpenPLC
- **WHEN** `canworks-deploy --config codesys.json --bridge HOST` is run with a CODESYS config
- **THEN** it stops before uploading with a message saying the config is for CODESYS
