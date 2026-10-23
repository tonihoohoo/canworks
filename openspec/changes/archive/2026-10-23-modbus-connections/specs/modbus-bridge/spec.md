## MODIFIED Requirements

### Requirement: Map hash
The bridge SHALL compute a 32-bit map hash of its config as `modbus-bridge-map` defines it, log it at start, and, in a config with `plc_link` true, serve it at input registers 0 (high word) and 1 (low word).

#### Scenario: Hash served
- **WHEN** a bridge config with `plc_link` true and map hash 0x1234ABCD runs and a client reads input registers 0 and 1
- **THEN** it reads 0x1234 and 0xABCD

### Requirement: PLC link on any bridge config
A bridge config SHALL accept `plc_link: true`, the only switch for the PLC link: holding registers 0-2 are the PLC link header (Requirement: PLC link header), input registers 0-1 the map hash and input byte 4 the status block, and a value located in those bytes SHALL be refused. Without `plc_link` a bridge config SHALL have no header and no hash in its image.

#### Scenario: CODESYS client with the header
- **WHEN** a config has `plc_link: true` and a client writes the header with running 1 and the matching hash, then the outputs
- **THEN** the outputs are applied, and a header with another hash leaves outputs off and logs the mismatch once

#### Scenario: Old config
- **WHEN** a bridge config without `plc_link` has a value at holding register 0
- **THEN** it is accepted and applied as a plain output register

### Requirement: Control block
With `control_location` (6 output bytes: counter word, command, network index, node, reserved), the bridge SHALL run a command once each time the counter changes, and SHALL echo the counter with a result in the status block (0 ok, 1 unknown command, 2 bad network, 3 bad node, 4 not a CANopen master network, 5 refused because the network is down or too many NMT commands wait, 6 not run because the bridge restarted). For a config with an OpenPLC connection (a PLC that rewrites its whole output image every poll), the first control block a client writes after the bridge starts SHALL be taken as the last one handled and SHALL NOT run; when its counter is not 0 the status block SHALL echo it with result 6. Commands:
- 1 run (end outputs off from idle)
- 2 idle (outputs off with the `on_client_loss` action)
- 3 NMT start, 4 NMT stop, 5 NMT pre-operational, 6 reset node, 7 reset communication, for the node on that CANopen master network (node 0 = all nodes)

#### Scenario: Stop one node
- **WHEN** a client writes command 4, network 0, node 7 and changes the counter from 41 to 42
- **THEN** NMT stop goes to node 7 once, and the status block shows counter 42 with result 0

#### Scenario: Other clients' first command runs
- **WHEN** a Modbus client of a config without `plc_link` writes the control block for the first time, command 4 with counter 1
- **THEN** the command runs

#### Scenario: Counter unchanged
- **WHEN** the client rewrites the same control block every 10 ms
- **THEN** the command runs only once

#### Scenario: Bridge restart
- **WHEN** the bridge of a config with `plc_link` restarts while the PLC keeps writing its last control block, command 3 with counter 42
- **THEN** no NMT start is sent, the status block shows counter 42 with result 6, and the client's next counter 43 runs its command

## ADDED Requirements

### Requirement: Connections ignored by the bridge
canworks-bridge SHALL accept `bridge.connections` as a list of objects and SHALL NOT read its entries, so a configurator-only field never stops a bridge. Anything else than a list SHALL be refused.

#### Scenario: Unknown kind
- **WHEN** a bridge config has `"connections": [{"kind": "future"}]`
- **THEN** the bridge starts and serves the registers as without it

### Requirement: Removed openplc field
canworks-bridge and the PC check SHALL refuse `bridge.openplc` with one message: the field was removed, OpenPLC is a connection on the Modbus bridge page, and the config must be opened in the configurator to add it.

#### Scenario: Old OpenPLC config
- **WHEN** `canworks-bridge --check-only` runs on a config with `"bridge": {"openplc": {}}`
- **THEN** it exits non-zero with that message, naming `bridge.openplc`

## REMOVED Requirements

### Requirement: OpenPLC section
**Reason**: OpenPLC is a connection (`modbus-connections`); the bridge needs only explicit settings and `plc_link`.
**Migration**: Adding an OpenPLC connection writes `plc_link`, `listen`, `writers`, `watchdog_ms` and `word_order`; the bridge refuses `openplc` (Requirement: Removed openplc field).
