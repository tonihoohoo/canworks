## ADDED Requirements

### Requirement: Safe torque off input of the drive model
The CiA 402 drive model SHALL have a safe torque off input, which a machine's safety relay sets. While it is on, the drive SHALL be in "switch on disabled" with "voltage enabled" off, SHALL refuse to go further in the power state machine, SHALL stop following the demand, and its actual velocity SHALL fall to 0 at the drive model's maximum acceleration. It SHALL send no EMCY for it, and the device's simulator status SHALL show it. When the input goes off, the drive SHALL stay in "switch on disabled" until the master runs the enable sequence again.

#### Scenario: Power stage off while enabled
- **WHEN** the drive is in operation enabled and the safe torque off input turns on
- **THEN** the statusword shows switch on disabled with voltage enabled off, the actual velocity falls to 0, and no EMCY is sent

#### Scenario: Enable refused while off
- **WHEN** the input is on and the master writes controlword 0x0006
- **THEN** the drive stays in switch on disabled

#### Scenario: Enable after the input goes off
- **WHEN** the input goes off and the master writes 0x0006, 0x0007 and 0x000F
- **THEN** the drive reaches operation enabled with its actual position unchanged
