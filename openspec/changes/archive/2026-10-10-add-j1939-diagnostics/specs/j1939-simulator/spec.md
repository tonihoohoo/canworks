## ADDED Requirements

### Requirement: Trouble codes in the simulator
A `canworks-j1939-sim` scenario MAY have `dtcs`, a list of codes with `spn`, `fmi`, optional `lamps`, `flash`, `from_s` and `to_s` (seconds after start; a code is active between them, from start to end when left out). With `dtcs` present the simulator SHALL send DM1 every second and on change as `j1939-diagnostics` describes, keep occurrence counts and previously active codes, answer Requests for DM1 and DM2, and carry out and acknowledge DM3 and DM11. It SHALL print every DM it receives decoded. With `--refuse-clear` it SHALL answer DM3 and DM11 with NACK.

#### Scenario: Faulty ECU on vcan
- **WHEN** the simulator runs a scenario with SPN 520192 FMI 3 from 5 s to 20 s, lamps amber
- **THEN** vcan0 carries DM1 with no codes for 5 s, then with the code and amber on, then without it again after 20 s, every second

#### Scenario: PLC clears the simulator
- **WHEN** the PLC sends a Request for DM3 to the simulator's address
- **THEN** the simulator answers ACK and its next DM2 answer is empty
