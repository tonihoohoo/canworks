# Online diagnostics

The plugin can open a small encrypted channel (TLS) that shows the live CANopen network to the engineering PC: node states, boot results and errors, emergency history, SDO variable values, the bus state. With permission it also reads and writes any object by SDO, sends NMT commands, scans the bus for devices, and sets node IDs and bit rates of devices with LSS. The configurator's [online view and scan page](configurator.md#online-view) and the `openplc-canopen-diag` command use it.

With permission it can also send raw CAN frames by hand and find the bit rate of an unknown bus ([Raw frames and bit rate](#raw-frames-and-bit-rate)).

It is off unless the config has `master.diagnostics` ([config.md](config.md#online-diagnostics)). The plugin listens only while the PLC runs, and nothing a client does touches the PLC scan: every request is served by the CAN thread between its own work (trace requests by the diagnostics thread), and a slow or stalled client is cut off instead of waited for.

## Setting it up

1. In the configurator, turn on **Online access** under **Bus and master**, save, and upload the program as usual. Or, by hand: choose a token, run `openplc-canopen-diag hash-token` and put the printed verifier in `master.diagnostics.token_verifier`.
2. The runtime log shows `diagnostics listen on 0.0.0.0:7531, read-only, encrypted (TLS)` when the PLC starts.
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
openplc-canopen-diag --runtime plc.local send 0x60A "40 18 10 01 00 00 00 00"    # needs allow_changes; see below
openplc-canopen-diag --runtime plc.local send 0x123 AA 55 --period-ms 100 --count 50  # cyclic
openplc-canopen-diag --runtime plc.local detect-bitrate [--rates 125,250,500]     # needs allow_changes
openplc-canopen-diag hash-token                                                       # prints a token_verifier
```

With several CAN networks ([config.md](config.md), `schema_version: 2`) every command that talks to the plugin takes `--network NAME`. `status` without it prints every network one after another, each headed by its name and interface; every other command without it exits with status 1 naming the networks. With one network `--network` may be left out, and an older plugin, which knows no networks, ignores it.

On a slave network ([slave.md](slave.md#diagnostics)) `status` prints the plugin's own device instead of a master and nodes: its node ID (or that it waits for LSS), NMT state, communication OK, SYNC count, EMCY code and error register, each TPDO and RPDO in force with its COB-ID, transmission type and mapped objects, and on a gateway's upper network the gateway's route count, whether the upper master is there and the active forwarded errors. `sdo-read` and `sdo-write` with the slave's own node ID read and write its dictionary; the other commands exit with status 1 saying that they need a master network.

```sh
openplc-canopen-diag --runtime plc.local status                                   # every network
openplc-canopen-diag --runtime plc.local status --network drives
openplc-canopen-diag --runtime plc.local sdo-read 2 0x1018 1 --network drives      # node 2 on drives, not on io
openplc-canopen-diag --runtime plc.local backup 2 --network drives                 # drives' node 2 EDS and bit rate
openplc-canopen-diag --runtime plc.local trace -o drives.pcapng --network drives --config canopen/canopen.json
```

`--runtime` takes `HOST` or `HOST:PORT` (default port 7531), or `local` for the [local simulator runtime](local-runtime.md) on this PC (`localhost` and the diagnostics port it publishes; the token comes from the project as for any runtime). `status` says when the runtime forces every network simulated (`simulation forced by the runtime`). Types are the CiA 301 names (`UNSIGNED16`, `INTEGER32`, `REAL32`, `VISIBLE_STRING`, `OCTET_STRING`, ...); `sdo-read` without `--type` prints hex bytes, and `sdo-write` takes hex bytes for `OCTET_STRING` and `DOMAIN`.

### Through a USB adapter on this PC: `--adapter`

With `--adapter TYPE:CHANNEL` in place of `--runtime` the commands go straight to the bus through a CAN adapter on the PC, with no runtime and no token ([pc-adapter.md](pc-adapter.md)):

```sh
openplc-canopen-diag adapters                                                      # what is plugged in
openplc-canopen-diag --adapter slcan:COM5 --bitrate 250 status
openplc-canopen-diag --adapter slcan:/dev/tty.usbmodem14101 --bitrate 250 scan --config canopen/canopen.json
openplc-canopen-diag --adapter socketcan:can0 --bitrate 500 --allow-changes sdo-write 5 0x2000 2 1000 --type UNSIGNED16
openplc-canopen-diag --adapter slcan:COM5 backup 5 --config canopen/canopen.json --network io
```

| Option | |
|---|---|
| `--adapter TYPE:CHANNEL` | `slcan:PORT` (Windows, macOS, Linux) or `socketcan:IFACE` (Linux); other python-can types are passed through untested. Not together with `--runtime`. |
| `--bitrate KBIT` | the bus's bit rate; without it, the network's `adapter.bitrate` from `--config`. There is no default. |
| `--adapter-option KEY=VALUE` | passed to python-can when opening the adapter, repeatable. |
| `--allow-changes` | allows SDO writes, NMT, restore and LSS for this command; without it the adapter only reads. `store` still asks. |
| `--force` | runs LSS, and `lss-set-id` with a node ID the bus already shows, while another master is active. |

What differs from a runtime:

| Command | Through a runtime | Through an adapter |
|---|---|---|
| `status` | master, bus state and counters, boot results, SDO variables | what the bus showed since connecting: node states from heartbeats, the last EMCY per node, the configured nodes from `--config`, and another master when one is active |
| `emcy` | the plugin's history since the PLC started | the EMCY messages seen since connecting |
| `nmt` | configured nodes | any node ID, one at a time |
| `scan`, `sdo-read`, `sdo-write`, `backup`, `compare`, `restore`, `store` | as described above | the same; `backup` does not ask whether the node has booted |
| `lss-*` | the plugin runs them | the PC runs them; refused while another master is active unless `--force` |
| `trace` | the runtime's interface | the adapter |
| `sim` | the plugin's simulated devices | not available |

### Simulated devices: `sim`

`openplc-canopen-diag sim ...` controls [simulated devices](simulator.md): the plugin's, with `--runtime HOST` (token as above; everything but `status`, `get` and `scenario list` needs `allow_changes`), or a standalone `openplc-canopen-sim`, with `--sim HOST[:PORT]` (default port 7532; token only when the simulator has one, from `--token` or `--token-file`). Without either it talks to the standalone simulator on `127.0.0.1:7532`. With several networks, `--network NAME` after `sim` picks the network whose simulated devices to talk to. These options may also follow the subcommand.

```sh
openplc-canopen-diag --runtime plc.local sim status
openplc-canopen-diag --runtime plc.local sim get 5 0x7130:1 0x7130:2           # or: get 5 --pdo
openplc-canopen-diag --runtime plc.local sim set 5 0x7130:1 450                # once; a value source moves it again
openplc-canopen-diag --runtime plc.local sim override 5 0x7130:1 1500          # held until released
openplc-canopen-diag --runtime plc.local sim release 5 [0x7130:1]              # without objects: all of node 5
openplc-canopen-diag --runtime plc.local sim source 5 0x7130:2 '{"sine": {"min": 200, "max": 260, "period_s": 10}}'
openplc-canopen-diag --runtime plc.local sim source 5 0x7130:2 none
openplc-canopen-diag sim fault 5 emcy 0x5000 --register 1 --runtime plc.local
openplc-canopen-diag --runtime plc.local sim clear 5 emcy                      # or: clear 5 all
openplc-canopen-diag --runtime plc.local sim status --network drives          # one of several networks
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

- **Status**: plugin version, time since the CANopen session started, the SHA-256 of the loaded `canopen.json`, the master's node ID and NMT state, the bus state and error counters (whether or not their PLC locations are configured), the SYNC source (`none`, `timer` with `period_us`, or `plc_cycle` with `cycles`) with the number of SYNCs sent, the last, shortest and longest interval between them in microseconds, cycles merged into one SYNC (`skipped`) and late synchronous PDOs (`late_pdos`, see [config.md](config.md#sync-from-the-plc-cycle)), `simulated_network` (true when `adapter.simulate` is on), and per configured node whether it is `simulated` (false, with `sim_conflict` true, when it is marked simulated but a real device on the bus already uses its node ID), its NMT state, status bit, whether it booted, the boot error letter with Lely's text, whether a boot retry is pending, the hold in force and who set it, its last EMCY and how many it sent, each SDO variable's raw value, status and abort code, and `pdo_timeouts`: one entry per TPDO with a [receive timeout](config.md#receive-timeout) giving `tpdo`, `timeout_ms`, `timed_out`, `count` (timeouts so far) and `since_ms` (time since its last PDO, `null` before the first), and for a cyclic CiA 402 axis the interpolation time period the plugin wrote to 0x60C2 (`interpolation_period_us`, see [cia402.md](cia402.md#cyclic-synchronous-modes)). The CLI prints these as `node 23 TPDO 1: TIMED OUT (timeout 200 ms, 2 timeout(s), last PDO 1800 ms ago)`. Between CANopen sessions (interface missing or down) the answer has `"session": false`, bus state 0 and every node 0.
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

- **Raw frames and bit rate detection** (both need `allow_changes`): see [Raw frames and bit rate](#raw-frames-and-bit-rate).

- **Device parameters** (`backup`, `compare`, `restore`, `store`): see [Replacing a device](#replacing-a-device). They run on the PC over the SDO read and write above, one SDO at a time, so they need no newer plugin. The node's EDS comes from `--config canopen.json` (default `canopen/canopen.json` when it exists) or `--eds FILE` for a node that is not configured. With several networks, `--network NAME` picks both the network the SDOs go to and the node's EDS, name and bit rate from that network of the config; a config with several networks needs it even when the runtime runs one.

- **Several networks**: one channel serves all networks of the config, with one port, one token, one `allow_changes` and one client limit. Each request acts on one network. Scans, LSS requests, traces, holds, EMCY history and `no bus` are per network: a scan on one network does not make a scan on another answer busy, and a network whose interface is missing answers `no bus` while the others answer normally.

## Replacing a device

Before a device breaks, back it up: `backup` reads every object its EDS lists as readable (`ro`, `rw`, `rwr`, `rww`, `const`; DOMAIN objects are left out) and writes a CiA 306 DCF: the EDS with a `ParameterValue` for each value, the identity from 0x1018, and `[DeviceComissioning]` with the node ID, name and bit rate. Objects that could not be read are listed at the top of the file with their abort code. A few hundred objects take a few seconds. A read that gets no answer three times in a row stops: the node is STOPPED or gone. The configurator's online view has the same as **Back up**, and other CANopen tools open the file.

After swapping the device (same node ID, set by its switches or by LSS):

1. `compare 23 --with node23.dcf` lists what differs between the new device and the backup. Writable and constant objects are compared; `--read-only` adds measured values. `--with-config` compares with what the configuration writes at boot, `--with-eds-defaults` with the EDS defaults (what was changed on the device).
2. `restore 23 node23.dcf --dry-run` shows the plan, then `restore 23 node23.dcf` writes it after asking (`--yes` skips the question). It writes only values that differ, only objects that are writable in 0x2000-0x9FFF (`--include-comm` adds 0x1000-0x1FFF), and never 0x1010/0x1011, PDO objects (0x1400-0x1BFF), program download objects (0x1F50-0x1F57), objects the configuration writes at boot or objects a write SDO variable owns: those come from the configuration at the next boot anyway. A device with a different vendor ID or product code is refused (`--ignore-identity` overrides); a different revision is a warning.
3. Some devices only accept parameters in PRE-OPERATIONAL and abort with 0x08000022 ("because of the present device state"). Use `--hold-preop`: the node is held in PRE-OPERATIONAL as an operator hold while writing and started again afterwards, also when a write fails. If the connection drops in between, the node stays held; release it with `nmt 23 start` or the START button.
4. The restored values are in the device's RAM only. `store 23` writes "save" to 0x1010 sub 1 (all parameters, or `--subindex N`), after asking. Storing is never part of restore, so flash is written only when you ask for it.

## Raw frames and bit rate

### Sending frames by hand

`send ID [DATA]` sends one CAN frame on the network: an SDO request to a device that is not in the config yet, an NMT command, a vendor's test frame. `ID` is the identifier (`0x60A`; up to `0x7FF`, or up to `0x1FFFFFFF` with `--ext`), `DATA` up to 8 bytes in hex (`"40 18 10 01"`, `40181001` or `40 18 10 01`). `--rtr --dlc N` sends a remote frame. With `--period-ms N` (10-60000) the frame is sent again every N ms until `--count` frames, `--duration` seconds or Ctrl-C; the command then stops the job and prints how many were sent.

The plugin sends from its diagnostics thread on a socket of its own, never from the PLC scan. Its own master (or slave) receives the frame like any frame on the bus and acts on it: a boot-up message you send makes the master boot that node, a frame on a node's TPDO changes the PLC's inputs. A trace shows the frame as sent from the PLC (Tx). On a simulated network the frame goes onto the simulated bus.

Guards:

- `allow_changes` must be on; without it every frame is refused with `changes not allowed`.
- `--force` is needed when the identifier is one the configured network uses (NMT, SYNC, TIME, LSS, the master's heartbeat and EMCY, and for every configured node its EMCY, its PDOs, its SDO channels and its heartbeat), and while any configured node is OPERATIONAL. The refusal says which (`0x202 is RPDO1 of node 2 (pingpong) on network can0; force needed`). The bench case, an unconfigured device with nothing running, needs no `--force`.
- At most 50 single frames per second per connection, cyclic periods of 10 ms or more, at most 8 cyclic jobs per network. A cyclic job ends after 10 minutes, when its connection closes, or when a write fails (`transmit queue full`: usually no other device acknowledges the frames).
- Every frame, and every cyclic job's start and end, is logged with the client's address, and forced ones with the reason.

### Finding the bit rate

`detect-bitrate` finds the bit rate of the traffic on the network's bus. The plugin ends the network's CANopen session (the nodes report not operational, the PLC keeps running, other networks are untouched), sets the interface to listen-only mode at each CiA 301 rate in turn (1000, 800, 500, 250, 125, 50, 20 and 10 kbit/s, or `--rates`), counts valid frames, error frames and identifiers for `--per-rate-ms` (default 1000) at each rate, then sets the configured bit rate again and starts a new session: the nodes boot again as after an unplugged adapter. In listen-only mode the adapter sends nothing, not even an acknowledge.

The result is `detected` with the rate where valid frames came with no more than 1 % error frames, and whether it matches `adapter.bitrate`; `ambiguous` when several rates or none clearly match; `silent` when no frame came at all; or `failed` with the reason. A device that has not been configured often sends nothing but its boot-up message: power-cycle or reset one while the sweep runs, or use `--rounds N` to sweep N times. On a bus where the listening adapter is the only other device, the transmitting device gets no acknowledge and repeats its frame until the master is back, which may make it error-passive for a moment.

Guards: `allow_changes`; `--force` while a node of the network is OPERATIONAL (the sweep stops CANopen there); refused on vcan and simulated networks (`no bit rate on a virtual bus`) and on a `socketcan` adapter with `configure_link: false`, whose link the plugin must not change. An adapter whose driver has no listen-only mode ends with `failed` and the configured rate restored; candleLight (gs_usb), MCP2515/MCP2518FD CAN HATs and slcan on Linux 6.1 or later have one.

The command exits 0 only on `detected`. Change `adapter.bitrate` (or use the configurator's **Use N kbit/s**), save and upload to make the network run at the detected rate.

## Protocol

TLS 1.2 or newer, then one JSON object per line (UTF-8, newline-terminated, at most 16 KiB) each way. Every request may carry an `id` (any JSON value), which its answer echoes. Answers are `{"id": ..., "ok": true, "result": {...}}` or `{"id": ..., "ok": false, "error": "reason"}`, in request order.

The plugin makes a new key and self-signed certificate in memory each time it opens the port. Clients do not check the certificate chain and pin nothing; instead the login is bound to the certificate the client received (`tls-server-end-point`, RFC 5929), so a machine in the middle with its own certificate fails the login on both sides. The login is SCRAM-SHA-256 (RFC 5802/7677 math, JSON framing), and the token never crosses the network:

```text
SaltedPassword  = PBKDF2-HMAC-SHA-256(token, salt, iterations)
ClientKey       = HMAC(SaltedPassword, "Client Key")     StoredKey = SHA-256(ClientKey)
ServerKey       = HMAC(SaltedPassword, "Server Key")
AuthMessage     = "openplc-canopen-diag/2," cnonce "," snonce "," salt "," iterations "," cbind
                  (nonces, salt and cbind in base64; cbind = SHA-256 of the server certificate's DER)
ClientProof     = ClientKey XOR HMAC(StoredKey, AuthMessage)
ServerSignature = HMAC(ServerKey, AuthMessage)
```

```json
{"op": "hello", "mech": "SCRAM-SHA-256-PLUS", "nonce": "<18 random bytes, base64>", "id": 1}
{"id": 1, "ok": true, "result": {"protocol": 2, "nonce": "<server nonce>", "salt": "...", "iterations": 4096}}
{"op": "login", "proof": "<ClientProof, base64>", "id": 2}
{"id": 2, "ok": true, "result": {"protocol": 2, "signature": "<ServerSignature, base64>", "version": "...", ...}}
```

A wrong proof closes the connection without an answer; the next login from that address is answered a second later at the earliest. The client checks `signature` before it uses anything else; `openplc-canopen-diag` and the configurator drop a connection whose signature is wrong ("could not prove it knows this project's token"). A connection that does not start with a TLS handshake (a client from before the encrypted channel) gets one line, `this runtime needs an encrypted connection; update openplc-canopen-diag`, and is closed.

The login answer carries `protocol` (2), `version`, `allow_changes`, `master_node_id` (the first network's) and `networks`: the networks in config order, each `{"name", "interface", "bitrate", "role", "master_node_id"}` (a slave network has `"role": "slave"` and `node_id`, null while it waits for LSS, instead of `master_node_id`; see [slave.md](slave.md#diagnostics)), the name empty for a version 1 config.

Every request after the hello may carry `network`, the name of the network it is for. With one network it may be left out. With several, a request without it answers `network required (io, drives)` and one with a name the plugin does not run `unknown network 'x' (io, drives)`. A client sends `network` only when the hello lists more than one network, so it also talks to an older plugin. Then:

| `op` | Fields | Result |
|---|---|---|
| `status` | | as above, with `network` (the network's name) |
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

| `trace_start` | `filters` (optional list of `{"id", "mask"}`, at most 16), `error_frames` (default false) | `next` (the sequence number to fetch after), `buffer_frames` (65536), `record_size` (24), `network`, `interface`, `bitrate` of the traced network |
| `trace_fetch` | `after` (the last sequence number received), `max` (1-4000, default 2000) | `count`, `next`, `more` (more frames are waiting), `lost` (frames the ring overwrote before this client fetched them), `kernel_drops` (frames the kernel dropped since tracing started), `session`, `frames` |
| `trace_stop` | | ends this client's trace |
| `send_frame` | `can_id` (the frame's identifier; `id` stays the request's own), `ext` (default false), `rtr` (default false), `dlc` (remote frames), `data` (hex, 0-8 bytes), `period_ms` (0 or left out: one frame; 10-60000: cyclic), `count` (cyclic, optional), `force` | one frame: `sent`; cyclic: `job`, `period_ms`, `count` |
| `send_frame_stop` | `job` (left out: all of this connection's jobs) | `stopped`: each job's `job`, `id`, `period_ms`, `sent` and `reason` (`stopped`, `count reached`, `time limit`, `transmit queue full`, ...), jobs that ended on their own included |
| `detect_bitrate` | `rates` (kbit/s), `per_rate_ms` (100-10000, default 1000), `rounds` (1-20, default 1), `force` | starts a sweep (unless one runs) and returns its progress as `detect_bitrate_status` |
| `detect_bitrate_status` | | `running`, `configured_kbit`, `rate_kbit` (the rate listened to now), `round`, `done`, `total`, `results` (per rate `bitrate_kbit`, `frames`, `error_frames`, `ids`: the first 16 identifiers), and once finished `verdict` (`detected`, `ambiguous`, `silent`, `failed`), `bitrate_kbit` and `matches_config` (detected), `candidates`, `error` (failed) and `finished_at`; `verdict` null before the first sweep |
| `sim_status`, `sim_get`, `sim_set`, `sim_override`, `sim_release`, `sim_source`, `sim_fault`, `sim_clear`, `sim_scenario_list`, `sim_scenario_start`, `sim_scenario_stop`, `sim_check_expr` | see [simulator.md](simulator.md#control-protocol) | the plugin's simulated devices; `nothing simulated` when the config simulates nothing, `node N is not simulated` for a node it does not simulate |

`send_frame`, `send_frame_stop`, `detect_bitrate` and `detect_bitrate_status` are served by the diagnostics thread and work on master and slave networks. `status` also carries `send_jobs` (the network's cyclic jobs: `job`, `id`, `ext`, `period_ms`, `sent`, `count`, `peer`) and `bitrate_sweep` (`running`). While a sweep runs, the network has no session: requests other than `status` and `detect_bitrate_status` answer `no bus`.

A client traces one network at a time: `trace_start` on another network moves its trace there, and `trace_fetch` for another network than the traced one answers `no trace running`.

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

- The channel is encrypted (TLS) and the login is SCRAM-SHA-256 bound to the TLS certificate: the token never crosses the network, a captured login cannot be replayed, and a machine in the middle can neither read nor change requests. Clients never fall back to an unencrypted connection.
- `canopen.json` holds only the token's verifier (`token_verifier`), which travels with the project. It does not let anyone log in, but like any password hash it lets a short, guessable token be found by trying words; use a random token (the configurator makes one of 192 bits).
- A config from before the encrypted channel has `token_sha256` instead; the plugin refuses it with a message saying to set the token again. In the configurator, **Online access** offers **Upgrade**, which keeps the token when this PC knows it; otherwise use **New token** or **Enter token…**. By hand: `openplc-canopen-diag hash-token` prints a `token_verifier` for a token. An older `openplc-canopen-diag` cannot connect to an updated plugin, and an updated one cannot connect to an older plugin ("too old for encrypted diagnostics"); update both.
- Read-only is the default. With `allow_changes`, anyone with the token can write any object of any node, stop or reset configured nodes, and change any LSS device's node ID or bit rate; leave it off outside commissioning.
- Set `bind` to the PLC's address on the network the engineering PC uses, so the port is not open on other networks the PLC is connected to, or firewall port 7531 so only the engineering PCs reach it.
- Sending frames and bit rate detection need `allow_changes`; frames on identifiers the network uses, and both while a node is OPERATIONAL, also need `force`. A forced frame can disturb a running machine as much as any other device on the bus could. Leave `allow_changes` off outside commissioning.
- A trace shows every frame on the bus, the same kind of data `status` and SDO reads already give a token holder. A capture filter limits bandwidth; it is not access control.
- At most 4 clients at a time; a fifth gets `too many clients`. A tracing configurator or CLI uses one of them. A client must finish its TLS handshake and login within 10 seconds, and one that stops reading its answers is disconnected. Wrong tokens are logged, at most once a minute per address.
- A port that is in use is logged and retried every 10 seconds; CANopen runs regardless.
