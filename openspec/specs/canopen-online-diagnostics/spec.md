# canopen-online-diagnostics Specification

## Purpose
An opt-in, token-protected TCP channel on the plugin that lets the configurator and `openplc-canopen-diag` watch node and bus state live, read and (when allowed) write objects over SDO, send NMT commands and scan the bus for nodes while the PLC runs.

## Requirements

### Requirement: Diagnostics channel is opt-in
The `master` object MAY give a `diagnostics` object with `token_sha256` (required: 64 hexadecimal characters, the SHA-256 of the access token), `port` (1024 to 65535, default 7531), `bind` (an IPv4 address, default `0.0.0.0`) and `allow_changes` (boolean, default false). Without `master.diagnostics` the plugin SHALL open no network listener. With it, the plugin SHALL listen on `bind`:`port` from the start of the CANopen session until the PLC stops, and SHALL log the address and whether changes are allowed. A listener that cannot be opened (port in use, address not on the host) SHALL be logged as a warning and SHALL NOT stop CANopen or the PLC; the plugin SHALL retry opening it every 10 seconds. An invalid `diagnostics` object SHALL reject the configuration, naming the field.

#### Scenario: Not configured
- **WHEN** `canopen.json` has no `master.diagnostics`
- **THEN** the plugin opens no TCP port

#### Scenario: Enabled read-only
- **WHEN** `master.diagnostics` is `{"token_sha256": "<64 hex>"}`
- **THEN** the plugin logs that diagnostics listen on `0.0.0.0:7531` read-only, and a client with the token can read status and scan

#### Scenario: Port in use
- **WHEN** another process already listens on port 7531
- **THEN** the plugin logs a warning naming the port, CANopen runs normally, and the listener opens once the port is free

#### Scenario: Bad token hash
- **WHEN** `token_sha256` is not 64 hexadecimal characters
- **THEN** the plugin rejects the configuration and names `master.diagnostics.token_sha256`

### Requirement: Access control
Each connection SHALL first present a token; the plugin SHALL compare its SHA-256 with `token_sha256` in constant time and close the connection without answering any request when it does not match. Failed attempts SHALL be logged at most once per minute per peer address. The plugin SHALL serve at most 4 connections at a time and refuse more. Without `allow_changes`, SDO writes and NMT commands SHALL be refused with the reason "changes not allowed" and nothing SHALL be sent on the bus. Every SDO write and NMT command carried out SHALL be logged with the peer address, the node and the object or command.

#### Scenario: Wrong token
- **WHEN** a client connects and presents a token whose SHA-256 differs from `token_sha256`
- **THEN** the connection is closed, no status is returned, and one warning naming the peer address is logged

#### Scenario: Write refused when read-only
- **WHEN** `allow_changes` is false and an authenticated client asks to write 0x2000 subindex 1 of node 5
- **THEN** the request is refused with "changes not allowed" and no SDO is sent

#### Scenario: Fifth client
- **WHEN** four authenticated clients are connected and a fifth connects
- **THEN** the fifth connection is refused and the four keep working

### Requirement: Diagnostics never disturb the PLC scan
Serving the channel SHALL NOT block or delay the PLC scan cycle hooks, and a slow or stalled client SHALL NOT delay CAN traffic, node boot or supervision. Requests SHALL be answered in the order each connection sent them. While the CAN interface is missing or down between bus sessions, the channel SHALL stay open and answer status with bus state 0 and every node with state 0, and SHALL refuse SDO, NMT and scan requests with the reason "no bus".

#### Scenario: Client stops reading
- **WHEN** a client asks for status repeatedly and stops reading the answers
- **THEN** PDO exchange, heartbeat supervision and the PLC scan continue unchanged, and the plugin closes that connection once its send buffer is full

#### Scenario: Cable unplugged
- **WHEN** the CAN interface goes down while a client is connected
- **THEN** status answers show bus state 0 and all nodes at state 0, and an SDO read request is refused with "no bus"

### Requirement: Live status
A status request SHALL return, as of no more than 100 ms before the answer:
- the plugin version, the time since the CANopen session started, and the SHA-256 of the loaded `canopen.json` file;
- the master node ID and NMT state code, and the bus state, TX and RX error counters and bus-off count as the bus diagnostics define them (whether or not their PLC locations are configured);
- the SYNC source (`none`, `timer` or `plc_cycle`), `sync_cycles` for `plc_cycle`, and the SYNC statistics: SYNCs sent, last, shortest and longest interval in microseconds, skipped frames and late PDOs;
- for each configured node: node ID, name, NMT state code as the state byte defines it, status bit value, whether its last boot succeeded, its last boot error letter with Lely's text (or none), whether a boot retry is pending, the hold in force (none, by the program, or by an operator, with STOPPED or PRE-OPERATIONAL), its last emergency code and error register, and for each SDO variable its name, current value, status code and abort code;
- for each node TPDO with `timeout_ms`: the TPDO number, the resolved timeout in milliseconds, whether it is timed out now, the number of timeouts since the session started, and the milliseconds since its last PDO.

These values SHALL be available whether or not the corresponding PLC locations are configured. The configurator's online view SHALL show the SYNC line (source, interval last/min/max, skipped, late PDOs) above the node list.

#### Scenario: Node without status locations
- **WHEN** node 5 has no `status_location`, `state_location` or EMCY locations, and is OPERATIONAL
- **THEN** the status answer shows node 5 with state 5, status bit TRUE and boot succeeded

#### Scenario: Node refused its configuration
- **WHEN** node 23's configuration download is aborted and its boot ends with error letter J
- **THEN** the status answer shows node 23 with boot failed, error letter J with Lely's text, and a retry pending

#### Scenario: Config fingerprint
- **WHEN** the configurator holds a `canopen.json` whose SHA-256 differs from the one in the status answer
- **THEN** the configurator can tell that the runtime runs a different configuration

#### Scenario: SYNC jitter visible
- **WHEN** `"sync_source"` is `"plc_cycle"` with a 10 ms task and the online view is open
- **THEN** the SYNC line shows source "PLC cycle", the last interval near 10000 µs, and the shortest and longest intervals seen since start

#### Scenario: No SYNC
- **WHEN** the master produces no SYNC
- **THEN** the status answer gives SYNC source `none` with zero counts

#### Scenario: Timed-out PDO without a location
- **WHEN** node 23's TPDO 1 has `"timeout_ms": 500` and no `timeout_location`, and it has stopped arriving
- **THEN** the status answer shows node 23's TPDO 1 as timed out with a count of at least 1, and `openplc-canopen-diag status` prints a line for node 23's TPDO 1 saying it is timed out

### Requirement: Emergency history
For each configured node the plugin SHALL keep the last 16 emergency messages received since the CANopen session started, each with its wall-clock time, error code, error register and the five manufacturer bytes, and SHALL return them on request, newest first. The history SHALL include messages whose log lines were suppressed by log throttling, up to the 16 kept. A boot-up message SHALL NOT clear the history.

#### Scenario: History after a sensor break
- **WHEN** node 3 sends EMCY 0x5030 three times and then 0x0000
- **THEN** the history for node 3 lists 0x0000 first and the three 0x5030 messages after it, each with its time

#### Scenario: Burst beyond the history size
- **WHEN** node 3 sends 40 emergency messages in one second
- **THEN** the history holds the newest 16 of them

### Requirement: Manual SDO read
An authenticated client SHALL be able to read any index and subindex of any node ID from 1 to 127 other than the master's own, configured or not, with a timeout from 10 to 10000 ms (default 1000). The answer SHALL be the raw bytes (expedited or segmented transfer, up to 4096 bytes; longer data SHALL be aborted with an error saying so) or the CiA 301 abort code, or "timeout". Reads of configured nodes SHALL wait for that node's current SDO transfer (boot configuration or SDO variable) to finish and SHALL NOT change the order or outcome of SDO variable transfers.

#### Scenario: Read the device name
- **WHEN** a client reads 0x1008 subindex 0 of node 5, whose device name is `RTD-8`
- **THEN** the answer carries the 5 bytes `49 4F 2D 58 35`

#### Scenario: Object does not exist
- **WHEN** a client reads 0x2100 subindex 0 that node 5 does not have
- **THEN** the answer carries abort code 0x06020000

#### Scenario: Node absent
- **WHEN** a client reads 0x1000 of node 40 and no device has that node ID
- **THEN** the answer is "timeout" after the requested timeout

### Requirement: Manual SDO write
With `allow_changes`, an authenticated client SHALL be able to write raw bytes (1 to 4096) to any index and subindex of any node ID from 1 to 127 other than the master's own, with the same timeout rules, transfer ordering and answers as manual reads. A write SHALL be logged before it is sent. The plugin SHALL NOT remember a manual write: an owned SDO variable or a later boot SHALL write its own value again as usual.

#### Scenario: Change a parameter by hand
- **WHEN** `allow_changes` is true and a client writes `1E 00` to 0x6110 subindex 1 of node 3
- **THEN** the plugin logs the write with the peer address, sends it, and answers success

#### Scenario: Owned variable wins after reboot
- **WHEN** node 3 has an owned write SDO variable for 0x6110 subindex 1 and a client writes a different value by hand, and node 3 then reboots
- **THEN** after the boot the master writes the program's value again

### Requirement: Manual NMT commands
With `allow_changes`, an authenticated client SHALL be able to send START, STOP, ENTER PRE-OPERATIONAL, RESET NODE or RESET COMMUNICATION to one configured node. STOP and ENTER PRE-OPERATIONAL SHALL hold the node in that state exactly as the program's NMT command byte values 2 and 128 do ("operator hold"). START SHALL release an operator hold or a program hold and start the node; RESET NODE and RESET COMMUNICATION SHALL release any hold and act as the byte values 129 and 130 do. The newest command SHALL win: a later change of the node's NMT command byte SHALL replace an operator hold, and an operator command SHALL replace a program hold until the byte changes again. Commands to node IDs not in the configuration SHALL be refused.

#### Scenario: Hold a node for maintenance
- **WHEN** a client sends STOP to node 5
- **THEN** node 5 goes to STOPPED, its status bit reads FALSE, the master does not reboot it, and the status answer shows an operator hold STOPPED

#### Scenario: Program changes its byte afterwards
- **WHEN** node 5 is under an operator hold STOPPED and the program changes node 5's NMT command byte from 0 to 1
- **THEN** the operator hold ends and the master starts node 5

#### Scenario: Release
- **WHEN** node 5 is under an operator hold and a client sends START
- **THEN** the master starts node 5 and PDO exchange resumes

#### Scenario: Unconfigured node
- **WHEN** a client sends RESET NODE to node 40, which is not in the configuration
- **THEN** the request is refused and nothing is sent

### Requirement: Network scan
An authenticated client SHALL be able to start a scan of node IDs 1 to 127 except the master's own. For each node ID the master SHALL read 0x1018 subindex 1 with a 100 ms timeout; for each node that answers it SHALL then read 0x1018 subindices 2 to 4, 0x1000 and 0x1008 (each optional: an abort leaves that field empty). The scan SHALL only read, SHALL NOT send any NMT command, and SHALL skip a configured node while its boot is in progress, reporting it as "booting". At most one scan SHALL run at a time; a second request SHALL get the running scan's progress. The scan SHALL finish within 10 seconds at 125 kbit/s or faster when no more than 10 devices answer. Progress (node IDs done) SHALL be available while it runs, and the result SHALL list each answering node ID with its identity fields, device type, device name, and a match against the configuration: "configured" (identity agrees with the node's configured identity values or, where those are not set, with its EDS `[DeviceInfo]`), "configured, different device" (naming the field that differs), or "not configured". Configured nodes that did not answer SHALL be listed as "configured, no answer". Devices in STOPPED do not answer SDO; the result SHALL say so.

#### Scenario: Scan a commissioning bus
- **WHEN** node 3 (configured RTD sensor), node 23 (configured as the valve but a different product code) and node 40 (not configured) are on the bus and a client starts a scan
- **THEN** the result lists 3 as configured, 23 as configured, different device (product code), and 40 as not configured with its vendor ID, product code, revision, serial number, device type and name

#### Scenario: Scan while PDOs run
- **WHEN** a scan runs while configured nodes exchange PDOs every SYNC
- **THEN** PDO exchange and heartbeat supervision continue without a missed deadline or a lost node

#### Scenario: Second scan request
- **WHEN** a scan is running and another client asks for a scan
- **THEN** that client gets the running scan's progress and its result when it ends

### Requirement: Command-line client
The deploy package SHALL install `openplc-canopen-diag`, which connects to `--runtime HOST[:PORT]` with a token given by `--token`, the `OPENPLC_CANOPEN_TOKEN` environment variable, or prompted, and offers: `status` (table of master, bus and nodes), `emcy NODE`, `sdo-read NODE INDEX SUB [--type T]`, `sdo-write NODE INDEX SUB VALUE --type T`, `nmt NODE start|stop|preop|reset|reset-comm`, `scan`, and `hash-token` (prints the `token_sha256` for a token). `--json` SHALL print the raw answer. A refused or failed request SHALL exit non-zero with the reason.

#### Scenario: Status from the engineering PC
- **WHEN** `openplc-canopen-diag --runtime plc.local status` runs with the right token
- **THEN** it prints the bus state and one line per node with state, boot result and last EMCY

#### Scenario: Write without permission
- **WHEN** `openplc-canopen-diag --runtime plc.local nmt 5 stop` runs and the config has `allow_changes` false
- **THEN** it prints "changes not allowed" and exits non-zero

### Requirement: LSS commissioning
An authenticated client SHALL be able to run LSS operations on the bus while CANopen runs. Every LSS operation SHALL be refused with "changes not allowed" and send nothing when `allow_changes` is false, and SHALL be refused with "LSS busy" while another LSS operation (from any client, or the master's own assignment) is in progress. Every operation carried out SHALL be logged with the peer address, the LSS address and the result. A device's LSS address is its vendor ID, product code, revision number and serial number. The operations are:
- **Find**: look for one device that has no node ID (0xFF) using LSS fastscan, optionally with a known vendor ID and product code to shorten the search. The result is that device's LSS address, or "none found". Finding runs in the background like the network scan: the client starts it and reads its progress and result; it SHALL finish within 20 seconds at 125 kbit/s or faster. The found device SHALL be left in the LSS waiting state.
- **Inquire**: given an LSS address, read that device's node ID (0xFF for none), or "not found".
- **Set node ID**: given an LSS address, a node ID from 1 to 127 and `store` (default false), set that node ID and, only when `store` is true, send LSS "store configuration"; then switch all devices to the LSS waiting state. It SHALL be refused, sending nothing, when the node ID is the master's own or that of a configured node that is currently booted. The result SHALL say whether the device had no node ID before (it then starts with the new ID right away) or had another ID (the new one becomes active after the device's next communication reset or power cycle).
- **Set bit rate**: given an LSS address, a bit rate from the CiA 301 table (10, 20, 50, 125, 250, 500, 800 or 1000 kbit/s) and `store` (default false), set that device's bit rate and, only when `store` is true, store it; then switch all devices to the LSS waiting state. The master SHALL NOT send LSS "activate bit timing parameters" and SHALL NOT change its own bit rate. The result SHALL say that the device uses the new bit rate after its next power cycle and that `adapter.bitrate` must be changed to match.
A device that refuses a request SHALL make the operation fail with the reason, and the master SHALL still switch all devices to the LSS waiting state. LSS operations SHALL NOT disturb PDO exchange or heartbeat supervision of the configured nodes.

#### Scenario: Find and assign a new device
- **WHEN** `allow_changes` is true, a device with node ID 0xFF is on the bus, and a client starts a find, then sets node ID 40 for the found address without `store`
- **THEN** the find returns the device's vendor ID, product code, revision and serial number, the set returns "had no node ID", the device boots as node 40, and no "store configuration" request is sent

#### Scenario: Store only when asked
- **WHEN** a client sets node ID 40 for a found address with `store` true
- **THEN** the master sends one LSS "store configuration" request after the node ID was set

#### Scenario: Read-only diagnostics
- **WHEN** `allow_changes` is false and a client asks to find a device
- **THEN** the request is refused with "changes not allowed" and no LSS frame is sent

#### Scenario: Node ID in use
- **WHEN** node 3 is configured and booted and a client asks to set node ID 3 for some LSS address
- **THEN** the request is refused, naming node 3 as in use, and no LSS frame is sent

#### Scenario: Set a bit rate
- **WHEN** a client sets 250 kbit/s for a device's LSS address with `store` true while the bus runs at 125 kbit/s
- **THEN** the device gets the bit rate and the store request, no "activate bit timing" request is sent, the bus keeps running at 125 kbit/s, and the result says the device switches after its next power cycle and `adapter.bitrate` must match

#### Scenario: No unconfigured device
- **WHEN** every device on the bus has a node ID and a client starts a find
- **THEN** the result is "none found"

### Requirement: LSS commands in the command-line client
`openplc-canopen-diag` SHALL offer `lss-find [--vendor V --product P]` (shows progress, then the found LSS address), `lss-inquire VENDOR PRODUCT REVISION SERIAL`, `lss-set-id VENDOR PRODUCT REVISION SERIAL NODE [--store]` and `lss-set-bitrate VENDOR PRODUCT REVISION SERIAL KBIT [--store]`. Without `--store` nothing SHALL be stored. A refused or failed operation SHALL exit non-zero with the reason.

#### Scenario: Set an ID from the command line
- **WHEN** `openplc-canopen-diag --runtime plc.local lss-set-id 0x1A2 0x3 0x10001 0x1234 40` runs with `allow_changes` true and that device on the bus
- **THEN** it prints that the device had no node ID and now starts as node 40, and exits 0

#### Scenario: Store needs the flag
- **WHEN** `lss-set-id` runs without `--store`
- **THEN** the request sent has `store` false

### Requirement: Frame capture
While at least one authenticated client has an active trace, the plugin SHALL record every CAN frame on the configured interface: frames from other devices and frames the master sends, each with its receive time (microseconds, UTC), identifier, standard or extended format, RTR flag, data and direction (Tx for frames sent from the PLC host, Rx otherwise). Capture SHALL NOT delay the PLC scan, PDO exchange, SDO transfers or supervision. Frames SHALL be kept in RAM only, never written to storage on the PLC. With no active trace the plugin SHALL NOT capture.

#### Scenario: Both directions recorded
- **WHEN** a client starts a trace while the master sends SYNC and RPDOs and node 23 answers with TPDOs and heartbeats
- **THEN** the fetched frames contain the SYNC and RPDO frames marked Tx and the TPDO and heartbeat frames marked Rx, in time order

#### Scenario: No trace, no capture
- **WHEN** no client has started a trace, or every trace client has stopped or disconnected
- **THEN** the plugin holds no capture socket open and records nothing

#### Scenario: PLC timing unchanged
- **WHEN** a trace runs at full bus load and the client fetches slowly
- **THEN** PDO cycles, heartbeat supervision and the PLC scan keep their timing, and the client is told how many frames it lost

### Requirement: Trace operations
The channel SHALL offer `trace_start`, `trace_fetch` and `trace_stop` to any authenticated client, without `allow_changes`. `trace_start` MAY give a list of identifier/mask filters and whether to include error frames, and SHALL return the sequence number to fetch after. `trace_fetch` with a sequence number SHALL return the frames recorded after it, in order, at most a requested maximum (default 2000, at most 4000) per answer, with the number of frames the client lost because the plugin's buffer wrapped and the number the operating system dropped. The plugin SHALL keep at least 65536 frames for clients to fetch. A trace SHALL end on `trace_stop`, on disconnect, or after 10 s without a fetch. Without a CANopen session, `trace_start` SHALL be refused with "no bus".

#### Scenario: Fetch in pieces
- **WHEN** 5000 frames were recorded since a client's last sequence number and it fetches with maximum 2000
- **THEN** the answer carries the next 2000 frames and the sequence number of the last one, and the following fetches return the rest

#### Scenario: Slow client
- **WHEN** a client does not fetch while 70000 frames are recorded
- **THEN** its next fetch returns the oldest frames still kept and says how many were lost

#### Scenario: Filter
- **WHEN** a client starts a trace with filter identifier 0x180 mask 0x780
- **THEN** it receives only frames with identifiers 0x180-0x1FF

#### Scenario: Read-only channel
- **WHEN** `allow_changes` is false and a client starts a trace
- **THEN** the trace runs and nothing is sent on the bus

#### Scenario: Forgotten trace
- **WHEN** a client starts a trace and then stops fetching without disconnecting
- **THEN** the plugin ends that trace after 10 s and stops capturing if no other trace is active

### Requirement: Capture across interface loss
When the CAN interface goes away during a trace (cable or USB adapter unplugged, interface down), the trace SHALL stay active and the next fetch SHALL say that there is no session. When the interface returns and a new CANopen session starts, capture SHALL resume without the client starting it again, and the frames SHALL show the gap.

#### Scenario: Adapter unplugged and back
- **WHEN** the CANable is unplugged for 5 s during a trace and plugged in again
- **THEN** fetches during the gap answer with no session and no frames, and after the session restarts the client receives the new frames on the same trace

### Requirement: Error frames
When a client asks for error frames, the plugin SHALL also record the CAN error frames the interface's driver reports (bus-off, controller error-warning and error-passive, protocol errors, missing acknowledgement), marked as error frames with their error class and data.

#### Scenario: Error frames requested
- **WHEN** a client starts a trace with error frames and the only device is disconnected, so the master's frames get no acknowledgement
- **THEN** the trace contains error frames for the missing acknowledgement as far as the driver reports them

### Requirement: Trace in the command-line client
`openplc-canopen-diag trace` SHALL record a trace from the runtime into a file, with options for the output file and format, duration, capture filters, error frames and a trigger with pre- and post-trigger time. It SHALL print the frame count, the frame rate and any lost or dropped frames when it ends, and SHALL stop on Ctrl-C and still write the file. `openplc-canopen-diag convert IN OUT` SHALL convert a trace file between the supported formats.

#### Scenario: Record to ASC for ten seconds
- **WHEN** a user runs `openplc-canopen-diag --runtime plc.local trace --duration 10 -o run.asc`
- **THEN** the command writes a Vector ASC file of ten seconds of bus traffic and prints the count, rate and losses

#### Scenario: Interrupted
- **WHEN** the user presses Ctrl-C during `openplc-canopen-diag trace -o run.pcapng`
- **THEN** the frames recorded so far are written to run.pcapng and the command exits with status 0

#### Scenario: Convert
- **WHEN** a user runs `openplc-canopen-diag convert run.log run.blf`
- **THEN** a BLF file with the same frames, times and directions is written

### Requirement: Simulator operations
When the plugin simulates at least one device, the diagnostics channel SHALL offer the simulator's live control for those devices as `sim_` operations: `sim_status`, `sim_get` and `sim_scenario_list` with the token alone, and the operations that change values, sources, faults or scenarios only with `allow_changes: true`. When the plugin simulates no device every `sim_` operation SHALL answer `nothing simulated`, and an operation naming a node that is not simulated SHALL answer `node N is not simulated`. The `status` answer SHALL carry `simulated_network` and, per node, `simulated`.

#### Scenario: Read-only access
- **WHEN** a client with the token but `allow_changes` false calls `sim_get` and then `sim_fault`
- **THEN** `sim_get` returns the value and `sim_fault` answers `changes not allowed`

#### Scenario: Nothing simulated
- **WHEN** a client calls `sim_status` on a runtime whose config simulates nothing
- **THEN** the answer is `nothing simulated`

#### Scenario: Mixed network
- **WHEN** node 5 is simulated and node 23 is real on `can0`, and a client calls `sim_fault` for node 23
- **THEN** the answer is `node 23 is not simulated`, and `status` shows node 5 with `simulated: true` and node 23 with `simulated: false`

### Requirement: Trace with simulated devices
Bus trace SHALL work on a simulated network with the same operations, filters and records as on a SocketCAN interface, with time stamps from the host's clock when the frame is delivered and the interface reported as `simulated`. On a real network the trace SHALL also record the frames of devices the plugin simulates there.

#### Scenario: Trace a simulated network
- **WHEN** a user starts a trace on a runtime with a simulated network
- **THEN** the trace records the SYNC, PDO, heartbeat and SDO frames of the simulated network, and the trace header says the interface is simulated

#### Scenario: Trace a mixed network
- **WHEN** node 5 is simulated on `can0` next to real node 23 and a user traces `can0`
- **THEN** the trace has the frames of both nodes

### Requirement: Simulator commands in the command-line client
`openplc-canopen-diag` SHALL have `sim` subcommands (`status`, `get`, `set`, `override`, `release`, `source`, `fault`, `clear`, `scenario start|stop|list`) that talk to the plugin's simulated devices with `--runtime` or to a standalone simulator with `--sim HOST[:PORT]`, with the same arguments and output as `openplc-canopen-sim`'s own subcommands.

#### Scenario: Fault from the PC
- **WHEN** a user runs `openplc-canopen-diag sim fault 5 emcy 0x5000 --register 1 --runtime plc.local` against a runtime that simulates node 5, with `allow_changes`
- **THEN** simulated node 5 sends EMCY 0x5000 and the online view shows it in node 5's EMCY history

### Requirement: One channel for all networks
The plugin SHALL serve all networks over one diagnostics channel, with one port, one token, one `allow_changes` setting and one client limit. The hello answer SHALL list the networks in config order, each with its name (empty for a version 1 config), interface, bit rate and master node ID, and SHALL keep `master_node_id` as the first network's.

#### Scenario: Hello with two networks
- **WHEN** a client says hello to a plugin running networks `io` on `can0` and `drives` on `can1`
- **THEN** the answer has protocol 1 and a `networks` list with both, in that order, each with its interface, bit rate and master node ID

### Requirement: Network selector on requests
Every request other than `hello` SHALL accept a `network` field naming a network. With one network it MAY be left out. With several, a request without it SHALL be refused with `network required` and the network names, and an unknown name with `unknown network` and the names. The request SHALL act on the named network only.

#### Scenario: SDO read on the second network
- **WHEN** a client sends `sdo_read` with `network: "drives"`, node 2, 0x1018:1
- **THEN** the read goes to node 2 on `can1`, not to node 2 on `can0`

#### Scenario: Old client and one network
- **WHEN** a client that never sends `network` talks to a plugin with a version 1 config
- **THEN** every request works as before this change

#### Scenario: Missing selector with two networks
- **WHEN** a client sends `status` without `network` to a plugin with two networks
- **THEN** the answer is an error naming `io` and `drives`

### Requirement: Network state is kept per network
Scans, LSS requests, traces, holds, EMCY history and the `no bus` answer SHALL be per network: a scan or LSS request on one network SHALL NOT make the same request on another network answer busy, and a network with no CANopen session SHALL answer `no bus` while the others answer normally. The status answer SHALL carry the network's name.

#### Scenario: Scan on both networks
- **WHEN** a client starts a scan on `io` and then on `drives`
- **THEN** both scans run, and `scan_status` for each network reports its own progress and nodes

#### Scenario: One network without a bus
- **WHEN** network `drives` has no interface and a client asks `status` for `io`
- **THEN** the answer shows `io` with its session, while `status` for `drives` shows `"session": false`

### Requirement: Network option in the command-line client
`openplc-canopen-diag` SHALL take `--network NAME` for every command that talks to the plugin. Without it, a command against several networks SHALL fail listing the names, except `status`, which SHALL print every network one after another.

#### Scenario: Status of all networks
- **WHEN** the user runs `openplc-canopen-diag --runtime plc.local status` against two networks
- **THEN** it prints the status of `io` and then of `drives`, each headed by its name and interface

#### Scenario: SDO read needs a network
- **WHEN** the user runs `sdo-read 2 0x1018 1` without `--network` against two networks
- **THEN** it exits with status 1 saying `--network` is needed and naming `io` and `drives`

### Requirement: Slave network status
For a slave network the diagnostics status SHALL report the role, own node ID, NMT state, communication OK, SYNC count, the PDO mappings the master has set, and the last EMCY sent. Master-only requests (scan, LSS commissioning, node SDO and NMT) SHALL be answered with a message that the network is a slave.

#### Scenario: Online view of a slave
- **WHEN** the configurator's online view opens a slave network the master has started
- **THEN** it shows OPERATIONAL, communication OK and the TPDO and RPDO mappings in force

#### Scenario: Scan on a slave network
- **WHEN** a client asks for a bus scan on a slave network
- **THEN** the answer says scans need a master network

### Requirement: Own dictionary in the object dictionary view
For a slave network the object dictionary view SHALL read the slave's own dictionary locally, without SDO, and SHALL allow writes only with `allow_changes`, to objects the EDS lets the master write.

#### Scenario: Read own object
- **WHEN** the user reads 0x2100:1 in the object dictionary view of a slave network
- **THEN** it shows the value the last scan wrote
