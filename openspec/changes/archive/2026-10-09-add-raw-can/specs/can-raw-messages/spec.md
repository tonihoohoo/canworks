## ADDED Requirements

### Requirement: Raw messages on every network
Every version 2 network, whatever its `protocol`, MAY have a `raw` object with `rx` and `tx` lists of messages and an optional `dbc` file name. The raw messages SHALL run next to the network's protocol on the same interface without changing what the protocol sends or receives. Raw messages SHALL be available in every build of the plugin, whichever protocols it was built with.

#### Scenario: Display next to CANopen nodes
- **WHEN** a CANopen network on `can0` with nodes 2 and 5 also has a raw `tx` message 0x510 every 100 ms
- **THEN** both nodes boot and exchange PDOs as before, and 0x510 appears on the bus every 100 ms with the values of its `%Q` locations

#### Scenario: Raw messages in a J1939-only build
- **WHEN** the plugin is built without CANopen and loads a network with protocol `none` and raw messages
- **THEN** the network runs and its raw messages work

### Requirement: Plain CAN networks
A version 2 network MAY have `"protocol": "none"`. Such a network SHALL have an `adapter` and MAY have `raw`; it SHALL NOT have `role`, `master`, `nodes`, `slave` or `j1939`, and each misplaced key SHALL be rejected naming the protocol it belongs to. A plain CAN network SHALL have bus monitoring, trace, bit rate detection, `send_frame` and diagnostics status like any network, and SHALL send nothing except its raw messages, program frames and frames sent through the diagnostics channel.

#### Scenario: Plain network
- **WHEN** a config has one network with protocol `none` on `can1` at 250 kbit/s with two `rx` and one `tx` message
- **THEN** the plugin logs one line naming the interface, the bit rate and the numbers of received and sent messages, and puts no CANopen or J1939 frame on `can1`

#### Scenario: Nodes on a plain network
- **WHEN** a network with protocol `none` has a `nodes` list
- **THEN** the file is rejected with an error saying nodes belong to a CANopen network

### Requirement: Received raw messages
Each `raw.rx` entry SHALL have `id` (0..0x7FF, or 0..0x1FFFFFFF with `extended: true`) and MAY have `name`, `mask` (default all ones), `rtr`, `dlc` (0..8), `timeout_ms` (0 = none, default), `status_location` (bit), `counter_location` (word), `id_location` (double word), `dlc_location` (byte), `data_location` (long word, the 8 data bytes with byte 0 lowest) and `signals`. A frame SHALL match when its format and remote flag equal the entry's and `(frame id AND mask) = (id AND mask)`; every matching entry SHALL receive it. On a match the plugin SHALL update the entry's locations no later than the next PLC scan, increment the counter (wrapping at 65535) and set the status bit TRUE. A frame with fewer data bytes than the entry's `dlc`, or than its signals need, SHALL NOT update any location and SHALL be counted as short. With `timeout_ms`, the status bit SHALL go FALSE when no matching frame arrived for that long; values SHALL hold their last state.

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

### Requirement: Sent raw messages
Each `raw.tx` entry SHALL have `id` (with `extended` as for `rx`) and MAY have `name`, `rtr`, `dlc` (0..8, default the smallest that holds every signal, at least 1 for a data frame), `fill` (byte, default 0), `period_ms` (1..60000), `on_change`, `min_gap_ms` (0..60000, default 0), `trigger_location` (bit), `enable_location` (bit), `data_location` (long word) and `signals`. An entry SHALL have at least one of `period_ms`, `on_change` and `trigger_location`. The plugin SHALL send the frame every `period_ms`, when any of its output locations changed (not sooner than `min_gap_ms` after the previous send), and on each rising edge of the trigger bit. While the enable bit is FALSE, periodic and on-change sends SHALL stop; a trigger edge SHALL still send. Sending SHALL start when the PLC runs and stop when it stops. `data_location` gives the whole frame; signals are written over it; bits neither covers SHALL come from `fill`. Identifiers SHALL be unique among a network's `tx` entries.

#### Scenario: Periodic and on change
- **WHEN** entry `Lamps` has `period_ms` 100, `on_change` and `min_gap_ms` 10, and the program changes signal `Red` at a time 40 ms after the last periodic send
- **THEN** the frame goes out at once with the new value, and the next periodic frame follows 100 ms after that

#### Scenario: Trigger only
- **WHEN** entry `Wake` is a remote frame with only a `trigger_location`, and the program sets that bit TRUE for three scans
- **THEN** exactly one remote frame is sent

#### Scenario: PLC stopped
- **WHEN** the PLC is stopped
- **THEN** no raw `tx` message is sent until it runs again

### Requirement: Raw signals
A raw signal SHALL have `start_bit` (0..63), `length` (1..64) and `iec_location`, and MAY have `name`, `byte_order` (`little`, default, or `big` as DBC numbers Motorola bits), `signed`, `scale`, `offset`, `unit`, `minimum` and `maximum`. The value SHALL be packed and unpacked as a raw integer, the same way J1939 signals are, and SHALL go to a location of the matching size (`%IX`/`%QX` for length 1, byte, word, double word or long word for up to 8, 16, 32 and 64 bits). `scale`, `offset`, `unit`, `minimum` and `maximum` SHALL be used by tools only. A signal reaching past the frame's `dlc` SHALL be rejected.

#### Scenario: Big-endian signal
- **WHEN** a signal has `byte_order` `big`, start bit 7 and length 16, and the frame's first two bytes are `12 34`
- **THEN** its location holds 0x1234

#### Scenario: Location too small
- **WHEN** a signal of length 12 has `iec_location` `%IB10`
- **THEN** the file is rejected naming the signal and saying it needs a word

### Requirement: Identifiers the protocol uses
A `tx` entry whose identifier the network's protocol uses SHALL be rejected unless it has `override_protocol: true`; the error SHALL name what the identifier is used for. On a CANopen network these are the identifiers the `send_frame` guard lists. On a J1939 network they are extended identifiers whose source address byte is the ECU's address or in its address range. A network with protocol `none` has none. A forced entry SHALL be logged at start.

#### Scenario: COB-ID of a PDO
- **WHEN** node 5 has RPDO1 on 0x205 and a raw `tx` entry uses 0x205
- **THEN** the file is rejected with "0x205 is RPDO1 of node 5; set override_protocol to send it as a raw message"

#### Scenario: Override
- **WHEN** the same entry has `override_protocol: true`
- **THEN** the config loads and the start log says raw message 0x205 overrides RPDO1 of node 5

### Requirement: Listen-only networks
`adapter.listen_only: true` SHALL be accepted only on a network with protocol `none` and no `tx` entries. The plugin SHALL put the controller into listen-only mode (silent mode on slcan) before the network starts and SHALL refuse every send on the network: program blocks with error 9, `send_frame` and replay with "network is listen-only". Where the mode cannot be set (vcan, a simulated bus, `configure_link: false`), the plugin SHALL log that the adapter still acknowledges frames and SHALL keep refusing sends.

#### Scenario: Watching a machine bus
- **WHEN** a plain network with `listen_only` on an slcan adapter receives frames from a running machine
- **THEN** the raw `rx` locations update and the adapter sends no frame and no acknowledgement

#### Scenario: Listen-only with a send entry
- **WHEN** a listen-only network has a `tx` entry
- **THEN** the file is rejected saying a listen-only network cannot send

### Requirement: Raw messages on simulated and lost buses
Raw messages SHALL work on a network with `adapter.simulate`, including a plain network, on the simulated bus it shares with other simulated networks of the same interface. When the interface is missing, down or bus-off, the raw path SHALL keep retrying like the network does, received entries SHALL time out, and sends SHALL resume when the bus is back.

#### Scenario: Simulated plain network
- **WHEN** a simulated plain network has an `rx` entry and the simulation file has a plain CAN device sending that identifier
- **THEN** the entry's locations update as on a real bus

#### Scenario: Unplugged adapter
- **WHEN** the adapter of a plain network is unplugged and plugged back in
- **THEN** entries with timeouts report the timeout while it is out, and frames flow again after it is back without a PLC restart

### Requirement: Locations of raw messages in the clash check
Every location in `raw` SHALL take part in the check for locations used twice, across all networks and the other plugin configs, like PDO locations.

#### Scenario: Same location twice
- **WHEN** a raw signal and a CANopen PDO entry both use `%IW304`
- **THEN** the file is rejected naming both paths
