## ADDED Requirements

### Requirement: Copy as ST call for J1939 PGNs
The configurator's J1939 network page SHALL offer "Copy as ST call" on each `rx` and `tx` entry. For an `rx` entry it SHALL copy Structured Text that declares a `J1939_RECEIVE` instance for the entry's PGN and source filter, drains it in a `WHILE` loop and unpacks each signal with `J1939_GET_BITS` (start bit, length, signedness from the entry, scaling as a comment), and a `J1939_REQUEST` call for the PGN to the entry's source (or global without one). For a `tx` entry it SHALL copy a `J1939_SEND` call with the PGN, priority and length filled in and a `J1939_SET_BITS` line per signal, with a comment that the entry must be removed, or `raw.program_override_protocol` set, before the program may send that PGN. The `NETWORK` input SHALL be the network's number, with its name in a comment, and instance names SHALL include the network's and the entry's names.

#### Scenario: Copy a received PGN
- **WHEN** the user picks "Copy as ST call" on `rx` entry Pressures (PGN 65280, source 0, signal Pressure at bit 0, 16 bits) of network 1 "machine"
- **THEN** the clipboard holds a `J1939_RECEIVE` instance with `NETWORK := 1`, `PGN := 65280`, `SOURCE := 0`, a `J1939_GET_BITS` line for Pressure and a `J1939_REQUEST` call to address 0
