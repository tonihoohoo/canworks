## MODIFIED Requirements

### Requirement: J1939 decoding
On a J1939 network, the trace SHALL decode extended frames as J1939: priority, PGN, source and destination, the message and signal names and values from the imported DBC, Address Claimed and Cannot Claim with the NAME fields, Requests with the requested PGN, acknowledgements, and transport protocol (BAM and RTS/CTS) sessions shown as one message with its reassembled data. For a multiplexed message only the signals active in that frame SHALL be decoded, and the row SHALL name the switch values; a switch value with no page SHALL be shown as an unknown page. Frames matching nothing SHALL show the identifier split without names.

#### Scenario: Signal decoded
- **WHEN** the trace holds PGN 65280 from address 0 and the DBC names its first signal `Pressure`
- **THEN** the row shows PGN 65280, source 0, `Pressure` and its scaled value with unit

#### Scenario: BAM session
- **WHEN** the trace holds a TP.CM BAM for PGN 65283 and six TP.DT frames
- **THEN** one row shows PGN 65283 with its 40 data bytes, and the seven frames remain visible as its parts

#### Scenario: Address claim
- **WHEN** the trace holds an Address Claimed from address 128
- **THEN** the row shows the claimed address and each NAME field

#### Scenario: Multiplexed PGN
- **WHEN** the DBC's PGN 65284 has switch `Page` with `Temp` on page 1 and `Press` on page 2, and the trace holds a frame with `Page` 2
- **THEN** the row shows `Page=2` and `Press` with its value, and no `Temp`
