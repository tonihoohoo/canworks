# j1939-pc-tools Specification

## Purpose
What the PC tools offer for J1939 networks: editing a network in the configurator, DBC import and export, deploy checks, located variable declarations and the online view.

## Requirements

### Requirement: DBC import
The PC tools SHALL read a DBC file and list its J1939 messages (29-bit identifiers) with PGN, priority, length, cycle time (`GenMsgCycleTime`), sender and signals (start bit, length, byte order, sign, scale, offset, unit, switch and page). Multiplexed messages, simple and extended (`SG_MUL_VAL_`), SHALL be imported with `multiplexer` and `mux`. Messages with 11-bit identifiers, attributes the import does not use, and messages with several switches but no `SG_MUL_VAL_` SHALL be listed as problems, not guessed.

#### Scenario: Import a machine DBC
- **WHEN** the user imports a DBC with PGN 65280 (cycle 100 ms, 4 signals) and one 11-bit message
- **THEN** the import lists PGN 65280 with its 4 signals and cycle time, and one problem naming the 11-bit message

#### Scenario: Import a multiplexed PGN
- **WHEN** the DBC has PGN 65284 with switch `Page` (`M`) and signals `m1` and `m2`
- **THEN** the import lists 65284 with `Page` as switch and each signal's page, and no problem

### Requirement: Config from imported messages
Adding an imported message SHALL create an `rx` or `tx` entry with the DBC's signal layout and names, `period_ms` from the cycle time for `tx`, `timeout_ms` of three times the cycle time for `rx`, the DBC priority, and suggested free IEC locations of the right size. The DBC file SHALL be copied into the project's `canworks/` folder and named in `j1939.dbc`.

#### Scenario: Receive a message
- **WHEN** the user adds PGN 65280 (cycle 100 ms) as received
- **THEN** the config has an `rx` entry for 65280 with `timeout_ms` 300 and each signal on a free `%I` location of matching size

### Requirement: Deploy checks for J1939
The deploy tool SHALL run the J1939 config checks before upload and SHALL include J1939 signal, status, state and address locations in the address clash check across networks and plugins.

#### Scenario: Clash with a CANopen PDO
- **WHEN** a J1939 signal and a CANopen TPDO entry both map `%IW200`
- **THEN** deploy refuses the upload naming both paths

### Requirement: Located variable declarations for J1939
The variable declarations the tools generate SHALL include every J1939 signal with a type matching its location size and sign, named after the network and signal, with scale, offset and unit in a comment.

#### Scenario: Declaration with scaling
- **WHEN** signal `Pressure` (16 bits, scale 0.1, unit bar) on network `machine` maps `%IW200`
- **THEN** the declarations hold `machine_Pressure AT %IW200 : UINT; (* x 0.1 + 0 bar *)`

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

### Requirement: J1939 online view
With online access, a J1939 network's online view SHALL show the claim state and address, the ECUs seen (address and NAME), each `rx` entry's last value per signal, age and timeout state, and each `tx` entry's send count.

#### Scenario: ECU appears
- **WHEN** a simulated ECU claims address 0 while the online view is open
- **THEN** the ECU list shows address 0 with its NAME
