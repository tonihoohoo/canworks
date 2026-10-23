## MODIFIED Requirements

### Requirement: Local adapter backend
The PC tools package SHALL include a local bus backend that opens a CAN adapter on the PC. It SHALL answer these diagnostics operations: `hello`, `status`, `emcy`, `sdo_read`, `sdo_write`, `nmt`, `scan`, `scan_status`, `scan_stop`, `lss_find`, `lss_find_status`, `lss_inquire`, `lss_set_id`, `lss_set_bitrate`, `trace_start`, `trace_fetch`, `trace_stop`, `send_frame`, `send_frame_stop`, `pdo_test_start`, `pdo_test_set`, `pdo_test_status`, `pdo_test_stop`, `sync_start` and `sync_stop`. Request and result fields SHALL be the same as the bridge's diagnostics channel except where this spec says otherwise. Any other operation SHALL answer `not available on a local adapter`. It SHALL need no OpenPLC Runtime, and no Python on the PC beyond what uv installs.

#### Scenario: Read a device with no PLC
- **WHEN** a CANopen device with node ID 5 is the only node on a bus with a USB adapter on the PC, and the user runs `canworks-diag --adapter slcan:COM5 --bitrate 250 --check-node 5 sdo-read 5 0x1018 1 --type UNSIGNED32`
- **THEN** it prints the device's vendor ID, and no runtime is involved

#### Scenario: Simulator op on a local adapter
- **WHEN** `canworks-diag --adapter socketcan:can0 --bitrate 250 sim status` runs
- **THEN** it exits with status 1 and says that this needs a runtime

#### Scenario: Bit rate detection is gone
- **WHEN** a client sends `detect_bitrate` to a local adapter
- **THEN** it answers `not available on a local adapter`

### Requirement: Another master on the bus
The backend SHALL detect another master from received NMT command frames, SYNC frames, or SDO requests to a node. Frames the adapter reports as its own sent frames (echo or loopback) SHALL never count. `status` SHALL then report `other_master: true` with what was seen and when. While another master is detected, the `lss_` operations except `lss_find_status` SHALL answer `another master is active on this bus` unless the request has `force: true` (CLI `--force`). Before an SDO request to a node that had a foreign SDO request within the last 200 ms, the backend SHALL wait until 200 ms have passed. Frames heard during the listen window before the first transmit SHALL NOT be taken as answers to a later request. An answer or abort from the node for another index or subindex than the backend's own initiate request SHALL be skipped, not aborted. Changing Allow changes on an open session SHALL NOT reopen the adapter or clear what was seen.

#### Scenario: PLC running on the same bus
- **WHEN** a PLC with the bridge runs SYNC on the bus and the user runs `lss-find --allow-changes` from the PC without `--force`
- **THEN** it exits with status 1 and says that another master is active

#### Scenario: Status shows the master
- **WHEN** commissioning is connected on an adapter and a SYNC frame is seen
- **THEN** Bus and master says that another master is active and since when

#### Scenario: Own requests on an adapter with echo
- **WHEN** the PC is the only master and reads and writes SDOs of node 23 through a gs_usb adapter, then switches Allow changes on
- **THEN** no other master is reported

### Requirement: Local scan and LSS
`scan` SHALL probe node IDs 1-127 with the bridge's algorithm: eight at a time, 100 ms per probe of 0x1018:1, then identity, device type and device name. It SHALL compare found devices with `--config` when given. `scan_stop` SHALL end a running scan after the probes in flight. The result SHALL then have `stopped: true` and the devices found so far. A failed send or the end of the connection SHALL end the scan the same way, with `error` giving the reason. The LSS operations SHALL behave as the bridge's, except that `lss_set_id` SHALL refuse a node ID from which a heartbeat or boot-up was heard in this session unless forced.

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

### Requirement: Local trace
`trace_start`, `trace_fetch` and `trace_stop` SHALL record the adapter's received frames and the frames this tool sent (Tx flag set) in the bridge's 24-byte record format, in a ring of 65536 records, with up to 16 ID and mask filters and error frames on request when the adapter delivers them. Time stamps SHALL come from the adapter when it gives them, otherwise from the PC clock. Trace export (pcapng, candump, ASC, BLF, TRC, CSV) and the configurator's Trace view SHALL work unchanged.

#### Scenario: Record from the PC
- **WHEN** `canworks-diag --adapter socketcan:can0 --bitrate 250 trace -o bench.pcapng --duration 10` runs
- **THEN** `bench.pcapng` holds the bus frames of those 10 seconds with CANopen decoding available as for a runtime trace

### Requirement: Local backend tests
CI SHALL test the backend on python-can's virtual bus with a fake device on every PC tools runner, and on Linux on `vcan0` against the standalone simulator and an LSS test slave. A parity test SHALL compare the read-only results of `status` (shared fields), `scan`, `sdo-read` and `backup` through the local adapter with the same commands through the bridge's diagnostics channel on the same bus.

#### Scenario: Parity holds
- **WHEN** the vcan job runs scan through `--adapter socketcan:vcan0` and through the bridge's channel on the same bus
- **THEN** both list the same devices with the same identity fields

### Requirement: Raw frames on a local adapter
On a local adapter, `send_frame` SHALL send one frame, or start a cyclic job, with the bridge's fields (`can_id`, `ext`, `rtr`, `dlc`, `data`, `period_ms`, `count`, `force`) and answers, through the backend's one transmit path, so the frames appear in a trace marked Tx. It SHALL be refused with "changes not allowed" unless the session allows changes. With changes allowed, it SHALL be refused unless the request carries `force: true` when the identifier is NMT, SYNC, TIME or LSS, or, with a config, the predefined EMCY, PDO, SDO or heartbeat identifier of a configured node, or while another master is detected on the bus, or while a node's last heartbeat within 30 seconds said OPERATIONAL; the refusal SHALL name the reason and end with "force needed". Extended identifiers SHALL never count as used. Single frames SHALL be limited to 50 per second per connection and cyclic jobs to 8 per adapter, with a period of 10-60000 ms; a job SHALL end after its count, on `send_frame_stop`, when its connection closes, when a send fails, or after 10 minutes. `send_frame_stop` SHALL stop the connection's own jobs and report each job's sent count and why it ended, also for a job that ended in the last 60 seconds. `status` SHALL list the adapter's cyclic jobs under `send_jobs`.

#### Scenario: Frame to an unconfigured device
- **WHEN** `canworks-diag --adapter slcan:COM5 --bitrate 250 --allow-changes send 0x60A "40 18 10 01 00 00 00 00"` runs and no node is OPERATIONAL
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
