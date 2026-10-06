# Online diagnostics

The plugin can open a small TCP channel that shows the live CANopen network to the engineering PC: node states, boot results and errors, emergency history, SDO variable values, the bus state. With permission it also reads and writes any object by SDO, sends NMT commands, scans the bus for devices, and sets node IDs and bit rates of devices with LSS. The configurator's [online view and scan page](configurator.md#online-view) and the `openplc-canopen-diag` command use it.

It is off unless the config has `master.diagnostics` ([config.md](config.md#online-diagnostics)). The plugin listens only while the PLC runs, and nothing a client does touches the PLC scan: every request is served by the CAN thread between its own work (trace requests by the diagnostics thread), and a slow or stalled client is cut off instead of waited for.

## Setting it up

1. In the configurator, turn on **Online access** under **Bus and master**, save, and upload the program as usual. Or, by hand: choose a token, run `openplc-canopen-diag hash-token` and put the printed hash in `master.diagnostics.token_sha256`.
2. The runtime log shows `diagnostics listen on 0.0.0.0:7531, read-only` when the PLC starts.
3. Open **Online** in the configurator, or run `openplc-canopen-diag --runtime plc.local status`.

## `openplc-canopen-diag`

Installed with the deploy tool ([install-pc.md](install-pc.md)). The token comes from `--token`, `--token-file FILE`, the `OPENPLC_CANOPEN_TOKEN` environment variable, or a prompt. `--json` prints the plugin's answer as it came. A refused or failed request exits with status 1 and the reason.

```sh
export OPENPLC_CANOPEN_TOKEN=...                 # Copy token in the configurator
openplc-canopen-diag --runtime plc.local status
openplc-canopen-diag --runtime plc.local emcy 23
openplc-canopen-diag --runtime plc.local sdo-read 23 0x1018 4 --type UNSIGNED32
openplc-canopen-diag --runtime plc.local sdo-write 23 0x2010 1 1 --type UNSIGNED8    # needs allow_changes
openplc-canopen-diag --runtime plc.local nmt 23 stop                                 # start | stop | preop | reset | reset-comm
openplc-canopen-diag --runtime plc.local scan
openplc-canopen-diag --runtime plc.local lss-find [--vendor 0x360 --product 0x1]   # needs allow_changes
openplc-canopen-diag --runtime plc.local lss-inquire 0x360 0x1 0 0x1234           # VENDOR PRODUCT REVISION SERIAL
openplc-canopen-diag --runtime plc.local lss-set-id 0x360 0x1 0 0x1234 12 [--store]
openplc-canopen-diag --runtime plc.local lss-set-bitrate 0x360 0x1 0 0x1234 250 [--store]
openplc-canopen-diag --runtime plc.local trace -o run.pcapng --duration 60         # see trace.md
openplc-canopen-diag convert run.pcapng run.asc
openplc-canopen-diag --runtime plc.local backup 23 [-o node23.dcf]                 # all parameters into a DCF
openplc-canopen-diag --runtime plc.local compare 23 --with node23.dcf            # or --with-config, --with-eds-defaults
openplc-canopen-diag --runtime plc.local restore 23 node23.dcf [--dry-run]       # needs allow_changes; never stores
openplc-canopen-diag --runtime plc.local store 23 [--subindex 1]                 # writes "save" to 0x1010; asks first
openplc-canopen-diag hash-token                                                       # prints token_sha256
```

`--runtime` takes `HOST` or `HOST:PORT` (default port 7531). Types are the CiA 301 names (`UNSIGNED16`, `INTEGER32`, `REAL32`, `VISIBLE_STRING`, `OCTET_STRING`, ...); `sdo-read` without `--type` prints hex bytes, and `sdo-write` takes hex bytes for `OCTET_STRING` and `DOMAIN`.

### Simulated devices: `sim`

`openplc-canopen-diag sim ...` controls [simulated devices](simulator.md): the plugin's, with `--runtime HOST` (token as above; everything but `status`, `get` and `scenario list` needs `allow_changes`), or a standalone `openplc-canopen-sim`, with `--sim HOST[:PORT]` (default port 7532; token only when the simulator has one, from `--token` or `--token-file`). Without either it talks to the standalone simulator on `127.0.0.1:7532`. These options may also follow the subcommand.

```sh
openplc-canopen-diag --runtime plc.local sim status
openplc-canopen-diag --runtime plc.local sim get 5 0x7130:1 0x7130:2           # or: get 5 --pdo
openplc-canopen-diag --runtime plc.local sim set 5 0x7130:1 450                # once; a value source moves it again
openplc-canopen-diag --runtime plc.local sim override 5 0x7130:1 1500          # held until released
openplc-canopen-diag --runtime plc.local sim release 5 [0x7130:1 ...]          # without objects: all of node 5
openplc-canopen-diag --runtime plc.local sim source 5 0x7130:2 '{"sine": {"min": 200, "max": 260, "period_s": 10}}'
openplc-canopen-diag --runtime plc.local sim source 5 0x7130:2 none
openplc-canopen-diag sim fault 5 emcy 0x5000 --register 1 --runtime plc.local
openplc-canopen-diag --runtime plc.local sim clear 5 emcy                      # or: clear 5 all
openplc-canopen-diag --sim 127.0.0.1 sim scenario list                         # start NAME | stop NAME
openplc-canopen-diag --sim 127.0.0.1 sim test --scenario sensor-break --junit results.xml
```

`NODE` is a node ID or the name of an extra device. Objects are written `0xIIII:S` (`0xIIII` is subindex 0). Values are numbers (decimal, `0x` hex or with a decimal point; `true` and `false` are 1 and 0); anything else is sent as a string, for VISIBLE_STRING objects. A source is the JSON of the simulation file's value sources, or `none` to remove it.

`fault NODE KIND ...` takes these kinds, each sending the fault of the same name in [Faults](simulator.md#faults):

| Kind | Arguments |
|---|---|
| `emcy` | `CODE [--register N] [--msef HEX] [--period-ms N]` (`--msef`: 5 bytes as 10 hex digits) |
| `heartbeat-stop` | |
| `power` | `off`, `on` or `cycle [--off-ms N]` |
| `reset` | `node` or `comm` |
| `nmt` | `stopped`, `preop` or `operational` |
| `sdo-abort` | `OBJ CODE [--on read\|write\|both] [--count N]` |
| `sdo-delay` | `MS [--object OBJ]` |
| `refuse-write-operational` | |
| `tpdo-stop` | `N` |
| `identity` | `[--vendor-id N] [--product-code N] [--revision-number N] [--serial-number N]`, at least one |
| `device-type` | `VALUE` |
| `forget-node-id` | |
| `drive-input` | `--blocked`, `--positive-limit`, `--negative-limit`, `--home-switch` set an input, `--no-blocked` ... clear it; inputs not named stay as they are |
| `json` | the fault's JSON, e.g. `'{"heartbeat": "stop"}'` |

`clear NODE KIND` takes the same names (`emcy`, `heartbeat`, `power`, `sdo-abort`, `sdo-delay`, `refuse-write-operational`, `tpdo-stop`, `identity`, `device-type`, `drive-input`) or `all`; `--object OBJ` clears only that object's `sdo-abort` rule and `--tpdo N` only that TPDO's `tpdo-stop`.

`sim test` runs scenarios as tests of a PLC program: each `--scenario NAME` (repeatable), or every scenario with `--all`, one after another (`--parallel`: together). It starts each with `sim_scenario_start`, polls `sim_scenario_list` until it passed, failed or was stopped, and stops a scenario that still runs after `--timeout` seconds in all (default 300). It prints one line per scenario (`PASS`, `FAIL`, `TIMEOUT` or `NOT RUN`, the time, and the scenario's message) and a summary, writes a JUnit XML report with `--junit FILE` (one test case per scenario; failed, stopped and timed-out ones have a `failure`), and exits 0 when every scenario passed, 1 when one did not, and 2 on a usage error, an unknown scenario or when it cannot connect or start a scenario.

## What it offers

- **Status**: plugin version, time since the CANopen session started, the SHA-256 of the loaded `canopen.json`, the master's node ID and NMT state, the bus state and error counters (whether or not their PLC locations are configured), `simulated_network` (true when `adapter.simulate` is on), and per configured node whether it is `simulated`, its NMT state, status bit, whether it booted, the boot error letter with Lely's text, whether a boot retry is pending, the hold in force and who set it, its last EMCY and how many it sent, and each SDO variable's raw value, status and abort code. Between CANopen sessions (interface missing or down) the answer has `"session": false`, bus state 0 and every node 0.
- **EMCY history**: the last 16 emergency messages of a configured node, newest first, with UTC time, code, error register and manufacturer bytes. Recorded before the log's rate limit, so a burst is complete here even when the log summarizes it.
- **SDO read and write**: any node ID except the master's, configured or not, any object, up to 4096 bytes, timeout 10-10000 ms (default 1000). Requests to a configured node wait for its boot configuration and for the program's triggered SDO variables, and go before its periodic SDO variable reads. Writes are logged with the client's address. A write to an object an SDO variable or the boot configuration also writes lasts until that next write: the program and the config win.
- **NMT** (configured nodes only): `stop` and `preop` hold the node there, also across a reboot, like the program's NMT command byte; `start` releases the hold. Whichever comes last wins: the program changing its byte replaces an operator's hold, and the other way round. `reset` and `reset-comm` reboot the node and the master configures it again. Each is logged with the client's address.
- **Scan**: node IDs 1-127 except the master's, 8 at a time, 100 ms per probe of 0x1018:1, then vendor ID, product code, revision, serial number, device type and device name from those that answered. A configured node that is booting is reported as booting and not disturbed. Each device is compared with the config: the node's `revision_number` and `serial_number` identity check and the 0x1F85-0x1F88 values first, then the vendor ID and product code of its EDS. About 2 seconds on a quiet bus. One scan runs at a time; a client asking while one runs gets its progress. Devices in STOPPED do not answer SDO and are not found. The master must be PRE-OPERATIONAL or OPERATIONAL.

- **Bus trace**: every CAN frame on the bus, received and sent, with the kernel's time stamp, for the configurator's [Trace view](configurator.md#trace) and `openplc-canopen-diag trace` ([trace.md](trace.md)). Read-only: the token is enough, `allow_changes` is not needed. The plugin opens a second, receive-only socket on the CAN interface while at least one client traces, keeps the newest 65536 frames in a ring, and each tracing client fetches what is new. Up to 16 ID/mask filters per client limit what is recorded (the plugin records the union of all clients' filters), and error frames are recorded on request.

- **LSS commissioning** (CiA 305, all need `allow_changes`): for devices without DIP switches, which get their node ID and bit rate over the bus. A device is addressed by its LSS address: vendor ID, product code, revision and serial number (0x1018:1-4).
  - *Find* searches with LSS fastscan for one device that has no node ID, optionally only devices with a given vendor ID and product code. It runs in the background like the scan: about 13 seconds when nothing answers, less when a device does. The result is the device's address and its node ID (255: none). One device at a time: give it a node ID, then find the next.
  - *Inquire* asks one device for its node ID.
  - *Set node ID* gives one device a node ID (1-127, not the master's, and not one a booted configured node uses). A device without a node ID starts with the new one at once; a device that had one keeps it until it is reset or power-cycled, and the plugin sends no NMT command to the old ID, which may belong to another device.
  - *Set bit rate* sets one device's bit rate (10, 20, 50, 125, 250, 500, 800 or 1000 kbit/s) for its next power cycle. LSS "activate bit timing" is never sent: the bus keeps its bit rate, and the user changes `adapter.bitrate` to match once every device is set.
  - Nothing is stored in the device's memory unless the request says `store: true` (`--store`); without it a power cycle undoes the change.
  - One LSS request runs at a time, shared with the boot-time assignment of nodes with `lss.assign` ([config.md](config.md#lss)); a request while one runs answers `LSS busy`. Each request ends with all devices switched back to LSS waiting and is logged with the client's address. PDOs, heartbeats and SDO traffic of the configured nodes go on meanwhile.

- **Device parameters** (`backup`, `compare`, `restore`, `store`): see [Replacing a device](#replacing-a-device). They run on the PC over the SDO read and write above, one SDO at a time, so they need no newer plugin. The node's EDS comes from `--config canopen.json` (default `canopen/canopen.json` when it exists) or `--eds FILE` for a node that is not configured.

## Replacing a device

Before a device breaks, back it up: `backup` reads every object its EDS lists as readable (`ro`, `rw`, `rwr`, `rww`, `const`; DOMAIN objects are left out) and writes a CiA 306 DCF: the EDS with a `ParameterValue` for each value, the identity from 0x1018, and `[DeviceComissioning]` with the node ID, name and bit rate. Objects that could not be read are listed at the top of the file with their abort code. A few hundred objects take a few seconds. A read that gets no answer three times in a row stops: the node is STOPPED or gone. The configurator's online view has the same as **Back up**, and other CANopen tools open the file.

After swapping the device (same node ID, set by its switches or by LSS):

1. `compare 23 --with node23.dcf` lists what differs between the new device and the backup. Writable and constant objects are compared; `--read-only` adds measured values. `--with-config` compares with what the configuration writes at boot, `--with-eds-defaults` with the EDS defaults (what was changed on the device).
2. `restore 23 node23.dcf --dry-run` shows the plan, then `restore 23 node23.dcf` writes it after asking (`--yes` skips the question). It writes only values that differ, only objects that are writable in 0x2000-0x9FFF (`--include-comm` adds 0x1000-0x1FFF), and never 0x1010/0x1011, PDO objects (0x1400-0x1BFF), program download objects (0x1F50-0x1F57), objects the configuration writes at boot or objects a write SDO variable owns: those come from the configuration at the next boot anyway. A device with a different vendor ID or product code is refused (`--ignore-identity` overrides); a different revision is a warning.
3. Some devices only accept parameters in PRE-OPERATIONAL and abort with 0x08000022 ("because of the present device state"). Use `--hold-preop`: the node is held in PRE-OPERATIONAL as an operator hold while writing and started again afterwards, also when a write fails. If the connection drops in between, the node stays held; release it with `nmt 23 start` or the START button.
4. The restored values are in the device's RAM only. `store 23` writes "save" to 0x1010 sub 1 (all parameters, or `--subindex N`), after asking. Storing is never part of restore, so flash is written only when you ask for it.

## Protocol

TCP, one JSON object per line (UTF-8, newline-terminated, at most 16 KiB) each way. Every request may carry an `id` (any JSON value), which its answer echoes. Answers are `{"id": ..., "ok": true, "result": {...}}` or `{"id": ..., "ok": false, "error": "reason"}`, in request order.

The first line must be the hello:

```json
{"op": "hello", "token": "the token", "id": 1}
```

A wrong token closes the connection without an answer. The answer carries `protocol` (1), `version`, `allow_changes` and `master_node_id`. Then:

| `op` | Fields | Result |
|---|---|---|
| `status` | | as above |
| `emcy` | `node` | `node_id`, `emcy` list |
| `sdo_read` | `node`, `index`, `subindex`, `timeout_ms` | `success`, `data` (hex bytes such as `"1E 00"`) and `size`, or `abort_code`, `abort_code_hex` and `error` |
| `sdo_write` | `node`, `index`, `subindex`, `data`, `timeout_ms` | `success`, or as for a read |
| `nmt` | `node`, `command` (`start`, `stop`, `preop`, `reset`, `reset-comm`) | `note` when the node has not booted yet |
| `scan` | | starts a scan (unless one runs) and returns its progress |
| `scan_status` | | `running`, `done`, `total`, and once finished `finished_at`, `seconds` and `nodes` |
| `lss_find` | `vendor_id` and `product_code` (optional, together) | starts a search (unless one runs) and returns its progress |
| `lss_find_status` | | `running`, `seconds`, and once finished `found`, `device` (`vendor_id`, `product_code`, `revision_number`, `serial_number`, `node_id`) and `error` when the search failed |
| `lss_inquire` | `vendor_id`, `product_code`, `revision_number`, `serial_number` | `node_id` (255: none), `configured` |
| `lss_set_id` | the address, `node`, `store` (default false) | `node_id`, `previous_node_id`, `had_node_id`, `note`, `stored` |
| `lss_set_bitrate` | the address, `bitrate_kbit`, `store` (default false) | `bitrate_kbit`, `note`, `stored` |

| `trace_start` | `filters` (optional list of `{"id", "mask"}`, at most 16), `error_frames` (default false) | `next` (the sequence number to fetch after), `buffer_frames` (65536), `record_size` (24), `interface`, `bitrate` |
| `trace_fetch` | `after` (the last sequence number received), `max` (1-4000, default 2000) | `count`, `next`, `more` (more frames are waiting), `lost` (frames the ring overwrote before this client fetched them), `kernel_drops` (frames the kernel dropped since tracing started), `session`, `frames` |
| `trace_stop` | | ends this client's trace |
| `sim_status`, `sim_get`, `sim_set`, `sim_override`, `sim_release`, `sim_source`, `sim_fault`, `sim_clear`, `sim_scenario_list`, `sim_scenario_start`, `sim_scenario_stop`, `sim_check_expr` | see [simulator.md](simulator.md#control-protocol) | the plugin's simulated devices; `nothing simulated` when the config simulates nothing, `node N is not simulated` for a node it does not simulate |

Numbers may also be given as strings (`"0x1018"`). `sdo_write`, `nmt`, the `lss_` ops except `lss_find_status`, and the `sim_` ops except `sim_status`, `sim_get`, `sim_scenario_list` and `sim_check_expr` answer `changes not allowed` unless the config has `allow_changes: true`. Requests other than `status` answer `no bus` while there is no CANopen session.

### Trace records

`frames` is base64 of `count` records of 24 bytes each, little-endian, oldest first:

| Offset | Size | Field |
|---|---|---|
| 0 | 8 | time stamp, microseconds since 1970 (UTC), from the kernel (`SO_TIMESTAMP`) |
| 8 | 4 | CAN ID with the SocketCAN flags: bit 31 extended frame, bit 30 remote request, bit 29 error frame (the ID bits then hold the error class) |
| 12 | 1 | DLC |
| 13 | 1 | flags: bit 0 sent from the PLC's computer (Tx: by the plugin, or by another program on it such as `cansend`), bit 1 gap: the capture restarted (after the interface went down or the session restarted); a gap record carries no frame |
| 14 | 2 | reserved, 0 |
| 16 | 8 | data, unused bytes 0 |

A trace ends when its client sends `trace_stop`, disconnects, or sends no `trace_fetch` for 10 seconds (`trace_fetch` then answers `no trace running`); the plugin logs each start and end. `trace_start` answers `no bus` while there is no CANopen session, and the capture is reopened with a gap record when the session comes back. Trace requests are served by the diagnostics server's own thread from its ring; they never wait on the CAN thread. Fetching every 100 ms keeps up with a fully loaded 1 Mbit/s bus (about 8000 frames per second).

## Security

- The channel is plain TCP: anyone who can watch the network can read the token. Use it on a trusted plant or lab network, not across the internet.
- Read-only is the default. With `allow_changes`, anyone with the token can write any object of any node, stop or reset configured nodes, and change any LSS device's node ID or bit rate; leave it off outside commissioning.
- Set `bind` to the PLC's address on the network the engineering PC uses, so the port is not open on other networks the PLC is connected to, or firewall port 7531 so only the engineering PCs reach it.
- The token's hash is in `canopen.json`, which travels with the project; the token is not. Use a random token (the configurator makes one of 192 bits); a short word can be found from its hash.
- A trace shows every frame on the bus, the same kind of data `status` and SDO reads already give a token holder. A capture filter limits bandwidth; it is not access control.
- At most 4 clients at a time; a fifth gets `too many clients`. A tracing configurator or CLI uses one of them. A client must send its hello within 10 seconds, and one that stops reading its answers is disconnected. Wrong tokens are logged, at most once a minute per address.
- A port that is in use is logged and retried every 10 seconds; CANopen runs regardless.
