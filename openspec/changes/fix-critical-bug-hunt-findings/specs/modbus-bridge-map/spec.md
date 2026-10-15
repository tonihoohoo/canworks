## ADDED Requirements

### Requirement: J1939 trouble code lists in bridge configs
A J1939 DM1 trouble code list (`dtcs_location` with `dtcs` above 1) in a Modbus bridge config SHALL place code k at 4 bytes per code from the start, as on a PLC runtime.

#### Scenario: Three codes
- **WHEN** a bridge config has `dtcs_location` `%ID560` with `dtcs` 3
- **THEN** the config is accepted and the three codes lie 4 bytes apart in the image, with no overlap error
