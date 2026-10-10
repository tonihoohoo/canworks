## Context

What exists today:

- **Diagnostics channel** (`plugin/src/can/diag.h`, `diag.cpp`): `DiagServer` runs its own thread with a non-blocking poll loop, TLS over memory BIOs (`secure_channel.h`), a SCRAM-SHA-256-PLUS login and one JSON object per line. Requests that need the bus become a `DiagRequest` and go through the network's `DiagHub` to the bus thread, which polls the hub on its request timer and answers through it; the server thread never touches a `Network`, the bus thread never blocks on a socket. Guards are split: `allow_changes` is checked on the server thread, the "node is OPERATIONAL, force needed" checks on the bus thread, which knows the states. Manual SDOs queue behind a node's boot configuration and SDO variables; NMT commands set operator holds; LSS has one operation at a time per network, shared with the boot-time LSS assignment. At most 4 clients, 16 KiB lines, 256 KiB output cap per client.
- **Engine** (`engine.cpp`): one `DiagServer` for all networks, created when the first network's master has `diagnostics`. The OpenPLC plugin and `canworks-bridge` both run the `Engine`; the bridge only adds a `DiagHost` (name, status part, config upload).
- **Lely CANopen** is built by `scripts/build-lely.sh` at the pinned ref `88848aa2`, configured with `--disable-python --disable-tests --disable-unit-tests` only, so the gateway parts are built into `liblely-co`. The plugin links `liblely-coapp liblely-co liblely-io2 liblely-ev liblely-util liblely-libc` through pkg-config (`plugin/CMakeLists.txt`). At that ref:
  - `lely/co/gw_txt.h` implements CiA 309-3 version 2.1 (`CO_GW_TXT_IMPL_HI 2`, `_LO 1`): `co_gw_txt_create()`, `co_gw_txt_send(gw, begin, end, at)` parses text and calls the send function with a `struct co_gw_req`, `co_gw_txt_recv(gw, srv)` formats a confirmation or indication and calls the receive function with the text, `co_gw_txt_pending()` counts unconfirmed requests. Pure C, no CAN access, no locking (one object per thread).
  - `lely/co/gw.h` implements CiA 309-1 version 2.0 (`co_gw_create`, `co_gw_init_net(gw, id, nmt)`, `co_gw_recv`), with `CO_GW_NUM_NET` 127 and services for SDO, PDO, NMT, error control, EMCY, LSS and Lely extensions (`_lss_fastscan`, `_sync`, `_time`, `_boot`).
- **Gateway naming:** `canopen-gateway` already means the CANopen-to-CANopen gateway (`gateway.h`, `GatewayLink`). This change is a different thing and is called the *CiA 309-3 gateway* (`cia309`) everywhere: config key, files, docs.
- **Unmerged `add-remote-access`** (branch `propose/add-remote-access`): `canworks-link` forwards connections from paired PCs to the local diagnostics port (7531) and the runtime's HTTPS port only, and adds `diagnostics.remote_link` to the config parser.

## Goals / Non-Goals

**Goals:**
- A tool that speaks CiA 309-3 over TCP reaches every CANopen master network of a plugin or bridge without any canworks code, at least from the PLC's own computer.
- From other machines, the same protection as the diagnostics channel: encrypted, token never on the wire, the same login.
- The gateway can do nothing the diagnostics channel would refuse; one set of rules, one place that enforces them.
- No influence on the PLC scan, PDO timing or supervision, whatever clients do.
- Reuse Lely's tested CiA 309-3 text parser and formatter instead of writing one.

**Non-Goals:**
- CiA 309-2 (Modbus TCP mapping) or CiA 309-4 (PROFINET); Modbus is `canworks-bridge`'s register map.
- Configuring the master through the gateway (`init`, `set id`, `set heartbeat`, guarding, `set rpdo`/`set tpdo`): the config is the only source of the network's setup.
- Writing PLC-owned process data (`w p`).
- J1939 or plain CAN networks (they answer `ERROR: 106`); raw frames stay `send_frame`.
- A second authentication scheme for third-party TLS clients (see open questions).

## Decisions

### 1. Lely's text layer with our own service dispatcher, not Lely's `co_gw_t`

Per session the gateway thread owns one `co_gw_txt_t`. Received bytes are split into lines and fed to `co_gw_txt_send()`; its send function receives the parsed `co_gw_req` and hands it to `Cia309Dispatch`, which turns it into one or more `DiagRequest`s on the right network's `DiagHub` and remembers the request's `data` pointer and sequence. When the hub answers, the dispatcher builds the matching `co_gw_con_*` (or an `co_gw_con` with an internal error code) and calls `co_gw_txt_recv()`, whose receive function appends the text to the session's output. Unsolicited events become `co_gw_ind_*` the same way. Syntax errors are answered by Lely itself (`ERROR: 101`).

Alternative considered: **Lely's full gateway (`co_gw_init_net` on the master's `co_nmt_t`)**, as `coctl` does. Rejected after reading `src/co/gw.c` at the pinned ref:
- for SDO to other nodes it creates a new client SDO per request with `co_csdo_create(net, NULL, id)`, on the node's default SDO channel, beside the coapp master's own transfers: a gateway read during a boot configuration or an SDO variable transfer would interleave segments on the same COB-IDs and abort both;
- it installs its own (chained) `cs`, `ng`, `lg`, `hb`, `st`, `boot` and `dn`/`up` indications on the `co_nmt_t` that the coapp master owns, and its `up_ind` saves the wrong previous handler;
- NMT commands go straight to `co_nmt_cs_req`, past the operator/program hold logic and the force checks; `set id`, `init`, `set heartbeat` and PDO configuration would change the running master;
- it must run on the bus thread's loop, so every client line would be parsed there.

Using only `gw_txt` keeps the bus thread untouched by text and lets every request take the diagnostics channel's path. CMake checks `co_gw_txt_create` with `check_symbol_exists`; a Lely build without it (a distro package configured with the gateway off) builds the plugin without the CiA 309-3 gateway, and a config with `cia309` is then rejected with "this build's Lely CANopen has no CiA 309-3 text gateway (co_gw_txt)".

### 2. Config

```json
"cia309": {
  "port": 7533,
  "bind": "127.0.0.1",
  "max_clients": 4,
  "allow_changes": false,
  "allow_force": false,
  "nets": { "1": "io", "2": "drives" },
  "default_net": 1
}
```

Top-level in a version 2 file, `master.cia309` in version 1. `port` 1024-65535 (default 7533, next to 7531 diagnostics and 7532 standalone simulator), `bind` `127.0.0.1` or `::1` only, `max_clients` 1-16, `nets` optional, `default_net` optional (the session's default network before `set network`). `port: 0` opens no plain port (tunnel sessions only). The bridge reads the same object. Unknown fields and a non-loopback `bind` reject the config, naming the field.

### 3. Two ways in: loopback plain port, and a switch on the diagnostics channel

CiA 309-3 has no authentication and no encryption. Plain TCP is therefore served on loopback only. That covers scripts on the device and anyone with SSH access (an SSH local forward is already authenticated and encrypted).

From other machines a client uses the diagnostics channel: TLS, the SCRAM login with the existing `token_verifier`, then `{"op": "cia309", "id": ...}`. The answer is `{"ok": true, "result": {"protocol": "CiA 309-3", "version": "2.1", "nets": [...]}}` as the last JSON line; from the next byte on, the connection carries CiA 309-3 lines inside the same TLS session until it closes. `DiagServer` hands the client (socket, `TlsConn`, peer) to `Cia309Server` through a queue and forgets it, so the session leaves the diagnostics limit of 4 and counts towards `cia309.max_clients`. The op is refused with `cia309 gateway not configured` without a `cia309` object, and with `too many gateway clients` at the limit.

`canworks-diag gateway --listen 127.0.0.1:7533` runs on the PC: for each local connection it opens a diagnostics connection, logs in, sends the `cia309` op and then copies bytes both ways. Any CiA 309-3 tool on the PC connects to `127.0.0.1:7533` and needs no token. `--exec LINE` sends lines and prints the answers; with no option it is an interactive prompt.

Alternatives considered:
- **A plain port on any address**: anyone on the network could stop nodes. Rejected.
- **A separate TLS port with a token line**: the client cannot check the plugin's ephemeral certificate, so a machine in the middle would read the token. Rejected; the diagnostics login already solves this.
- **A separate TLS port with client certificates pinned in the config**: no secret on the wire and works with generic TLS tunnels, but it is a second key management scheme. Recorded as an open question, not built now.

The remote link of `add-remote-access` forwards the diagnostics port, so `canworks-diag gateway --runtime NAME` works over it unchanged; the loopback port is never forwarded.

### 4. Network numbering

CiA 309 network numbers are 1-127. Without `nets`, network *n* is the *n*-th network of the config in config order, the order of the diagnostics hello and of the Modbus control block's network index (+1). Networks that are not CANopen master networks keep their number but answer `ERROR: 106`, except a slave network, which serves SDO to its own node ID from the local dictionary with the rules of the diagnostics "own dictionary" view. With `nets`, only the listed numbers exist. Net 0 in a request means the session's default network (`set network`, else `default_net`, else `ERROR: 104`). The plugin logs the numbering when the gateway opens; `canworks-diag gateway --list` and the HTML network docs show it.

### 5. Services and how they map

| CiA 309-3 | canworks | Guard |
|---|---|---|
| `r <idx> <sub> <type>` (SDO upload) | `sdo_read`, the value formatted by Lely for the type | none |
| `w <idx> <sub> <type> <value>` (SDO download) | `sdo_write` | `allow_changes`; `allow_force` for a configured OPERATIONAL node |
| `set sdo_timeout <ms>` | session timeout, clamped to 10-10000 ms | none |
| `start`, `stop`, `preop`, `reset node`, `reset comm` | `nmt` per configured node; node 0 = each configured node | `allow_changes`; `allow_force` for anything but start to an OPERATIONAL node |
| `r p <pdo>` (read PDO data) | new hub op `pdo_read`: the last values the master received in that node TPDO | none |
| `lss_switch_glob 0` | all devices to LSS waiting | `allow_changes` |
| `lss_switch_sel <vendor> <product> <rev> <serial>` | remembered per session (selects nothing on the bus yet) | `allow_changes` |
| `lss_set_node <id>` | `lss_set_id` with the selected address, `store` false | `allow_changes`; node ID of the master or of a booted configured node refused |
| `lss_conf_bitrate 0 <index>` | `lss_set_bitrate` with the selected address | `allow_changes` |
| `lss_store` | new hub op `lss_store` (select, store, waiting) | `allow_changes` |
| `lss_get_node`, `lss_inquire_addr` | `lss_inquire` | `allow_changes` (LSS frames are sent) |
| `_lss_fastscan` (Lely extension) | `lss_find` | `allow_changes` |
| `set network`, `set node`, `info version`, `set command_timeout` | session state, answered on the gateway thread | none |
| `lss_switch_glob 1`, `lss_activate_bitrate`, `init`, `set id`, `set heartbeat`, guarding and heartbeat enable/disable, `set rpdo`, `set tpdo`, `w p`, `_sync`, `_time`, `_boot` | not served: `ERROR: 100`, with the reason in the log | |

PDO numbers in `r p` are the gateway's virtual RPDO numbers: node *k*'s TPDO *n* (1-4) is RPDO (*k* − 1) × 4 + *n*, so a number never moves when nodes are added (127 × 4 = 508 fits the CiA 301 range). Only TPDOs of configured nodes that the master maps can be read; any other number answers `ERROR: 102` with "PDO not configured" in the log.

A refusal for a guard answers `ERROR: 102` ("request not processed due to internal state") and logs `cia309 PEER: REQUEST refused: REASON`, the same reason text the diagnostics channel answers. Every SDO download, NMT and LSS command carried out is logged with the client's address, prefixed `cia309`, like diagnostics changes.

Why `allow_force` instead of a per-request force: CiA 309-3 lines have no field for it, and adding a canworks token to the syntax would break the "any standard tool" goal. A gateway for a test bench where the PLC is the machine controller can set it; the default keeps the machine safe.

### 6. Notifications

The bus thread already records EMCYs (history), NMT state changes and heartbeat loss per node. A new `DiagHub` event queue (bounded, 1024 entries, under a short mutex like `GatewayLink`'s EMCY queue) receives them when at least one gateway session is open (an atomic flag; nothing is recorded otherwise). The gateway thread fans them out: EMCY as `<net> <node> EMCY <code> <register> <5 bytes>`, boot-up as `<net> <node> BOOT_UP` (when the session has boot-up indication on, the CiA 309-3 default), node state changes and heartbeat loss as error control indications, all formatted by Lely from `co_gw_ind_*`. A session that is behind on notifications loses the oldest; the next line it gets says how many were lost (a canworks comment line starting with `#`, which CiA 309-3 parsers skip). The bus thread never waits for the queue.

### 7. Threads, limits, scan independence

`Cia309Server` runs one thread with a poll loop, like `DiagServer`, for the plain listener and the handed-over TLS sessions. Per session: at most 8 commands outstanding (more answer `ERROR: 102`), commands answered in the order sent, one at a time per session on the bus thread, line limit 16 KiB, output cap 256 KiB (over it for 10 s: closed), command timeout default 5 s (`set command_timeout`), after which the session answers `ERROR: 103` and drops the late answer. Loopback sessions have no idle timeout (a SCADA connection stays open); tunnelled sessions follow the diagnostics channel's TLS rules. A full `max_clients` closes new plain connections with one `ERROR: 102` line. Nothing in the gateway runs on the PLC scan hooks; the bus thread only sees `DiagRequest`s it already serves.

### 8. Bridge

`canworks-bridge` runs the same `Engine`, so it gets the gateway with no code of its own besides its status part (gateway sessions with address and request count). Gateway requests do not feed and do not end the Modbus output watchdog; NMT commands from the gateway follow the same rules as those from the Modbus control block.

### 9. Tests

- Unit (`test/unit`): every served service parsed by Lely and dispatched to a fake `DiagHub`, answers formatted back (text in, text out); every refused service; guards with and without `allow_changes`/`allow_force`; network numbering with and without `nets`; limits (outstanding commands, line length, output cap); the event queue under overflow.
- Integration (`test/cia309/run.sh`, a CI step next to `test/lss/run.sh`): the plugin on vcan with the device simulator and a Python client (`tools/deploy/canworks/cia309.py`, standard library only) over the loopback port and through `canworks-diag gateway`; SDO read and write, NMT with holds, `r p`, EMCY from the simulator, LSS on the simulator's unconfigured device, refusals; and the bridge with `examples/modbus-bridge` the same way while a Modbus client keeps writing (watchdog unaffected).
- PLC timing: the existing scan-time check of the trace test, repeated with 4 gateway clients reading in a loop.

## Risks / Trade-offs

- [Lely's `gw_txt` may format or parse a corner differently from other CiA 309-3 implementations] → it is the reference used by `coctl`; the unit tests pin the exact lines we promise in the docs; bugs found go upstream or into a thin pre/post filter.
- [`allow_force` is coarse: one switch for all clients] → off by default, logged per use, documented as test-bench only.
- [Virtual PDO numbers differ from the master's real RPDO numbers in its DCF] → documented and listed; real numbers would move when the config changes.
- [Event queue adds work on the bus thread] → only while a session is open; one mutex push per event, no formatting there.
- [A local process on the PLC computer can use the plain port without a token] → loopback only, opt-in, `allow_changes` off by default; anyone with a shell there can already reach the CAN interface.

## Migration Plan

Nothing to migrate: the gateway is off without `cia309`. Rollback is removing the object; an older plugin rejects a config with `cia309` as an unknown field, so the plugin and the PC tools are updated together (deploy tool version bump).

## Implementation notes (defaults picked)

- **Open questions 1, 3, 6, 7: the safer option, nothing new built.** No client-certificate TLS port; `w p` always `ERROR: 100`; no configurator console (`canworks-diag gateway` is the prompt); `_sync`, `_time` and `_boot` are not even parsed as services by Lely at the pinned ref, and anything it parses that is not in the table answers `ERROR: 100`.
- **Open question 2: one `allow_force` switch**, off by default, as designed.
- **Open question 4: virtual numbers** (node − 1) × 4 + n, as designed; the network docs show them at each TPDO.
- **Open question 5: 7533 on loopback when `cia309` is present** (the gateway is opt-in already; `port: 0` turns the plain port off).
- **Open question 8: Lely's text is kept verbatim** and the lost-notifications line is a `#` comment. The answers, the SDO abort form (`ERROR: 06020000 (...)`, no `0x`), lower-case hex values and the indications (`1 3 EMCY 5030 01 ...`, `1 2 ERRORx STOP`, `1 7 ERROR 203 (Heartbeat lost)`) are Lely's; the spec scenarios were adjusted to them. Output lines end in CR LF; input takes LF or CR LF.
- **Lely parses a single number in front of a node-level command as the node ID**, including `r p` (so `[6] 1 r p 5` uses the default network); `<net> 0 r p n` names the network. Kept as Lely does it.
- **NMT to node 0 is one hub request** (`nmt` with `node` 0, gateway only) instead of one per node, so the "any configured node OPERATIONAL, force needed" guard is checked once on the bus thread and nothing is half done.
- **`lss_switch_glob 0` sends nothing**: every LSS operation of the gateway already ends with all devices in LSS waiting; it only clears the session's selection. A successful `_lss_fastscan` makes the found device the selection. `lss_inquire_addr` confirms the selected device answers and returns the requested part of the selection. `_lss_fastscan` takes vendor ID and product code fixed (masks 0xFFFFFFFF) or free (0), revision and serial masks 0, matching the diagnostics channel's `lss_find`; it waits at least 25 s whatever the command timeout.
- **Hub answers are routed by `from_cia309`**: the hub keeps a second answer list and wake pipe for the gateway thread, so the diagnostics server and the gateway never take each other's answers.
- **Unknown fields in `cia309` are errors** (elsewhere in the config they are warnings), as the spec says; `nets` is refused in a version 1 file; `port` equal to the diagnostics port is refused.
- **The command timeout** is clamped to 100-60000 ms; an SDO command waits at least the SDO timeout + 0.5 s.
- **Scan timing check (7.3)**: the trace test has no scan-time check to repeat, so the integration test runs four sessions reading in a loop and compares the master's SYNC statistics (`late_pdos` unchanged, maximum SYNC interval under three periods) from the diagnostics status.
- **The integration test runs on the simulated bus** (`adapter.simulate`), so it is a ctest test in the plugin job (`cia309_gateway`) rather than a vcan step.

## Open Questions

1. Should a separate TLS port with client certificates pinned by fingerprint (no token) be added for third-party machines that cannot run `canworks-diag gateway`?
2. Is one `allow_force` switch acceptable, or should force be allowed only for some services (SDO writes but not NMT stop)?
3. PDO write (`w p`) for master TPDO entries that have no PLC location and no Modbus location: useful on test benches, or always refused?
4. Virtual PDO numbering ((node − 1) × 4 + n) versus the master DCF's real RPDO numbers: which do target tools expect?
5. Default plain port: 7533 on loopback, or no plain port unless `port` is given?
6. Should the configurator offer a "CiA 309-3 console" (a line prompt over the tunnel), or is `canworks-diag gateway` enough?
7. Lely's `_sync`, `_time` and `_boot` extensions: keep refusing, or serve `_boot` (re-boot a configured node) as an alias of `reset node`?
8. How the notification "lost N" line should look for strict parsers that do not skip `#` lines.
