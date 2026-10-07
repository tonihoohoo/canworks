## ADDED Requirements

### Requirement: Send raw frames
The channel SHALL offer `send_frame` to send one CAN frame, or a cyclic job, on the request's network: a standard (11-bit) or extended (29-bit) identifier, a data frame with 0-8 data bytes or a remote frame with a DLC. A single frame SHALL be written once and answered with `sent`. A request with `period_ms` (10-60000) SHALL start a cyclic job that sends the frame at that period and SHALL be answered with a job number; the job SHALL end after `count` frames when given, on `send_frame_stop`, when its client disconnects, when a write fails, or after 10 minutes. The plugin SHALL send from the diagnostics side, never delaying the PLC scan, PDO exchange or supervision. On a simulated network the frame SHALL go onto the simulated bus. Frames sent this way SHALL be received by the plugin's own master or slave like any frame on the bus, and SHALL appear in traces marked Tx. Every single frame, and each cyclic job's start and end with its count, SHALL be logged with the client's address.

#### Scenario: One frame to an unconfigured device
- **WHEN** `allow_changes` is true, no node is OPERATIONAL, and a client sends identifier 0x60A with data `40 18 10 01 00 00 00 00`
- **THEN** the frame is sent once, the answer has `sent`, a running trace shows it as Tx followed by the device's answer on 0x58A, and the runtime log names the client's address

#### Scenario: Cyclic frame stops with its client
- **WHEN** a client starts a cyclic job with period 100 ms and then disconnects
- **THEN** the plugin stops sending that frame and logs how many were sent

#### Scenario: Cyclic frame with a count
- **WHEN** a client starts a cyclic job with period 50 ms and count 20
- **THEN** exactly 20 frames are sent and the job ends

#### Scenario: Period too short
- **WHEN** a client asks for a period of 2 ms
- **THEN** the request is refused naming the allowed range

### Requirement: Guards on raw frames
`send_frame` SHALL be refused with "changes not allowed" unless the config has `allow_changes: true`. With it, the request SHALL be refused unless it carries `force: true` when the identifier is in the running network's COB-ID map (NMT, SYNC, TIME, the EMCY, PDO, SDO and heartbeat COB-IDs of the configured nodes and of the master or the plugin's own slave, LSS), or when any configured node of the network, or the plugin's own slave, is OPERATIONAL; the refusal SHALL name the reason. Single frames SHALL be limited to 50 per second per client and cyclic jobs to 8 per network; requests over a limit SHALL be refused with "rate limit" or "too many jobs". `send_frame_stop` SHALL stop one of the client's own jobs, or all of them without a job number, and answer each job's sent count and why it ended. `status` SHALL list the network's cyclic jobs.

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

### Requirement: Bit rate detection
The channel SHALL offer `detect_bitrate` to find the bit rate of the traffic on a network's bus. The plugin SHALL end the network's CANopen session as on an adapter loss, then for each requested rate (default 1000, 800, 500, 250, 125, 50, 20 and 10 kbit/s), for `rounds` rounds (1-20, default 1), set the interface to that rate in listen-only mode and count, for `per_rate_ms` (100-10000, default 1000), the valid frames, the error frames and the distinct identifiers it receives. It SHALL NOT transmit or acknowledge any frame during the sweep. Afterwards it SHALL set the configured bit rate without listen-only and start a new CANopen session. `detect_bitrate` SHALL answer at once with the sweep's progress and `detect_bitrate_status` SHALL return progress and, when finished, the per-rate counts and a verdict: `detected` with the bit rate when exactly one rate received valid frames with error frames no more than 1 % of them, `ambiguous` with the candidates otherwise when frames were received, `silent` when no frame was received at any rate, or `failed` with the reason; with `detected` it SHALL say whether the rate equals the configured one. One sweep SHALL run per network at a time; other networks SHALL keep running. While a sweep runs, other requests on that network except `status`, `detect_bitrate_status` and trace requests SHALL answer "no bus".

#### Scenario: Wrong configured rate
- **WHEN** `adapter.bitrate` is 500000, the only device sends heartbeats at 250 kbit/s, and a client runs `detect_bitrate`
- **THEN** the result is `detected` 250 kbit/s with `matches_config` false, the 250 kbit/s row lists the device's heartbeat identifier, and afterwards the interface runs at 500 kbit/s again with a new CANopen session

#### Scenario: Silent bus
- **WHEN** the devices on the bus send nothing during the sweep
- **THEN** the result is `silent` and says that a device powered on or reset during the sweep sends a boot-up message that is enough

#### Scenario: Nothing is sent
- **WHEN** a sweep runs while a second analyser records the bus
- **THEN** the analyser sees no frame and no error frame from the PLC's adapter until the sweep ends

### Requirement: Guards on bit rate detection
`detect_bitrate` SHALL be refused with "changes not allowed" unless the config has `allow_changes: true`, and without `force: true` while any configured node of the network, or the plugin's own slave, is OPERATIONAL. It SHALL be refused on a vcan interface and on a simulated network ("no bit rate on a virtual bus"), on a `socketcan` adapter with `configure_link: false`, and with "no bus" when the interface is missing. When the adapter's driver does not support listen-only mode, the sweep SHALL stop before listening, restore the configured bit rate and end with `failed` naming that. A second `detect_bitrate` on a network while one runs SHALL return the running sweep's progress.

#### Scenario: Running machine
- **WHEN** node 5 is OPERATIONAL and a client asks for a sweep without `force`
- **THEN** the request is refused saying CANopen on that network would stop and force is needed

#### Scenario: vcan
- **WHEN** the network runs on vcan0 and a client asks for a sweep
- **THEN** the request is refused with "no bit rate on a virtual bus" and the session goes on

#### Scenario: Link left to the system
- **WHEN** the adapter has `configure_link: false`
- **THEN** the request is refused naming `configure_link`

### Requirement: Raw frame and bit rate commands in the command-line client
`openplc-canopen-diag send ID [DATA]` SHALL send one frame, with `--ext`, `--rtr` with `--dlc N`, and `--force`; with `--period-ms` it SHALL start a cyclic job, keep running until `--count` frames, `--duration` seconds or Ctrl-C, and stop the job on exit. `openplc-canopen-diag send-stop [JOB]` SHALL stop jobs of its own connection only and is meant for scripts that keep a connection. `openplc-canopen-diag detect-bitrate` SHALL run a sweep with `--rates`, `--per-rate-ms`, `--rounds` and `--force`, print progress and a table per rate, and exit 0 only on `detected`. Each command SHALL take `--network` as the other commands do. A plugin that answers `unknown op` SHALL be reported as too old for the command.

#### Scenario: Send from the terminal
- **WHEN** `openplc-canopen-diag --runtime plc.local send 0x60A "40 18 10 01 00 00 00 00"` runs with `allow_changes` true and nothing OPERATIONAL
- **THEN** it prints that the frame was sent and exits 0

#### Scenario: Detect from the terminal
- **WHEN** `openplc-canopen-diag --runtime plc.local detect-bitrate --rates 125,250,500` runs on a bus at 250 kbit/s
- **THEN** it prints one row per rate with frame and error counts, then `250 kbit/s`, and exits 0

#### Scenario: Older plugin
- **WHEN** the runtime's plugin predates these ops
- **THEN** the command exits 1 saying the runtime's plugin is too old for it
