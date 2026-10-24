## ADDED Requirements

### Requirement: Receive counter
An `rx` entry with `counter_location` SHALL increment it, wrapping from 65535 to 0, for every message the entry takes (after its source filter), and SHALL write it to the image together with that message's signal values. A message sent with the transport protocol SHALL count once, when it is complete. The counter SHALL start at 0 when the bridge starts and SHALL NOT be reset by a receive timeout, an address claim or the bus going down.

#### Scenario: Messages within one poll
- **WHEN** PGN 65280 from source 0 has `"counter_location": "%IW212"`, arrives every 10 ms and a Modbus client polls every 100 ms
- **THEN** the input register for `%IW212` grows by about 10 between polls

#### Scenario: Other source not counted
- **WHEN** the entry has `source` 0 and source 3 sends PGN 65280
- **THEN** `%IW212` does not change

#### Scenario: Multi-packet message
- **WHEN** a 20-byte message for the entry arrives over the transport protocol in 3 packets
- **THEN** `%IW212` grows by one, once the message is complete
