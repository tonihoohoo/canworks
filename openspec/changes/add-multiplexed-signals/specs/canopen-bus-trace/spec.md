## MODIFIED Requirements

### Requirement: Raw message decoding
A trace of a network with raw messages SHALL show each frame that matches a raw message with the message's name and its signal values (raw and, when the signal has scale, offset or unit, the scaled value with the unit). For a multiplexed message only the signals active in that frame SHALL be decoded, the row SHALL name the switch values, and a switch value with no page SHALL be shown as an unknown page; graph series of a multiplexed signal SHALL take points only from frames where it is active. For a forced message on an identifier the protocol uses, the raw decoding SHALL be shown next to the protocol's. The frame inspector SHALL mark the bits of the signals active in the frame in its bit grid. A trace opened with a DBC file and no config SHALL decode with the DBC's messages the same way. Other frames SHALL be shown as before.

#### Scenario: Joystick frame
- **WHEN** a trace of a plain network has a frame `0x123 FF 0F 00 00 00 00 00 00` and the config has `Joystick` with signal `X` (start 0, length 12, signed, scale 0.1, unit %)
- **THEN** the row reads `Joystick X=-1 (-0.1 %)` and the inspector marks bits 0 to 11 as `X`

#### Scenario: Multiplexed frame
- **WHEN** the config's `Status` has switch `Page` (byte 0), `Temp` on page 1 and `Press` (unit kPa) on page 2 at bytes 1-2, and the trace has `Status` with bytes `02 90 01`
- **THEN** the row reads `Status [Page=2] Press=400 kPa`, the inspector marks `Page` and `Press` only, and a graph of `Temp` gets no point from this frame

#### Scenario: Unknown page
- **WHEN** the trace has `Status` with `Page` 7 and no signal is on page 7
- **THEN** the row reads `Status [Page=7 unknown]`
