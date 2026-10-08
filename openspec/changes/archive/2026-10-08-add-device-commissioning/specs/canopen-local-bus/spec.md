## MODIFIED Requirements

### Requirement: Local adapter backend
The PC tools package SHALL include a local bus backend that opens a CAN adapter on the PC and answers the diagnostics operations `hello`, `status`, `emcy`, `sdo_read`, `sdo_write`, `nmt`, `scan`, `scan_status`, `lss_find`, `lss_find_status`, `lss_inquire`, `lss_set_id`, `lss_set_bitrate`, `trace_start`, `trace_fetch`, `trace_stop`, `send_frame`, `send_frame_stop`, `detect_bitrate`, `detect_bitrate_status`, `pdo_test_start`, `pdo_test_set`, `pdo_test_status`, `pdo_test_stop`, `sync_start` and `sync_stop`, with the same request fields and result fields as the plugin's diagnostics channel except where this spec says otherwise. Any other operation SHALL answer `not available on a local adapter`. It SHALL need no OpenPLC Runtime, and no Python on the PC beyond what uv installs.

#### Scenario: Read a device with no PLC
- **WHEN** a CANopen device with node ID 5 is the only node on a bus with a USB adapter on the PC, and the user runs `openplc-canopen-diag --adapter slcan:COM5 --bitrate 250 sdo-read 5 0x1018 1 --type UNSIGNED32`
- **THEN** it prints the device's vendor ID, and no runtime is involved

#### Scenario: Simulator op on a local adapter
- **WHEN** `openplc-canopen-diag --adapter socketcan:can0 --bitrate 250 sim status` runs
- **THEN** it exits with status 1 and says that this needs a runtime

### Requirement: Guest on the bus
The backend SHALL send nothing on connect and SHALL listen for at least one second before its first transmit. It SHALL never send heartbeat, TIME or broadcast NMT, never start a node on its own, and never send SYNC except while a SYNC producer the user started with `sync_start` runs. All frames it sends SHALL go through one transmit path.

#### Scenario: Connect sends nothing
- **WHEN** the configurator connects to an adapter and the user only watches the online view
- **THEN** a trace on another device shows no frame from the PC

#### Scenario: SYNC only on request
- **WHEN** the user starts a PDO test on node 5 without SYNC
- **THEN** a trace shows no SYNC frame from the PC, and SYNC frames appear only after the user starts SYNC with a period

### Requirement: Bit rate detection on a local adapter
On a local adapter, `detect_bitrate` SHALL answer at once with progress and sweep in the background: for each requested rate (default 1000, 800, 500, 250, 125, 50, 20 and 10 kbit/s) and round (`rounds` 1-20, `per_rate_ms` 100-10000, default 1000) it SHALL open the adapter in listen-only mode and count valid frames, error frames (when the adapter reports them) and the first 16 identifiers, stop early after a round with a `detected` verdict, and then open the adapter again at the connection's bit rate so the connection keeps working. `detect_bitrate_status` SHALL return the progress and, when finished, the per-rate counts and the plugin's verdict (`detected`, `ambiguous`, `silent`, `failed`) computed by the same rules, with `matches_config` against the connection's bit rate; a `silent` verdict SHALL carry the hint that a lone device needs the lone-device sweep or a second device that acknowledges. Because listen-only sends nothing, not even an acknowledge, it SHALL need neither allow-changes nor `force`. Rates the adapter type cannot be set to (on slcan, any but 10, 20, 50, 100, 125, 250, 500, 750 and 1000 kbit/s) SHALL NOT be tried; the result SHALL list only the rates listened at and name the left-out ones in `skipped_kbit`, and a sweep with no rate left SHALL be refused naming them. It SHALL be refused with "busy" when another connection of the same tool uses the adapter. While it runs, other operations except `status` SHALL answer "no bus", and the adapter's cyclic jobs SHALL end. Listen-only SHALL be: on slcan, silent mode (`m1`, then `O`) when the firmware answers `m1` with CR, the channel opened with `L` instead of `O` when it refuses `m1` with an error (BEL), with `m0` sent when the channel is closed after silent mode and before a normal `O`; when the firmware leaves `m1` unanswered it cannot confirm listen-only, and the sweep SHALL be refused with a reason ending in "disturb_bus needed" unless the request has `disturb_bus: true`, which opens it with `m1` then `O`; PCAN with its listen-only parameter, and SocketCAN by setting the link to the rate with listen-only on, which needs root or CAP_NET_ADMIN, and setting it back to its bit rate, listen-only off and its up or down state afterwards. Without that permission the request SHALL be refused naming it and the `sudo` command; on a vcan interface it SHALL be refused with "no bit rate on a virtual bus"; on other adapter types, and on a driver that rejects listen-only, with "the adapter's driver has no listen-only mode".

#### Scenario: Unknown bus from the PC
- **WHEN** a device sends heartbeats at 250 kbit/s, a second device on the bus acknowledges its frames, and `openplc-canopen-diag --adapter slcan:COM5 --bitrate 500 detect-bitrate` runs
- **THEN** it prints `250 kbit/s detected`, no frame and no acknowledge came from the PC during the sweep, and the adapter is open at 500 kbit/s again afterwards

#### Scenario: Lone device without lone-device mode
- **WHEN** the only device on the bus sends heartbeats at 250 kbit/s and `detect-bitrate` runs without `--lone-device`
- **THEN** it prints `silent` with the hint that a lone device needs `--lone-device` or a second device that acknowledges

#### Scenario: SocketCAN without permission
- **WHEN** a user without CAP_NET_ADMIN runs `detect-bitrate` on `socketcan:can0`
- **THEN** it is refused naming CAP_NET_ADMIN and the `sudo ip link set` command, and the link is unchanged

#### Scenario: Adapter type without listen-only
- **WHEN** `detect-bitrate` runs on `gs_usb:0`
- **THEN** it is refused with "the adapter's driver has no listen-only mode" and the adapter is not opened

#### Scenario: Shared adapter
- **WHEN** two connections of the configurator use the same adapter and one of them sends `detect_bitrate`
- **THEN** the request is refused with "busy" and both connections keep working

## ADDED Requirements

### Requirement: Lone-device bit rate sweep
On a local adapter, `detect_bitrate` with `lone_device: true` (CLI `detect-bitrate --lone-device`) SHALL open the adapter in normal mode at each rate, so that it acknowledges frames, and count valid frames, error frames and identifiers as the listen-only sweep does, with the same verdict rules and early stop. With `probe` (`"lss"`, or `{"sdo": NODE}`; CLI `--probe lss` or `--probe sdo:NODE`) it SHALL send, when no valid frame came in the first half of the rate's listening time, one probe at that rate: for `lss`, LSS switch state global to configuration, inquire node ID, and switch state global back to waiting; for `sdo`, an SDO upload request of 0x1000 subindex 0 to the node. The sweep SHALL need allow-changes; it SHALL be refused, sending nothing, while another master is detected or when frames from more than one node ID were heard in the last 30 seconds; and when the detected rate shows more than one node ID, the result SHALL warn that the bus is not a lone device. The adapter SHALL be opened again at the connection's bit rate afterwards. On a runtime, `lone_device` SHALL be refused with "only on a USB adapter".

#### Scenario: Lone device on the bench
- **WHEN** the only device on the bus runs at 125 kbit/s with heartbeats and `openplc-canopen-diag --adapter slcan:COM5 --bitrate 250 --allow-changes detect-bitrate --lone-device` runs
- **THEN** it prints `125 kbit/s detected` and the adapter is open at 250 kbit/s again afterwards

#### Scenario: Quiet device without node ID
- **WHEN** the only device has no node ID, sends nothing, runs at 500 kbit/s and the sweep runs with `--probe lss`
- **THEN** the device's LSS answer at 500 kbit/s gives `500 kbit/s detected` and the device is back in LSS waiting state

#### Scenario: Not a lone device
- **WHEN** the connection heard heartbeats of nodes 5 and 7 in the last 30 seconds and a lone-device sweep is requested
- **THEN** it is refused saying more than one node is on the bus, and nothing is sent

### Requirement: PDO test on a local adapter
On a local adapter, with allow-changes, `pdo_test_start` SHALL take a node and its PDO layout (TPDOs and RPDOs with COB-ID, transmission type, event timer and entries with index, subindex, bit length, type and name); the CLI and configurator SHALL build the layout from `--config` for a configured node or by reading the device's PDO communication and mapping objects over SDO, with names and types from the EDS, keeping only PDOs whose COB-ID has bit 31 clear. `pdo_test_status` SHALL return per TPDO the last reception time, count, the measured period and the decoded values, and per RPDO the values in force and the sent count. `pdo_test_set` SHALL set RPDO entry values by name or index and subindex; an event-driven RPDO (transmission type 254 or 255) SHALL be sent on each set and then every `repeat_ms` when given, and a synchronous RPDO (0-240) after each SYNC the PC sends. `sync_start` SHALL send SYNC every `period_ms` (1-10000) with an optional counter (2-240), on the COB-ID from the device's 0x1005 when read, else 0x080, and `sync_stop` SHALL stop it. These operations SHALL be refused while another master is detected unless the request has `force: true`, and SHALL stop, saying why, when another master appears, on `pdo_test_stop` or `sync_stop`, and when the connection closes. All frames SHALL go through the single transmit path. One PDO test per node and one SYNC producer per adapter SHALL run at a time.

#### Scenario: Try a digital output module
- **WHEN** node 5's RPDO1 maps 0x6200:01 (UNSIGNED8), the user starts node 5, starts a PDO test and runs `openplc-canopen-diag --adapter slcan:COM5 --bitrate 250 --allow-changes pdo-test 5 --set 0x6200:01=0x0F`
- **THEN** one frame 0x205 with data `0F` is sent and the trace shows it as Tx

#### Scenario: Read inputs with SYNC
- **WHEN** node 5's TPDO1 has transmission type 1, the PDO test runs with `--sync 100`
- **THEN** SYNC is sent every 100 ms, and `pdo_test_status` shows TPDO1 with a period near 100 ms and its decoded values

#### Scenario: Another master
- **WHEN** another master's NMT command is heard while a PDO test sends SYNC
- **THEN** SYNC and RPDO sending stop and the status says another master appeared
