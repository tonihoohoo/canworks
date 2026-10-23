## MODIFIED Requirements

### Requirement: Diagnostics channel is opt-in
The `master` object (or the top-level `diagnostics` of a version 2 file) MAY give a `diagnostics` object with `token_verifier` (required: a SCRAM-SHA-256 verifier of the access token in the form `SCRAM-SHA-256$<iterations>:<salt>$<StoredKey>:<ServerKey>`, base64 fields, iterations 4096 to 1000000, salt at least 16 bytes), `port` (1024 to 65535, default 7531), `bind` (an IPv4 address, default `0.0.0.0`) and `allow_changes` (boolean, default false). Without `diagnostics` the bridge SHALL open no network listener. With it, the bridge SHALL listen on `bind`:`port` from the start of the CANopen session until the PLC stops, and SHALL log the address and whether changes are allowed. A listener that cannot be opened (port in use, address not on the host) SHALL be logged as a warning and SHALL NOT stop CANopen or the PLC; the bridge SHALL retry opening it every 10 seconds. An invalid `diagnostics` object SHALL reject the configuration, naming the field. The former `token_sha256` SHALL reject the configuration with a message saying that the channel is encrypted now and the token must be set again (the configurator's Online access, or `canworks-diag hash-token`).

#### Scenario: Not configured
- **WHEN** `canworks.json` has no `master.diagnostics`
- **THEN** the bridge opens no TCP port

#### Scenario: Enabled read-only
- **WHEN** `master.diagnostics` is `{"token_verifier": "SCRAM-SHA-256$4096:..."}`
- **THEN** the bridge logs that diagnostics listen on `0.0.0.0:7531` read-only, and a client with the token can read status and scan

#### Scenario: Port in use
- **WHEN** another process already listens on port 7531
- **THEN** the bridge logs a warning naming the port, CANopen runs normally, and the listener opens once the port is free

#### Scenario: Bad token hash
- **WHEN** `master.diagnostics` still has the former `token_sha256`
- **THEN** the bridge rejects the configuration, names `master.diagnostics.token_sha256` and says to set the token again for the encrypted channel

#### Scenario: Bad verifier
- **WHEN** `token_verifier` does not start with `SCRAM-SHA-256$` or its salt is shorter than 16 bytes
- **THEN** the bridge rejects the configuration and names `master.diagnostics.token_verifier`

### Requirement: Access control
Every connection SHALL be TLS 1.2 or newer, with a key and self-signed certificate the bridge generates in memory each time it opens the listener and never writes to disk. Inside TLS the client SHALL log in with SCRAM-SHA-256 bound to the server certificate (`tls-server-end-point`): the bridge SHALL accept a login only when the client's proof matches the verifier and the certificate this connection uses, compared in constant time, and SHALL then return its server signature with the hello information. A failed login SHALL close the connection without answering any request. The token itself SHALL never be sent. Failed attempts SHALL be logged at most once per minute per peer address, and a peer address whose login failed SHALL wait at least 1 second before its next login is answered. The bridge SHALL serve at most 4 connections at a time and refuse more. Without `allow_changes`, SDO writes and NMT commands SHALL be refused with the reason "changes not allowed" and nothing SHALL be sent on the bus. Every SDO write and NMT command carried out SHALL be logged with the peer address, the node and the object or command.

#### Scenario: Wrong token
- **WHEN** a client logs in with a token that does not match `token_verifier`
- **THEN** the connection is closed, no status is returned, and one warning naming the peer address is logged

#### Scenario: Token never on the wire
- **WHEN** a client logs in and the whole exchange is captured, including the TLS keys of that connection
- **THEN** the capture does not contain the token, and replaying the client's login on a new connection fails

#### Scenario: Machine in the middle
- **WHEN** a proxy terminates the client's TLS with its own certificate and opens its own TLS connection to the bridge, forwarding the login
- **THEN** the bridge rejects the login and the client reports that the runtime could not prove it knows the token, and no request is served

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
- **THEN** PDO exchange, heartbeat supervision and the PLC scan continue unchanged, and the bridge closes that connection once its send buffer is full

#### Scenario: Cable unplugged
- **WHEN** the CAN interface goes down while a client is connected
- **THEN** status answers show bus state 0 and all nodes at state 0, and an SDO read request is refused with "no bus"

### Requirement: Live status
A status request SHALL return, as of no more than 100 ms before the answer:
- the bridge version, the time since the CANopen session started, and the SHA-256 of the loaded `canworks.json` file;
- the master node ID and NMT state code, and the bus state, TX and RX error counters and bus-off count as the bus diagnostics define them (whether or not their PLC locations are configured);
- the SYNC source (`none` or `timer`) and the SYNC statistics: SYNCs sent, last, shortest and longest interval in microseconds, skipped frames and late PDOs;
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
- **WHEN** the configurator holds a `canworks.json` whose SHA-256 differs from the one in the status answer
- **THEN** the configurator can tell that the bridge runs a different configuration

#### Scenario: SYNC jitter visible
- **WHEN** `sync_period_us` is 10000 and the online view is open
- **THEN** the SYNC line shows source "timer", the last interval near 10000 µs, and the shortest and longest intervals seen since start

#### Scenario: No SYNC
- **WHEN** the master produces no SYNC
- **THEN** the status answer gives SYNC source `none` with zero counts

#### Scenario: Timed-out PDO without a location
- **WHEN** node 23's TPDO 1 has `"timeout_ms": 500` and no `timeout_location`, and it has stopped arriving
- **THEN** the status answer shows node 23's TPDO 1 as timed out with a count of at least 1, and `canworks-diag status` prints a line for node 23's TPDO 1 saying it is timed out

### Requirement: Emergency history
For each configured node the bridge SHALL keep the last 16 emergency messages received since the CANopen session started, each with its wall-clock time, error code, error register and the five manufacturer bytes, and SHALL return them on request, newest first. The history SHALL include messages whose log lines were suppressed by log throttling, up to the 16 kept. A boot-up message SHALL NOT clear the history.

#### Scenario: History after a sensor break
- **WHEN** node 3 sends EMCY 0x5030 three times and then 0x0000
- **THEN** the history for node 3 lists 0x0000 first and the three 0x5030 messages after it, each with its time

#### Scenario: Burst beyond the history size
- **WHEN** node 3 sends 40 emergency messages in one second
- **THEN** the history holds the newest 16 of them

### Requirement: Manual SDO write
With `allow_changes`, an authenticated client SHALL be able to write raw bytes (1 to 4096) to any index and subindex of any node ID from 1 to 127 other than the master's own, with the same timeout rules, transfer ordering and answers as manual reads. A write to a configured node that is OPERATIONAL SHALL be refused unless the request carries `force: true`, with a reason saying the node is running. A write SHALL be logged before it is sent, saying when it was forced. The bridge SHALL NOT remember a manual write: an owned SDO variable or a later boot SHALL write its own value again as usual.

#### Scenario: Change a parameter by hand
- **WHEN** `allow_changes` is true, node 3 is PRE-OPERATIONAL and a client writes `1E 00` to 0x6110 subindex 1 of node 3
- **THEN** the bridge logs the write with the peer address, sends it, and answers success

#### Scenario: Write to a running node
- **WHEN** node 3 is OPERATIONAL and a client writes 0x6110 subindex 1 without `force`
- **THEN** the request is refused saying node 3 is OPERATIONAL and force is needed, and nothing is sent

#### Scenario: Forced write to a running node
- **WHEN** the same request carries `force: true`
- **THEN** the write is sent and the log line says it was forced

#### Scenario: Owned variable wins after reboot
- **WHEN** node 3 has an owned write SDO variable for 0x6110 subindex 1 and a client writes a different value by hand, and node 3 then reboots
- **THEN** after the boot the master writes the program's value again

### Requirement: Frame capture
While at least one authenticated client has an active trace, the bridge SHALL record every CAN frame on the configured interface: frames from other devices and frames the master sends, each with its receive time (microseconds, UTC), identifier, standard or extended format, RTR flag, data and direction (Tx for frames sent from the PLC host, Rx otherwise). Capture SHALL NOT delay the PLC scan, PDO exchange, SDO transfers or supervision. Frames SHALL be kept in RAM only, never written to storage on the PLC. With no active trace the bridge SHALL NOT capture.

#### Scenario: Both directions recorded
- **WHEN** a client starts a trace while the master sends SYNC and RPDOs and node 23 answers with TPDOs and heartbeats
- **THEN** the fetched frames contain the SYNC and RPDO frames marked Tx and the TPDO and heartbeat frames marked Rx, in time order

#### Scenario: No trace, no capture
- **WHEN** no client has started a trace, or every trace client has stopped or disconnected
- **THEN** the bridge holds no capture socket open and records nothing

#### Scenario: PLC timing unchanged
- **WHEN** a trace runs at full bus load and the client fetches slowly
- **THEN** PDO cycles, heartbeat supervision and the PLC scan keep their timing, and the client is told how many frames it lost

### Requirement: Trace operations
The channel SHALL offer `trace_start`, `trace_fetch` and `trace_stop` to any authenticated client, without `allow_changes`. `trace_start` MAY give a list of identifier/mask filters and whether to include error frames, and SHALL return the sequence number to fetch after. `trace_fetch` with a sequence number SHALL return the frames recorded after it, in order, at most a requested maximum (default 2000, at most 4000) per answer, with the number of frames the client lost because the bridge's buffer wrapped and the number the operating system dropped. The bridge SHALL keep at least 65536 frames for clients to fetch. A trace SHALL end on `trace_stop`, on disconnect, or after 10 s without a fetch. Without a CANopen session, `trace_start` SHALL be refused with "no bus".

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
- **THEN** the bridge ends that trace after 10 s and stops capturing if no other trace is active

### Requirement: Error frames
When a client asks for error frames, the bridge SHALL also record the CAN error frames the interface's driver reports (bus-off, controller error-warning and error-passive, protocol errors, missing acknowledgement), marked as error frames with their error class and data.

#### Scenario: Error frames requested
- **WHEN** a client starts a trace with error frames and the only device is disconnected, so the master's frames get no acknowledgement
- **THEN** the trace contains error frames for the missing acknowledgement as far as the driver reports them

### Requirement: Simulator operations
When the bridge simulates at least one device, the diagnostics channel SHALL offer the simulator's live control for those devices as `sim_` operations: `sim_status`, `sim_get` and `sim_scenario_list` with the token alone, and the operations that change values, sources, faults or scenarios only with `allow_changes: true`. When the bridge simulates no device every `sim_` operation SHALL answer `nothing simulated`, and an operation naming a node that is not simulated SHALL answer `node N is not simulated`. The `status` answer SHALL carry `simulated_network` and, per node, `simulated`.

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
Bus trace SHALL work on a simulated network with the same operations, filters and records as on a SocketCAN interface, with time stamps from the host's clock when the frame is delivered and the interface reported as `simulated`. On a real network the trace SHALL also record the frames of devices the bridge simulates there.

#### Scenario: Trace a simulated network
- **WHEN** a user starts a trace on a runtime with a simulated network
- **THEN** the trace records the SYNC, PDO, heartbeat and SDO frames of the simulated network, and the trace header says the interface is simulated

#### Scenario: Trace a mixed network
- **WHEN** node 5 is simulated on `can0` next to real node 23 and a user traces `can0`
- **THEN** the trace has the frames of both nodes

### Requirement: Simulator commands in the command-line client
`canworks-diag` SHALL have `sim` subcommands (`status`, `get`, `set`, `override`, `release`, `source`, `fault`, `clear`, `scenario start|stop|list`) that talk to the bridge's simulated devices with `--runtime` or to a standalone simulator with `--sim HOST[:PORT]`, with the same arguments, fault kind names and output as `canworks-canopen-sim`'s own subcommands.

#### Scenario: Fault from the PC
- **WHEN** a user runs `canworks-diag sim fault 5 emcy 0x5000 --register 1 --runtime plc.local` against a runtime that simulates node 5, with `allow_changes`
- **THEN** simulated node 5 sends EMCY 0x5000 and the online view shows it in node 5's EMCY history

#### Scenario: NMT state fault
- **WHEN** a user runs `canworks-diag sim fault 5 nmt-state stopped --sim localhost`
- **THEN** simulated node 5 goes to STOPPED, as with `canworks-canopen-sim fault 5 nmt-state stopped`, and `canworks-diag sim fault 5 nmt stopped` is refused as an unknown fault kind

### Requirement: One channel for all networks
The bridge SHALL serve all networks over one diagnostics channel, with one port, one token, one `allow_changes` setting and one client limit. The hello answer SHALL list the networks in config order, each with its name (empty for a version 1 config), interface, bit rate and master node ID, and SHALL keep `master_node_id` as the first network's.

#### Scenario: Hello with two networks
- **WHEN** a client says hello to a bridge running networks `io` on `can0` and `drives` on `can1`
- **THEN** the answer has protocol 1 and a `networks` list with both, in that order, each with its interface, bit rate and master node ID

### Requirement: Network selector on requests
Every request other than `hello` SHALL accept a `network` field naming a network. With one network it MAY be left out. With several, a request without it SHALL be refused with `network required` and the network names, and an unknown name with `unknown network` and the names. The request SHALL act on the named network only.

#### Scenario: SDO read on the second network
- **WHEN** a client sends `sdo_read` with `network: "drives"`, node 2, 0x1018:1
- **THEN** the read goes to node 2 on `can1`, not to node 2 on `can0`

#### Scenario: Old client and one network
- **WHEN** a client that never sends `network` talks to a bridge with a version 1 config
- **THEN** every request works as before this change

#### Scenario: Missing selector with two networks
- **WHEN** a client sends `status` without `network` to a bridge with two networks
- **THEN** the answer is an error naming `io` and `drives`

### Requirement: Network option in the command-line client
`canworks-diag` SHALL take `--network NAME` for every command that talks to the bridge. Without it, a command against several networks SHALL fail listing the names, except `status`, which SHALL print every network one after another.

#### Scenario: Status of all networks
- **WHEN** the user runs `canworks-diag --runtime plc.local status` against two networks
- **THEN** it prints the status of `io` and then of `drives`, each headed by its name and interface

#### Scenario: SDO read needs a network
- **WHEN** the user runs `sdo-read 2 0x1018 1` without `--network` against two networks
- **THEN** it exits with status 1 saying `--network` is needed and naming `io` and `drives`

### Requirement: Encrypted clients
`canworks-diag`, the configurator and `canworks-canopen-sim` SHALL connect with TLS, log in with SCRAM-SHA-256 bound to the certificate they received, and check the bridge's server signature before using any answer; a wrong signature SHALL drop the connection with "the runtime could not prove it knows this project's token". They SHALL NOT validate the certificate chain or pin a certificate. They SHALL NOT fall back to an unencrypted connection.

#### Scenario: Wrong signature
- **WHEN** a machine in the middle answers the client's login with a signature made without the verifier
- **THEN** the client drops the connection saying the runtime could not prove it knows this project's token, and sends no request

### Requirement: Send raw frames
The channel SHALL offer `send_frame` to send one CAN frame, or a cyclic job, on the request's network: a standard (11-bit) or extended (29-bit) identifier given as `can_id` (the request's own `id` stays free for matching its answer), a data frame with 0-8 data bytes or a remote frame with a DLC. A single frame SHALL be written once and answered with `sent`. A request with `period_ms` (10-60000) SHALL start a cyclic job that sends the frame at that period and SHALL be answered with a job number; the job SHALL end after `count` frames when given, on `send_frame_stop`, when its client disconnects, when a write fails, or after 10 minutes. The bridge SHALL send from the diagnostics side, never delaying the PLC scan, PDO exchange or supervision. On a simulated network the frame SHALL go onto the simulated bus. Frames sent this way SHALL be received by the bridge's own master or slave like any frame on the bus, and SHALL appear in traces marked Tx. Every single frame, and each cyclic job's start and end with its count, SHALL be logged with the client's address.

#### Scenario: One frame to an unconfigured device
- **WHEN** `allow_changes` is true, no node is OPERATIONAL, and a client sends identifier 0x60A with data `40 18 10 01 00 00 00 00`
- **THEN** the frame is sent once, the answer has `sent`, a running trace shows it as Tx followed by the device's answer on 0x58A, and the runtime log names the client's address

#### Scenario: Cyclic frame stops with its client
- **WHEN** a client starts a cyclic job with period 100 ms and then disconnects
- **THEN** the bridge stops sending that frame and logs how many were sent

#### Scenario: Cyclic frame with a count
- **WHEN** a client starts a cyclic job with period 50 ms and count 20
- **THEN** exactly 20 frames are sent and the job ends

#### Scenario: Period too short
- **WHEN** a client asks for a period of 2 ms
- **THEN** the request is refused naming the allowed range

### Requirement: Guards on raw frames
`send_frame` SHALL be refused with "changes not allowed" unless the config has `allow_changes: true`. With it, the request SHALL be refused unless it carries `force: true` when the identifier is in the running network's COB-ID map (NMT, SYNC, TIME, the EMCY, PDO, SDO and heartbeat COB-IDs of the configured nodes and of the master or the bridge's own slave, LSS), or when any configured node of the network, or the bridge's own slave, is OPERATIONAL; the refusal SHALL name the reason. Single frames SHALL be limited to 50 per second per client and cyclic jobs to 8 per network; requests over a limit SHALL be refused with "rate limit" or "too many jobs". `send_frame_stop` SHALL stop one of the client's own jobs, or all of them without a job number, and answer each job's sent count and why it ended. `status` SHALL list the network's cyclic jobs.

#### Scenario: Identifier the network uses
- **WHEN** node 5 has RPDO1 on 0x205 and a client sends 0x205 without `force`
- **THEN** the request is refused with "0x205 is RPDO1 of node 5; force needed" and nothing is sent

#### Scenario: Running machine
- **WHEN** node 5 is OPERATIONAL and a client sends 0x60A without `force`
- **THEN** the request is refused saying node 5 is OPERATIONAL and force is needed

#### Scenario: Forced
- **WHEN** the same request carries `force: true`
- **THEN** the frame is sent and the log line says it was forced

#### Scenario: Read-only channel
- **WHEN** `allow_changes` is false and a client sends any frame
- **THEN** the request is refused with "changes not allowed"

#### Scenario: Too fast by hand
- **WHEN** a client sends 60 single frames within one second
- **THEN** the frames over 50 are refused with "rate limit"

### Requirement: Direction of frames on a simulated bus
In a trace of a simulated network, a frame sent by the bridge's master (NMT, SYNC, heartbeat, RPDOs, SDO requests, LSS) or by `send_frame` SHALL be recorded as Tx, and a frame sent by a simulated device as Rx, as on a SocketCAN interface.

#### Scenario: SYNC on a simulated network
- **WHEN** a trace runs on simulated network io, whose master sends SYNC
- **THEN** the SYNC frames are Tx and the "Tx only" filter shows them

### Requirement: Diagnostics channel on the bridge
`canworks-bridge` SHALL serve the diagnostics channel with the same operations, access control and encryption as the bridge. Its hello SHALL name the host as `bridge`. Live status SHALL add a `bridge` part with the state, the outputs-off reason, the connected clients (address, requests, writer or not) and the watchdog time left.

#### Scenario: Status of a bridge
- **WHEN** `canworks-diag status` connects to a bridge with one writer client
- **THEN** it shows the networks as for a bridge, and a bridge line with state running, one client and its address

### Requirement: Config upload to the bridge
The `put_config` operation SHALL carry a config and every file it names as one upload of at most 8 MB (file names relative to the config folder), and SHALL need `allow_changes` and `diagnostics.allow_config_upload`.
- The bridge SHALL check the new config in a staging folder and answer with every problem found.
- On a valid config, it SHALL stop its networks, put the files in place and restart with them.
- If the new config fails at start, it SHALL restore the previous files, restart with them, and report that.

canworks-bridge SHALL refuse `put_config` with a message saying its config comes with the program upload.

#### Scenario: Invalid upload
- **WHEN** a client uploads a config whose node names an EDS that is not in the upload
- **THEN** the answer lists the missing file, and the running networks were never stopped

#### Scenario: Upload not allowed
- **WHEN** `allow_config_upload` is not set and a client sends `put_config`
- **THEN** the request is refused with a message naming the setting

### Requirement: Request limits before and after login
Before a connection has logged in, including while its address waits after a failed login, the bridge SHALL hold at most 16 KB of request data for it and SHALL close it when a line grows past that; while an address waits after a failed login, the bridge SHALL NOT read more from its connections. A connection that has not logged in within 5 seconds SHALL be closed. After login, a request line SHALL be limited to 16 KB, except a `put_config` line on a host that takes configs, which keeps its larger limit. Finding the end of a line SHALL take time in proportion to the data received.

#### Scenario: Data during the login backoff
- **WHEN** a login from an address fails and a second connection from that address sends 64 KB without a newline during the wait
- **THEN** that connection is closed with "request line too long" and the bridge's memory does not grow with the data

#### Scenario: Large request that is not a config
- **WHEN** a logged-in client sends a 1 MB `status` line
- **THEN** the request is refused with "request line too long" and the connection closed

### Requirement: Replay rate across loops
A looping replay SHALL be checked as one repeating sequence, counting the gap from its last frame back to its first, and refused when any one-second window of the repeated sequence holds more than 1000 frames. While a replay runs, the bridge SHALL never send more than 1000 of its frames within any one second.

#### Scenario: Short dense loop
- **WHEN** a client asks to replay 10 frames 1 ms apart with `loop`
- **THEN** the request is refused naming the 1000 frames per second limit, and nothing is sent

### Requirement: Guard map covers every identifier the network uses
The guard map for `send_frame` and `replay` SHALL hold every identifier the running network uses as configured, including 29-bit COB-IDs, the PDO COB-IDs of the bridge's own slave, and the SDO channels of the master.

#### Scenario: 29-bit PDO
- **WHEN** node 5's TPDO 1 is configured with a 29-bit COB-ID 0x18FF0005 and a client sends that extended identifier without `force`
- **THEN** the request is refused naming TPDO 1 of node 5

### Requirement: Device error history
The command-line client and the configurator SHALL read a node's pre-defined error field (0x1003) with the manual SDO read: sub-index 0 for the number of entries, then sub-indices 1 up to that number (at most 254), sub-index 1 being the newest. Each entry SHALL be shown with its sub-index, the error code (the low 16 bits) with its CiA 301 error class in words, and the manufacturer-specific information (the high 16 bits) in hex. An abort 0x06020000 on sub-index 0 SHALL be shown as "no error history (0x1003)"; an abort on an entry SHALL end the list there and show the abort code with its text. Clearing SHALL write the UNSIGNED8 value 0 to sub-index 0 with the manual SDO write, so it SHALL need `allow_changes`, SHALL be refused on an OPERATIONAL node unless the request carries `force: true`, and SHALL be logged by the bridge like every manual write. Both SHALL work against a runtime and on a local adapter.

#### Scenario: Read the error history
- **WHEN** node 5's 0x1003 holds 2 entries, 0x00004210 at sub-index 1 and 0x00125000 at sub-index 2
- **THEN** the history lists 0x4210 "temperature" with information 0x0000 first, then 0x5000 "device hardware" with information 0x0012, and the count 2

#### Scenario: Device without error history
- **WHEN** node 5 aborts the read of 0x1003 sub-index 0 with 0x06020000
- **THEN** the history says node 5 has no error history (0x1003)

#### Scenario: Clear refused read-only
- **WHEN** `allow_changes` is false and a client asks to clear node 5's error history
- **THEN** the request is refused with "changes not allowed" and nothing is sent

#### Scenario: Clear a running node
- **WHEN** `allow_changes` is true, node 5 is OPERATIONAL and a client clears its error history without `force`
- **THEN** the request is refused saying node 5 is OPERATIONAL and force is needed; with `force` the write of 0 to 0x1003 sub-index 0 is sent, logged as forced, and a new read shows count 0

### Requirement: Boot count in the status
The status answer SHALL give, for each configured node, `boots`: how many times the node booted successfully since the bridge started. A reset and boot that both happen between two status requests SHALL still show as a higher count, though the node's state and boot result are the same as before.

#### Scenario: Reset between two status requests
- **WHEN** node 6 is OPERATIONAL with `boots` 1, a client resets it and the master boots it again within half a second
- **THEN** the next status answer shows node 6 OPERATIONAL with `boots` 2

## REMOVED Requirements

### Requirement: Clients against an older plugin
**Reason**: It described the removed OpenPLC plugin; its scenarios change with the plugin gone.
**Migration**: Requirement: Clients against an older bridge version.

### Requirement: Raw frame commands in the command-line client
**Reason**: It described the removed OpenPLC plugin; its scenarios change with the plugin gone.
**Migration**: Requirement: Raw frame commands in the diagnostics client.

## ADDED Requirements

### Requirement: Clients against an older bridge version
Against a bridge that does not complete a TLS handshake, `canworks-diag` and the configurator SHALL stop with a message saying the bridge is too old for encrypted diagnostics and needs an update.

#### Scenario: Client against an older bridge
- **WHEN** a user runs `canworks-diag --runtime plc.local status` against a bridge without TLS
- **THEN** the command exits 1 saying the bridge does not speak encrypted diagnostics and must be updated

### Requirement: Raw frame commands in the diagnostics client
`canworks-diag send ID [DATA]` SHALL send one frame. It SHALL take `--ext`, `--rtr` with `--dlc N`, and `--force`. With `--period-ms` it SHALL start a cyclic job, keep running until `--count` frames, `--duration` seconds or Ctrl-C, and stop the job on exit. `canworks-diag send-stop [JOB]` SHALL stop jobs of its own connection only; it is meant for scripts that keep a connection. Each command SHALL take `--network` as the other commands do. A bridge that answers `unknown op` SHALL be reported as too old for the command. `canworks-diag` SHALL have no `detect-bitrate` command.

#### Scenario: Send from the terminal
- **WHEN** `canworks-diag --runtime plc.local send 0x60A "40 18 10 01 00 00 00 00"` runs with `allow_changes` true and nothing OPERATIONAL
- **THEN** it prints that the frame was sent and exits 0

#### Scenario: Older bridge
- **WHEN** the bridge predates these ops
- **THEN** the command exits 1 saying the bridge is too old for it

#### Scenario: No detect command
- **WHEN** a user runs `canworks-diag --runtime plc.local detect-bitrate`
- **THEN** argument parsing fails with exit status 2 because the command does not exist
