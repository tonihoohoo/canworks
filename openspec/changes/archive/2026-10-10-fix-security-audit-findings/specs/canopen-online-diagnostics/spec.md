## MODIFIED Requirements

### Requirement: Manual SDO write
With `allow_changes`, an authenticated client SHALL be able to write raw bytes (1 to 4096) to any index and subindex of any node ID from 1 to 127 other than the master's own, with the same timeout rules, transfer ordering and answers as manual reads. A write to a configured node that is OPERATIONAL SHALL be refused unless the request carries `force: true`, with a reason saying the node is running. A write SHALL be logged before it is sent, saying when it was forced. The plugin SHALL NOT remember a manual write: an owned SDO variable or a later boot SHALL write its own value again as usual.

#### Scenario: Change a parameter by hand
- **WHEN** `allow_changes` is true, node 3 is PRE-OPERATIONAL and a client writes `1E 00` to 0x6110 subindex 1 of node 3
- **THEN** the plugin logs the write with the peer address, sends it, and answers success

#### Scenario: Write to a running node
- **WHEN** node 3 is OPERATIONAL and a client writes 0x6110 subindex 1 without `force`
- **THEN** the request is refused saying node 3 is OPERATIONAL and force is needed, and nothing is sent

#### Scenario: Forced write to a running node
- **WHEN** the same request carries `force: true`
- **THEN** the write is sent and the log line says it was forced

#### Scenario: Owned variable wins after reboot
- **WHEN** node 3 has an owned write SDO variable for 0x6110 subindex 1 and a client writes a different value by hand, and node 3 then reboots
- **THEN** after the boot the master writes the program's value again

### Requirement: Manual NMT commands
With `allow_changes`, an authenticated client SHALL be able to send START, STOP, ENTER PRE-OPERATIONAL, RESET NODE or RESET COMMUNICATION to one configured node. Any command other than START to a node that is OPERATIONAL SHALL be refused unless the request carries `force: true`. STOP and ENTER PRE-OPERATIONAL SHALL hold the node in that state exactly as the program's NMT command byte values 2 and 128 do ("operator hold"). START SHALL release an operator hold or a program hold and start the node; RESET NODE and RESET COMMUNICATION SHALL release any hold and act as the byte values 129 and 130 do. The newest command SHALL win: a later change of the node's NMT command byte SHALL replace an operator hold, and an operator command SHALL replace a program hold until the byte changes again. Commands to node IDs not in the configuration SHALL be refused.

#### Scenario: Hold a node for maintenance
- **WHEN** node 5 is OPERATIONAL and a client sends STOP to node 5 with `force: true`
- **THEN** node 5 goes to STOPPED, its status bit reads FALSE, the master does not reboot it, and the status answer shows an operator hold STOPPED

#### Scenario: Stop without force
- **WHEN** node 5 is OPERATIONAL and a client sends STOP without `force`
- **THEN** the request is refused saying node 5 is OPERATIONAL and force is needed, and nothing is sent

#### Scenario: Program changes its byte afterwards
- **WHEN** node 5 is under an operator hold STOPPED and the program changes node 5's NMT command byte from 0 to 1
- **THEN** the operator hold ends and the master starts node 5

#### Scenario: Release
- **WHEN** node 5 is under an operator hold and a client sends START
- **THEN** the master starts node 5 and PDO exchange resumes

#### Scenario: Unconfigured node
- **WHEN** a client sends RESET NODE to node 40, which is not in the configuration
- **THEN** the request is refused and nothing is sent

## ADDED Requirements

### Requirement: Request limits before and after login
Before a connection has logged in, including while its address waits after a failed login, the plugin SHALL hold at most 16 KB of request data for it and SHALL close it when a line grows past that; while an address waits after a failed login, the plugin SHALL NOT read more from its connections. A connection that has not logged in within 5 seconds SHALL be closed. After login, a request line SHALL be limited to 16 KB, except a `put_config` line on a host that takes configs, which keeps its larger limit. Finding the end of a line SHALL take time in proportion to the data received.

#### Scenario: Data during the login backoff
- **WHEN** a login from an address fails and a second connection from that address sends 64 KB without a newline during the wait
- **THEN** that connection is closed with "request line too long" and the plugin's memory does not grow with the data

#### Scenario: Large request that is not a config
- **WHEN** a logged-in client sends a 1 MB `status` line
- **THEN** the request is refused with "request line too long" and the connection closed

### Requirement: Replay rate across loops
A looping replay SHALL be checked as one repeating sequence, counting the gap from its last frame back to its first, and refused when any one-second window of the repeated sequence holds more than 1000 frames. While a replay runs, the plugin SHALL never send more than 1000 of its frames within any one second.

#### Scenario: Short dense loop
- **WHEN** a client asks to replay 10 frames 1 ms apart with `loop`
- **THEN** the request is refused naming the 1000 frames per second limit, and nothing is sent

### Requirement: Guard map covers every identifier the network uses
The guard map for `send_frame` and `replay` SHALL hold every identifier the running network uses as configured, including 29-bit COB-IDs, the PDO COB-IDs of the plugin's own slave, and the SDO channels of the master.

#### Scenario: 29-bit PDO
- **WHEN** node 5's TPDO 1 is configured with a 29-bit COB-ID 0x18FF0005 and a client sends that extended identifier without `force`
- **THEN** the request is refused naming TPDO 1 of node 5

### Requirement: Scan on a running network
A network scan SHALL be refused while any configured node of the network is OPERATIONAL unless the request carries `force: true`. It SHALL still not need `allow_changes`.

#### Scenario: Scan during production
- **WHEN** node 5 is OPERATIONAL and a client starts a scan without `force`
- **THEN** the request is refused saying nodes are running and force is needed

### Requirement: Bit rate detection ends in bounded time
A bit rate sweep SHALL be refused when its listening time per rate times the number of rates and rounds exceeds 120 s. `detect_bitrate_stop` SHALL end a running sweep after its current rate. When a sweep ends for any reason, the plugin SHALL set the configured bit rate and bring the link up, retrying once, and SHALL log when either fails.

#### Scenario: Stop a sweep
- **WHEN** a sweep runs and a client with `allow_changes` sends `detect_bitrate_stop`
- **THEN** the sweep ends after the current rate, the configured bit rate is set again, and the network's session starts again

### Requirement: Log and memory housekeeping
Logging of single `send_frame` requests SHALL be at most one line per second per client, with a count of the frames not logged one by one. Records of failed logins SHALL be dropped 10 minutes after their last use.

#### Scenario: Many single frames
- **WHEN** a client sends 50 single frames within one second
- **THEN** the log has at most two lines for them, the last giving the count
