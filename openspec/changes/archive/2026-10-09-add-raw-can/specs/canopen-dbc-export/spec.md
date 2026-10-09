## ADDED Requirements

### Requirement: Raw messages in the DBC
The exported DBC of a network SHALL contain every raw receive and send message with its identifier (extended identifiers with the DBC's extended flag), DLC, name and signals with their layout, sign, scale, offset, unit and limits, and the send period as `GenMsgCycleTime`. Send messages SHALL have the PLC as sender. A plain network's DBC SHALL hold only its raw messages. Importing the exported file into the CAN messages page SHALL give back the same messages and signals.

#### Scenario: Round trip
- **WHEN** a plain network with `Joystick` (receive) and `Lamps` (send, 100 ms) is exported and the file is imported into a new plain network
- **THEN** the new network's messages, layouts, scaling and period equal the original's
