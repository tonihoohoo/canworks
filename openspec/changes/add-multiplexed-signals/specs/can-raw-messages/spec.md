## MODIFIED Requirements

### Requirement: Received raw messages
Each `raw.rx` entry SHALL have `id` (0..0x7FF, or 0..0x1FFFFFFF with `extended: true`) and MAY have `name`, `mask` (default all ones), `rtr`, `dlc` (0..8), `timeout_ms` (0 = none, default), `status_location` (bit), `counter_location` (word), `id_location` (double word), `dlc_location` (byte), `data_location` (long word, the 8 data bytes with byte 0 lowest) and `signals`. A frame SHALL match when its format and remote flag equal the entry's and `(frame id AND mask) = (id AND mask)`; every matching entry SHALL receive it. On a match the plugin SHALL update the entry's locations no later than the next PLC scan, increment the counter (wrapping at 65535) and set the status bit TRUE. A frame with fewer data bytes than the entry's `dlc`, or than the signals active in that frame need (`can-multiplexed-signals`), SHALL NOT update any location and SHALL be counted as short. With `timeout_ms`, the status bit SHALL go FALSE when no matching frame arrived for that long; values SHALL hold their last state.

#### Scenario: Signal into the PLC
- **WHEN** entry `Joystick` (id 0x123) has signal `X` at start bit 0, length 12, signed, little-endian, at `%IW304`, and the frame `0x123 FF 0F 00 00 00 00 00 00` arrives
- **THEN** within one scan `%IW304` is -1 and the entry's counter has grown by one

#### Scenario: Range of identifiers
- **WHEN** an entry has id 0x600, mask 0x7F0 and `id_location` `%ID308`, and frames 0x603 then 0x60A arrive
- **THEN** the entry takes both, the counter grows by two, and `%ID308` ends at 0x60A

#### Scenario: Timeout
- **WHEN** an entry has `timeout_ms` 300 and its sender stops
- **THEN** about 300 ms after the last frame the status bit goes FALSE and the signal locations keep their last values

#### Scenario: Short frame
- **WHEN** an entry's signals need 4 bytes and a matching frame with DLC 2 arrives
- **THEN** no location changes and the diagnostics status counts one short frame

#### Scenario: Short page only
- **WHEN** page 1 of an entry needs 2 bytes, page 2 needs 6, and a frame of page 1 with DLC 2 arrives
- **THEN** page 1's signals are written and no short frame is counted

### Requirement: Raw signals
A raw signal SHALL have `start_bit` (0..63), `length` (1..64) and `iec_location`, and MAY have `name`, `byte_order` (`little`, default, or `big` as DBC numbers Motorola bits), `signed`, `scale`, `offset`, `unit`, `minimum`, `maximum`, `multiplexer`, `mux` and, on received messages, `valid_location` (`can-multiplexed-signals`). A switch of a send entry with `pages` `all` or `rotate` SHALL have no `iec_location`. The value SHALL be packed and unpacked as a raw integer, the same way J1939 signals are, and SHALL go to a location of the matching size (`%IX`/`%QX` for length 1, byte, word, double word or long word for up to 8, 16, 32 and 64 bits). `scale`, `offset`, `unit`, `minimum` and `maximum` SHALL be used by tools only. A signal reaching past the frame's `dlc` SHALL be rejected.

#### Scenario: Big-endian signal
- **WHEN** a signal has `byte_order` `big`, start bit 7 and length 16, and the frame's first two bytes are `12 34`
- **THEN** its location holds 0x1234

#### Scenario: Location too small
- **WHEN** a signal of length 12 has `iec_location` `%IB10`
- **THEN** the file is rejected naming the signal and saying it needs a word

#### Scenario: Valid bit on a send message
- **WHEN** a `raw.tx` signal has a `valid_location`
- **THEN** the file is rejected saying valid bits belong to received signals
