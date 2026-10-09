## ADDED Requirements

### Requirement: Protocol per network
A version 2 network MAY have `protocol`, `"canopen"` (default) or `"j1939"`. A J1939 network SHALL have `adapter` and `j1939`, and SHALL NOT have `role`, `master`, `nodes` or `slave`; each misplaced key SHALL be rejected with a message naming the protocol it belongs to. Version 1 files SHALL NOT have `protocol` or `j1939`.

#### Scenario: Existing config
- **WHEN** a version 2 config without `protocol` is loaded
- **THEN** every network runs as a CANopen network exactly as before this change

#### Scenario: J1939 network with nodes
- **WHEN** a network has `"protocol": "j1939"` and a `nodes` list
- **THEN** the file is rejected with an error saying nodes belong to a CANopen network

### Requirement: ECU identity
`j1939.ecu` SHALL have `name` (fields `identity_number` 0..2^21-1, `manufacturer_code` 0..2047, `ecu_instance` 0..7, `function_instance` 0..31, `function` 0..255, `vehicle_system` 0..127, `vehicle_system_instance` 0..15, `industry_group` 0..7, `arbitrary_address_capable`) and `address` 0..253, and MAY have `address_range` [low, high] within 0..253, `state_location` and `address_location`. Missing NAME fields SHALL default to 0 and false.

#### Scenario: Address out of range
- **WHEN** `j1939.ecu.address` is 254
- **THEN** the file is rejected naming the path and the range 0..253

#### Scenario: Range without arbitrary address capability
- **WHEN** `address_range` is set and `arbitrary_address_capable` is false
- **THEN** the file is rejected saying a range needs an arbitrary-address-capable NAME

### Requirement: Received messages
Each `j1939.rx` entry SHALL have `pgn` (0..0x3FFFF) and `signals`, and MAY have `source` (0..253), or `source_name` with optional `source_name_mask`, `timeout_ms` (0 = no supervision, default) and `status_location`. A PDU1 PGN (PF < 240) SHALL have PS 0. Two entries with the same PGN SHALL differ in their source filter.

#### Scenario: Same PGN from two ECUs
- **WHEN** two `rx` entries have PGN 65280, one with `source` 0 and one with `source` 3
- **THEN** the file loads and each entry takes only its own source's messages

#### Scenario: Same PGN, no filter twice
- **WHEN** two `rx` entries have PGN 65280 and neither has a source filter
- **THEN** the file is rejected naming both paths

### Requirement: Sent messages
Each `j1939.tx` entry SHALL have `pgn` and `signals`, and MAY have `priority` 0..7 (default 6), `destination` (0..253 or 255, default 255, only for PDU1 PGNs), `length` 1..1785 bytes (default: the smallest whole number of bytes, at least 8, that holds every signal), `period_ms` (0 = on change and request only) and `min_gap_ms`. TX PGNs SHALL be unique in a network.

#### Scenario: Destination on a PDU2 PGN
- **WHEN** a `tx` entry with PGN 65281 (PF 255) has `destination` 3
- **THEN** the file is rejected saying PDU2 PGNs are always broadcast

#### Scenario: Signal past the message length
- **WHEN** a `tx` entry has `length` 8 and a signal at start bit 60 with length 8
- **THEN** the file is rejected naming the signal and the length

### Requirement: Signals
Each signal SHALL have `name`, `start_bit`, `length` 1..64 and `iec_location`, and MAY have `byte_order` (`little` default, or `big`), `signed`, `scale`, `offset`, `unit` and `valid_location`. The IEC location size SHALL hold the length (X for 1 bit, B up to 8, W up to 16, D up to 32, L up to 64). Signals of one message SHALL NOT overlap. RX signals SHALL use `%I` and TX signals `%Q`.

#### Scenario: Location too small
- **WHEN** a 16-bit signal maps `%IB10`
- **THEN** the file is rejected naming the signal, its length and the location

### Requirement: Periodic requests
Each `j1939.requests` entry SHALL have `pgn` and `period_ms` (100..600000) and MAY have `destination` (0..253 or 255, default 255).

#### Scenario: Request every second
- **WHEN** a request entry has PGN 65282, destination 0 and `period_ms` 1000
- **THEN** the file loads

### Requirement: Interfaces and simulation for J1939 networks
A J1939 network SHALL NOT share its interface or serial device with any other network, and SHALL NOT have `adapter.simulate: true`; the rejection SHALL say to use a vcan interface for simulation.

#### Scenario: Simulated J1939 network
- **WHEN** a J1939 network has `adapter.simulate: true`
- **THEN** the file is rejected with an error saying J1939 networks run on SocketCAN or slcan interfaces and to use vcan for simulation

### Requirement: J1939 in the schema and writers
`schema/canworks.v2.schema.json` SHALL describe `protocol` and the `j1939` object. Tools that write a config SHALL write version 2 whenever any network is a J1939 network. The example `examples/j1939/canworks.json` SHALL validate, and it SHALL use only proprietary PGNs (0xEF00, 0xFF00..0xFFFF).

#### Scenario: Only a J1939 network
- **WHEN** the configurator saves a config whose one network is J1939
- **THEN** the file has `schema_version: 2` and that network has `"protocol": "j1939"`
