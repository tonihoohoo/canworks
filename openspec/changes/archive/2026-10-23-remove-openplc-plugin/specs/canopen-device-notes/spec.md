## MODIFIED Requirements

### Requirement: Notes stay on the PC
Notes files SHALL NOT be copied to the PLC by the deploy tool or read by the bridge, and SHALL NOT change any value written to a device.

#### Scenario: Not deployed
- **WHEN** `canworks-deploy --bridge` uploads a config whose folder holds `valve.eds` and `valve.eds.notes.json`
- **THEN** the upload contains `valve.eds` and no notes file
