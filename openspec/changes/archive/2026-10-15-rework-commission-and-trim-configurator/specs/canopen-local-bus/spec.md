## ADDED Requirements

### Requirement: Bit rate check on connect
Opening a local adapter session SHALL check that the bus runs at the given bit rate before any operation runs. The check SHALL listen for one second, in listen-only mode when the adapter has one.
- At least one valid frame and no error frame SHALL confirm the rate.
- Any error frame, error warning, error passive or bus-off state, or a receive error count above zero with no valid frame, SHALL refuse the session with "the bus does not run at N kbit/s" and what was seen.
- When nothing was heard, the backend SHALL send one LSS "inquire node ID" frame (0x7E5, command 0x5E) once, without automatic retransmission where the adapter can turn that off. The rate SHALL be confirmed when the adapter reports the frame sent with no error frame within 100 ms. An acknowledge error alone SHALL refuse the session with "no device acknowledged at N kbit/s: the bit rate is wrong, or no device is powered and connected". Bit, stuff or form errors SHALL refuse it with "the bus does not run at N kbit/s".
- On an adapter that cannot report a sent frame (slcan and untested types), a silent bus SHALL need a node ID (`check_node`, CLI `--check-node N`). An SDO read of 0x1000 sub 0 from that node SHALL confirm the rate when it gets any answer, including an abort. Without a node ID, or with no answer, the session SHALL be refused, naming `--check-node`.
- A bit rate the adapter cannot be set to SHALL be refused before anything is sent to the adapter, naming the rate.

A refused check SHALL close the adapter. `hello` and `status` SHALL report `bitrate_check` with `result` (`confirmed`) and `how` (`traffic`, `probe acknowledged` or `node N answered`).

#### Scenario: Wrong rate refused
- **WHEN** devices send heartbeats at 500 kbit/s and the user connects at 1000 kbit/s
- **THEN** the session is refused with "the bus does not run at 1000 kbit/s", the adapter is closed, and no operation runs

#### Scenario: Busy bus confirmed
- **WHEN** a device sends heartbeats at 500 kbit/s and the user connects at 500 kbit/s
- **THEN** the session opens with `bitrate_check` `confirmed` by `traffic`, and the PC sent nothing

#### Scenario: Silent single device
- **WHEN** one device in PRE-OPERATIONAL without heartbeat is on the bus at 250 kbit/s and the user connects a gs_usb adapter at 250 kbit/s
- **THEN** the backend sends one LSS inquire node ID frame, the adapter reports it acknowledged, and the session opens `confirmed` by `probe acknowledged`

#### Scenario: Silent single device at a wrong rate
- **WHEN** the same device runs at 250 kbit/s and the user connects at 500 kbit/s
- **THEN** the probe is not acknowledged, it is not retransmitted, and the session is refused saying the bit rate is wrong or no device is connected

#### Scenario: slcan on a silent bus
- **WHEN** an slcan adapter connects to a silent bus without `--check-node`
- **THEN** the command exits 1 saying the bit rate could not be checked and to give `--check-node N`, and with `--check-node 5` it opens when node 5 answers

### Requirement: Bus errors end the connection
After the check, the backend SHALL end the session when the adapter reports bus-off or error passive, or 10 error frames within one second with no valid frame. Every handle SHALL then get "connection ended: <reason>", running jobs (scan, PDO test, SYNC, raw send, trace) SHALL stop, and the adapter SHALL be closed.

#### Scenario: Cable moved to another bus
- **WHEN** a connected session at 500 kbit/s starts getting error frames only, more than 10 in a second
- **THEN** the session ends with the reason, the adapter is closed, and the next request answers "connection ended"

### Requirement: gs_usb adapters
On gs_usb adapters, the backend SHALL handle the following:
- **Echo frames:** it SHALL never treat the adapter's echo of a sent frame as a received frame. Echoes SHALL NOT count as another master, heartbeat or answer. They SHALL confirm the send, and the trace SHALL list each sent frame once with its Tx flag.
- **Stopped sending:** a send whose echo does not arrive within 0.5 s SHALL end the session with "adapter stopped sending".
- **Bit timings:** they SHALL come from the device's own timing limits, trying the sample points 87.5, 85, 80 and 75 %.
- **Failed set or start:** a failure to set or start the channel SHALL leave it in reset mode.
- **USB stall on open:** the backend SHALL reset the USB device and retry once. If the retry fails, it SHALL refuse with "adapter gs_usb:N does not answer (USB stall): unplug it and plug it in again".
- **Close:** closing SHALL reset the channel before releasing the USB interface.

#### Scenario: Own SDO request is not another master
- **WHEN** the configurator reads 0x1018 from node 23 through a gs_usb adapter and no other master is on the bus
- **THEN** `status` reports no other master, and the trace lists the request once, as sent

#### Scenario: Rate without timing
- **WHEN** the adapter's clock and limits give no timing for the chosen rate
- **THEN** the connection is refused naming the adapter and the rate, and the adapter can be opened at another rate at once without a replug

### Requirement: One open path and one transmit path
The backend SHALL open adapters through a single function that takes a listen-only flag. It SHALL send every frame through one transmit path that feeds the trace, the send confirmation and the other-master bookkeeping. It SHALL dispatch operations from one table.

#### Scenario: New operation added
- **WHEN** a later change adds an operation
- **THEN** it is one entry in the op table using the transmit path, and the existing operations' code is unchanged

## MODIFIED Requirements

### Requirement: Local adapter backend
The PC tools package SHALL include a local bus backend that opens a CAN adapter on the PC. It SHALL answer these diagnostics operations: `hello`, `status`, `emcy`, `sdo_read`, `sdo_write`, `nmt`, `scan`, `scan_status`, `scan_stop`, `lss_find`, `lss_find_status`, `lss_inquire`, `lss_set_id`, `lss_set_bitrate`, `trace_start`, `trace_fetch`, `trace_stop`, `send_frame`, `send_frame_stop`, `pdo_test_start`, `pdo_test_set`, `pdo_test_status`, `pdo_test_stop`, `sync_start` and `sync_stop`. Request and result fields SHALL be the same as the plugin's diagnostics channel except where this spec says otherwise. Any other operation SHALL answer `not available on a local adapter`. It SHALL need no OpenPLC Runtime, and no Python on the PC beyond what uv installs.

#### Scenario: Read a device with no PLC
- **WHEN** a CANopen device with node ID 5 is the only node on a bus with a USB adapter on the PC, and the user runs `canworks-diag --adapter slcan:COM5 --bitrate 250 --check-node 5 sdo-read 5 0x1018 1 --type UNSIGNED32`
- **THEN** it prints the device's vendor ID, and no runtime is involved

#### Scenario: Simulator op on a local adapter
- **WHEN** `canworks-diag --adapter socketcan:can0 --bitrate 250 sim status` runs
- **THEN** it exits with status 1 and says that this needs a runtime

#### Scenario: Bit rate detection is gone
- **WHEN** a client sends `detect_bitrate` to a local adapter
- **THEN** it answers `not available on a local adapter`

### Requirement: Bit rate is never guessed
Opening an adapter SHALL need a bit rate from `--bitrate` or from the selected network's `adapter.bitrate` in `--config`. Without either, the command SHALL exit with status 1 and say so. The tools SHALL NOT search for the bus's bit rate. They SHALL check the given rate on connect (see "Bit rate check on connect"). On a SocketCAN interface that is already up, the interface's own bit rate SHALL be used, reported and checked, and the interface SHALL NOT be reconfigured.

#### Scenario: No bit rate
- **WHEN** `canworks-diag --adapter slcan:COM5 scan` runs without `--bitrate` or `--config`
- **THEN** it exits with status 1, says that the bit rate is needed, and sends nothing

#### Scenario: Bit rate from the config
- **WHEN** `--config canworks/canworks.json --network drives` is given and that network's `adapter.bitrate` is 500000
- **THEN** the adapter is opened and checked at 500 kbit/s

### Requirement: Guest on the bus
On connect, the backend SHALL send nothing except the one probe frame of the bit rate check on a silent bus, or the check's SDO read when the user gave a node ID. It SHALL listen for at least one second before its first transmit. It SHALL never send heartbeat, TIME or broadcast NMT, and never start a node on its own. It SHALL never send SYNC except while a SYNC producer the user started with `sync_start` runs. All frames it sends SHALL go through one transmit path.

#### Scenario: Connect sends nothing
- **WHEN** the configurator connects to an adapter on a bus with heartbeat traffic and the user only watches
- **THEN** a trace on another device shows no frame from the PC

#### Scenario: SYNC only on request
- **WHEN** the user starts a PDO test on node 5 without SYNC
- **THEN** a trace shows no SYNC frame from the PC, and SYNC frames appear only after the user starts SYNC with a period

### Requirement: Another master on the bus
The backend SHALL detect another master from received NMT command frames, SYNC frames, or SDO requests to a node. Frames the adapter reports as its own sent frames (echo or loopback) SHALL never count. `status` SHALL then report `other_master: true` with what was seen and when. While another master is detected, the `lss_` operations except `lss_find_status` SHALL answer `another master is active on this bus` unless the request has `force: true` (CLI `--force`). Before an SDO request to a node that had a foreign SDO request within the last 200 ms, the backend SHALL wait until 200 ms have passed. Frames heard during the listen window before the first transmit SHALL NOT be taken as answers to a later request. An answer or abort from the node for another index or subindex than the backend's own initiate request SHALL be skipped, not aborted. Changing Allow changes on an open session SHALL NOT reopen the adapter or clear what was seen.

#### Scenario: PLC running on the same bus
- **WHEN** a PLC with the plugin runs SYNC on the bus and the user runs `lss-find --allow-changes` from the PC without `--force`
- **THEN** it exits with status 1 and says that another master is active

#### Scenario: Status shows the master
- **WHEN** commissioning is connected on an adapter and a SYNC frame is seen
- **THEN** Bus and master says that another master is active and since when

#### Scenario: Own requests on an adapter with echo
- **WHEN** the PC is the only master and reads and writes SDOs of node 23 through a gs_usb adapter, then switches Allow changes on
- **THEN** no other master is reported

### Requirement: Local scan and LSS
`scan` SHALL probe node IDs 1-127 with the plugin's algorithm: eight at a time, 100 ms per probe of 0x1018:1, then identity, device type and device name. It SHALL compare found devices with `--config` when given. `scan_stop` SHALL end a running scan after the probes in flight. The result SHALL then have `stopped: true` and the devices found so far. A failed send or the end of the connection SHALL end the scan the same way, with `error` giving the reason. The LSS operations SHALL behave as the plugin's, except that `lss_set_id` SHALL refuse a node ID from which a heartbeat or boot-up was heard in this session unless forced.

#### Scenario: Scan an unknown bus
- **WHEN** devices with node IDs 3 and 40 are on the bus and `scan` runs without a config
- **THEN** both are listed with vendor ID, product code, revision, serial number, device type and name

#### Scenario: ID already in use
- **WHEN** node 12 sent a heartbeat and `lss-set-id ... 12` runs without `--force`
- **THEN** it is refused, naming node 12 as heard on the bus

#### Scenario: Cancel a scan
- **WHEN** a scan is at node ID 40 and the client sends `scan_stop`
- **THEN** the scan ends within one probe time with `stopped: true` and the devices found below node ID 48

#### Scenario: Adapter stops sending during a scan
- **WHEN** the adapter stops confirming sends during a scan
- **THEN** the scan ends at once with the adapter's error, not after probing every node ID

### Requirement: Command-line options for a local adapter
`canworks-diag` SHALL take these options: `--adapter TYPE:CHANNEL`, `--bitrate KBIT`, `--check-node N`, `--adapter-option KEY=VALUE` (repeatable), `--allow-changes` and `--force`. `--adapter` and `--runtime` SHALL be mutually exclusive. With `--adapter`, no token SHALL be asked for. `--network NAME` with `--config` SHALL pick the network whose bit rate and EDS files are used.

#### Scenario: Both targets given
- **WHEN** `--runtime plc.local --adapter slcan:COM5` are both given
- **THEN** the command exits with status 2 and says that only one may be given

## REMOVED Requirements

### Requirement: Hook for raw frames and bit rate detection
**Reason**: Renamed to "One open path and one transmit path", without bit rate detection.
**Migration**: None.

### Requirement: Bit rate detection on a local adapter
**Reason**: Toni does not want automatic bit rate detection. The connection checks the given rate instead (see "Bit rate check on connect").
**Migration**: Pick the bit rate. A wrong one is refused at connect.

### Requirement: Detect in the adapter connection form
**Reason**: There is no bit rate detection.
**Migration**: None.

### Requirement: Lone-device bit rate sweep
**Reason**: There is no bit rate detection. The sweep also wedged gs_usb adapters on macOS with unacknowledged frames at wrong rates.
**Migration**: The connect check's probe confirms a single silent device's rate.
