## ADDED Requirements

### Requirement: Raw message decoding
A trace of a network with raw messages SHALL show each frame that matches a raw message with the message's name and its signal values (raw and, when the signal has scale, offset or unit, the scaled value with the unit). For a forced message on an identifier the protocol uses, the raw decoding SHALL be shown next to the protocol's. The frame inspector SHALL mark the signals' bits in its bit grid. A trace opened with a DBC file and no config SHALL decode with the DBC's messages the same way. Other frames SHALL be shown as before.

#### Scenario: Joystick frame
- **WHEN** a trace of a plain network has a frame `0x123 FF 0F 00 00 00 00 00 00` and the config has `Joystick` with signal `X` (start 0, length 12, signed, scale 0.1, unit %)
- **THEN** the row reads `Joystick X=-1 (-0.1 %)` and the inspector marks bits 0 to 11 as `X`
