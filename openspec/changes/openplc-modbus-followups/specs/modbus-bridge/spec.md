## MODIFIED Requirements

### Requirement: Control block
With `control_location` (6 output bytes: counter word, command, network index, node, reserved), the bridge SHALL run a command once each time the counter changes, and SHALL echo the counter with a result in the status block (0 ok, 1 unknown command, 2 bad network, 3 bad node, 4 not a CANopen master network, 5 refused because the network is down or too many NMT commands wait, 6 not run because the bridge restarted). For a config with `bridge.openplc` (a PLC that rewrites its whole output image every poll), the first control block a client writes after the bridge starts SHALL be taken as the last one handled and SHALL NOT run; when its counter is not 0 the status block SHALL echo it with result 6. Commands:
- 1 run (end outputs off from idle)
- 2 idle (outputs off with the `on_client_loss` action)
- 3 NMT start, 4 NMT stop, 5 NMT pre-operational, 6 reset node, 7 reset communication, for the node on that CANopen master network (node 0 = all nodes)

#### Scenario: Stop one node
- **WHEN** a client writes command 4, network 0, node 7 and changes the counter from 41 to 42
- **THEN** NMT stop goes to node 7 once, and the status block shows counter 42 with result 0

#### Scenario: Other clients' first command runs
- **WHEN** a Modbus client of a config without `bridge.openplc` writes the control block for the first time, command 4 with counter 1
- **THEN** the command runs

#### Scenario: Counter unchanged
- **WHEN** the client rewrites the same control block every 10 ms
- **THEN** the command runs only once

#### Scenario: Bridge restart
- **WHEN** the bridge of an OpenPLC config restarts while the PLC keeps writing its last control block, command 3 with counter 42
- **THEN** no NMT start is sent, the status block shows counter 42 with result 6, and the client's next counter 43 runs its command

### Requirement: SDO bridge registers
With `sdo_bridge_location` (`request`: 14 output bytes, `response`: 14 input bytes), a client SHALL read or write one object of up to 4 bytes on a node of a CANopen master network. The request is counter, command (1 read, 2 write), network index, node, sub-index, index, length, reserved and value. The response is counter echo, status (0 idle, 1 busy, 2 done, 3 aborted), reserved, abort code and value. A request SHALL start when the counter changes, and SHALL go through the same queue and timeout as the SDO function blocks and the gateway's SDO bridge. A write SHALL need `sdo_bridge_write: true`; without it the request SHALL end aborted with abort code 0x08000020 and nothing is sent. For a config with `bridge.openplc`, the first SDO request a client writes after the bridge starts SHALL be taken as the last one handled and SHALL NOT be sent; when its counter is not 0 the response SHALL show it aborted with abort code 0x08000021. A bridged request SHALL be logged at debug level, and an abort or timeout at info level.

#### Scenario: Read the vendor ID
- **WHEN** a client writes command 1, network 0, node 5, index 0x1018, sub-index 1, length 4 and a new counter
- **THEN** the response shows that counter with status 1, then status 2 with node 5's vendor ID in the value

#### Scenario: No replayed write after a restart
- **WHEN** the bridge of an OpenPLC config restarts while the PLC's last request, an SDO write with counter 9, is still in its output image
- **THEN** nothing is sent to the node and the response shows counter 9 with status 3 and abort code 0x08000021

### Requirement: Nodes to pre-operational on client loss
`on_client_loss` SHALL also take `"preop"`: outputs stop as with `"stop"`, and NMT enter pre-operational SHALL be sent to each configured node of every CANopen master network (not node 0, so devices canworks does not manage are left alone). Leaving outputs off SHALL send NMT start to each of those nodes. The log lines SHALL name the client loss as the cause.

#### Scenario: Watchdog with preop
- **WHEN** `on_client_loss` is `"preop"` and the writer stops writing for `watchdog_ms`
- **THEN** RPDOs stop, the master sends NMT enter pre-operational to each configured node, the log says it was the client loss, and the next accepted write sends NMT start to each configured node
