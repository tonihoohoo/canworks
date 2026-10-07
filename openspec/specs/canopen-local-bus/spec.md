# canopen-local-bus Specification

## Purpose
Commissioning CANopen devices straight from the engineering PC through a USB CAN adapter, with no OpenPLC Runtime: the PC tools open the adapter with python-can and act as a guest on the bus for scan, SDO, the object dictionary, parameters, LSS and trace.

## Requirements

### Requirement: Local adapter backend
The PC tools package SHALL include a local bus backend that opens a CAN adapter on the PC and answers the diagnostics operations `hello`, `status`, `emcy`, `sdo_read`, `sdo_write`, `nmt`, `scan`, `scan_status`, `lss_find`, `lss_find_status`, `lss_inquire`, `lss_set_id`, `lss_set_bitrate`, `trace_start`, `trace_fetch`, `trace_stop`, `send_frame`, `send_frame_stop`, `detect_bitrate` and `detect_bitrate_status`, with the same request fields and result fields as the plugin's diagnostics channel except where this spec says otherwise. Any other operation SHALL answer `not available on a local adapter`. It SHALL need no OpenPLC Runtime, and no Python on the PC beyond what uv installs.

#### Scenario: Read a device with no PLC
- **WHEN** a CANopen device with node ID 5 is the only node on a bus with a USB adapter on the PC, and the user runs `openplc-canopen-diag --adapter slcan:COM5 --bitrate 250 sdo-read 5 0x1018 1 --type UNSIGNED32`
- **THEN** it prints the device's vendor ID, and no runtime is involved

#### Scenario: Simulator op on a local adapter
- **WHEN** `openplc-canopen-diag --adapter socketcan:can0 --bitrate 250 sim status` runs
- **THEN** it exits with status 1 and says that this needs a runtime

### Requirement: Supported adapters
The backend SHALL support `slcan` adapters (serial-line adapters such as a CANable with stock firmware) on Windows, macOS and Linux, and `socketcan` interfaces on Linux, selected as `TYPE:CHANNEL`. It SHALL pass any other adapter type that python-can knows to python-can, with `--adapter-option KEY=VALUE` options, and the documentation SHALL list those types as untested. `openplc-canopen-diag adapters` SHALL list the serial ports and python-can interfaces it finds, marking known slcan adapters.

#### Scenario: CANable on a Mac
- **WHEN** a CANable with stock firmware is plugged into a Mac and the user runs `openplc-canopen-diag adapters`
- **THEN** the list shows its `/dev/tty.usbmodem...` port as an slcan adapter, with the `--adapter slcan:...` text to use

#### Scenario: Unknown adapter type
- **WHEN** the user gives `--adapter foo:0`
- **THEN** the command exits with status 1 and names the adapter types python-can has installed

### Requirement: Bit rate is never guessed
Opening an adapter SHALL need a bit rate from `--bitrate` or from the selected network's `adapter.bitrate` in `--config`. Without either, the command SHALL exit with status 1 and say so. On a SocketCAN interface that is already up, the interface's own bit rate SHALL be used and reported, and the interface SHALL NOT be reconfigured.

#### Scenario: No bit rate
- **WHEN** `openplc-canopen-diag --adapter slcan:COM5 scan` runs without `--bitrate` or `--config`
- **THEN** it exits with status 1, says that the bit rate is needed, and sends nothing

#### Scenario: Bit rate from the config
- **WHEN** `--config canopen/canopen.json --network drives` is given and that network's `adapter.bitrate` is 500000
- **THEN** the adapter is opened at 500 kbit/s

### Requirement: Guest on the bus
The backend SHALL send nothing on connect and SHALL listen for at least one second before its first transmit. It SHALL never send SYNC, heartbeat, TIME or broadcast NMT, and never start a node on its own. All frames it sends SHALL go through one transmit path.

#### Scenario: Connect sends nothing
- **WHEN** the configurator connects to an adapter and the user only watches the online view
- **THEN** a trace on another device shows no frame from the PC

### Requirement: Another master on the bus
The backend SHALL detect another master from NMT command frames, SYNC frames, or SDO requests to a node that it did not send itself. `status` SHALL then report `other_master: true` with what was seen and when. While another master is detected, the `lss_` operations except `lss_find_status` SHALL answer `another master is active on this bus` unless the request has `force: true` (CLI `--force`). Before an SDO request to a node that had a foreign SDO request within the last 200 ms, it SHALL wait until 200 ms have passed.

#### Scenario: PLC running on the same bus
- **WHEN** a PLC with the plugin runs SYNC on the bus and the user runs `lss-find --allow-changes` from the PC without `--force`
- **THEN** it exits with status 1 and says that another master is active

#### Scenario: Status shows the master
- **WHEN** the configurator's online view runs on an adapter and a SYNC frame is seen
- **THEN** the banner says that another master is active and since when

### Requirement: Changes are opt-in per session
`sdo_write`, `nmt` and the `lss_` operations except `lss_find_status` SHALL answer `changes not allowed` unless the session was opened with allow-changes (CLI `--allow-changes`, or the configurator's checkbox for this connection, which starts off and is not saved). The backend SHALL NOT write 0x1010 or send LSS store on its own. Storing SHALL happen only through `store` (which asks first) or an LSS request with `store: true`.

#### Scenario: Read-only by default
- **WHEN** `openplc-canopen-diag --adapter slcan:COM5 --bitrate 250 nmt 5 stop` runs without `--allow-changes`
- **THEN** it exits with status 1 with "changes not allowed (start with --allow-changes)" and sends no frame

#### Scenario: LSS set ID does not store
- **WHEN** `lss-set-id ... 12 --allow-changes` runs without `--store`
- **THEN** the device gets node ID 12 and no LSS store command is sent

### Requirement: Local status
On a local adapter, `status` SHALL report `local: true`, the adapter, the bit rate, the bus state and error counters when the adapter reports them (otherwise `null`), `other_master`, and for each node ID heard since connect its last NMT state from heartbeat or boot-up, the time since last heard, and its last EMCY. With `--config`, configured nodes SHALL be listed by name, also when silent. It SHALL NOT report boot results, holds, SDO variables or SYNC counters.

#### Scenario: Heartbeat node
- **WHEN** node 5 sends a heartbeat with state 127 every 500 ms
- **THEN** `status` lists node 5 as PRE-OPERATIONAL, last heard less than a second ago

### Requirement: Local scan and LSS
`scan` SHALL probe node IDs 1-127 with the plugin's algorithm (eight at a time, 100 ms per probe of 0x1018:1, then identity, device type and device name) and compare found devices with `--config` when given. The LSS operations SHALL behave as the plugin's, except that `lss_set_id` SHALL refuse a node ID from which a heartbeat or boot-up was heard in this session unless forced.

#### Scenario: Scan an unknown bus
- **WHEN** devices with node IDs 3 and 40 are on the bus and `scan` runs without a config
- **THEN** both are listed with vendor ID, product code, revision, serial number, device type and name

#### Scenario: ID already in use
- **WHEN** node 12 sent a heartbeat and `lss-set-id ... 12` runs without `--force`
- **THEN** it is refused, naming node 12 as heard on the bus

### Requirement: Local NMT
On a local adapter `nmt` SHALL accept any node ID 1-127, send the command once and keep no hold. `restore --hold-preop` SHALL send `preop` before writing and `start` afterwards, also when a write fails.

#### Scenario: Restore with hold
- **WHEN** `restore 5 node5.dcf --hold-preop --allow-changes --yes` runs on a local adapter
- **THEN** node 5 gets NMT pre-operational, then the writes, then NMT start

### Requirement: Local trace
`trace_start`, `trace_fetch` and `trace_stop` SHALL record the adapter's received frames and the frames this tool sent (Tx flag set) in the plugin's 24-byte record format, in a ring of 65536 records, with up to 16 ID and mask filters and error frames on request when the adapter delivers them. Time stamps SHALL come from the adapter when it gives them, otherwise from the PC clock. Trace export (pcapng, candump, ASC, BLF, TRC, CSV) and the configurator's Trace view SHALL work unchanged.

#### Scenario: Record from the PC
- **WHEN** `openplc-canopen-diag --adapter socketcan:can0 --bitrate 250 trace -o bench.pcapng --duration 10` runs
- **THEN** `bench.pcapng` holds the bus frames of those 10 seconds with CANopen decoding available as for a runtime trace

### Requirement: Device parameters on a local adapter
`backup`, `compare`, `restore` and `store` SHALL work on a local adapter as on a runtime, with the node's EDS from `--config` or `--eds`.

#### Scenario: Back up before a PLC exists
- **WHEN** `openplc-canopen-diag --adapter slcan:COM5 --bitrate 250 backup 5 --eds valve.eds -o node5.dcf` runs
- **THEN** `node5.dcf` is written as it would be through a runtime

### Requirement: One user of an adapter
An adapter SHALL be opened by one tool at a time. A second tool opening it SHALL get `adapter in use (another tool has it open)`. The configurator SHALL close an adapter it no longer uses after the same idle time as a runtime connection.

#### Scenario: Configurator holds the adapter
- **WHEN** the configurator's online view uses `slcan:COM5` and the user runs `openplc-canopen-diag --adapter slcan:COM5 --bitrate 250 status`
- **THEN** the CLI exits with status 1 and says that the adapter is in use

### Requirement: Command-line options for a local adapter
`openplc-canopen-diag` SHALL take `--adapter TYPE:CHANNEL`, `--bitrate KBIT`, `--adapter-option KEY=VALUE` (repeatable), `--allow-changes` and `--force`. `--adapter` and `--runtime` SHALL be mutually exclusive. With `--adapter`, no token SHALL be asked for. `--network NAME` with `--config` SHALL pick the network whose bit rate and EDS files are used.

#### Scenario: Both targets given
- **WHEN** `--runtime plc.local --adapter slcan:COM5` are both given
- **THEN** the command exits with status 2 and says that only one may be given

### Requirement: Hook for raw frames and bit rate detection
The backend SHALL open adapters through a single function that takes a listen-only flag, SHALL send every frame through one transmit path that feeds the trace and the other-master bookkeeping, and SHALL dispatch operations from one table, so that later operations (raw frame transmit, bit rate detection) are added without changing the existing ones.

#### Scenario: New operation added
- **WHEN** a later change adds a `send_frame` operation
- **THEN** it is one entry in the op table using the transmit path, and the existing operations' code is unchanged

### Requirement: Local backend tests
CI SHALL test the backend on python-can's virtual bus with a fake device on every PC tools runner, and on Linux on `vcan0` against the standalone simulator and an LSS test slave. A parity test SHALL compare the read-only results of `status` (shared fields), `scan`, `sdo-read` and `backup` through the local adapter with the same commands through the plugin's diagnostics channel on the same bus.

#### Scenario: Parity holds
- **WHEN** the vcan job runs scan through `--adapter socketcan:vcan0` and through the plugin's channel on the same bus
- **THEN** both list the same devices with the same identity fields

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
On a local adapter, `detect_bitrate` SHALL answer at once with progress and sweep in the background: for each requested rate (default 1000, 800, 500, 250, 125, 50, 20 and 10 kbit/s) and round (`rounds` 1-20, `per_rate_ms` 100-10000, default 1000) it SHALL open the adapter in listen-only mode and count valid frames, error frames (when the adapter reports them) and the first 16 identifiers, stop early after a round with a `detected` verdict, and then open the adapter again at the connection's bit rate so the connection keeps working. `detect_bitrate_status` SHALL return the progress and, when finished, the per-rate counts and the plugin's verdict (`detected`, `ambiguous`, `silent`, `failed`) computed by the same rules, with `matches_config` against the connection's bit rate. Because listen-only sends nothing, not even an acknowledge, it SHALL need neither allow-changes nor `force`. Rates the adapter type cannot be set to (on slcan, any but 10, 20, 50, 100, 125, 250, 500, 750 and 1000 kbit/s) SHALL NOT be tried; the result SHALL list only the rates listened at and name the left-out ones in `skipped_kbit`, and a sweep with no rate left SHALL be refused naming them. It SHALL be refused with "busy" when another connection of the same tool uses the adapter. While it runs, other operations except `status` SHALL answer "no bus", and the adapter's cyclic jobs SHALL end. Listen-only SHALL be: on slcan, silent mode (`m1`, then `O`) unless the firmware refuses `m1` with an error (BEL; some firmware answers no command at all), else the channel opened with `L` instead of `O`, with `m0` sent when the channel is closed after silent mode and before a normal `O`; PCAN with its listen-only parameter, and SocketCAN by setting the link to the rate with listen-only on, which needs root or CAP_NET_ADMIN, and setting it back to its bit rate, listen-only off and its up or down state afterwards. Without that permission the request SHALL be refused naming it and the `sudo` command; on a vcan interface it SHALL be refused with "no bit rate on a virtual bus"; on other adapter types, and on a driver that rejects listen-only, with "the adapter's driver has no listen-only mode".

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
