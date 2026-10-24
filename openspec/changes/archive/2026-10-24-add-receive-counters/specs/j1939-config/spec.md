## MODIFIED Requirements

### Requirement: Received messages
Each `j1939.rx` entry SHALL have `pgn` (0..0x3FFFF) and `signals`, and MAY have `source` (0..253), or `source_name` with optional `source_name_mask`, `timeout_ms` (0 = no supervision, default), `status_location` and `counter_location` (an `%IW` word). A PDU1 PGN (PF < 240) SHALL have PS 0. Two entries with the same PGN SHALL differ in their source filter.

#### Scenario: Same PGN from two ECUs
- **WHEN** two `rx` entries have PGN 65280, one with `source` 0 and one with `source` 3
- **THEN** the file loads and each entry takes only its own source's messages

#### Scenario: Same PGN, no filter twice
- **WHEN** two `rx` entries have PGN 65280 and neither has a source filter
- **THEN** the file is rejected naming both paths

#### Scenario: Counter location not a word
- **WHEN** an `rx` entry has `"counter_location": "%IX202.0"`
- **THEN** the file is rejected naming the entry and that the counter needs an `%IW` input
