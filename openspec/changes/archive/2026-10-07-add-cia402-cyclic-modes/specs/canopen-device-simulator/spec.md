## MODIFIED Requirements

### Requirement: CiA 402 drive model
A simulated device whose profile is CiA 402 SHALL run a drive model: the power drive state machine on 0x6040/0x6041 (including fault and fault reset, quick stop and the "target reached", "set-point acknowledge" and "following error" bits), the modes of operation in 0x6060/0x6061 that its EDS lists in 0x6502 among profile position, profile velocity, homing, cyclic synchronous position, cyclic synchronous velocity and cyclic synchronous torque (the torque set-point 0x6071 accelerating the axis by a configurable gain, limited by the maximum velocity), actual position and velocity (0x6064, 0x606C) following the demand with configurable acceleration limits and a first-order lag, software position limits (0x607D), a following error window (0x6065) that faults the drive with EMCY 0x8611 when exceeded, limit switch inputs that a user can set, and in the cyclic synchronous modes with operation enabled a SYNC watchdog that faults the drive with EMCY 0x8700 when, after at least one SYNC in that mode, no SYNC arrives for three interpolation periods (0x60C2, or 10 ms when the EDS has none), which a drive setting can switch off; without any SYNC the model keeps following on every tick as before. The model SHALL count set-point steps larger than its maximum velocity times the interpolation period and report the count in the device's simulator status. Objects the EDS does not have SHALL be left out of the model and reported once.

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

#### Scenario: SYNC stops in CSP
- **WHEN** the drive runs mode 8 with operation enabled, 0x60C2 is 10 ms, and SYNC stops
- **THEN** at the first simulator tick 30 ms or more after the last SYNC the drive goes to FAULT and sends EMCY 0x8700, and not before
