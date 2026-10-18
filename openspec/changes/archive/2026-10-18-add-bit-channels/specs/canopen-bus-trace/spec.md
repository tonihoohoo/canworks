## ADDED Requirements

### Requirement: Bit channels in PDO decoding
A decoded PDO SHALL show, under an entry with bit channels, one line per bit channel with its name (the declared variable name in editor-project mode) and its value 0 or 1.

#### Scenario: Panel frame
- **WHEN** node 11's TPDO1 carries 0x6000:1 = 0x08 and bit 3 is named `jog_x_plus`
- **THEN** the frame shows the entry's value 0x08 and under it `panel_jog_x_plus` = 1
