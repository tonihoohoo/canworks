# j1939-trace Specification

## Purpose
How the bus trace and diagnostics decode and show J1939 traffic.

## Requirements

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

### Requirement: J1939 identifier in the frame inspector
The frame inspector SHALL show a 29-bit J1939 identifier split into priority, reserved, data page, PDU format, PDU specific (as destination or group extension) and source address, and the PGN it gives.

#### Scenario: Inspect a PDU1 frame
- **WHEN** the user inspects identifier 0x18EF0380
- **THEN** the inspector shows priority 6, PF 0xEF, destination 3, source 0x80 and PGN 0xEF00

### Requirement: J1939 in the command-line trace
`canworks-diag trace` and `explain` SHALL use the J1939 decoding for J1939 networks. When the network's DBC cannot be read, including when cantools is not installed, they SHALL warn "decoding without the DBC" with the reason and decode with the config's own messages and signals, never stopping with a traceback.

#### Scenario: Explain a claim
- **WHEN** the user runs `canworks-diag explain 18EEFF80#D204000000820000 --network machine`
- **THEN** the output names Address Claimed from 128 and the NAME fields

#### Scenario: cantools missing
- **WHEN** cantools is not installed and the user runs `canworks-diag explain 18FF0000#0102 --config examples/j1939/canworks.json`
- **THEN** the output warns that it decodes without `machine.dbc` because cantools is not installed, explains the frame as PGN 65280 `Pressures` from the config, and the command exits 0

### Requirement: Diagnostic messages in the trace
The J1939 decoding SHALL decode, without needing a DBC:
- DM1 and DM2 (after transport protocol reassembly): each lamp's state and flash, and each trouble code as SPN, FMI with a short text for the failure mode, occurrence count and, when CM is set, a note that it uses an older SPN format; the all-zero code as "no active codes"
- Requests for DM1, DM2, DM3 and DM11 by their DM names, and the ACK or NACK that answers them
- DM13 with the command for each data link and the suspend signal
- DM22 with its control byte meaning, SPN and FMI
- Component ID (PGN 65249) and Software ID (PGN 65242) as text fields

When the network's DBC has a signal whose `SPN` attribute equals a code's SPN, the code SHALL also show that signal's name. The frame inspector SHALL explain the four bytes of a trouble code bit by bit.

#### Scenario: DM1 with two codes
- **WHEN** the trace holds a DM1 BAM from address 0 with amber on and codes SPN 520192 FMI 3 OC 2 and SPN 520193 FMI 1 OC 1
- **THEN** one row shows DM1 from 0, amber warning lamp on, and both codes with their FMI texts and counts

#### Scenario: Clear and acknowledgement
- **WHEN** the trace holds a Request for DM11 from 249 to 128 and an ACK from 128
- **THEN** the rows read "Request DM11 (clear active DTCs)" and "ACK DM11"
