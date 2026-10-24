# Commissioning from the PC with a USB CAN adapter

`canworks-diag` and the configurator can talk to the bus straight through a CAN adapter plugged into the PC, with no runtime and no PLC: scan the bus, read and write objects, browse a device's object dictionary, back up, compare and restore parameters, give devices node IDs with LSS, and record a trace. Use it to set up devices on the bench before they go into a machine, to check a device that a PLC does not reach, or on a bus where another master (a PLC, a drive controller) already runs.

The PC is a guest on the bus, not its master. It sends nothing until you act, and never sends heartbeats, TIME, or NMT commands to all nodes, nor SYNC except in a PDO test you start with a SYNC period. It does not configure nodes at boot, run PDOs for a program or simulate devices: that is the bridge's job on the device. It can write a node's configuration to a device once, for a device that keeps its own configuration (see [Commissioning one device](#commissioning-one-device)).

## Adapters

| Adapter | `--adapter` | Windows 10 and 11 | macOS | Linux |
|---|---|---|---|---|
| slcan adapters (CANable and CANable 2.0 with stock firmware, and other USB serial adapters that speak slcan) | `slcan:PORT` | `COM5`; the built-in USB serial driver, nothing to install | `/dev/tty.usbmodem14101`; nothing to install | `/dev/ttyACM0`; join the `dialout` group once (`sudo usermod -aG dialout $USER`, then log in again) |
| SocketCAN interfaces (CAN HATs, candleLight firmware, PEAK USB on Linux, `vcan0`) | `socketcan:can0` | - | - | built into the kernel |
| gs_usb adapters (candleLight firmware and compatible adapters, USB ID 1D50:606F) | `gs_usb:0` (the first) | nothing to install: the tools bring the driver and libusb | `brew install libusb` once; the tools bring the Python driver | use `socketcan:can0`: the kernel driver makes them a SocketCAN interface |

Other interfaces python-can knows (`pcan`, `kvaser`, `ixxat`, `vector`, ...) are passed through untested: `--adapter pcan:PCAN_USBBUS1` works when python-can and the vendor's driver do, and the tools say the type is untested. Their options go in `--adapter-option KEY=VALUE` (repeatable).

`canworks-diag adapters` lists what is plugged in: serial ports with USB IDs (recognised slcan adapters named), SocketCAN interfaces on Linux, gs_usb adapters on macOS and Windows (every USB ID the gs_usb driver knows, numbered from 0 in the order `gs_usb:N` opens them, each with its USB bus and address), and what python-can finds for the other types. Each line starts with the `--adapter` value to use.

A SocketCAN interface that is already up is used at its own bit rate. One that is down is brought up at the given bit rate when the user may; otherwise the message gives the `sudo ip link set ...` command to run first.

## The bit rate

There is no default and no automatic detection: you give the bus's bit rate, and the tools refuse to connect when the bus does not run at it. Give `--bitrate KBIT`, or `--config` with a `canworks.json`, whose network's `adapter.bitrate` is then used (`--network` picks one of several networks). Under **Commission a CANopen device** in the configurator you pick the rate in the connect panel that **Connect…** in the connection bar opens.

### The check on connect

Every connection checks the bit rate before anything else is sent:

1. The adapter listens for 1 s in listen-only mode (slcan silent mode, gs_usb listen-only; SocketCAN, the virtual bus and other adapter types listen normally, as does a gs_usb device without listen-only mode or slcan firmware that does not answer the mode command). Valid frames with at most 1 % error frames confirm the rate ("frames on the bus"). Error frames refuse it: "the bus does not run at 250 kbit/s". Reports of the adapter's own error counters going down (error warning, back to error active, still up from a connection at another rate) are not errors on the wire and do not count. A gs_usb adapter drops what it still held from the last connection before it listens, so a refused rate never refuses the next one.
2. A silent bus gets one probe in one-shot mode: an LSS "inquire node ID" (0x7E5, `5E 00 …`), which every device acknowledges at its own bit rate, whatever its LSS support. A gs_usb adapter reports whether the frame got out; SocketCAN and the virtual bus confirm it by the absence of error frames. An acknowledged probe confirms the rate ("a device acknowledged the probe"). Missing acknowledgement or bit errors refuse it: "no device acknowledged at 250 kbit/s: the bit rate is wrong, the device is off or the bus is not terminated".
3. slcan cannot tell whether a frame got out. On a silent bus it needs `--check-node N` (in the configurator, **Node ID for the check**): node N must answer an SDO read of 0x1000. Without it the connection is refused and the message says so.

A network with `adapter.listen_only: true` (a plain CAN network that only listens) connects listen-only and stays so: no probe is sent, a silent bus leaves the rate unconfirmed (`"result": "unconfirmed"`), and anything the connection would send is refused. Its adapter must really be able to listen only: a gs_usb device without that mode, and adapter types the tools open normally (SocketCAN, pcan and other pass-through types), refuse to connect with "adapter gs_usb:0: this adapter cannot listen only".

The result shows in `hello` and `status` as `bitrate_check` (`{"result": "confirmed", "how": "traffic", "bitrate_kbit": 250}`), and in the configurator's connection line. A refused check closes the adapter again at once, so the next try (at another rate) works without a replug.

### Bus errors end the connection

After the check, the connection ends when the adapter goes bus-off or error passive, or when 10 error frames arrive within 1 s without a valid frame. A gs_usb adapter whose sent frame is not echoed within 0.5 s ends it too ("the adapter stopped sending"). Every later request then answers "connection ended: <reason>": a scan, PDO test, SYNC, transmit list job or trace on the connection stops (the trace keeps its frames and says the connection ended). Connecting again runs the check again.

## First steps

```sh
canworks-diag adapters
canworks-diag --adapter slcan:COM5 --bitrate 250 status                 # what the bus shows: heartbeats, EMCY, another master
canworks-diag --adapter slcan:COM5 --bitrate 250 scan --config canworks/canworks.json
canworks-diag --adapter slcan:COM5 --bitrate 250 sdo-read 5 0x1018 4 --type UNSIGNED32
canworks-diag --adapter slcan:COM5 --bitrate 250 backup 5 -o node5.dcf --config canworks/canworks.json
canworks-diag --adapter slcan:COM5 --bitrate 250 --allow-changes lss-find
canworks-diag --adapter slcan:COM5 --bitrate 250 --allow-changes lss-set-id 0x360 0x1 0 0x1234 12
canworks-diag --adapter slcan:COM5 --bitrate 250 trace -o bench.pcapng --duration 60
```

The commands are the ones of [diagnostics.md](diagnostics.md), with `--adapter` in place of `--runtime`; no token is needed. In the configurator, press **Commission a device without a config** on the start page (see [configurator.md](configurator.md#commission-a-canopen-device)); a config's own online view works through the runtime, or through [an adapter on another machine](#an-adapter-on-another-machine).

## Changes are off until you allow them

Without `--allow-changes` (in the configurator: **Unlock…** in the connection bar, asked each time, never saved, and switched back with **Lock** without closing the connection) the adapter only reads: status, scan, SDO reads, the object dictionary, backup, compare and trace. SDO writes, NMT commands, restore and every LSS command are refused with "changes not allowed".

Saving to a device's non-volatile memory (0x1010, `store`, and LSS **Store in the device** or `--store`) is never part of anything else and always needs its own command or tick, also with changes allowed: each store wears the device's flash memory.

## Another master on the bus

The tools listen for a second before their first frame. A bus that carries NMT commands, SYNC, TIME or SDO requests the PC did not send has another master; `status` and the configurator say so ("another master is active on this bus") for 30 seconds after the last such frame.

- SDO requests to a node wait while that master is talking to the same node. An answer the node gives that master meanwhile is not taken for the tool's own and does not abort the transfer.
- LSS commands are refused while another master is active, because LSS addresses every device at once and the master may be using LSS itself. `--force` (in the configurator, **Run anyway** in the question) runs them anyway.
- `lss-set-id` refuses a node ID the bus already shows (by heartbeat) unless forced.
- NMT goes to one node at a time; the other master may start the node again.
- `sdo-write`, `nmt` other than `start`, `scan`, and the writes of `configure` and `restore` need `--force` while another master is active or any node's heartbeat in the last 30 s said OPERATIONAL (see [diagnostics.md](diagnostics.md#changes-to-a-running-network)). The tools listen only a second first, so a node with a slow heartbeat or node guarding may not have shown its own state yet; the refusal says what was seen. The PC sends no node-guarding requests, which would disturb the other master's guarding.

## Limits

- No NMT master, no node configuration at boot, no PDOs for a program: the bridge does that on the device. The PDO test sends a device's RPDOs and SYNC only while it runs, for checking one device.
- No simulated devices, no PLC values: those need the bridge.
- `status` shows only what the bus showed since connecting: node states from heartbeats, the last EMCY per node, and the counts of valid frames and error frames received. The adapter's own state (active, passive) shows when python-can reports it.
- One tool per adapter: a second configurator or CLI on the same adapter gets "adapter ... in use". The configurator keeps the adapter open from **Connect** until **Disconnect** (or until you leave Commission a CANopen device); the CLI for one command.
- Types other than `slcan`, `socketcan` and `gs_usb` are untested. gs_usb: the tools compute the bit timing from the adapter's own limits (sample point 87.5, 85, 80 or 75 %) and refuse a rate it cannot run at before opening it; a USB stall on open resets the adapter once, then asks for a replug ("does not answer (USB stall): unplug it and plug it in again"). The adapter's echo of each sent frame is the send confirmation, never a frame from the bus.
- slcan has no 800 kbit/s: the tools refuse it before opening the adapter.

## Sending frames

`send` and `send-stop` work on an adapter as on a runtime (see [diagnostics.md](diagnostics.md#raw-frames)), with these guards:

- `send` needs `--allow-changes`. It needs `--force` for an identifier the bus uses: NMT, SYNC, TIME and LSS always, and with `send --config canworks.json` the predefined EMCY, PDO, SDO and heartbeat identifiers of the configured nodes. `--force` may stand before or after the command. It also needs `--force` while another master is active or a node's heartbeat says OPERATIONAL. Single frames are limited to 50 per second, cyclic jobs to 8 per adapter (10-60000 ms, at most 10 minutes); a job ends when the command or the configurator connection that started it closes.

## An adapter on another machine

The adapter can also sit in another machine: a Linux box at the machine or on the bench, with the CAN bus, while the configurator, the project folders, the EDS files and the OpenPLC Editor stay on your PC. That machine runs `canworks-diag adapter-serve`, which serves its adapter to PCs on the network with the same protocol as the bridge's diagnostics channel: TLS with a certificate made at every start, and a token login (SCRAM-SHA-256) bound to that certificate, so the token never crosses the network and a machine in the middle cannot log in. Every operation runs on that machine, where the bus is: the bit rate check, SDO transfers, LSS, the scan and the trace. Only the results cross the network, so a slow link makes the pages slower, not the bus timing different.

On the machine with the adapter (Linux; install the PC tools there with the one-line installer of [install-pc.md](install-pc.md)):

```sh
canworks-diag adapter-serve --adapter socketcan:can0 --bitrate 500
token: 3hK...  (shown once; --new-token makes another)
```

- **The bit rate** is the server's: `--bitrate` is required and never guessed. The server opens the adapter and runs [the check on connect](#the-check-on-connect) when the first PC logs in; a refused check is that PC's connect error, with the same message as on a USB adapter. A SocketCAN interface that is already up at another rate is refused rather than used. `--check-node N` is the slcan check node. When the last PC disconnects, the server closes the adapter, so `canworks-diag --adapter` on the machine itself can use it again.
- **The token** is printed once, at the first start. The server keeps only its verifier, in `adapter-serve.json` in the PC tools' settings folder of the user that runs it (`~/.config/canworks`, readable by that user only), per port; the plain token is never written there. `--new-token` makes another (the old one stops working); `--token-file FILE` uses the token in FILE instead, for scripted installs. A wrong token closes the connection; the next login from the same address waits a second, at most 10 failed logins a minute are tried at all, and each one is logged.
- **Changes** need the server's permission and the PC's: without `--allow-changes` the server refuses SDO writes, NMT, LSS, frames, the PDO test and SYNC with "the adapter server on HOST was started without --allow-changes", and with it each PC still allows changes for its own session (`--allow-changes` on the PC, **Unlock…** in the configurator). On a server without it the configurator shows **Read-only (adapter server)** and offers no Unlock…. The server never stores parameters on a device by itself.
- **Limits:** 4 PCs at a time (several connections each: the configurator opens a few), 8 connections that have not logged in yet and 2 per address, 30 s to log in, and a connection idle for 10 minutes is closed. Cyclic frames, a trace and a PDO test belong to the connection that started them and stop when it closes, also when the network goes away.
- `--port` (default 7536) and `--bind ADDR` (default every address; `127.0.0.1` when PCs only come through an SSH port forward).

On the PC, `--adapter remote:HOST[:PORT]` with the server's token (`--token`, `--token-file`, `$CANWORKS_TOKEN` or a prompt) works like a local adapter; the server sets the bit rate, so `--bitrate` is not given:

```sh
canworks-diag --adapter remote:benchbox --token-file benchbox.token scan
canworks-diag --adapter remote:benchbox --allow-changes lss-set-id 0x360 0x1 0 0x1234 12
```

Errors about the server's own adapter name that machine: an interface the server cannot find shows on the PC as "no CAN interface slcan0 on the adapter machine HOST", never as if the PC lacked it (the server's own log says "on this machine"). A trace's summary counts the frames the server's kernel dropped as "dropped by the adapter machine's kernel (HOST)", in the configurator and in `canworks-diag trace`. A runtime given as `remote:HOST` is named as such ("HOST is a runtime, not an adapter server: connect without remote:"). `canworks-diag discover` lists adapter servers apart from runtimes. In the configurator, the connect panel offers **Adapter on another machine** next to **USB adapter** in Commission a CANopen device, and next to **Runtime** and **CANopen simulator** with a config ([configurator.md](configurator.md#commission-a-canopen-device)).

### As a service

To keep the server running without a terminal, also after a reboot:

```sh
sudo canworks-diag adapter-serve --adapter socketcan:can0 --bitrate 500 --install-service
```

This makes the token first (as your user, printed once), writes `/etc/systemd/system/canworks-adapter-can0.service` running the same command as the user who ran sudo, with only the capability to bring the SocketCAN interface up at the bit rate (`CAP_NET_ADMIN`) and restarted on failure, and starts it. When Avahi is installed it also writes `/etc/avahi/services/canworks-adapter-can0.service`, so PCs on the local network find the server (`_canworks._tcp`, TXT `kind=adapter` with the machine's name, the adapter and the bit rate). When it stops, the server logs one last line, `stopped (SIGTERM), N PCs were connected` (`stopped (Ctrl-C)` in a terminal), so `journalctl -u canworks-adapter-can0` shows a `systemctl stop`. `canworks-diag adapter-serve --status` says whether the service runs and which PCs are connected; `sudo canworks-diag adapter-serve --remove-service` stops it and removes both files. An slcan adapter's serial port needs the user in the `dialout` group, as on a PC.

Run as root without sudo (a script, or the configurator's Devices jobs), `--service-user USER` names the user the service runs as; `--token-verifier-file FILE` keeps a token verifier made elsewhere (`SCRAM-SHA-256$...`), so the token itself never comes to the machine; `--without-discovery` leaves the Avahi file out. A reinstall without a token option keeps the token and restarts the service with the new options.

The configurator's [Devices workspace](devices.md#remote-can-adapter) does all of this over SSH: **Remote CAN adapter** › **Turn on…** on the device's page installs the PC tools there when needed (`scripts/install-adapter.sh`), keeps the token on your PC, and **Connect from this PC** connects to it.

### From another network

Discovery stays on the local network, and the remote link is for runtimes. From another network, forward the port over SSH and connect to the forward:

```sh
ssh -N -L 7536:127.0.0.1:7536 user@benchbox        # on the PC; the server may then use --bind 127.0.0.1
canworks-diag --adapter remote:127.0.0.1 --token-file benchbox.token status
```

### Security

- Anyone with the token can read the bus; with `--allow-changes` on the server, also change devices. Keep the token like a password; this PC's configurator keeps it in its settings (`online.json`, readable by you only), per server.
- No certificate pinning is needed: the login proves the token to the server and the server's signature proves it to the PC, both bound to the server's certificate.
- The server holds the adapter only while a PC is logged in. Plain (not TLS) connections and connections that do not log in in time are closed before anything reaches the bus.

## Commissioning one device

A device on the bench, with only the adapter and the device on the bus, from new to ready for the machine. Every step is optional and none runs by itself. In the configurator, **Commission a CANopen device** opens on the Nodes table and connects only from **Connect…** in the connection bar, whose panel lists up to three recent connections first (one click each, still with the bit rate check); the bar then shows the connection. It has the pages **Nodes**, **Trace** and **Frame lab**; a node opens on its **Status** tab. Every change made through the page, and the bus events of the session, go into a log in the bottom panel that **Save log** downloads (`node12-commissioning-<time>.txt`: UTC time, node, what was done and the result, with the device's identity and EDS at the top, no host names or tokens; bus events only when **Include bus events** is ticked). A control locked because **Allow changes** is off offers **Unlock…** in place.

The device's bit rate comes from its documentation or its DIP switches; a device that is still at an unknown rate is found by trying the likely ones: a wrong one is refused at once. On a silent bus with an slcan adapter, a device that has a node ID answers the check with `--check-node`; a device without one (LSS) needs an adapter that confirms its frames (gs_usb, SocketCAN).

```sh
D="canworks-diag --adapter gs_usb:0"
$D --bitrate 250 --allow-changes lss-find                             # 1. find it (no node ID yet)
$D --bitrate 250 --allow-changes lss-set-id 0x360 0x1 0 0x1234 12     # 2. node ID 12 (--store to keep it)
$D --bitrate 250 scan --config canworks/canworks.json                   # 3. identity and EDS
$D --bitrate 250 --allow-changes configure 12 --from-node 12 --config canworks/canworks.json
                                                                      # 4. write the configuration
$D --bitrate 250 --allow-changes pdo-test 12 --config canworks/canworks.json --start --sync 100
                                                                      # 5. PDO test (Ctrl-C ends it)
$D --bitrate 250 --allow-changes store 12 --config canworks/canworks.json  # 6. store on the device
$D --bitrate 250 configure 12 --from-node 12 --config canworks/canworks.json --verify-only
                                                                      # 7. after a power cycle: still there?
$D --bitrate 250 backup 12 -o node12.dcf --config canworks/canworks.json  # 8. back it up
```

**Write configuration** (`configure`) writes what the bridge would write to the node at boot (PDO communication and mapping, heartbeat, startup SDOs, the configuration date and time) from a node of a config (`--from-node N --config FILE`) or from any CiA 306 DCF (`--dcf FILE`: a DCF export, a backup, another tool's DCF), for a device that keeps its configuration because no canworks master configures it: a device for another controller, a spare part, a device that only needs its settings. It reads the device first and shows the plan: every write with the source's and the device's value, PDOs as CiA 301 sequences (COB-ID switched off, mapping count 0, entries, count, the other communication entries, COB-ID on), a PDO sequence sent whole when any of its values differs, and the entries left out with the reason (store and restore commands, read-only entries, a fixed mapping, the program download objects 0x1F50-0x1F57). It refuses a device of another vendor or product (`--ignore-identity` writes anyway) and a source made for another node ID. It holds the node in PRE-OPERATIONAL while writing (`--no-hold` does not), starts it again when it was OPERATIONAL, reads every value back and says whether it is verified. A failed write ends its PDO sequence, which stays switched off. `--dry-run` shows the plan only. `--verify-only` compares without writing, for example after a power cycle. `--restore-defaults` first restores the device's defaults (0x1011) and resets it; `--store` stores afterwards (0x1010), only when everything was written and read back. Neither happens without its option. `restore-defaults NODE [--reset]` restores the defaults on its own.

On a bridge, `configure` refuses a node the bridge configures itself: the bridge writes its configuration at every boot, so change the bridge's config and reset the node instead. For other nodes the bridge cannot hold the node in PRE-OPERATIONAL (it sends NMT only to the nodes it configures), and the result says so.

**PDO test** (`pdo-test`, in the configurator the node's **PDO test** tab in Commission a CANopen device) shows the node's TPDOs with their decoded values, periods and counts, and sends its RPDOs with the values you set (`--set NAME=VALUE`, by entry name, `0xIIII:SS` or `RPDO1.name`; `--repeat-ms` for an event-driven RPDO). The layout comes from the configuration when the node is in it, otherwise from the device; a PDO whose mapping entries cannot all be read is left out, with a note naming the entry. `--start` sends NMT Start to the node; `--sync MS` sends SYNC from the PC, so RPDOs and TPDOs with synchronous transmission run. The test needs `--allow-changes` and `--force` while another master is active, ends when another master appears unless forced, and ends with the command or when the configurator leaves the tab. It is not offered on a runtime: there the PLC runs the PDOs.
