## ADDED Requirements

### Requirement: Node-RED flow
The PC tools SHALL write a bridge config's register map as a Node-RED flow (JSON importable by Node-RED with the `node-red-contrib-modbus` palette) on one tab, containing: a Modbus TCP client node for the bridge; one input register read node per suggested read channel at the poll period; a link out "canworks in" emitting one message per changed value with `msg.topic` the row's name (the entry's `name` when it has one, else the map's generated name such as `dio.0x6000:1`) and `msg.payload` the decoded value (type, word order, sign, REAL, bit and scale/offset applied), every value once after start; a link in "canworks out" that sets the named output value and writes the changed write channels, after the output image has been read back from the bridge once; and a keepalive that rewrites the outputs at most every third of `watchdog_ms` when the watchdog is on. When the config locates the bridge's status block, control block, live list or SDO blocks, the flow SHALL also show the status as node status, emit the live list as per-node signals, and offer "canworks nmt", "canworks sdo" and "canworks sdo result" links using the bridge's counter handshake. Node ids SHALL be stable for the same config path and names, so a re-import replaces the tab's nodes.

#### Scenario: Named value both ways
- **WHEN** the flow of the example bridge config is imported and the simulated node's input `dio.0x6401:1` changes
- **THEN** "canworks in" emits a message with topic `dio.0x6401:1` and the new value, and a message `{topic: "dio.0x6411:1", payload: 5}` to "canworks out" makes holding register 1 hold 5

#### Scenario: Restart keeps outputs
- **WHEN** outputs hold non-zero values and Node-RED restarts
- **THEN** the first write after the restart carries the values read back from the bridge, not zeros

#### Scenario: Watchdog
- **WHEN** the bridge has `watchdog_ms` 1000 and the flow runs with no messages to "canworks out"
- **THEN** outputs stay on, and they go off by the watchdog within `watchdog_ms` after Node-RED stops
