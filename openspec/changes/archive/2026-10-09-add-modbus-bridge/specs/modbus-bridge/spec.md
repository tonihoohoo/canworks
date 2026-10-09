## ADDED Requirements

### Requirement: Bridge process
`canworks-bridge --config FILE` SHALL run the networks of a bridge config (a version 2 config with a `bridge` object) on Linux without an OpenPLC runtime. It SHALL run every network kind the build includes (CANopen master, slave and gateway, J1939, plain CAN, raw messages, simulated networks), the diagnostics channel and trace exactly as the plugin does. The only difference is that the process image is served to Modbus TCP clients instead of a PLC program. It SHALL log one line naming its config, its protocols, its listen address and the number of input and output bytes, and SHALL exit with a non-zero status and the check's messages when the config is not valid.

#### Scenario: CANopen network behind Modbus
- **WHEN** the bridge runs a config with a CANopen master network on `can0` with node 5 and a `bridge` object
- **THEN** node 5 is booted and exchanges PDOs as under the plugin, and a Modbus client reads its TPDO values from input registers

#### Scenario: Config without bridge object
- **WHEN** `canworks-bridge` is started with a config that has no `bridge` object
- **THEN** it exits with an error saying the config is not a bridge config

### Requirement: Byte-addressed locations
In a bridge config every IEC location SHALL be byte-addressed: `%IBn` is input byte n, `%IWn` bytes n..n+1, `%IDn` bytes n..n+3, `%ILn` bytes n..n+7 and `%IXn.b` bit b of byte n, the same for `%Q`. Two locations SHALL clash when their byte ranges overlap, or when a bit location lies in a byte another location of the same direction covers, unless both are bits of different bit numbers. Word, double and long word locations SHALL start at an even byte. The image SHALL hold values most significant byte first. `sync_source: "plc_cycle"` SHALL be rejected, since the bridge has no PLC cycle.

#### Scenario: Overlap in byte mode
- **WHEN** a bridge config has `%ID4` on one PDO entry and `%IW6` on another
- **THEN** the config is rejected with an error naming both entries and the overlapping bytes 6 and 7

#### Scenario: Odd word location
- **WHEN** a bridge config puts a 16-bit entry at `%IW3`
- **THEN** the config is rejected with an error saying word locations must start at an even byte

### Requirement: Register and bit map
The bridge SHALL serve input byte n as input register n/2 (even n the high byte, odd n the low byte), input bit `%IXn.b` as discrete input n·8+b, output byte n as holding register n/2 and output bit `%QXn.b` as coil n·8+b. Holding registers and coils SHALL read back the output image. A 32- or 64-bit value SHALL occupy consecutive registers, highest word first with `word_order: "high_first"` (default) and lowest word first with `"low_first"`. REAL32 and REAL64 objects SHALL be served as their IEEE bit patterns.

#### Scenario: 32-bit input
- **WHEN** a TPDO entry UNSIGNED32 at `%ID4` holds 0x12345678 and a client reads input registers 2 and 3
- **THEN** it gets 0x1234 and 0x5678, and with `word_order: "low_first"` it gets 0x5678 and 0x1234

#### Scenario: Output bit as coil
- **WHEN** a client writes coil 801 to 1 and `%QX100.1` is bound to an RPDO entry
- **THEN** the RPDO carries TRUE for that entry, and holding register 50 reads back with bit 1 of its high byte set

### Requirement: Consistent requests
Every read request SHALL be answered from one input snapshot, and every write request SHALL be applied to the outputs as one snapshot. A value spanning several registers SHALL never mix two snapshots within one request.

#### Scenario: Fast-changing counter
- **WHEN** a node's 32-bit counter changes every millisecond and a client reads its two registers in one request 10,000 times
- **THEN** every pair read is a value the node actually sent

### Requirement: Outputs without a scan
A write request SHALL publish its new output snapshot immediately. Synchronous RPDOs SHALL carry it from the next SYNC, event-driven RPDOs from the next SYNC on a network with a SYNC period and at once on one without, and raw messages sent on change and J1939 messages sent on change SHALL go out without waiting for a cycle. Rising-edge inputs of the config (SDO variable triggers, NMT command bytes, raw trigger bits) SHALL be detected between consecutive published snapshots, so rewriting the same value creates no edge.

#### Scenario: Cyclic rewrite
- **WHEN** a client writes the same holding registers, including an SDO variable's trigger bit at 1, every 10 ms
- **THEN** the SDO variable is transferred once, at the first write that set the bit

#### Scenario: Event-driven output
- **WHEN** a client changes a value mapped into an event-driven RPDO
- **THEN** the RPDO is sent at the next SYNC when the network has a SYNC period, and within 2 ms of the write response when it has none

### Requirement: Output watchdog
The bridge SHALL feed its watchdog with every accepted write request (functions 5, 6, 15, 16, 23) from a writer client. When no such write arrived for `watchdog_ms` (default 1000; 0 turns the watchdog off), the bridge SHALL enter outputs off with the action of `on_client_loss`:
- `"stop"` (default): outputs stop: no RPDOs, no raw or J1939 transmit messages. SYNC keeps running, so nodes that send their inputs on SYNC keep sending them and a node's RPDO event timer sees the outputs stop
- `"zero"`: every output location is set to 0, the outputs are sent once, then they stop
- `"hold"`: outputs keep being sent with their last values

Inputs, SYNC, node supervision, the diagnostics channel and J1939 address claim SHALL keep running. The next accepted write SHALL end outputs off. Entering and leaving SHALL be logged with the reason.

#### Scenario: Client unplugged
- **WHEN** the client that writes outputs every 50 ms stops and `watchdog_ms` is 1000 with the default action
- **THEN** about 1 s later RPDOs stop, SYNC and input registers keep updating, the status block reads 2, and the log names the watchdog

#### Scenario: Reader does not feed the watchdog
- **WHEN** only a client that reads input registers is connected
- **THEN** the watchdog runs out and outputs stay off

### Requirement: Status block
With `status_location` (8 input bytes), the bridge SHALL publish:
- byte 0: state (1 running, 2 outputs off by watchdog, 3 outputs off by idle command)
- byte 1: number of connected clients
- bytes 2-3: a counter incremented every 100 ms
- bytes 4-5: the last control counter handled
- byte 6: the last control result
- byte 7: 0

#### Scenario: Bridge alive
- **WHEN** a client reads the status block twice 500 ms apart
- **THEN** the counter has grown by about 5

### Requirement: Control block
With `control_location` (6 output bytes: counter word, command, network index, node, reserved), the bridge SHALL run a command once each time the counter changes, and SHALL echo the counter with a result in the status block (0 ok, 1 unknown command, 2 bad network, 3 bad node, 4 not a CANopen master network). Commands:
- 1 run (end outputs off from idle)
- 2 idle (outputs off with the `on_client_loss` action)
- 3 NMT start, 4 NMT stop, 5 NMT pre-operational, 6 reset node, 7 reset communication, for the node on that CANopen master network (node 0 = all nodes)

#### Scenario: Stop one node
- **WHEN** a client writes command 4, network 0, node 7 and changes the counter from 41 to 42
- **THEN** NMT stop goes to node 7 once, and the status block shows counter 42 with result 0

#### Scenario: Counter unchanged
- **WHEN** the client rewrites the same control block every 10 ms
- **THEN** the command runs only once

### Requirement: Live list
Each `live_lists` entry SHALL name a CANopen master network and a 16-byte input location. Bit n of that block (byte n/8, bit n mod 8) SHALL be set while node n of that network is OPERATIONAL.

#### Scenario: Node lost
- **WHEN** node 7 stops sending heartbeats
- **THEN** bit 7 of the live list clears when the master declares it lost

### Requirement: SDO bridge registers
With `sdo_bridge_location` (`request`: 14 output bytes, `response`: 14 input bytes), a client SHALL read or write one object of up to 4 bytes on a node of a CANopen master network. The request is counter, command (1 read, 2 write), network index, node, sub-index, index, length, reserved and value. The response is counter echo, status (0 idle, 1 busy, 2 done, 3 aborted), reserved, abort code and value. A request SHALL start when the counter changes, and SHALL go through the same queue and timeout as the SDO function blocks and the gateway's SDO bridge. A write SHALL need `sdo_bridge_write: true`; without it the request SHALL end aborted with abort code 0x08000020 and nothing is sent.

#### Scenario: Read the vendor ID
- **WHEN** a client writes command 1, network 0, node 5, index 0x1018, sub-index 1, length 4 and a new counter
- **THEN** the response shows that counter with status 1, then status 2 with node 5's vendor ID in the value

### Requirement: Clients and access
The bridge SHALL listen on `listen` and accept at most `max_clients` connections (default 16), closing further ones at accept with a log line. A client whose address is not in `readers` (when set) SHALL be disconnected at accept. A write from a client not in `writers` (when set) SHALL get exception 0x01 and change nothing. The bridge SHALL answer requests for `unit_id` (default 1), 0 and 255, and SHALL answer other unit IDs with exception 0x0B. It SHALL support functions 1, 2, 3, 4, 5, 6, 15, 16, 23 and 8 (loopback), answer other functions with exception 0x01, and answer addresses outside the image or counts over 125 registers read, 123 registers written or 2000 bits with exception 0x02 or 0x03. A connection idle for 60 s SHALL be closed.

#### Scenario: Write from a reader
- **WHEN** `writers` is `["10.0.0.20"]` and a client at 10.0.0.30 writes a holding register
- **THEN** it gets exception 0x01 and the output image is unchanged

#### Scenario: Read past the image
- **WHEN** the input image is 40 bytes and a client reads input registers 18 to 21
- **THEN** it gets exception 0x02

### Requirement: One owner per interface
A process (bridge or OpenPLC plugin) SHALL take an exclusive lock for each real CAN interface it uses before bringing it up. When the lock is held by another process, the network SHALL fail to start with an error naming the interface and the owner's process ID, and the other networks SHALL run.

#### Scenario: Second bridge on can0
- **WHEN** two bridge instances are configured with networks on `can0`
- **THEN** the second logs that `can0` is owned by the first one's process ID and does not touch the interface

### Requirement: Several instances
`scripts/install-bridge.sh` SHALL build and install the bridge with the same protocol options as the plugin install (`--without-canopen`, `--without-j1939`), and SHALL install a systemd template unit `canworks-bridge@NAME` that runs the config in `/etc/canworks-bridge/NAME/` with `CAP_NET_BIND_SERVICE` and restarts on failure. A release SHALL publish a multi-arch container image of the bridge.

#### Scenario: Two machine sections
- **WHEN** `canworks-bridge@press` uses `can0` on port 502 and `canworks-bridge@feeder` uses `can1` on port 1502
- **THEN** both run, each serving only its own networks
