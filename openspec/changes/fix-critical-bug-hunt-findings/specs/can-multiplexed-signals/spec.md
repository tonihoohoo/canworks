## ADDED Requirements

### Requirement: Switch values beyond the switch's length
On raw CAN and J1939 alike, a transmitted switch value SHALL be cut to the switch's length before the page is chosen, so the frame always carries the signals of the page its switch field says.

#### Scenario: Value 17 on a 4-bit switch
- **WHEN** a raw message has a 4-bit switch with signal A on page 1 and the PLC writes 17 to the switch
- **THEN** the frame's switch field reads 1 and signal A is packed
