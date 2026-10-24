## ADDED Requirements

### Requirement: Receive counter of an input PDO
A PDO the node sends (`tx_pdos` entry) MAY give `counter_location`, an `%IW` input word. The bridge SHALL increment it, wrapping from 65535 to 0, for every frame of that PDO that updates the PDO's inputs, and SHALL write it to the image together with or after the inputs of that frame, by the next scan, so a counter that moved never comes with older values. While the program holds the network stopped (inputs keep their values) frames SHALL NOT be counted. A PDO shorter than its mapping SHALL NOT be counted. The counter SHALL start at 0 when the bridge starts and SHALL NOT be reset by a timeout, a node loss, a CANopen session restart or the PLC link stopping. It SHALL work alike on a SocketCAN interface and on the simulated bus. `counter_location` on an `rx_pdos` entry SHALL be refused naming the field, and a counter location that another binding uses SHALL be refused naming both uses.

#### Scenario: Frames merged into one poll
- **WHEN** node 5's TPDO 1 has `"counter_location": "%IW40"` and the node sends it every 10 ms while a Modbus client polls every 50 ms
- **THEN** the input register for `%IW40` grows by about 5 between polls, while the PDO's value registers show only the last frame

#### Scenario: Short PDO not counted
- **WHEN** node 5 sends TPDO 1 with 2 data bytes and the mapping needs 4
- **THEN** `%IW40` does not change and the short PDO is logged as before

#### Scenario: Wrap
- **WHEN** `%IW40` reads 65535 and one more TPDO 1 arrives
- **THEN** `%IW40` reads 0

#### Scenario: Counter on an RPDO
- **WHEN** an `rx_pdos` entry has `counter_location`
- **THEN** the configuration is rejected naming the field and that it is only for `tx_pdos`

#### Scenario: Without a counter
- **WHEN** no PDO has `counter_location`
- **THEN** the image, the Modbus map and the variable list are the same as before
