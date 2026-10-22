## ADDED Requirements

### Requirement: OpenPLC section
A bridge config MAY have an `openplc` object inside `bridge` with `poll_ms` (5-1000, default 10), `remote_device` (a file name, default `canworks`) and `iec_base` (an `%IW`/`%QW` index). With it the bridge SHALL listen on `127.0.0.1:1502` and let only `127.0.0.1` write unless `listen` and `writers` are set, SHALL default `watchdog_ms` to 5 × `poll_ms` (at least 50), SHALL refuse `word_order` `"high_first"`, and SHALL refuse a config whose `status_location` is not input byte 4 or that places any other location in input bytes 0-11 or output bytes 0-5.

#### Scenario: Defaults
- **WHEN** a bridge config has `"openplc": {}` and no `listen`, `writers` or `watchdog_ms`
- **THEN** the bridge listens on 127.0.0.1 port 1502, accepts writes only from 127.0.0.1, and its watchdog is 50 ms

#### Scenario: Location in the header
- **WHEN** an `openplc` bridge config maps an RPDO entry at `%QW2`
- **THEN** the config is refused, naming the entry and saying output bytes 0-5 hold the PLC link header

### Requirement: Map hash
The bridge SHALL compute a 32-bit map hash of its config as `modbus-bridge-map` defines it, log it at start, and, in an `openplc` config, serve it at input registers 0 (high word) and 1 (low word).

#### Scenario: Hash served
- **WHEN** an `openplc` bridge config with map hash 0x1234ABCD runs and a client reads input registers 0 and 1
- **THEN** it reads 0x1234 and 0xABCD

### Requirement: PLC link header
In an `openplc` config, holding registers 0-2 SHALL be the PLC link header (running, map hash high word, map hash low word) and not part of the output image. A write covering register 0 SHALL set the link state: ok when running is 1 and the hash equals the bridge's, stopped when running is 0, mismatch otherwise. Stopped SHALL set status byte 0 to 5. Writes to other output registers SHALL be answered normally and applied only while the state is ok. Entering stopped SHALL enter outputs off at once with the `on_client_loss` action, using the output values from before that write. Entering mismatch SHALL enter outputs off, set status byte 0 to 4, and log once naming both hashes. A write with state ok SHALL end outputs off as an accepted write does. Until the first header write the state SHALL be stopped.

#### Scenario: PLC stops
- **WHEN** outputs run with `on_client_loss: "hold"`, then the runtime's stop round writes the header with running 0 followed by all-zero output registers
- **THEN** the outputs keep being sent with the values from before the stop round, and the zeros are not applied

#### Scenario: Program built for another map
- **WHEN** the program writes the header with running 1 and hash 0x11111111 while the bridge's hash is 0x22222222
- **THEN** output writes change nothing, status byte 0 reads 4, and the log names both hashes once

#### Scenario: PLC starts again
- **WHEN** after a stop the header is written with running 1 and the matching hash, followed by the outputs
- **THEN** outputs off ends and the new values are sent

### Requirement: Nodes to pre-operational on client loss
`on_client_loss` SHALL also take `"preop"`: outputs stop as with `"stop"`, and NMT enter pre-operational SHALL be sent to all nodes of every CANopen master network. Leaving outputs off SHALL send NMT start to all nodes of those networks.

#### Scenario: Watchdog with preop
- **WHEN** `on_client_loss` is `"preop"` and the writer stops writing for `watchdog_ms`
- **THEN** RPDOs stop, the master sends NMT enter pre-operational with node 0, and the next accepted write sends NMT start with node 0
