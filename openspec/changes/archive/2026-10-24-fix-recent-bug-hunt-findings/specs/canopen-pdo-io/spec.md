## ADDED Requirements

### Requirement: Bit channels in the generated programs on the bridge
In a bridge config each bit channel of a PDO entry SHALL be declared as a BOOL in the generated declarations of every PLC target and the ST map export, at the bit the register map shows. `canworks_in` SHALL read it from its entry, and `canworks_out` SHALL set it in its entry's word.

#### Scenario: Input bits
- **WHEN** an OpenPLC editor project is saved for a config with bit channels `first_bit` and `bit3` on a TPDO entry
- **THEN** the canworks list has both as BOOL and `canworks_in` sets them from the entry's register
