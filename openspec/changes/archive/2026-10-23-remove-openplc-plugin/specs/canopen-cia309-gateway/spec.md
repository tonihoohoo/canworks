## MODIFIED Requirements

### Requirement: CiA 309-3 gateway is opt-in
A version 2 file MAY have a top-level `cia309` object (a version 1 file `master.cia309`) with `port` (0 or 1024 to 65535, default 7533), `bind` (`127.0.0.1` or `::1`, default `127.0.0.1`), `max_clients` (1 to 16, default 4), `allow_changes` (default false), `allow_force` (default false), `nets` (an object mapping network numbers 1 to 127 to network names) and `default_net`. Without `cia309` the bridge and the bridge SHALL open no gateway port and SHALL refuse the diagnostics `cia309` op. With it, they SHALL listen on `bind`:`port` (no plain listener when `port` is 0) from the start of the CANopen session until the PLC or bridge stops, SHALL log the address, whether changes and force are allowed and the network numbering, and SHALL retry a listener that cannot be opened every 10 seconds without stopping CANopen or the PLC. A `bind` that is not a loopback address, an unknown field, a `nets` entry naming an unknown network or two numbers for one network SHALL reject the configuration, naming the field. A bridge built against a Lely CANopen without the CiA 309-3 text layer SHALL reject a configuration with `cia309`, saying so.

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
A connection to the diagnostics channel that has logged in SHALL be able to send `{"op": "cia309"}`. With `cia309` configured and fewer than `max_clients` gateway sessions open, the bridge SHALL answer with the protocol name, version and network numbering and SHALL from then on treat the connection, inside the same TLS session, as a CiA 309-3 session. The connection SHALL then no longer count towards the diagnostics channel's client limit and SHALL count towards `max_clients`. The op SHALL NOT need `allow_changes`.

#### Scenario: Switch after login
- **WHEN** a client logs in to the diagnostics channel, sends the `cia309` op and then `[1] 1 2 r 0x1018 1 u32`
- **THEN** it receives the JSON answer, then `[1] 0x000001a2` (node 2's vendor ID, as Lely's text layer prints it) as a text line

#### Scenario: Gateway full
- **WHEN** 4 gateway sessions are open with the default `max_clients` and a fifth logged-in client sends the `cia309` op
- **THEN** it is answered `too many gateway clients` and stays a diagnostics connection

### Requirement: Lely's text layer
Each session SHALL parse its lines and format its answers and notifications with Lely CANopen's CiA 309-3 text layer (`co_gw_txt`), version 2.1. Parsed requests SHALL be carried out by the bridge's own dispatcher through the diagnostics channel's bus-thread requests; Lely's CiA 309-1 service object (`co_gw_t`) SHALL NOT be attached to a running master. A line Lely cannot parse SHALL be answered with `ERROR: 101`.

#### Scenario: Syntax error
- **WHEN** a client sends `[7] 1 2 r 0x1018`
- **THEN** it receives `[7] ERROR: 101` and nothing is sent on the bus

### Requirement: Gateway never disturbs the PLC scan
The gateway SHALL run on its own thread, SHALL hand bus work to the bus threads only through the diagnostics hub, and SHALL NOT block or delay the PLC scan hooks, PDO exchange, SYNC, node boot or supervision, whatever its clients send or fail to read.

#### Scenario: Four busy clients
- **WHEN** four sessions read objects in a loop while the PLC runs a 10 ms task
- **THEN** the scan time and PDO timing stay as without them

#### Scenario: Client stops reading
- **WHEN** a session sends requests and never reads its answers
- **THEN** the bridge closes it once 256 KiB of answers are waiting for 10 seconds, and other sessions keep being served

## REMOVED Requirements

### Requirement: Gateway client in the command-line tools
**Reason**: It described the removed OpenPLC plugin; its scenarios change with the plugin gone.
**Migration**: Requirement: Gateway client in the PC tools.

## ADDED Requirements

### Requirement: Gateway client in the PC tools
`canworks-diag gateway` SHALL, with `--listen ADDRESS:PORT` (default `127.0.0.1:7533`), open a local plain port on the PC and connect each accepted connection to the runtime's diagnostics channel with the usual login and the `cia309` op, copying bytes both ways; with `--exec LINE` (repeatable) send the lines and print the answers; with `--list` print the network numbering; and otherwise give an interactive prompt. It SHALL take `--runtime`, the token options and `--network` (as the default network) as the other commands do, and SHALL refuse a `--listen` address that is not loopback unless `--listen-any` is given.

#### Scenario: Tool on the engineering PC
- **WHEN** `canworks-diag --runtime plc.local gateway` runs and a CiA 309-3 tool on the PC connects to `127.0.0.1:7533`
- **THEN** the tool's `[1] 1 2 r 0x1018 1 u32` is answered by the runtime, and no token is sent by the tool

#### Scenario: Older bridge
- **WHEN** the bridge answers the `cia309` op with `unknown op`
- **THEN** the command exits 1 saying the bridge is too old for the CiA 309-3 gateway
