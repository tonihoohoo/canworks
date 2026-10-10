## ADDED Requirements

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
