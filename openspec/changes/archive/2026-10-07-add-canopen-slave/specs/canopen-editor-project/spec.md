## ADDED Requirements

### Requirement: Declarations for slave bindings
The located variable declarations and the generated editor project SHALL include one variable per slave binding and status location, named from the object's `name` (or its EDS parameter name), prefixed with the network name, with the IEC type matching the location size.

#### Scenario: Slave declarations
- **WHEN** network `line` binds 0x2000:1 (UNSIGNED16) named `speed_setpoint` to `%IW300`
- **THEN** the declarations contain `line_speed_setpoint AT %IW300 : UINT;`
