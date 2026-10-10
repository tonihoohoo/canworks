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

### Requirement: Diagnostic messages in DBC import
A DBC message whose PGN is a diagnostic message this change handles (DM1 65226, DM2 65227, DM3 65228, DM11 65235, DM13 57088, DM22 49920) SHALL be listed by the import as a problem saying it is handled by `diagnostics`, and SHALL NOT be offered as an `rx` or `tx` entry. Its signals' `SPN` attributes SHALL still be read for naming codes in the trace and the Faults panel.

#### Scenario: Vendor DBC with DM1
- **WHEN** the user imports a DBC that defines PGN 65226 and PGN 65280
- **THEN** the picker offers PGN 65280 and lists 65226 as a problem pointing to diagnostics

### Requirement: Diagnostics in the configurator
The J1939 network page SHALL have a Diagnostics section with:
- the watched ECUs (`diagnostics.rx`): source or NAME filter, timeout, and each location, with free locations suggested at the right size (`dtcs` consecutive double words for codes)
- the network's own codes (`diagnostics.dtcs`): SPN, FMI (picked from the 32 failure modes with their texts), lamps, flash and a free `%QX` suggested
- `lamps_location`, `clear_location`, `accept_clear` and `dm13`

with the same validation and problem list as the rest of the page. A `j1939.rx` entry for PGN 65226 SHALL be flagged with a hint to use the Diagnostics section.

#### Scenario: Add an own code
- **WHEN** the user adds an own code with SPN 520192, FMI 3, lamp amber, and saves
- **THEN** the config has the entry with a free `%QX` location and no problems

### Requirement: Faults in the J1939 online view
With online access, a J1939 network's online view SHALL have a Faults panel: one row per ECU that sent DM1, with its lamps, its active codes (SPN, SPN name when known, FMI text, OC) and the time since its last DM1; the network's own active and previously active codes; and actions to read an ECU's previously active codes (DM2) and to clear its codes (DM3 or DM11). A clear SHALL ask for confirmation naming the ECU and what will be cleared.

#### Scenario: ECU raises a fault
- **WHEN** the simulator at address 0 starts reporting SPN 520192 FMI 3 while the Faults panel is open
- **THEN** the row for address 0 shows the amber lamp and the code within 2 s

### Requirement: Trouble codes from the command line
`canworks-diag dm` SHALL offer:
- `list`: every ECU that sent DM1, with lamps and codes, from the plugin's status, or on a local adapter after listening 1.5 s
- `read --address N`: the previously active codes of ECU N (DM2)
- `clear --address N [--previous]`: DM11, or DM3 with `--previous`, refused without `--force`

Through the plugin it SHALL use the PLC's claimed address. On a local adapter it SHALL claim a J1939 address for itself (default 249, `--source-address` to change) with a NAME of its own, refuse to send if it cannot claim, and send nothing when only listing.

#### Scenario: List faults through the PLC
- **WHEN** the user runs `canworks-diag dm list --network machine` while ECU 0 reports one code
- **THEN** the output shows address 0, its lamps and the code with its FMI text

#### Scenario: Clear without force
- **WHEN** the user runs `canworks-diag dm clear --address 0`
- **THEN** nothing is sent and the tool says the clear needs `--force`

### Requirement: Declarations for diagnostics
The located variable declarations SHALL include every diagnostics location: for a watched ECU `<network>_dm<source>_status`, `_lamps`, `_flash`, `_count` and `_dtc0`, `_dtc1`, ... (`UDINT`), and for each own code `<network>_dtc_<spn>_<fmi>` (`BOOL`), plus `<network>_dm_lamps` and `<network>_dm_clears`.

#### Scenario: Watched engine
- **WHEN** network `machine` watches source 0 with `count_location` `%IB222`
- **THEN** the declarations hold `machine_dm0_count AT %IB222 : USINT;`
