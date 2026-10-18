## ADDED Requirements

### Requirement: Bit channels as one-bit signals
The DBC export SHALL add, for each bit channel, an unsigned one-bit signal at the entry's start bit plus the bit number, named after the bit channel's declared variable name, next to the entry's own signal.

#### Scenario: Two buttons
- **WHEN** TPDO1 of node `panel` maps 0x6000:1 at byte 0 with bits 0 and 3 named `jog_x_minus` and `jog_x_plus`
- **THEN** the message has the entry's 8-bit signal and the one-bit signals `panel_jog_x_minus` at bit 0 and `panel_jog_x_plus` at bit 3
