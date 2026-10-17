## ADDED Requirements

### Requirement: Extended program frames and 29-bit PDOs
On a CANopen network, a program frame with an extended identifier SHALL be refused when it equals a PDO COB-ID the network owns.

#### Scenario: Extended frame on an owned PDO
- **WHEN** a TPDO uses a 29-bit COB-ID and `CAN_SEND` sends that identifier with `EXTENDED` TRUE
- **THEN** the block reports the owned-identifier error and nothing is sent
