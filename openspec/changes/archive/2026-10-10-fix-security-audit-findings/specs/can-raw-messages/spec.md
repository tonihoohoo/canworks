## ADDED Requirements

### Requirement: Raw message locations inside the I/O image
Every location of a `raw.rx` or `raw.tx` entry (status, counter, identifier, DLC, data, trigger, enable and signal locations) SHALL lie inside the runtime's I/O image, checked as CANopen and J1939 locations are. A location outside it SHALL make the config refused at load with a message naming the entry and the location, and the configurator's check SHALL refuse it too. The plugin SHALL never read or write a location outside the image.

#### Scenario: Location past the image
- **WHEN** the image has 1024 entries and a `raw.tx` signal has `iec_location` `%QW5000`
- **THEN** the config is refused naming the entry and `%QW5000`, and the runtime does not start the networks

### Requirement: Failed sends stay pending
An on-change or trigger send of a `raw.tx` entry that the interface refuses (for example a full transmit queue or an interface that is down) SHALL NOT count as sent: the entry SHALL stay pending and be sent with its current values on a later 1 ms tick, still subject to `min_gap_ms`. Failed periodic sends SHALL NOT be sent in a burst afterwards.

#### Scenario: Queue full on a change
- **WHEN** the program changes signal `Red` while the interface's transmit queue is full, and the queue drains 20 ms later
- **THEN** the frame with the new value goes out once the queue has room, without another change by the program
