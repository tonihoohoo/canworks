## ADDED Requirements

### Requirement: J1939 decoding
On a J1939 network, the trace SHALL decode extended frames as J1939: priority, PGN, source and destination, the message and signal names and values from the imported DBC, Address Claimed and Cannot Claim with the NAME fields, Requests with the requested PGN, acknowledgements, and transport protocol (BAM and RTS/CTS) sessions shown as one message with its reassembled data. Frames matching nothing SHALL show the identifier split without names.

#### Scenario: Signal decoded
- **WHEN** the trace holds PGN 65280 from address 0 and the DBC names its first signal `Pressure`
- **THEN** the row shows PGN 65280, source 0, `Pressure` and its scaled value with unit

#### Scenario: BAM session
- **WHEN** the trace holds a TP.CM BAM for PGN 65283 and six TP.DT frames
- **THEN** one row shows PGN 65283 with its 40 data bytes, and the seven frames remain visible as its parts

#### Scenario: Address claim
- **WHEN** the trace holds an Address Claimed from address 128
- **THEN** the row shows the claimed address and each NAME field

### Requirement: J1939 identifier in the frame inspector
The frame inspector SHALL show a 29-bit J1939 identifier split into priority, reserved, data page, PDU format, PDU specific (as destination or group extension) and source address, and the PGN it gives.

#### Scenario: Inspect a PDU1 frame
- **WHEN** the user inspects identifier 0x18EF0380
- **THEN** the inspector shows priority 6, PF 0xEF, destination 3, source 0x80 and PGN 0xEF00

### Requirement: J1939 in the command-line trace
`opencan-diag trace` and `explain` SHALL use the J1939 decoding for J1939 networks.

#### Scenario: Explain a claim
- **WHEN** the user runs `opencan-diag explain 18EEFF80#D204000000820000 --network machine`
- **THEN** the output names Address Claimed from 128 and the NAME fields
