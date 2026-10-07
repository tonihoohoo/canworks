## ADDED Requirements

### Requirement: Bit explanations in PDO layouts
The byte grid of each PDO in the network document SHALL explain every bit when it is pointed at or focused: the CANopen bit number, the byte and bit in the byte, the mapped object with index, subindex, EDS name and data type, the bit's position and weight within the object, and the PLC address and variable name, or that the bit is unused. The explanation texts SHALL come from the same model as the frame explanation and SHALL be inlined so the document stays one offline file. Without script the grid SHALL show as before.

#### Scenario: Point at a bit in the document
- **WHEN** a reader points at bit 18 of node 5's TPDO1, which is bit 2 of a 16-bit analog input mapped to `%IW100`
- **THEN** the document shows the object, "bit 2 of 16 (weight 4)" and `%IW100`
