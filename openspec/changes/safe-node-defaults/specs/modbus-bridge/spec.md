## ADDED Requirements

### Requirement: Bus flag in the status block
Status block byte 7 bit 1 SHALL be set while any CAN network of the bridge has its interface down or missing or its controller bus-off, and clear otherwise; error-warning and error-passive SHALL NOT set it. Bit 0 keeps its meaning from modbus-bridge "Unclean stop reported". The bridge's diagnostics status SHALL name the networks whose bus is not ok.

#### Scenario: Interface down
- **WHEN** the bridge runs one network on `can0` and `can0` is taken down
- **THEN** within 200 ms byte 7 bit 1 is set, and it clears within 200 ms after `can0` is up again

#### Scenario: Simulated network
- **WHEN** every network is simulated
- **THEN** bit 1 stays clear
