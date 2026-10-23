## ADDED Requirements

### Requirement: Node-RED package
The PC tools SHALL contain a Node-RED node package `node-red-canworks` whose version equals the deploy package version and which has no runtime dependencies (its own Modbus TCP client with functions 3, 4 and 16). `canworks-deploy --export-nodered-package OUT` SHALL write it as a `.tgz` that Node-RED's palette upload and `npm install <file>` accept, without network access; the same bytes for the same tools version. Each `deploy-v` release SHALL attach it as `node-red-canworks-<version>.tgz`. The package SHALL run on Node-RED 3 and 4 with Node.js 18 or newer.

#### Scenario: Offline install
- **WHEN** a user writes the package with `--export-nodered-package` on a PC without internet and installs it in Node-RED with `npm install` from that file
- **THEN** the install fetches nothing and the palette shows the canworks nodes

### Requirement: Bridge config node
The package SHALL have a config node **canworks bridge** holding the bridge's host, port, poll period (default 10 ms, kept between 10 ms and a third of `watchdog_ms`) and the layout the flow export writes (register map rows, bridge blocks, mailboxes, networks, `watchdog_ms`, word order, map hash). It SHALL open exactly one Modbus TCP connection to the bridge for all nodes that use it, poll the input channels and write the changed output and request channels once per poll period, reconnect with a growing delay (0.5 s to 5 s) after a loss, and SHALL show its state (connected, polling, reconnecting, refused writes) as the status of the nodes that use it. A config node without a layout SHALL refuse to start and say "export the flow from canworks".

#### Scenario: One connection
- **WHEN** a flow uses one **canworks bridge** with a **canworks in**, a **canworks out**, two **canworks sdo** and a **canworks can receive** node
- **THEN** the bridge reports one connected client

#### Scenario: Bridge goes away
- **WHEN** the bridge stops for 10 s and starts again
- **THEN** the nodes show "reconnecting", running jobs end with ERROR_ID 20, and after the bridge is back values flow again without a redeploy

### Requirement: Values in and out
**canworks in** SHALL emit one message per changed value, `msg.topic` the register map row's name and `msg.payload` the decoded value (type, word order, sign, REAL, bit, scale and offset applied, `msg.unit` when set, 64-bit integers beyond 2^53 as decimal strings), every value once after the first read, plus `bridge.state`, `bridge.clients`, `bridge.command`, `<network>.node<N>.operational` from the live lists and, with network info, `<network>.bus_state`, `<network>.bus_load`, `<network>.rx_errors`, `<network>.tx_errors`, `<network>.bus_offs` and for J1939 networks `<network>.address`, `<network>.claim`, `<network>.name` and `<network>.ecus`, each unless a register map row has that name (the row wins). An optional topic filter (exact names or a prefix ending in `*`) SHALL limit what one node emits. **canworks out** SHALL set the named output from `{topic, payload}`, refuse values outside the type's range with a warning and no write, and send the change with the next poll. Before its first write after a connect the config node SHALL read the outputs back from the bridge; values set before that SHALL be held (last value per name wins). While the bridge's watchdog is on, the outputs SHALL be rewritten at least every third of `watchdog_ms`.

#### Scenario: Named value both ways
- **WHEN** the flow of the example bridge config runs and the simulated node's input `dio.0x6401:1` changes
- **THEN** **canworks in** emits topic `dio.0x6401:1` with the new value within two poll periods plus one SYNC period, and `{topic: "dio.0x6411:1", payload: 5}` to **canworks out** makes holding register 1 hold 5

#### Scenario: Restart keeps outputs
- **WHEN** outputs hold non-zero values and Node-RED restarts
- **THEN** the first write after the restart carries the values read back from the bridge, not zeros

#### Scenario: Watchdog
- **WHEN** the bridge has `watchdog_ms` 1000 and the flow runs with no messages to **canworks out**
- **THEN** outputs stay on, and they go off by the watchdog within `watchdog_ms` after Node-RED stops

### Requirement: Block nodes
The package SHALL have these nodes, each with the inputs of its ST block(s) as form fields that `msg.payload` fields of the same name override, and the ST family's ERROR_IDs:

| Node | ST blocks | Bridge part |
|---|---|---|
| **canworks nmt** (`start`, `stop`, `preop`, `reset`, `reset_comm`, `run`, `idle`) | `CO_NMT` | control block |
| **canworks sdo** (read, write; `datatype` unsigned, signed, real, bytes, string; up to 1024 bytes) | `CO_SDO_READ`, `CO_SDO_WRITE`, their `_BYTES`, `_STRING`, `_REAL` forms | SDO registers for numbers up to 4 bytes, a request mailbox otherwise |
| **canworks emcy** | `CO_RECV_EMCY` | receive mailbox |
| **canworks can send** | `CAN_SEND` | request mailbox |
| **canworks can cyclic** (start or change, stop) | `CAN_SEND_CYCLIC` | request mailbox, cyclic job |
| **canworks can receive** (`can_id`, mask, extended, `all_ids`) | `CAN_RECEIVE` | receive mailbox |
| **canworks j1939 send**, **j1939 request**, **j1939 receive** (`pgn`, source filter, `all_pgns`) | `J1939_SEND`, `J1939_REQUEST`, `J1939_RECEIVE` | request mailbox, receive mailbox |
| **canworks j1939 dm** (read DM1 or DM2, clear DM3 or DM11) | `J1939_DM_READ`, `J1939_DM_CLEAR` | request mailbox |
| **canworks find ecu** | `J1939_FIND_ECU` | request mailbox |

Form fields that Node-RED keeps for itself (a node's `id`, `type` and `name`) SHALL be named `can_id`, `datatype` and `ecu_name`, and `msg.payload` SHALL accept either name. `network` SHALL be the network's name or index, or left out when the config has one network of the kind the node needs; a network of the wrong kind SHALL end the job with the family's ERROR_ID for it (10 for J1939, 4 for CANopen). A job SHALL end with exactly one message: `msg.topic` kept, `msg.payload` the result (`null` on error) and `msg.canworks` `{status: "done" | "error", errorId, abortCode, abortText, request}`; data SHALL be a `Buffer` (arrays of numbers and hex strings accepted), DTCs `{spn, fmi, oc, cm}`. A node whose bridge part is not in the layout SHALL end each job with ERROR_ID 22 and show why in its status. The node's status SHALL show busy, done or the ERROR_ID.

#### Scenario: Long SDO read
- **WHEN** a **canworks sdo** node reads 0x1008:0 of node 5 as `string` and the device name is 40 bytes long
- **THEN** one message arrives with `msg.payload` the 40-character name and `msg.canworks.status` `done`

#### Scenario: Missing mailbox
- **WHEN** a **canworks can send** node runs on a config without request mailboxes
- **THEN** it ends with ERROR_ID 22 and its status says the config has no request mailbox

### Requirement: Sharing the mailboxes
The config node SHALL queue jobs in the order they arrive, give the oldest waiting job the first free request mailbox, and keep that mailbox for the job's whole transfer (staging, the operation and fetching). Short SDO jobs SHALL share the SDO registers and NMT jobs the control block in the same way. Waiting SHALL NOT count against a job's timeout (default 5 s). At most 64 jobs SHALL wait per bridge; a job beyond that SHALL end with the family's "no free slot" ERROR_ID (5, or 9 for J1939). A new request SHALL use a counter the bridge has not seen (not the last one and not the response's echo).

#### Scenario: Three reads, one mailbox
- **WHEN** three long SDO reads start in the same millisecond on a config with one request mailbox
- **THEN** they run one after the other in that order and each ends with its own result

### Requirement: Receivers in Node-RED
Each **canworks can receive**, **canworks j1939 receive** and **canworks emcy** node SHALL hold one receiver while it is deployed and the link is up, opened with its filter and closed when the node is closed. The config node SHALL read every configured receive block every poll, give each record to its receiver's node in batch order as one message (CAN `{id, extended, dlc, data, time}`, J1939 `{pgn, source, destination, priority, data, time}`, EMCY `{node, code, register, data, time}`), fetch long J1939 messages, and acknowledge each block's batch once every record in it is taken. Record layouts and times SHALL follow the bridge's receive layout as generated ("Layout from one source"). When the bridge closes a receiver (generation changed), the node SHALL send one message with ERROR_ID 8 and open it again. More receivers than the bridge allows SHALL end with the family's "no free receiver" ERROR_ID in the node's status.

#### Scenario: Frames between polls
- **WHEN** a node sends 20 frames matching a **canworks can receive** filter within 5 ms
- **THEN** the node emits 20 messages in order and none is dropped

### Requirement: Restart and link stop
After every connect, before its first other write, the config node SHALL read the holding registers of the outputs, the control block, the SDO request, every request block and the receive acknowledgement and write them back unchanged, so a bridge restart takes them as its baseline. Jobs running at a connection loss SHALL end with ERROR_ID 20; jobs ended by the bridge with ERROR_ID 8 SHALL end with 8. The package SHALL NOT repeat a job by itself. Cyclic jobs and receivers SHALL be set up again once the link is back, and a **canworks can cyclic** that was running SHALL say so with one message. The cyclic job keepalives SHALL be written every poll while Node-RED runs, so the bridge stops the frames within 1 s after Node-RED stops.

#### Scenario: Bridge restart during idle
- **WHEN** the bridge restarts while the last CAN send's request is still in its holding registers and no job is running
- **THEN** no frame goes out, and the next **canworks can send** after the reconnect runs and ends `done`

#### Scenario: Node-RED stops
- **WHEN** a **canworks can cyclic** job sends every 100 ms and Node-RED stops
- **THEN** the frames stop within 1 s

### Requirement: Read-only flows
The flow of a Node-RED connection (modbus-connections) whose `writes` is false, and of any config with `plc_link` true (an OpenPLC connection owns the outputs and the mailboxes), SHALL have a config node marked read-only: **canworks in** works, nothing is written to the bridge, the tab has no **canworks out**, a **canworks out** added by hand warns once and drops values, and block nodes end each job with ERROR_ID 22 and the status "read-only". With `plc_link` true and `writes` ticked on the Node-RED connection, Problems SHALL warn that the PLC owns the bridge's writes and that the flow stays read-only.

#### Scenario: Dashboard next to OpenPLC
- **WHEN** a config has an OpenPLC connection and a Node-RED connection, and the user imports the Node-RED flow while the PLC runs
- **THEN** **canworks in** emits the values and the PLC's link stays ok

#### Scenario: Node-RED that writes
- **WHEN** a config without `plc_link` has a Node-RED connection with `writes` true
- **THEN** its flow has **canworks out** and the block nodes run jobs

### Requirement: Node-RED connection files
The Node-RED connection's Download SHALL give the flow (`--export-nodered` with the connection's `bridge_host` and `period_ms`, default 10), and its row SHALL also offer **Package** (`node-red-canworks-<tools version>.tgz`, the file `--export-nodered-package` writes), and the message after either download SHALL say how to install the package ("Install it once in Node-RED: Manage palette > Install > upload" after **Package**; the package name the flow needs after **Download**). Out of date SHALL follow the flow's map hash only; the package SHALL NOT make a connection out of date.

#### Scenario: Both files
- **WHEN** the user adds a Node-RED connection and presses Download and then Node-RED package
- **THEN** the browser downloads `<config name>-<connection name>.json` and `node-red-canworks-<version>.tgz`, equal to the command-line files

### Requirement: Layout from one source
The package's layout table (mailbox offsets, operation codes, record sizes, status bits, ERROR_ID texts) SHALL be generated from the PC tools' mailbox layout and block tables, and a test SHALL fail when the committed table differs from a fresh one. A test SHALL also compare the generated sizes, operation codes, states, kinds and flags with the bridge's own (`mailboxes.h`, record sizes in `mailboxes.cpp`). The package tests SHALL run every node against a scripted model of the bridge's registers and, in CI, against the real bridge.

#### Scenario: Stale layout
- **WHEN** a change moves the receive mailbox's record words in `mailboxlayout.py` without regenerating the package's layout
- **THEN** CI fails naming `lib/layout.js`
