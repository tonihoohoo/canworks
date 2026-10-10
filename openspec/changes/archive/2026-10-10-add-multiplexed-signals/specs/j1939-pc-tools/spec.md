## MODIFIED Requirements

### Requirement: DBC import
The PC tools SHALL read a DBC file and list its J1939 messages (29-bit identifiers) with PGN, priority, length, cycle time (`GenMsgCycleTime`), sender and signals (start bit, length, byte order, sign, scale, offset, unit, switch and page). Multiplexed messages, simple and extended (`SG_MUL_VAL_`), SHALL be imported with `multiplexer` and `mux`. Messages with 11-bit identifiers, attributes the import does not use, and messages with several switches but no `SG_MUL_VAL_` SHALL be listed as problems, not guessed.

#### Scenario: Import a machine DBC
- **WHEN** the user imports a DBC with PGN 65280 (cycle 100 ms, 4 signals) and one 11-bit message
- **THEN** the import lists PGN 65280 with its 4 signals and cycle time, and one problem naming the 11-bit message

#### Scenario: Import a multiplexed PGN
- **WHEN** the DBC has PGN 65284 with switch `Page` (`M`) and signals `m1` and `m2`
- **THEN** the import lists 65284 with `Page` as switch and each signal's page, and no problem

### Requirement: J1939 DBC export
Exporting a DBC of a J1939 network SHALL write its `rx` and `tx` messages with 29-bit identifiers (receive messages with their source filter address, or 254 when unfiltered; send messages with the configured address), `VFrameFormat` J1939PG, cycle times and signals with their multiplexing (`M`, `mN`, `mNM` and `SG_MUL_VAL_` for value ranges, several values or nested switches), and SHALL load in cantools strict mode.

#### Scenario: Round trip
- **WHEN** a network imported from a DBC is exported again
- **THEN** cantools loads the exported file and its messages have the same PGNs and signal layouts

#### Scenario: Extended multiplexing round trip
- **WHEN** a network has a message with a nested switch and a signal on values 1-2 and 5-9, and is exported and imported again
- **THEN** the imported signals have the same `multiplexer` and `mux` as the original

### Requirement: J1939 network in the configurator
The configurator SHALL let the user add a network as CANopen or J1939. A J1939 network page SHALL have the ECU identity (NAME fields, address, range, state and address locations), "Import DBC…" with a message picker that marks each message receive or send (send preselected when the DBC sender matches the ECU), the `rx`, `tx` and request tables with signal rows (including Switch and Page, as on the CAN messages page) and locations, the `pages` choice on send messages with switches, and the same validation, problem list and save as CANopen networks.

#### Scenario: Build a J1939 network from a DBC
- **WHEN** the user adds a J1939 network, imports a DBC, picks two messages to receive and one to send, and saves
- **THEN** the saved config has a J1939 network with two `rx` and one `tx` entries and no problems
