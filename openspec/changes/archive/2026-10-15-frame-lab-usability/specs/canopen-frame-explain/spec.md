# Spec Delta

## MODIFIED Requirements

### Requirement: Identifier layer
The identifier layer SHALL show every identifier bit with its value and weight. For an 11-bit identifier in the CANopen predefined set it SHALL split the bits into the 4-bit function code and the 7-bit node ID, show the arithmetic (for example `0x185 = 3 × 0x80 + 5`), and name the message type and the node with its configured name. It SHALL explain that the identifier is also the priority and that a lower identifier wins arbitration. A 29-bit identifier SHALL be shown with its bits and marked as outside the CANopen predefined set. An identifier changed by the configuration (a PDO COB-ID that is not the default) SHALL be named by its configured use.

#### Scenario: Default TPDO identifier
- **WHEN** frame `185#...` is explained
- **THEN** the identifier layer shows function code 3, node ID 5, TPDO1 of node 5

#### Scenario: Configured COB-ID
- **WHEN** node 5's TPDO2 is configured with COB-ID 0x1A0
- **THEN** a frame with identifier 0x1A0 is explained as TPDO2 of node 5, with a note that this is a configured, not a default, identifier

#### Scenario: Function code without a node ID
- **WHEN** frame `080#` (SYNC) or `000#0105` (NMT) is explained
- **THEN** the low 7 identifier bits are captioned as part of the identifier with no node ID, and nothing reads "null" or names a node
