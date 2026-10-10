# CiA 309-3 gateway

The plugin and `canworks-bridge` can serve their CANopen master networks as a **CiA 309-3 ASCII gateway**: one text line per command (`[1] 1 5 r 0x1018 1 u32`), one line per answer, and unsolicited lines for emergencies, boot-ups and lost nodes. SCADA systems, test benches, shell scripts and other CANopen tools that speak CiA 309-3 reach the network without any canworks code, and a Python script needs nothing but a socket.

It is off unless the config has a `cia309` object. It does nothing the diagnostics channel ([diagnostics.md](diagnostics.md)) would refuse, uses the same bus-thread path, and never touches the PLC scan.

## Configuration

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

A top-level object in a version 2 file, `master.cia309` in a version 1 file. Every field is optional; `"cia309": {}` is a read-only gateway on `127.0.0.1:7533`.

| Field | Meaning |
|---|---|
| `port` | Plain TCP port on the loopback address, 1024-65535 (default 7533). `0`: no plain port, sessions through the diagnostics channel only. Must differ from the diagnostics port. |
| `bind` | `127.0.0.1` (default) or `::1`. Any other address is refused: CiA 309-3 has no login, so the plain port never opens on a network. |
| `max_clients` | Gateway sessions at a time, plain and tunnelled together, 1-16 (default 4). |
| `allow_changes` | SDO downloads, NMT commands and LSS (default false: read-only). |
| `allow_force` | Carry out what the diagnostics channel refuses without `force`: an SDO write to an OPERATIONAL configured node, an NMT command other than start to one (or to node 0 while any is OPERATIONAL). One switch for every client and service; for test benches only (default false). |
| `nets` | Explicit network numbers, `{"<1-127>": "<network name>"}` (version 2 only). Without it network *n* is the *n*-th network of the file. Each network at most one number. |
| `default_net` | The network a command without a network number goes to before the session's `set network`. With one network that network is the default anyway. |

Unknown fields in `cia309` reject the file (elsewhere they are warnings): the gateway opens a port without a login, so a misspelled setting must not pass unnoticed. A plugin built against a Lely CANopen without its text gateway (`co_gw_txt`) rejects a config with `cia309`, saying so; `scripts/build-lely.sh` builds it.

The configurator has a "CiA 309-3 gateway" part under Online access; `canworks-deploy --check` and the configurator's Check apply the same rules. The log names the address, the mode and the numbering when the port opens:

```
CiA 309-3 gateway listens on 127.0.0.1:7533 (loopback only; other machines through the diagnostics channel), read-only; networks 1 = io, 2 = drives
```

## Two ways in

- **The plain port** on the PLC's loopback address: for scripts and tools on the PLC's own computer, or from elsewhere through an SSH local forward (`ssh -L 7533:127.0.0.1:7533 plc`), which is authenticated and encrypted already.
- **Through the diagnostics channel** from other machines: after the usual TLS and SCRAM login, the `{"op": "cia309"}` request switches that connection to CiA 309-3 lines in the same TLS session. `canworks-diag gateway` does this for you on the engineering PC:

```sh
canworks-diag --runtime plc.local gateway --listen          # a local port 127.0.0.1:7533 for CiA 309-3 tools
canworks-diag --runtime plc.local gateway --exec "1 2 r 0x1018 1 u32"
canworks-diag --runtime plc.local gateway --list            # the network numbering
canworks-diag --runtime plc.local gateway                   # an interactive prompt
canworks-diag --runtime plc.local gateway --network drives  # the session's default network
```

With `--listen` each connection to the local port opens its own gateway session; the tool on the PC needs no token. `--listen` refuses an address that is not loopback unless `--listen-any` is given. A runtime whose plugin is too old answers `unknown op`, and the command says so. Over the remote link ([remote-access.md](remote-access.md)) it works the same way, since it only uses the diagnostics port.

A tunnelled session leaves the diagnostics channel's limit of 4 clients and counts towards `max_clients`. A full gateway answers the op `too many gateway clients` (the connection stays a diagnostics one) and a further plain connection one `ERROR: 102` line before it is closed.

## Network numbering

CiA 309 network *n* is the *n*-th network of the config (config order, from 1: the order of the diagnostics hello and the Modbus control block's network index + 1), or the number `nets` gives it. A number that does not exist answers `ERROR: 106`, and so does any command to a J1939 or plain CAN network. A slave network serves SDO to its own node ID from its own dictionary (the diagnostics channel's rules); everything else there answers `ERROR: 107`. `canworks-diag gateway --list`, the configurator and the HTML network documentation ([network-docs.md](network-docs.md)) show the numbering.

A command without a network number uses the session's default (`set network`, else `default_net`, else the only network); without one it answers `ERROR: 104`. Lely's parser reads a single number in front of a node-level command as the node ID (`[1] 5 r 0x1000 0 u32` is node 5 of the default network) and in front of a network-level command as the network (`[1] 2 lss_store`).

## Services

| Command | What happens | Needs |
|---|---|---|
| `r <index> <sub> <type>` | SDO upload, queued behind the node's boot configuration and SDO variables, up to 4096 bytes; the value printed for the type | |
| `w <index> <sub> <type> <value>` | SDO download | `allow_changes`; `allow_force` for an OPERATIONAL configured node |
| `set sdo_timeout <ms>` | the session's SDO timeout, 10-10000 ms (default 1000) | |
| `start`, `stop`, `preop`, `reset node`, `reset comm` | NMT to a configured node, or node 0 for every configured node; stop and preop hold the node, start releases the hold (the operator rules of the diagnostics channel) | `allow_changes`; `allow_force` for anything but start to an OPERATIONAL node |
| `r p <n>` | the values the master last received in node *k*'s TPDO *m* (1-4), *n* = (*k* − 1) × 4 + *m*; no SDO | |
| `lss_switch_glob 0` | clears the session's selection (every LSS operation ends with all devices waiting already) | `allow_changes` |
| `lss_switch_sel <vendor> <product> <revision> <serial>` | remembers the address for the next LSS commands; selects nothing on the bus yet | `allow_changes` |
| `lss_set_node <id>` | configure node ID on the selected device, not stored; not the master's ID, nor that of a booted configured node | `allow_changes` |
| `lss_conf_bitrate 0 <index>` | configure bit timing (CiA 305 table 0, index 0-4 and 6-8), not stored, never activated | `allow_changes` |
| `lss_store` | store configuration on the selected device | `allow_changes` |
| `lss_get_node`, `lss_inquire_addr <0x5A-0x5D>` | inquire the selected device | `allow_changes` (LSS frames are sent) |
| `_lss_fastscan <vendor> <mask> <product> <mask> <rev> <mask> <serial> <mask>` | finds a device without a node ID (Lely's extension); masks 0 or 0xFFFFFFFF for vendor and product, 0 for the rest; the found device becomes the selection | `allow_changes` |
| `set network`, `set node`, `set command_timeout`, `info version`, `boot_up_indication Enable/Disable` | session settings, answered without bus access | |

Each LSS command is one LSS operation of the diagnostics channel: one at a time per network (shared with the master's own assignment), ending with every device in LSS waiting; another running answers `ERROR: 102` with "LSS busy" in the log.

**Not served**, answered `ERROR: 100` and changing nothing: `init`, `set id`, `set heartbeat`, `enable`/`disable guarding` and `heartbeat`, `set rpdo`, `set tpdo`, `w p` (PDO write), `lss_switch_glob 1`, `lss_activate_bitrate`, `lss_identity`, `lss_ident_nonconf`, `_lss_slowscan`. The config owns the network's setup, and the PLC program owns the outputs.

**Answers** are Lely's (CiA 309-3 version 2.1): a value, `OK`, `ERROR: <code> (<text>)` with the internal error codes 100-107, or the SDO abort code in hex (`ERROR: 06020000 (Object does not exist in the object dictionary)`). A guard refusal answers `ERROR: 102` and logs `cia309 <client>: <line> refused: <reason>`, the reason the diagnostics channel would give. Every SDO download, NMT and LSS command carried out is logged with the client's address as coming from the CiA 309-3 gateway.

## Notifications

While a session is open it gets a line for every EMCY of a configured node (`1 3 EMCY 5030 01 0 0 0 0 0`: network, node, code, error register, manufacturer bytes), every boot-up (`1 3 BOOT_UP`, unless `boot_up_indication Disable`), every NMT state change (`1 3 ERRORx STOP`, Lely's form) and every lost heartbeat or node guarding (`1 7 ERROR 203 (Heartbeat lost)`). The bus thread records events only while a session is open and never waits for one. A session more than 1024 notifications behind loses the oldest and gets a comment line `# 12 notifications lost ...`; CiA 309-3 clients skip lines starting with `#`.

## Limits

At most 8 commands outstanding per session, answered in the order sent, one at a time on the bus thread; a ninth answers `ERROR: 102`. A line longer than 16 KiB closes the session. A command the bus thread has not answered within the command timeout (default 5 s, `set command_timeout`, 100-60000 ms; an LSS search waits at least 25 s) answers `ERROR: 103` and its late answer is dropped. A session that leaves more than 256 KiB of answers unread for 10 s is closed; while it is over that limit nothing more is read from it. Plain sessions have no idle timeout.

## Examples

A Python script on the PLC:

```python
import socket
s = socket.create_connection(("127.0.0.1", 7533))
s.sendall(b"[1] 1 2 r 0x1018 1 u32\r\n")
print(s.recv(256).decode())   # [1] 0x000001a2
```

The deploy tool's own client, standard library only (`canworks.cia309`), also works through a logged-in diagnostics connection:

```python
from canworks import cia309, diag
c = diag.Client("plc.local", token="...")
c.connect()
g, info = cia309.Client.tunnel(c)
g.command("1 2 r 0x1008 0 vs")
```

## Modbus bridge

`canworks-bridge` serves the same gateway next to its Modbus TCP server ([modbus-bridge.md](modbus-bridge.md#cia-309-3-gateway)). Gateway requests neither feed nor end the output watchdog, and the bridge status lists the gateway sessions.

## Security

- The plain port listens on loopback only, and only with `cia309` in the config. Anyone with a shell on the PLC computer can use it without a token; they can reach the CAN interface anyway.
- From other machines the gateway is reached only through the diagnostics channel: TLS, the SCRAM login, the token never on the wire.
- `allow_changes` and `allow_force` are off by default and apply to every client of the gateway; `allow_force` lets a standard tool stop nodes the program drives.
