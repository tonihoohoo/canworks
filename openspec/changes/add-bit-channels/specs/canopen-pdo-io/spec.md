## ADDED Requirements

### Requirement: Bit channels of a PDO entry
A PDO entry of an integer type (INTEGER8 to INTEGER64, UNSIGNED8 to UNSIGNED64) MAY list `bits`, each with a bit number `bit`, an optional `name` and, except in a CODESYS or Modbus bridge config, an `iec_location`. Bit 0 SHALL be the least significant bit of the entry's value. A bit channel of a TPDO entry SHALL have an `%IX` location and one of an RPDO entry a `%QX` location. An entry with bits MAY leave out its own `iec_location`; an RPDO entry with bits SHALL NOT have one. The plugin SHALL reject, naming the node, the PDO, the object and the bit: `bits` on a BOOLEAN, REAL32 or REAL64 entry, a bit number outside the type's size, a bit listed twice, a location of the wrong area or size, a location outside the image, and a location that overlaps any other location of the config.

#### Scenario: Input bits
- **WHEN** node 11's TPDO1 entry 0x6000:1 (UNSIGNED8) has bits 0 and 3 at `%IX140.0` and `%IX140.3` and no `iec_location`
- **THEN** the configuration is accepted

#### Scenario: Output entry with a location and bits
- **WHEN** an RPDO entry 0x6200:1 has `iec_location` `%QB40` and a bit at `%QX140.0`
- **THEN** the plugin rejects the configuration and names the node, the RPDO and 0x6200:1

#### Scenario: Bit past the type
- **WHEN** an UNSIGNED8 entry lists bit 8
- **THEN** the plugin rejects the configuration and names the entry and bit 8

#### Scenario: Bits on a REAL
- **WHEN** a REAL32 entry lists bits
- **THEN** the plugin rejects the configuration and names the entry

#### Scenario: Overlap with another location
- **WHEN** a bit channel is at `%IX10.0` and the same node's status bit is also `%IX10.0`
- **THEN** the plugin rejects the configuration and names both

### Requirement: Bit channels exchanged with the scan
Each scan the plugin SHALL write every input bit channel's bit of the entry's received value to its `%IX` location, together with the entry's own location when it has one, and SHALL build every output entry that has bits from its `%QX` locations, sending 0 for bits that are not listed. Bit channels SHALL follow the entry's value in every other rule: receive timeouts, node failure and outputs sent again when a node comes up.

#### Scenario: Button pressed
- **WHEN** node 11 sends 0x6000:1 = 0x08 and bit 3 is mapped to `%IX140.3`
- **THEN** `%IX140.3` is TRUE and `%IX140.0` is FALSE in the next scan

#### Scenario: Lamps
- **WHEN** an RPDO entry 0x6200:1 maps bit 0 to `%QX140.0` and bit 2 to `%QX140.2`, and the program sets only `%QX140.2`
- **THEN** the RPDO carries 0x04 for 0x6200:1

#### Scenario: Whole value and bits
- **WHEN** a TPDO entry 0x6041 has `iec_location` `%IW100` and bit 3 at `%IX120.3`, and the drive sends 0x0638
- **THEN** `%IW100` holds 0x0638 and `%IX120.3` is TRUE
