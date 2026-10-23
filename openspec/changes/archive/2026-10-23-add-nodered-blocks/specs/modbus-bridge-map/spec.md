## MODIFIED Requirements

### Requirement: Node-RED flow
The PC tools SHALL write a bridge config's Node-RED flow (JSON importable by Node-RED with the `node-red-canworks` package of the same tools version, nodered-blocks) on one tab, containing: one **canworks bridge** config node with the bridge's host, port and poll period and the layout (register map rows with name, byte, type, bit, scale, offset and unit; status, control, live list, SDO and mailbox blocks; networks with name and kind; `watchdog_ms`; word order; map hash); one **canworks in** and one **canworks out** node using it; and a comment naming the package and the docs. Row names SHALL be the entry's `name` when it has one, else the map's generated name such as `dio.0x6000:1`. The flow SHALL NOT use `node-red-contrib-modbus` or generated function-node code. For a read-only flow (nodered-blocks "Read-only flows") the config node SHALL be marked read-only and the tab SHALL have no **canworks out**. Node ids SHALL be stable for the same config path and names, so a re-import replaces the tab's nodes.

#### Scenario: Named value both ways
- **WHEN** the flow of the example bridge config is imported with the package installed and the simulated node's input `dio.0x6401:1` changes
- **THEN** **canworks in** emits a message with topic `dio.0x6401:1` and the new value, and a message `{topic: "dio.0x6411:1", payload: 5}` to **canworks out** makes holding register 1 hold 5

#### Scenario: Re-import
- **WHEN** the user imports a newer export of the same config
- **THEN** Node-RED offers to replace the tab's nodes instead of adding a second tab

#### Scenario: No third-party palette
- **WHEN** the flow of any shipped example bridge config is written
- **THEN** it contains no node of a type outside `node-red-canworks` and Node-RED's core (`tab`, `comment`)

#### Scenario: Restart keeps outputs
- **WHEN** outputs hold non-zero values and Node-RED restarts
- **THEN** the first write after the restart carries the values read back from the bridge, not zeros

#### Scenario: Watchdog
- **WHEN** the bridge has `watchdog_ms` 1000 and the flow runs with no messages to **canworks out**
- **THEN** outputs stay on, and they go off by the watchdog within `watchdog_ms` after Node-RED stops
