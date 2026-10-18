## ADDED Requirements

### Requirement: Declarations for bit channels
The located variable declarations and `main` of a new editor project SHALL declare one `BOOL` per located bit channel, right after its entry's declaration (or where it would be when the entry has no location), named `<node>_<name>`, or `<node>_<entry part>_bit<n>` without a `name`, where the entry part is the entry's `name` or its EDS name as the entry's own declaration uses it. With several networks the network prefix SHALL apply as for other names. The comment SHALL name the node, the PDO, the object's index:subindex, the bit number and the device note's bit name when there is one.

#### Scenario: Named bit
- **WHEN** node `panel` maps bit 3 of 0x6000:1 to `%IX140.3` with `name` `jog_x_plus`
- **THEN** the declarations contain `panel_jog_x_plus : BOOL AT %IX140.3;`

#### Scenario: Default name
- **WHEN** node `panel` maps bit 3 of 0x6000:1, which the EDS names "Read input 8 bit 1", to `%IX140.3` without a name
- **THEN** the declarations contain `panel_Read_input_8_bit_1_bit3 : BOOL AT %IX140.3;`
