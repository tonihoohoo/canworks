## MODIFIED Requirements

### Requirement: Default behaviour by device profile
Without any behaviour configured for it, a simulated device SHALL choose its behaviour from the device profile in the low 16 bits of 0x1000:
- CiA 401: each digital output object (0x6200, 0x6220, 0x6250) SHALL be copied to the digital input object at the same subindex (0x6000, 0x6020, 0x6050), and each analogue output (0x6411) to the analogue input (0x6401), when both exist;
- CiA 404: each process value object the EDS maps by default into a TPDO SHALL move slowly (a sine of 60 seconds period) between 25 % and 75 % of its EDS limits, or of its data type's range when the EDS gives none;
- any other profile, CiA 402 included: objects keep their values, so only the master, value sources, expressions and the user change them.
A device's default behaviour SHALL be switchable off.

#### Scenario: I/O module loopback
- **WHEN** a simulated CiA 401 module with 0x6200:1 and 0x6000:1 gets 0x6200:1 = 0x05 from the master's RPDO
- **THEN** its next TPDO carrying 0x6000:1 carries 0x05

#### Scenario: Profile without a default
- **WHEN** a device with profile 0 is simulated with no behaviour configured
- **THEN** none of its objects change except by SDO, RPDO or the user

#### Scenario: Default switched off
- **WHEN** a CiA 401 device is simulated with its default behaviour switched off
- **THEN** 0x6000:1 keeps its file value when 0x6200:1 changes

#### Scenario: Drive EDS
- **WHEN** a device whose 0x1000 says profile 402 is simulated and the master writes 0x6040 = 0x000F
- **THEN** 0x6041 keeps its file value, as for any profile without a default

### Requirement: Scenarios
A scenario SHALL be a named list of steps run in order, each with an optional start time or delay: set or override a value, give or remove a value source, inject or clear a device fault, wait until a condition on any simulated object holds (with a timeout), expect a condition (now, within a time, or for a whole duration), log a message, and repeat a block. A scenario SHALL be startable and stoppable while the simulator runs and SHALL report its current step. Scenarios marked `autostart` SHALL start when the simulation starts. Several scenarios MAY run at the same time. An expect that fails, or a wait that times out, SHALL fail the scenario with the step, the condition and the value seen; the simulation SHALL go on.

#### Scenario: Test a PLC alarm
- **WHEN** a scenario sets 0x7130:1 of node 5 to 900, then expects 0x6200:1 bit 2 of node 7 to become 1 within 500 ms
- **THEN** the scenario passes when the PLC program switches on the alarm output in time, and fails with the value seen otherwise

#### Scenario: Machine fault step
- **WHEN** a scenario has a machine fault step or a `drive_input` fault step
- **THEN** the step is refused as unknown, naming the step and the scenario

## REMOVED Requirements

### Requirement: CiA 402 drive model
**Reason**: CiA 402 support is dropped entirely (Toni, 2026-10-22).
**Migration**: A drive's objects can be given value sources or expressions in the simulation file like any device's.

### Requirement: Drive reset on NMT reset node
**Reason**: The drive model is removed; NMT reset node resets every simulated device as "Standard CANopen device behaviour" says.
**Migration**: None.
