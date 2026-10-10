## ADDED Requirements

### Requirement: CiA 309-3 gateway is opt-in
A version 2 file MAY have a top-level `cia309` object (a version 1 file `master.cia309`) with `port` (0 or 1024 to 65535, default 7533), `bind` (`127.0.0.1` or `::1`, default `127.0.0.1`), `max_clients` (1 to 16, default 4), `allow_changes` (default false), `allow_force` (default false), `nets` (an object mapping network numbers 1 to 127 to network names) and `default_net`. Without `cia309` the plugin and the bridge SHALL open no gateway port and SHALL refuse the diagnostics `cia309` op. With it, they SHALL listen on `bind`:`port` (no plain listener when `port` is 0) from the start of the CANopen session until the PLC or bridge stops, SHALL log the address, whether changes and force are allowed and the network numbering, and SHALL retry a listener that cannot be opened every 10 seconds without stopping CANopen or the PLC. A `bind` that is not a loopback address, an unknown field, a `nets` entry naming an unknown network or two numbers for one network SHALL reject the configuration, naming the field. A plugin built against a Lely CANopen without the CiA 309-3 text layer SHALL reject a configuration with `cia309`, saying so.

#### Scenario: Not configured
- **WHEN** the config has no `cia309`
- **THEN** nothing listens on port 7533 and a logged-in diagnostics client's `cia309` op answers `cia309 gateway not configured`

#### Scenario: Plain port on the network refused
- **WHEN** `cia309.bind` is `0.0.0.0`
- **THEN** the configuration is rejected naming `cia309.bind` and saying the plain gateway port listens on loopback only and remote clients use the diagnostics channel

#### Scenario: Enabled read-only
- **WHEN** `cia309` is `{}`
- **THEN** the log says the CiA 309-3 gateway listens on `127.0.0.1:7533`, read-only, and lists `1 = io` for a config whose only network is `io`

### Requirement: Remote sessions through the diagnostics channel
A connection to the diagnostics channel that has logged in SHALL be able to send `{"op": "cia309"}`. With `cia309` configured and fewer than `max_clients` gateway sessions open, the plugin SHALL answer with the protocol name, version and network numbering and SHALL from then on treat the connection, inside the same TLS session, as a CiA 309-3 session. The connection SHALL then no longer count towards the diagnostics channel's client limit and SHALL count towards `max_clients`. The op SHALL NOT need `allow_changes`.

#### Scenario: Switch after login
- **WHEN** a client logs in to the diagnostics channel, sends the `cia309` op and then `[1] 1 2 r 0x1018 1 u32`
- **THEN** it receives the JSON answer, then `[1] 0x000001a2` (node 2's vendor ID, as Lely's text layer prints it) as a text line

#### Scenario: Gateway full
- **WHEN** 4 gateway sessions are open with the default `max_clients` and a fifth logged-in client sends the `cia309` op
- **THEN** it is answered `too many gateway clients` and stays a diagnostics connection

### Requirement: Lely's text layer
Each session SHALL parse its lines and format its answers and notifications with Lely CANopen's CiA 309-3 text layer (`co_gw_txt`), version 2.1. Parsed requests SHALL be carried out by the plugin's own dispatcher through the diagnostics channel's bus-thread requests; Lely's CiA 309-1 service object (`co_gw_t`) SHALL NOT be attached to a running master. A line Lely cannot parse SHALL be answered with `ERROR: 101`.

#### Scenario: Syntax error
- **WHEN** a client sends `[7] 1 2 r 0x1018`
- **THEN** it receives `[7] ERROR: 101` and nothing is sent on the bus

### Requirement: Network numbering
Without `nets`, CiA 309 network n SHALL be the n-th network of the config in config order. With `nets`, only the listed numbers SHALL exist. A network number that does not exist SHALL be answered `ERROR: 106`, and so SHALL every request to a J1939 or plain CAN network. A request with network 0 or none SHALL use the session's default network (`set network`, else `default_net`), and SHALL be answered `ERROR: 104` when there is none and the config has several networks; with one network that network SHALL be the default. On a slave network, SDO requests to the slave's own node ID SHALL read and write its own dictionary with the diagnostics channel's own-dictionary rules, and every other request SHALL be answered `ERROR: 107`.

#### Scenario: Second network
- **WHEN** the config has networks `io` and `drives` and a client sends `[3] 2 4 r 0x1000 0 u32`
- **THEN** the read goes to node 4 on `drives`

#### Scenario: Explicit numbers
- **WHEN** `nets` is `{"10": "drives"}` and a client sends `[1] 1 4 r 0x1000 0 u32`
- **THEN** it receives `[1] ERROR: 106`

#### Scenario: Default network
- **WHEN** a client sends `[1] set network 2` and then `[2] 4 r 0x1000 0 u32`
- **THEN** the read goes to node 4 on network 2

### Requirement: SDO services
A session SHALL be able to read (`r`) any index and subindex of any node ID 1 to 127 other than the master's own, configured or not, with the data types of CiA 309-3, up to 4096 bytes, and with `allow_changes` to write (`w`) them, with the same transfer ordering as the diagnostics channel's manual SDO read and write (behind the node's boot configuration and SDO variables). `set sdo_timeout` SHALL set the session's SDO timeout (clamped to 10 to 10000 ms, default 1000). An SDO abort SHALL be answered with its CiA 301 abort code, a missing answer with `ERROR: 103`.

#### Scenario: Read the device type
- **WHEN** a client sends `[1] 1 5 r 0x1000 0 u32` and node 5 answers
- **THEN** it receives `[1]` followed by node 5's device type

#### Scenario: Object missing
- **WHEN** a client reads 0x2100 subindex 0 that node 5 does not have
- **THEN** it receives `ERROR: 06020000` (the abort code in hex, as Lely's text layer prints it) for that sequence number

#### Scenario: Write read-only
- **WHEN** `allow_changes` is false and a client sends `[2] 1 5 w 0x2000 1 u8 3`
- **THEN** it receives `[2] ERROR: 102`, no SDO is sent, and the log says changes are not allowed with the client's address

### Requirement: NMT services
With `allow_changes`, a session SHALL be able to send `start`, `stop`, `preop`, `reset node` and `reset comm` to a configured node, or to every configured node with node 0, with the hold rules of the diagnostics channel's manual NMT commands (stop and preop hold the node, start releases a hold, the newest command wins). Commands to node IDs not in the configuration SHALL be answered `ERROR: 107` and send nothing.

#### Scenario: Stop a node in pre-operational
- **WHEN** `allow_changes` is true, node 5 is PRE-OPERATIONAL and a client sends `[4] 1 5 stop`
- **THEN** node 5 goes to STOPPED under an operator hold and the client receives `[4] OK`

### Requirement: Nodes the PLC owns
A request that the diagnostics channel refuses without `force` (an SDO write to a configured node that is OPERATIONAL, an NMT command other than start to a configured node that is OPERATIONAL, NMT to node 0 while any configured node is OPERATIONAL) SHALL be answered `ERROR: 102` and send nothing unless `allow_force` is true. With `allow_force` it SHALL be carried out as a forced request and logged as forced.

#### Scenario: Running node
- **WHEN** node 5 is OPERATIONAL, `allow_changes` is true, `allow_force` is false and a client sends `[5] 1 5 stop`
- **THEN** it receives `[5] ERROR: 102`, node 5 stays OPERATIONAL, and the log says node 5 is OPERATIONAL and force is not allowed on the gateway

#### Scenario: Test bench with force
- **WHEN** the same request comes with `allow_force` true
- **THEN** node 5 goes to STOPPED and the log line says the command was forced through the CiA 309-3 gateway

### Requirement: PDO read
A session SHALL be able to read the last values the master received in a configured node's TPDO 1 to 4 with `r p`, using the gateway RPDO number (node − 1) × 4 + TPDO number, on the session's default network or the one named as `<net> 0` in front (Lely's parser reads a single number in front of `r p` as a node ID). A number without a TPDO the master maps SHALL be answered `ERROR: 102`. `w p`, `set rpdo` and `set tpdo` SHALL be answered `ERROR: 100`.

#### Scenario: Read node 2's TPDO 1
- **WHEN** node 2's TPDO 1 maps two UNSIGNED16 entries and a client sends `[6] 1 0 r p 5`
- **THEN** it receives `[6]` with the count 2 and the two values the master received last

#### Scenario: PDO write
- **WHEN** a client sends a `w p` request
- **THEN** it receives `ERROR: 100` and nothing changes

### Requirement: LSS services
With `allow_changes`, a session SHALL be able to use `lss_switch_glob 0`, `lss_switch_sel`, `lss_set_node`, `lss_conf_bitrate`, `lss_store`, `lss_get_node`, `lss_inquire_addr` and Lely's `_lss_fastscan`, each carried out as one LSS operation of the diagnostics channel (one at a time per network, shared with the master's own assignment, ending with all devices in LSS waiting): `lss_switch_sel` SHALL only remember the address for the session's following LSS requests, `lss_set_node` SHALL refuse the master's node ID and the node ID of a booted configured node, and nothing SHALL be stored unless `lss_store` is sent. `lss_switch_glob 1` and `lss_activate_bitrate` SHALL be answered `ERROR: 100`. Without `allow_changes` every LSS request SHALL be answered `ERROR: 102` and send no LSS frame; a request while another LSS operation runs SHALL be answered `ERROR: 102` with "LSS busy" in the log.

#### Scenario: Give a new device a node ID
- **WHEN** `allow_changes` is true, a device without a node ID is on the bus, and a client runs `_lss_fastscan`, `lss_switch_sel` with the found address and `lss_set_node 40`
- **THEN** the device boots as node 40 and no LSS store request was sent

#### Scenario: Activate bit timing
- **WHEN** a client sends `lss_activate_bitrate`
- **THEN** it receives `ERROR: 100` and the bus keeps its bit rate

### Requirement: Services not served
`init`, `set id`, `set heartbeat`, node guarding and heartbeat enable and disable, and Lely's `_sync`, `_time` and `_boot` SHALL be answered `ERROR: 100`, send nothing and change nothing. `info version`, `set network`, `set node` and `set command_timeout` SHALL be answered on the gateway thread without bus access.

#### Scenario: Change the heartbeat
- **WHEN** a client sends `[9] 1 set heartbeat 100`
- **THEN** it receives `[9] ERROR: 100` and the master's heartbeat is unchanged

### Requirement: Notifications
While a session is open, it SHALL receive an unsolicited line for every EMCY a configured node sends (code, error register and manufacturer bytes), for every boot-up of a configured node (unless the session turned boot-up indication off), and for every NMT state change and heartbeat loss of a configured node, on every network the gateway serves. The bus thread SHALL record these events only while at least one session is open and SHALL never wait for a session. A session that falls more than 1024 events behind SHALL lose the oldest and SHALL be told how many it lost in a line starting with `#`.

#### Scenario: EMCY from a node
- **WHEN** a session is open and node 3 on network 1 sends EMCY 0x5030 with register 0x01
- **THEN** the session receives a line `1 3 EMCY 5030 01 ...` with the manufacturer bytes (Lely's format)

#### Scenario: Node lost
- **WHEN** node 7 stops sending heartbeats
- **THEN** every open session receives the heartbeat loss indication for network 1 node 7

### Requirement: Gateway never disturbs the PLC scan
The gateway SHALL run on its own thread, SHALL hand bus work to the bus threads only through the diagnostics hub, and SHALL NOT block or delay the PLC scan hooks, PDO exchange, SYNC, node boot or supervision, whatever its clients send or fail to read.

#### Scenario: Four busy clients
- **WHEN** four sessions read objects in a loop while the PLC runs a 10 ms task
- **THEN** the scan time and PDO timing stay as without them

#### Scenario: Client stops reading
- **WHEN** a session sends requests and never reads its answers
- **THEN** the plugin closes it once 256 KiB of answers are waiting for 10 seconds, and other sessions keep being served

### Requirement: Session limits
The gateway SHALL serve at most `max_clients` sessions (plain and tunnelled together) and SHALL answer a further plain connection with one `ERROR: 102` line and close it. A session SHALL have at most 8 commands outstanding, answered in the order sent; a further command SHALL be answered `ERROR: 102`. A line longer than 16 KiB SHALL close the session. A command the bus thread has not answered within the session's command timeout (default 5 s, `set command_timeout`) SHALL be answered `ERROR: 103`. Every SDO download, NMT and LSS command carried out SHALL be logged with the client's address, marked as coming from the CiA 309-3 gateway.

#### Scenario: Pipelined commands
- **WHEN** a client sends 10 read commands without waiting
- **THEN** it receives answers to the first 8 in order and `ERROR: 102` for the 9th and 10th

### Requirement: Gateway client in the command-line tools
`canworks-diag gateway` SHALL, with `--listen ADDRESS:PORT` (default `127.0.0.1:7533`), open a local plain port on the PC and connect each accepted connection to the runtime's diagnostics channel with the usual login and the `cia309` op, copying bytes both ways; with `--exec LINE` (repeatable) send the lines and print the answers; with `--list` print the network numbering; and otherwise give an interactive prompt. It SHALL take `--runtime`, the token options and `--network` (as the default network) as the other commands do, and SHALL refuse a `--listen` address that is not loopback unless `--listen-any` is given.

#### Scenario: Tool on the engineering PC
- **WHEN** `canworks-diag --runtime plc.local gateway` runs and a CiA 309-3 tool on the PC connects to `127.0.0.1:7533`
- **THEN** the tool's `[1] 1 2 r 0x1018 1 u32` is answered by the runtime, and no token is sent by the tool

#### Scenario: Older plugin
- **WHEN** the runtime's plugin answers the `cia309` op with `unknown op`
- **THEN** the command exits 1 saying the runtime's plugin is too old for the CiA 309-3 gateway
