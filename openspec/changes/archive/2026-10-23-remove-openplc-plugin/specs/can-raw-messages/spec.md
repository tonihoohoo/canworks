## MODIFIED Requirements

### Requirement: Raw messages on every network
Every version 2 network, whatever its `protocol`, MAY have a `raw` object with `rx` and `tx` lists of messages and an optional `dbc` file name. `dbc` SHALL name a file relative to the config (the configurator keeps it in the config folder); the bridge SHALL NOT read it. The raw messages SHALL run next to the network's protocol on the same interface without changing what the protocol sends or receives. Raw messages SHALL be available in every build of the bridge, whichever protocols it was built with.

#### Scenario: Display next to CANopen nodes
- **WHEN** a CANopen network on `can0` with nodes 2 and 5 also has a raw `tx` message 0x510 every 100 ms
- **THEN** both nodes boot and exchange PDOs as before, and 0x510 appears on the bus every 100 ms with the values of its `%Q` locations

#### Scenario: Raw messages in a J1939-only build
- **WHEN** the bridge is built without CANopen and loads a network with protocol `none` and raw messages
- **THEN** the network runs and its raw messages work

#### Scenario: DBC file missing on the PLC
- **WHEN** a network's `raw.dbc` names a file that is not next to the config on the PLC
- **THEN** the bridge starts the network and its raw messages as usual

### Requirement: Plain CAN networks
A version 2 network MAY have `"protocol": "none"`. Such a network SHALL have an `adapter` and MAY have `raw`; it SHALL NOT have `role`, `master`, `nodes`, `slave` or `j1939`, and each misplaced key SHALL be rejected naming the protocol it belongs to. A plain CAN network SHALL have bus monitoring, trace, bit rate detection, `send_frame` and diagnostics status like any network, and SHALL send nothing except its raw messages, program frames and frames sent through the diagnostics channel.

#### Scenario: Plain network
- **WHEN** a config has one network with protocol `none` on `can1` at 250 kbit/s with two `rx` and one `tx` message
- **THEN** the bridge logs one line naming the interface, the bit rate and the numbers of received and sent messages, and puts no CANopen or J1939 frame on `can1`

#### Scenario: Nodes on a plain network
- **WHEN** a network with protocol `none` has a `nodes` list
- **THEN** the file is rejected with an error saying nodes belong to a CANopen network

### Requirement: Received raw messages
Each `raw.rx` entry SHALL have `id` (0..0x7FF, or 0..0x1FFFFFFF with `extended: true`) and MAY have `name`, `mask` (default all ones), `rtr`, `dlc` (0..8), `timeout_ms` (0 = none, default), `status_location` (bit), `counter_location` (word), `id_location` (double word), `dlc_location` (byte), `data_location` (long word, the 8 data bytes with byte 0 lowest) and `signals`. A frame SHALL match when its format and remote flag equal the entry's and `(frame id AND mask) = (id AND mask)`; every matching entry SHALL receive it. On a match the bridge SHALL update the entry's locations no later than the next PLC scan, increment the counter (wrapping at 65535) and set the status bit TRUE. A frame with fewer data bytes than the entry's `dlc`, or than the signals active in that frame need (`can-multiplexed-signals`), SHALL NOT update any location and SHALL be counted as short. With `timeout_ms`, the status bit SHALL go FALSE when no matching frame arrived for that long; values SHALL hold their last state.

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

### Requirement: Sent raw messages
Each `raw.tx` entry SHALL have `id` (with `extended` as for `rx`) and MAY have `name`, `rtr`, `dlc` (0..8, default the smallest that holds every signal, at least 1 for a data frame), `fill` (byte, default 0), `period_ms` (1..60000), `on_change`, `min_gap_ms` (0..60000, default 0), `trigger_location` (bit), `enable_location` (bit), `data_location` (long word) and `signals`. An entry SHALL have at least one of `period_ms`, `on_change` and `trigger_location`. The bridge SHALL send the frame every `period_ms`, when any of its output locations changed (not sooner than `min_gap_ms` after the previous send), and on each rising edge of the trigger bit. While the enable bit is FALSE, periodic and on-change sends SHALL stop; a trigger edge SHALL still send. Sending SHALL start when the PLC runs and stop when it stops. `data_location` gives the whole frame; signals are written over it; bits neither covers SHALL come from `fill`. Identifiers SHALL be unique among a network's `tx` entries.

#### Scenario: Periodic and on change
- **WHEN** entry `Lamps` has `period_ms` 100, `on_change` and `min_gap_ms` 10, and the program changes signal `Red` at a time 40 ms after the last periodic send
- **THEN** the frame goes out at once with the new value, and the next periodic frame follows 100 ms after that

#### Scenario: Trigger only
- **WHEN** entry `Wake` is a remote frame with only a `trigger_location`, and the program sets that bit TRUE for three scans
- **THEN** exactly one remote frame is sent

#### Scenario: PLC stopped
- **WHEN** the PLC is stopped
- **THEN** no raw `tx` message is sent until it runs again

### Requirement: Listen-only networks
`adapter.listen_only: true` SHALL be accepted only on a network with protocol `none` and no `tx` entries. The bridge SHALL put the controller into listen-only mode (silent mode on slcan) before the network starts and SHALL refuse every send on the network: program blocks with error 9, `send_frame` and replay with "network is listen-only". Where the mode cannot be set (vcan, a simulated bus, `configure_link: false`), the bridge SHALL log that the adapter still acknowledges frames and SHALL keep refusing sends.

#### Scenario: Watching a machine bus
- **WHEN** a plain network with `listen_only` on an slcan adapter receives frames from a running machine
- **THEN** the raw `rx` locations update and the adapter sends no frame and no acknowledgement

#### Scenario: Listen-only with a send entry
- **WHEN** a listen-only network has a `tx` entry
- **THEN** the file is rejected saying a listen-only network cannot send

### Requirement: Locations of raw messages in the clash check
Every location in `raw` SHALL take part in the check for locations used twice, across all networks and the other bridge configs, like PDO locations.

#### Scenario: Same location twice
- **WHEN** a raw signal and a CANopen PDO entry both use `%IW304`
- **THEN** the file is rejected naming both paths

### Requirement: Raw message locations inside the I/O image
Every location of a `raw.rx` or `raw.tx` entry (status, counter, identifier, DLC, data, trigger, enable and signal locations) SHALL lie inside the runtime's I/O image, checked as CANopen and J1939 locations are. A location outside it SHALL make the config refused at load with a message naming the entry and the location, and the configurator's check SHALL refuse it too. The bridge SHALL never read or write a location outside the image.

#### Scenario: Location past the image
- **WHEN** the image has 1024 entries and a `raw.tx` signal has `iec_location` `%QW5000`
- **THEN** the config is refused naming the entry and `%QW5000`, and the runtime does not start the networks
