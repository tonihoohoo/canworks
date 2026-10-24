## ADDED Requirements

### Requirement: CAN bus object named after the network
The CODESYS build and export SHALL name each CAN bus object after its canworks network.

#### Scenario: One network
- **WHEN** a config with one network "field" is built into CODESYS
- **THEN** the CAN bus object is named "field"
