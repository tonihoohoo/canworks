# j1939-diagnostics Specification

## Purpose
J1939-73 trouble codes on a J1939 network: the `diagnostics` config, other ECUs' DM1 codes and lamps mapped to the program, the PLC's own DM1, the answers to DM1, DM2, DM3, DM11 and DM22 requests, and DM13.

## Requirements

### Requirement: Diagnostics config
A J1939 network's `j1939` object MAY have `diagnostics` with:
- `rx`: a list of entries, each with `source` (0..253) or `source_name` (with optional `source_name_mask`), optional `timeout_ms` (0..600000, default 3000, 0 = no supervision), and at least one of `status_location` (%IX), `lamps_location` (%IB), `flash_location` (%IB), `count_location` (%IB) and `dtcs_location` (%ID) with `dtcs` (1..32, required with `dtcs_location`). Two entries SHALL NOT have the same source filter.
- `dtcs`: a list of the network's own trouble codes, each with `spn` (0..524287), `fmi` (0..31) and `active_location` (%QX), and optional `lamps` (a subset of `mil`, `red`, `amber`, `protect`) and `flash` (`slow` or `fast`). No two entries SHALL have the same `spn` and `fmi`.
- optional `lamps_location` (%QB), `clear_location` (%IB), `accept_clear` (default true) and `dm13` (default true).

Each violation SHALL be rejected with the path and the allowed range or the conflicting path.

#### Scenario: Watch the engine ECU
- **WHEN** `diagnostics.rx` has one entry with `source` 0, `lamps_location` `%IB221` and `dtcs_location` `%ID56` with `dtcs` 4
- **THEN** the file loads and `%ID56` to `%ID59` are reserved for the four codes

#### Scenario: SPN out of range
- **WHEN** a `diagnostics.dtcs` entry has `spn` 600000
- **THEN** the file is rejected naming the entry and the range 0..524287

#### Scenario: Duplicate own code
- **WHEN** two `diagnostics.dtcs` entries both have SPN 520192 and FMI 3
- **THEN** the file is rejected naming both paths

### Requirement: Trouble code value in the PLC
Every trouble code given to the program SHALL be one `UDINT` equal to SPN + FMI × 2^19 + OC × 2^24 + CM × 2^31. Lamp bytes SHALL use the DM1 wire layout: MIL in bits 7-6, red stop lamp in bits 5-4, amber warning lamp in bits 3-2, protect lamp in bits 1-0, each 00 off, 01 on, 11 not available; the flash byte the same positions with 00 slow, 01 fast, 11 no flash.

#### Scenario: One code
- **WHEN** an ECU reports SPN 520192, FMI 3, occurrence count 2
- **THEN** the program reads 520192 + 3 × 524288 + 2 × 16777216 = 16#021FF000

### Requirement: Receive DM1 into the PLC
The network SHALL take DM1 (PGN 65226) of any length from every source. For each `diagnostics.rx` entry, every DM1 from a matching source SHALL, by the next scan, set `lamps_location` and `flash_location` to bytes 1 and 2, `count_location` to the number of codes (0 when the message carries only the all-zero code, at most 255), the first `dtcs` codes to consecutive double words from `dtcs_location` in message order with unused slots 0, and `status_location` TRUE. With `timeout_ms` above 0 and no DM1 from the source for that long, `status_location` SHALL go FALSE and the other locations SHALL hold their values.

#### Scenario: Several codes by BAM
- **WHEN** ECU 0 sends a DM1 with five codes (22 bytes, BAM) and the entry maps `dtcs` 4
- **THEN** the program reads 5 at `count_location` and the first four codes at `%ID56` to `%ID59`

#### Scenario: Fault cleared on the ECU
- **WHEN** ECU 0's next DM1 carries only the all-zero code and all lamps off
- **THEN** `count_location` reads 0, `%ID56` to `%ID59` read 0 and `lamps_location` reads 0

#### Scenario: ECU silent
- **WHEN** ECU 0 stops sending DM1 and `timeout_ms` is 3000
- **THEN** about 3 s later `status_location` reads FALSE and the codes keep their last values

### Requirement: Old SPN conversion method
A received code with the CM bit set SHALL be passed on unchanged (CM in bit 31), counted per source in the diagnostics status, and logged once per source naming the source address.

#### Scenario: Legacy ECU
- **WHEN** ECU 3 sends a DM1 whose code has CM 1
- **THEN** the program reads the code with bit 31 set and the log has one line naming address 3

### Requirement: Send own DM1
When `diagnostics.dtcs` is non-empty or `lamps_location` is set, the network SHALL, while its address is claimed and DM13 has not suspended it, send DM1 globally with priority 6 every 1000 ms and once after a scan in which the set of active codes or the lamps changed, at most one change-driven send per 1000 ms. A code SHALL be active while its `active_location` is TRUE in the last finished scan. Byte 1 SHALL be the OR of the active codes' lamps and `lamps_location`; with no active code the message SHALL carry one all-zero code with bytes 7-8 0xFF. Each code's occurrence count SHALL start at 0, rise by 1 on each FALSE-to-TRUE of its bit and stop at 126. Messages longer than 8 bytes SHALL go out with the transport protocol.

#### Scenario: Fault raised
- **WHEN** the program sets the `active_location` of SPN 520192 FMI 3 (lamps amber) for the first time
- **THEN** within one scan plus the send time the bus carries a DM1 from the network's address with amber on and the code with OC 1, and it repeats every second

#### Scenario: No faults
- **WHEN** no own code is active and `lamps_location` is 0
- **THEN** a DM1 with all lamps off and the all-zero code goes out every second

#### Scenario: Not yet claimed
- **WHEN** the network is still claiming its address
- **THEN** it sends no DM1

### Requirement: Previously active codes
A code that stops being active SHALL be kept, with its occurrence count, in the previously active list until cleared. The list SHALL be held in memory only and SHALL be empty after the plugin starts.

#### Scenario: Fault goes away
- **WHEN** an own code was active with OC 2 and its bit goes FALSE
- **THEN** the next DM1 no longer carries it and a DM2 request is answered with it and OC 2

### Requirement: DM requests and clears
When the network sends its own DM1 it SHALL:
- answer a Request for DM1 or DM2, sent to its address or global, with the current active or previously active list, subject to the request reply gate
- on a Request for DM3 sent to its address, clear the previously active list and answer with ACK; on one sent globally, clear without ACK
- on a Request for DM11 sent to its address, clear the previously active list and every occurrence count and answer with ACK; on one sent globally, do the same without ACK; codes still active SHALL stay active with OC 1
- add 1 (modulo 256) to `clear_location` for each clear it carries out
- with `accept_clear` false, answer DM3 and DM11 Requests sent to its address with NACK, and ignore global ones
- answer a DM22 command sent to its address with DM22's negative acknowledgement

A network that does not send its own DM1 SHALL treat these PGNs like any other PGN it does not send.

#### Scenario: Tool clears
- **WHEN** a service tool at address 249 sends a Request for DM11 to the PLC's address while one own code is still active
- **THEN** the PLC answers ACK, `clear_location` increases by 1, DM2 is empty and the next DM1 carries the active code with OC 1

#### Scenario: Clears refused
- **WHEN** `accept_clear` is false and a tool sends a Request for DM3 to the PLC's address
- **THEN** the PLC answers NACK and the previously active list is unchanged

### Requirement: DM13 suspends broadcasts
With `dm13` true, a DM13 (PGN 57088) sent to the network's address or globally that commands the current data link to stop broadcasts SHALL suspend DM1 and every `tx` entry with `period_ms` above 0. Address claims, request answers and on-change sends SHALL continue. Broadcasts SHALL resume on a DM13 commanding start for the current data link, or 6 s after the last DM13 that commanded stop or hold. With `dm13` false, DM13 SHALL be ignored.

#### Scenario: Flashing tool quiets the bus
- **WHEN** a tool sends DM13 "stop broadcast" globally and repeats it every 5 s
- **THEN** the PLC's periodic PGNs and DM1 stop and stay stopped while the repeats continue

#### Scenario: Tool goes away
- **WHEN** the tool stops repeating DM13
- **THEN** about 6 s after the last one the PLC's periodic PGNs and DM1 resume
