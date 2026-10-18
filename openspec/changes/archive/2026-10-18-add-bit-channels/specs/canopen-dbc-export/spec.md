## ADDED Requirements

### Requirement: Bit channels as one-bit signals
The DBC export SHALL add, for each bit channel, an unsigned one-bit signal at the entry's start bit plus the bit number, named `<node>_<name>`, or `<node>_<entry signal>_bit<n>` without a `name`, with a comment naming the object, the bit and its location. The written file SHALL carry the bit signals in place of the entry's own signal, so no two signals overlap; the decoding model the bus trace uses SHALL keep both.

#### Scenario: Two buttons
- **WHEN** TPDO1 of node `panel` maps 0x6000:1 at byte 0 with bits 0 and 3 named `jog_x_minus` and `jog_x_plus`
- **THEN** the written message has the one-bit signals `panel_jog_x_minus` at bit 0 and `panel_jog_x_plus` at bit 3 and no 8-bit signal for the entry, and cantools loads the file in strict mode
