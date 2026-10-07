## ADDED Requirements

### Requirement: Local adapter backend
The PC tools package SHALL include a local bus backend that opens a CAN adapter on the PC and answers the diagnostics operations `hello`, `status`, `emcy`, `sdo_read`, `sdo_write`, `nmt`, `scan`, `scan_status`, `lss_find`, `lss_find_status`, `lss_inquire`, `lss_set_id`, `lss_set_bitrate`, `trace_start`, `trace_fetch` and `trace_stop`, with the same request fields and result fields as the plugin's diagnostics channel except where this spec says otherwise. Any other operation SHALL answer `not available on a local adapter`. It SHALL need no OpenPLC Runtime, and no Python on the PC beyond what uv installs.

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
