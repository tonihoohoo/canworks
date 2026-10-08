## MODIFIED Requirements

### Requirement: CiA 402 drive model
A simulated device whose profile is CiA 402 SHALL run a drive model: the power drive state machine on 0x6040/0x6041 (including fault and fault reset, quick stop and the "target reached", "set-point acknowledge" and "following error" bits), the modes of operation in 0x6060/0x6061 that its EDS lists in 0x6502 among profile position, profile velocity, homing, cyclic synchronous position, cyclic synchronous velocity and cyclic synchronous torque (homing with methods 17 and 18 on the limit switches, 19 to 22 on the home switch, and 33, 34, 35 and 37 on the current position; the torque set-point 0x6071 accelerating the axis by a configurable gain, less the load torque a machine joint gives, limited by the maximum velocity), actual position and velocity (0x6064, 0x606C) following the demand with configurable acceleration limits and a first-order lag, software position limits (0x607D), a following error window (0x6065) that faults the drive with EMCY 0x8611 when exceeded, home switch, limit switch and blocked inputs that a user and a machine model can set (an input is on when either sets it), an actual torque (0x6077) that shows a machine joint's load while operation is enabled, and in the cyclic synchronous modes with operation enabled a SYNC watchdog that faults the drive with EMCY 0x8700 when, after at least one SYNC in that mode, no SYNC arrives for three interpolation periods (0x60C2, or 10 ms when the EDS has none), which a drive setting can switch off; without any SYNC the model keeps following on every tick as before. The model SHALL count set-point steps larger than its maximum velocity times the interpolation period and report the count in the device's simulator status. Objects the EDS does not have SHALL be left out of the model and reported once.

#### Scenario: Enable the drive
- **WHEN** a master writes controlword 0x0006, then 0x0007, then 0x000F
- **THEN** the statusword passes through "ready to switch on" and "switched on" and reaches "operation enabled"

#### Scenario: Profile position move
- **WHEN** the drive is enabled in profile position mode and the master sets target position 10000 with a rising new set-point bit
- **THEN** the drive acknowledges the set-point, the actual position moves to 10000 at no more than the profile velocity, and "target reached" is set

#### Scenario: Following error
- **WHEN** a user blocks the simulated axis and the master commands a move beyond the following error window
- **THEN** the drive goes to FAULT and sends EMCY 0x8611

#### Scenario: Cyclic synchronous torque
- **WHEN** the drive is enabled in mode 10 and the master sends target torque 100 at every SYNC
- **THEN** the actual velocity rises at the configured gain times 100 until the maximum velocity and 0x6061 shows 10

#### Scenario: Cyclic synchronous torque under load
- **WHEN** a machine joint gives node 6 a load of 165 per mille and the master sends target torque 200 in mode 10
- **THEN** the actual velocity rises at the configured gain times 35

#### Scenario: Input from a fault and from the machine
- **WHEN** the machine clears the home switch input and a user sets it with the `drive_input` fault
- **THEN** the drive sees the home switch on until the fault is cleared

#### Scenario: Homing on the home switch
- **WHEN** a machine joint's home flag sets the home switch input at and below position 0, the drive starts at 20 mm and the master homes it with method 21
- **THEN** the drive moves in the negative direction until the switch comes on, leaves it slowly, sets the home position and reports homing attained

#### Scenario: SYNC stops in CSP
- **WHEN** the drive runs mode 8 with operation enabled, 0x60C2 is 10 ms, and SYNC stops
- **THEN** at the first simulator tick 30 ms or more after the last SYNC the drive goes to FAULT and sends EMCY 0x8700, and not before

### Requirement: Scenarios
A scenario SHALL be a named list of steps run in order, each with an optional start time or delay: set or override a value, give or remove a value source, inject or clear a fault (a device fault, or a machine fault on a network with a machine), wait until a condition on any simulated object or on the machine's counters and sensors holds (with a timeout), expect a condition (now, within a time, or for a whole duration), log a message, and repeat a block. A scenario SHALL be startable and stoppable while the simulator runs and SHALL report its current step. Scenarios marked `autostart` SHALL start when the simulation starts. Several scenarios MAY run at the same time. An expect that fails, or a wait that times out, SHALL fail the scenario with the step, the condition and the value seen; the simulation SHALL go on.

#### Scenario: Test a PLC alarm
- **WHEN** a scenario sets 0x7130:1 of node 5 to 900, then expects 0x6200:1 bit 2 of node 7 to become 1 within 500 ms
- **THEN** the scenario passes when the PLC program switches on the alarm output in time, and fails with the value seen otherwise

#### Scenario: Machine fault step
- **WHEN** a scenario on `motion` injects a jam of joint `z` at 20 s and expects node 6's statusword fault bit within 200 ms
- **THEN** the scenario passes when the drive faults in time
