## MODIFIED Requirements

### Requirement: Local adapter backend
The PC tools package SHALL include a local bus backend that opens a CAN adapter on the PC and answers the diagnostics operations `hello`, `status`, `emcy`, `sdo_read`, `sdo_write`, `nmt`, `scan`, `scan_status`, `lss_find`, `lss_find_status`, `lss_inquire`, `lss_set_id`, `lss_set_bitrate`, `trace_start`, `trace_fetch`, `trace_stop`, `send_frame`, `send_frame_stop`, `detect_bitrate` and `detect_bitrate_status`, with the same request fields and result fields as the plugin's diagnostics channel except where this spec says otherwise. Any other operation SHALL answer `not available on a local adapter`. It SHALL need no OpenPLC Runtime, and no Python on the PC beyond what uv installs.

#### Scenario: Read a device with no PLC
- **WHEN** a CANopen device with node ID 5 is the only node on a bus with a USB adapter on the PC, and the user runs `openplc-canopen-diag --adapter slcan:COM5 --bitrate 250 sdo-read 5 0x1018 1 --type UNSIGNED32`
- **THEN** it prints the device's vendor ID, and no runtime is involved

#### Scenario: Simulator op on a local adapter
- **WHEN** `openplc-canopen-diag --adapter socketcan:can0 --bitrate 250 sim status` runs
- **THEN** it exits with status 1 and says that this needs a runtime

## ADDED Requirements

### Requirement: Raw frames on a local adapter
On a local adapter, `send_frame` SHALL send one frame, or start a cyclic job, with the plugin's fields (`can_id`, `ext`, `rtr`, `dlc`, `data`, `period_ms`, `count`, `force`) and answers, through the backend's one transmit path, so the frames appear in a trace marked Tx. It SHALL be refused with "changes not allowed" unless the session allows changes. With changes allowed, it SHALL be refused unless the request carries `force: true` when the identifier is NMT, SYNC, TIME or LSS, or, with a config, the predefined EMCY, PDO, SDO or heartbeat identifier of a configured node, or while another master is detected on the bus, or while a node's last heartbeat within 30 seconds said OPERATIONAL; the refusal SHALL name the reason and end with "force needed". Extended identifiers SHALL never count as used. Single frames SHALL be limited to 50 per second per connection and cyclic jobs to 8 per adapter, with a period of 10-60000 ms; a job SHALL end after its count, on `send_frame_stop`, when its connection closes, when a send fails, or after 10 minutes. `send_frame_stop` SHALL stop the connection's own jobs and report each job's sent count and why it ended, also for a job that ended in the last 60 seconds. `status` SHALL list the adapter's cyclic jobs under `send_jobs`.

#### Scenario: Frame to an unconfigured device
- **WHEN** `openplc-canopen-diag --adapter slcan:COM5 --bitrate 250 --allow-changes send 0x60A "40 18 10 01 00 00 00 00"` runs and no node is OPERATIONAL
- **THEN** the frame is sent once and the command exits 0

#### Scenario: Identifier of a configured node
- **WHEN** `--config` names node 5 and the user sends on 0x205 without `--force`
- **THEN** the request is refused saying that 0x205 is RPDO1 of node 5 and force is needed, and nothing is sent

#### Scenario: Another master
- **WHEN** a SYNC frame from another master was seen within 30 seconds and the user sends 0x60A without `--force`
- **THEN** the request is refused saying that another master is active and force is needed

#### Scenario: Cyclic job with a count
- **WHEN** the user sends 0x60B with `--period-ms 20 --count 4`
- **THEN** exactly 4 frames are sent and the job ends with "count reached"

### Requirement: Bit rate detection on a local adapter
On a local adapter, `detect_bitrate` SHALL answer at once with progress and sweep in the background: for each requested rate (default 1000, 800, 500, 250, 125, 50, 20 and 10 kbit/s) and round (`rounds` 1-20, `per_rate_ms` 100-10000, default 1000) it SHALL open the adapter in listen-only mode and count valid frames, error frames (when the adapter reports them) and the first 16 identifiers, stop early after a round with a `detected` verdict, and then open the adapter again at the connection's bit rate so the connection keeps working. `detect_bitrate_status` SHALL return the progress and, when finished, the per-rate counts and the plugin's verdict (`detected`, `ambiguous`, `silent`, `failed`) computed by the same rules, with `matches_config` against the connection's bit rate. Because listen-only sends nothing, not even an acknowledge, it SHALL need neither allow-changes nor `force`. It SHALL be refused with "busy" when another connection of the same tool uses the adapter. While it runs, other operations except `status` SHALL answer "no bus", and the adapter's cyclic jobs SHALL end. Listen-only SHALL be: slcan opened with `L` instead of `O`, PCAN with its listen-only parameter, and SocketCAN by setting the link to the rate with listen-only on, which needs root or CAP_NET_ADMIN, and setting it back to its bit rate, listen-only off and its up or down state afterwards. Without that permission the request SHALL be refused naming it and the `sudo` command; on a vcan interface it SHALL be refused with "no bit rate on a virtual bus"; on other adapter types, and on a driver that rejects listen-only, with "the adapter's driver has no listen-only mode".

#### Scenario: Unknown bus from the PC
- **WHEN** the only device on the bus sends heartbeats at 250 kbit/s and `openplc-canopen-diag --adapter slcan:COM5 --bitrate 500 detect-bitrate` runs
- **THEN** it prints `250 kbit/s detected`, no frame and no acknowledge came from the PC during the sweep, and the adapter is open at 500 kbit/s again afterwards

#### Scenario: SocketCAN without permission
- **WHEN** a user without CAP_NET_ADMIN runs `detect-bitrate` on `socketcan:can0`
- **THEN** it is refused naming CAP_NET_ADMIN and the `sudo ip link set` command, and the link is unchanged

#### Scenario: Adapter type without listen-only
- **WHEN** `detect-bitrate` runs on `gs_usb:0`
- **THEN** it is refused with "the adapter's driver has no listen-only mode" and the adapter is not opened

#### Scenario: Shared adapter
- **WHEN** two connections of the configurator use the same adapter and one of them sends `detect_bitrate`
- **THEN** the request is refused with "busy" and both connections keep working

### Requirement: Detect in the adapter connection form
The configurator's USB adapter connect box SHALL have "Detect" next to the bit rate. It SHALL close the configurator's own connections to adapters, run a bit rate sweep on the adapter in the form with nothing else open, show the rate being listened to, and on `detected` select that rate in the bit rate field; for `ambiguous`, `silent` and `failed` it SHALL say so and leave the field as it was. On the Scan page with a USB adapter as the target, Detect bit rate SHALL run without Allow changes and without the warning about CANopen stopping.

#### Scenario: Pick the rate before connecting
- **WHEN** the bus runs at 250 kbit/s, the form shows 500 kbit/s and the user presses Detect
- **THEN** the form says `250 kbit/s detected` and the bit rate field shows 250 kbit/s, ready to connect
