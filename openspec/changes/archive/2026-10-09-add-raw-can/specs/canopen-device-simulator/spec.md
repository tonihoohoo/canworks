## ADDED Requirements

### Requirement: Plain CAN devices
The simulation file SHALL accept a `raw_devices` list. Each device SHALL have a `name`, a `network` when the config has several, `send` entries (identifier, extended, DLC, period, and per signal a layout and a value source as for CANopen objects) and MAY have `replies` (when a frame with this identifier, and optionally this data under a byte mask, is received, send this frame after an optional delay). Plain CAN devices SHALL run on the simulated bus and in the standalone simulator on a SocketCAN interface or USB adapter, SHALL be shown in the simulation view, and SHALL take part in scenarios and fault injection (stop sending, wrong DLC).

#### Scenario: Simulated joystick
- **WHEN** the simulation file has a device sending `Joystick` every 100 ms with signal `X` as a sine from -1000 to 1000 over 4 s
- **THEN** on a simulated plain network the PLC's `Joystick_X` follows the sine and the status bit stays TRUE

#### Scenario: Reply to a request frame
- **WHEN** a device has a reply "on 0x7E0 data 02 01 0C send 0x7E8 04 41 0C 1A F8" and the program sends `0x7E0 02 01 0C 00 00 00 00 00`
- **THEN** a receiver on 0x7E8 gets the reply frame

#### Scenario: Device stops
- **WHEN** a scenario stops the joystick device
- **THEN** the `Joystick` status bit goes FALSE after its timeout
