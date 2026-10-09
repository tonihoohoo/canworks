## Context

The engine lives in the plugin. After `add-j1939-ecu` and `add-raw-can` it has:
- a shared CAN core in `plugin/src/can/`: adapters, trace, raw frames, raw messages, diagnostics server, process image, IEC locations, the config model
- protocol folders that each run networks behind `NetworkRuntime`
- the OpenPLC entry points

Its coupling to OpenPLC is small. `plugin_runtime_args_t` gives it image read and write, the image lock and the logger (7 files, 26 uses before those changes). The process image already uses lock-free triple buffers between the scan and the bus threads, and edge detection for SDO triggers and NMT command bytes runs in `cycle_end`.

OpenPLC v4 ships its own Modbus TCP server plugin, but it exposes only `%IX`, `%QX`, `%IW` and `%QW`, needs the PLC program to declare every location, and adds a scan. It does not meet the goal of "any PLC or app without OpenPLC".

Vendor manuals (17 products, see the project notes) show the common gateway shape: a CAN master with a Modbus TCP server, a vendor tool that builds the map, an optional control/status word, a node live list or status tag, a client-loss timeout with hold, zero or a value, and boot-time SDOs. None documents multi-register consistency, none implements CiA 309-2, and none exports anything for the PLC side.

## Goals / Non-Goals

**Goals:**
- Any Modbus TCP client can use every config-mapped canworks value, on every protocol, with no PLC runtime on the bridge machine.
- One config file and one engine, shared with the plugin. The register map is derived from the config, not configured a second time.
- A multi-register value never tears within one request.
- Outputs stop when the client goes away.
- The client side is generated: a map file and a PLC variable list.
- No CI time increase.

**Non-Goals:**
- Raw frame, J1939 send and J1939 request mailboxes (a later `add-bridge-mailboxes`).
- CiA 309-2 function 43/13, Modbus/TCP Security, Modbus RTU.
- Windows or macOS bridge hosts.
- Running the bridge and the OpenPLC plugin on one interface.
- Engineering-unit scaling in the bridge.

## Decisions

### 1. One bridge, same engine, new host

`canworks-bridge` is a second executable over the same core and protocol folders. The networks already run in one shared engine (`plugin/src/can/engine.*`) that the plugin entry points call. The bridge host drives that same engine and gives it what OpenPLC gives the plugin, through the existing `plugin_runtime_args_t` interface emulated over the bridge's byte image:
- input locations written from the bus side and output locations read to the bus side
- the logger
- the "outputs running" state that starts and stops outputs, and a cycle-end call after each accepted write

The OpenPLC path keeps today's behaviour exactly, since nothing in it changes. The bridge host implements the interface on a byte image (Decision 3) and the Modbus server. Emulating the existing interface instead of adding a new host layer keeps the protocol code and its tests untouched. Protocols, diagnostics, trace and the simulated bus are unchanged and do not know which host runs them.

*Alternatives:*
- **One bridge per protocol.** Rejected: it duplicates the server, watchdog, status, diagnostics and packaging. It also cannot share one bus between a protocol and raw messages, and blocks later routing between protocols.
- **Modbus server inside the OpenPLC plugin.** Rejected: it still needs OpenPLC, conflicts with OpenPLC's own Modbus plugin on port 502, and keeps the per-type addressing that cannot pack mixed sizes densely.

**Build.** The bridge is a CMake target `canworks-bridge` built with the same options `CANWORKS_WITH_CANOPEN` and `CANWORKS_WITH_J1939` (raw is always in). It needs no OpenPLC header.

### 2. No scan in the bridge

- **Inputs:** the bus threads publish input snapshots as today. A Modbus read request takes the newest snapshot once and answers every register of the request from it.
- **Outputs:** a write request applies its registers to a working copy of the output image and publishes one snapshot. The bus threads take it before the next SYNC, or at once for event-driven outputs, raw TX on change and J1939 TX on change.
- **Edges:** the rising-edge logic that runs in `cycle_end` in the plugin (SDO variable triggers, NMT command bytes, raw TX trigger bits) runs per published output snapshot, comparing it with the previous one. A pulse written as 1 then 0 in two requests counts once. Clients that rewrite the same value cyclically, as Modbus client channels usually do, create no edges.
- **Snapshot age:** the server reads the newest snapshot at request time, so latency is the client's poll period plus at most one SYNC period. There is no fixed bridge cycle.
- **`sync_source: "plc_cycle"`:** rejected in a bridge config, since there is no PLC cycle.

### 3. Byte-addressed image and the register rule

A bridge config's locations are byte-addressed, the Siemens/IEC byte-area convention:
- `%IBn` is byte n
- `%IWn` is bytes n..n+1
- `%IDn` is bytes n..n+3
- `%ILn` is bytes n..n+7
- `%IXn.b` is bit b of byte n
- the same for `%Q`

Locations overlap only when their byte ranges overlap, and the clash check uses byte ranges.

The image is stored big-endian: the most significant byte of a word, double or long word sits at its lowest byte. Then:

| Location | Modbus |
| --- | --- |
| input byte n | input register n/2; even n is the high byte, odd n the low byte |
| `%IXn.b` | discrete input n·8+b, and bit b of byte n inside the input register |
| output byte n | holding register n/2, same byte rule |
| `%QXn.b` | coil n·8+b |

Word, double and long word locations SHALL start at an even byte, which a load check enforces. A 32-bit value at `%ID4` is registers 2 and 3. With `word_order: "high_first"` (default) register 2 is the high word. With `"low_first"` the words are stored swapped, so register 2 is the low word, for clients that expect that order. Bytes within a register always follow Modbus big-endian. REAL32 and REAL64 objects are raw IEEE bits, so the client declares them as REAL with the same word order.

*Why a fixed rule:* the map follows from the config, both sides can derive it independently, and the configurator can show it. Clients needing another layout use a different word order or rearrange the config's locations ("Pack for Modbus"). Per-entry swap options, as some vendors offer, are not needed in slice 1.

*Why not the OpenPLC per-type tables:* they cannot pack mixed sizes into one register block, so a client would need one request per type.

### 4. The bridge object

```json
"bridge": {
  "listen": "0.0.0.0:502",
  "unit_id": 1,
  "word_order": "high_first",
  "max_clients": 16,
  "writers": ["192.168.10.20"],
  "readers": ["192.168.10.0/24"],
  "watchdog_ms": 1000,
  "on_client_loss": "stop",
  "status_location": "%IB496",
  "control_location": "%QB496",
  "live_lists": [ { "network": "field", "location": "%IB480" } ],
  "sdo_bridge_location": { "request": "%QB464", "response": "%IB448" },
  "sdo_bridge_write": false
}
```

- **`listen`:** required. The systemd unit grants `CAP_NET_BIND_SERVICE` for port 502.
- **`unit_id`:** 0..255, default 1. Requests with unit 0 or 255 are also answered; other units get exception 0x0B (gateway target failed to respond).
- **`writers`, `readers`:** IPv4/IPv6 addresses or prefixes. Absent `readers` means any client may read; absent `writers` means any client that may read may also write. A client not in `readers` is disconnected at accept. A write from a client not in `writers` gets exception 0x01 and changes nothing.
- **Location blocks:** each is optional. Its locations take part in the clash check.

### 5. Watchdog and client loss

The watchdog is fed by every accepted write request (function 5, 6, 15, 16 or 23) from a writer. When it runs out (`watchdog_ms`, default 1000, 0 = off) or the control block commands idle, the bridge enters **outputs off** with the `on_client_loss` action:
- **`"stop"`** (default): no RPDOs, no raw TX and no J1939 TX. SYNC keeps running, so inputs that nodes send on SYNC keep updating (a reading HMI still sees live values) and a node with an RPDO event timer notices the outputs stop. Inputs, supervision, heartbeat, the diagnostics channel and J1939 address claim keep running.
- **`"zero"`:** every output location is set to 0 and sent once, then outputs stop as with `"stop"`.
- **`"hold"`:** outputs keep being sent with their last values.

The next accepted write (watchdog), or a run command (control), ends outputs off. The log and the status block show the reason. `"stop"` is the default because Toni set "outputs stop" (2026-10-09); the vendor products default to hold after 60 s.

### 6. Status, control and live list

**Status block** (`status_location`, 8 bytes, input):

| Bytes | Content |
| --- | --- |
| 0 | state: 1 running, 2 outputs off (watchdog), 3 outputs off (idle command) |
| 1 | number of connected clients |
| 2-3 | heartbeat counter, +1 every 100 ms |
| 4-5 | last control counter handled (echo) |
| 6 | last control result: 0 ok, 1 unknown command, 2 bad network, 3 bad node, 4 not a CANopen master network |
| 7 | reserved, 0 |

**Control block** (`control_location`, 6 bytes, output): counter (word), command (byte), network index (byte), node (byte), reserved (byte). A command runs once when the counter changes; the status block echoes the counter with the result. Commands:
- 1 run, 2 idle
- 3 NMT start, 4 NMT stop, 5 NMT pre-operational, 6 reset node, 7 reset communication (node 0 = all nodes of that CANopen master network)

*Why a counter, not a toggle bit or write events:* client channels rewrite registers cyclically, so a write event cannot mean "new command". The counter handshake is what the J1939 gateway manuals use, and it lets the client match each result to its command.

**Live list** (`live_lists`, 16 bytes per CANopen master network, input): bit n set while node n is OPERATIONAL. Bit 0 is always 0.

### 7. SDO bridge registers

The fields and results are those of the CANopen gateway's SDO bridge, so one backend serves both. The request goes through the same path as the SDO function blocks: it queues behind other requests to the same node and shares their timeout.

**Request** (output, 14 bytes): counter (word), command (byte: 1 read, 2 write), network index (byte), node (byte), sub-index (byte), index (word), length (byte, 1..4), reserved (byte), value (double word).

**Response** (input, 14 bytes): counter echo (word), status (byte: 0 idle, 1 busy, 2 done, 3 aborted), reserved (byte), abort code (double word), value (double word), reserved (word).

A write needs `sdo_bridge_write: true`; otherwise it ends aborted with 0x08000020. Segmented transfers are a later mailbox change.

### 8. Clients and protocol details

- **Functions:** 1, 2, 3, 4, 5, 6, 15, 16, 23 and 8 (diagnostics loopback only). Other functions get exception 0x01.
- **Limits:** at most 125 registers per read and 123 per write, per Modbus. An address outside the image size (highest used byte + 1, rounded up to even) gets exception 0x02.
- **Reading outputs:** holding registers and coils read back the output image.
- **Function 23:** applies the write before the read, both on one snapshot pair.
- **Connections:** up to `max_clients`; the next one is closed at accept and logged. Idle connections are closed after 60 s without a request, so dead clients do not hold slots.
- **Server thread:** one thread with `poll()`. Requests are handled in arrival order and never block on the bus.

### 9. Instances and interface ownership

`canworks-bridge --config DIR/canworks.json`. The systemd template `canworks-bridge@NAME` uses `/etc/canworks-bridge/NAME/`. Each process takes an exclusive `flock` on `/run/canworks/<interface>.lock` for every real interface it uses before bringing it up. A second process gets a clear start error naming the interface and the owner's PID. The OpenPLC plugin takes the same lock, so the bridge and an OpenPLC runtime cannot fight over `can0` on one machine. Simulated interfaces are per process and take no lock.

### 10. Config upload over the diagnostics channel

`put_config` carries the config and every file it names (EDS, DBC, simulation file) as a map of relative file names to base64 contents, at most 8 MB in all; names must stay inside the config folder. It needs `allow_changes` and the new `diagnostics.allow_config_upload`.

The bridge then:
- runs the full config check on the new files in a staging folder
- answers with the check result
- on success, stops its networks, moves the files into place, and restarts with the new config

If the new config fails at start, it restores the previous files and restarts with them. The answer and the log say so.

The OpenPLC plugin refuses `put_config`, since its config comes with the program upload.

### 11. Map exports and Pack for Modbus

A shared Python module (`canworks/modbusmap.py`) computes the register map from a bridge config with the rule of Decision 3. The configurator, `canworks-deploy --export-modbus-map` and the HTML document all use it.

**Formats:**
- **CSV and JSON:** one row per location with name, network, node, object or signal, direction, Modbus table, start address, register or bit count, data type, word order, scale, offset and unit.
- **ST:** a `VAR_GLOBAL` list with typed variables and comments, plus a comment table of suggested client channels: function, start, count and direction, at most 125 or 123 registers each, covering the used ranges. Common PLC tools have no standard import for Modbus client channels, so the table is for typing in.

**Pack for Modbus** reassigns a bridge config's locations densely:
- inputs from byte 0 in network, node and PDO order, word-aligned
- status and diagnostic locations after the data
- outputs the same way
- the bridge's own blocks at the end

The aim is that a client needs as few requests as possible.

### 12. CI and tests

- C++ tests in the existing plugin test job, on the simulated bus with a small Modbus TCP client in the test:
  - map rule and word order
  - consistency (a value changing every millisecond is never torn)
  - writes to RPDOs and SYNC timing
  - edges from cyclic rewrites
  - watchdog actions, control and live list
  - SDO bridge registers
  - allowlists and exceptions
  - interface lock
- Python tests for the map exports and Pack for Modbus in the existing tools shards.
- The area classifier counts `plugin/src/bridge/**` as `shared`. No new job is added.
- The container image is built only by the release workflow.

## Risks / Trade-offs

- **Modbus TCP has no authentication.** Mitigated by allowlists, a separate writers list and docs that say to keep the bridge on a machine network. TLS is a later option.
- **Byte addressing differs from OpenPLC addressing.** A config moves between plugin and bridge only through the configurator's target switch, which repacks the locations. Since the project is not in real use, no automatic conversion is kept.
- **Port 502 and capabilities.** The unit grants `CAP_NET_BIND_SERVICE`; the container maps the port.
- **The bridge emulates the runtime interface.** The protocol paths stay as they are; the existing plugin tests are the guard, and the bridge tests check that the emulation gives the same map the PC tools compute.
