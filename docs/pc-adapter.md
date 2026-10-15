# Commissioning from the PC with a USB CAN adapter

`canworks-diag` and the configurator can talk to the bus straight through a CAN adapter plugged into the PC, with no runtime and no PLC: scan the bus, read and write objects, browse a device's object dictionary, back up, compare and restore parameters, give devices node IDs with LSS, and record a trace. Use it to set up devices on the bench before they go into a machine, to check a device that a PLC does not reach, or on a bus where another master (a PLC, a drive controller) already runs.

The PC is a guest on the bus, not its master. It sends nothing until you act, and never sends heartbeats, TIME, or NMT commands to all nodes, nor SYNC except in a PDO test you start with a SYNC period. It does not configure nodes at boot, run PDOs for a program or simulate devices: that is the plugin's job on the runtime. It can write a node's configuration to a device once, for a device that keeps its own configuration (see [Commissioning one device](#commissioning-one-device)).

## Adapters

| Adapter | `--adapter` | Windows 10 and 11 | macOS | Linux |
|---|---|---|---|---|
| slcan adapters (CANable and CANable 2.0 with stock firmware, and other USB serial adapters that speak slcan) | `slcan:PORT` | `COM5`; the built-in USB serial driver, nothing to install | `/dev/tty.usbmodem14101`; nothing to install | `/dev/ttyACM0`; join the `dialout` group once (`sudo usermod -aG dialout $USER`, then log in again) |
| SocketCAN interfaces (CAN HATs, candleLight firmware, PEAK USB on Linux, `vcan0`) | `socketcan:can0` | - | - | built into the kernel |
| gs_usb adapters (candleLight firmware and compatible adapters, USB ID 1D50:606F) | `gs_usb:0` (the first) | untested | `brew install libusb` once; the tools bring the Python driver | use `socketcan:can0`: the kernel driver makes them a SocketCAN interface |

Other interfaces python-can knows (`pcan`, `kvaser`, `ixxat`, `vector`, ...) are passed through untested: `--adapter pcan:PCAN_USBBUS1` works when python-can and the vendor's driver do, and the tools say the type is untested. Their options go in `--adapter-option KEY=VALUE` (repeatable).

`canworks-diag adapters` lists what is plugged in: serial ports with USB IDs (recognised slcan adapters named), SocketCAN interfaces on Linux, gs_usb adapters by USB ID on macOS and Windows (numbered from 0 in USB order), and what python-can finds for the other types. Each line starts with the `--adapter` value to use.

A SocketCAN interface that is already up is used at its own bit rate. One that is down is brought up at the given bit rate when the user may; otherwise the message gives the `sudo ip link set ...` command to run first.

## The bit rate

There is no default and no automatic detection: you give the bus's bit rate, and the tools refuse to connect when the bus does not run at it. Give `--bitrate KBIT`, or `--config` with a `canworks.json`, whose network's `adapter.bitrate` is then used (`--network` picks one of several networks). Under **Commission a CANopen device** in the configurator you pick the rate in the connect form on the Nodes table.

### The check on connect

Every connection checks the bit rate before anything else is sent:

1. The adapter listens for 1 s in listen-only mode (slcan silent mode, gs_usb listen-only; SocketCAN and the virtual bus listen normally). Valid frames with at most 1 % error frames confirm the rate ("frames on the bus"). Error frames refuse it: "the bus does not run at 250 kbit/s".
2. A silent bus gets one probe in one-shot mode: an LSS "inquire node ID" (0x7E5, `5E 00 …`), which every device acknowledges at its own bit rate, whatever its LSS support. A gs_usb adapter reports whether the frame got out; SocketCAN and the virtual bus confirm it by the absence of error frames. An acknowledged probe confirms the rate ("a device acknowledged the probe"). Missing acknowledgement or bit errors refuse it: "no device acknowledged at 250 kbit/s: the bit rate is wrong, the device is off or the bus is not terminated".
3. slcan cannot tell whether a frame got out. On a silent bus it needs `--check-node N` (in the configurator, **Node ID for the check**): node N must answer an SDO read of 0x1000. Without it the connection is refused and the message says so.

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

The commands are the ones of [diagnostics.md](diagnostics.md), with `--adapter` in place of `--runtime`; no token is needed. In the configurator, press **Commission a CANopen device** on the start page (see [configurator.md](configurator.md#commission-a-canopen-device)); a config's own online view works through the runtime only.

## Changes are off until you allow them

Without `--allow-changes` (in the configurator: **Allow changes** in the connection bar, asked each time, never saved, and switched on or off without closing the connection) the adapter only reads: status, scan, SDO reads, the object dictionary, backup, compare and trace. SDO writes, NMT commands, restore and every LSS command are refused with "changes not allowed".

Saving to a device's non-volatile memory (0x1010, `store`, and LSS **Store in the device** or `--store`) is never part of anything else and always needs its own command or tick, also with changes allowed: each store wears the device's flash memory.

## Another master on the bus

The tools listen for a second before their first frame. A bus that carries NMT commands, SYNC, TIME or SDO requests the PC did not send has another master; `status` and the configurator say so ("another master is active on this bus") for 30 seconds after the last such frame.

- SDO requests to a node wait while that master is talking to the same node. An answer the node gives that master meanwhile is not taken for the tool's own and does not abort the transfer.
- LSS commands are refused while another master is active, because LSS addresses every device at once and the master may be using LSS itself. `--force` (in the configurator, **Run anyway** in the question) runs them anyway.
- `lss-set-id` refuses a node ID the bus already shows (by heartbeat) unless forced.
- NMT goes to one node at a time; the other master may start the node again.
- `sdo-write`, `nmt` other than `start`, and `scan` need `--force` while a node's heartbeat in the last 30 s said OPERATIONAL, as on a runtime (see [diagnostics.md](diagnostics.md#changes-to-a-running-network)).

## Limits

- No NMT master, no node configuration at boot, no PDOs for a program: the plugin does that on the runtime. The PDO test sends a device's RPDOs and SYNC only while it runs, for checking one device.
- No simulated devices, no CiA 402 axes, no PLC values: those need the runtime.
- `status` shows only what the bus showed since connecting: node states from heartbeats, the last EMCY per node, and the counts of valid frames and error frames received. The adapter's own state (active, passive) shows when python-can reports it.
- One tool per adapter: a second configurator or CLI on the same adapter gets "adapter ... in use". The configurator keeps the adapter open from **Connect** until **Disconnect** (or until you leave Commission a CANopen device); the CLI for one command.
- Types other than `slcan`, `socketcan` and `gs_usb` are untested. gs_usb: the tools compute the bit timing from the adapter's own limits (sample point 87.5, 85, 80 or 75 %) and refuse a rate it cannot run at before opening it; a USB stall on open resets the adapter once, then asks for a replug ("does not answer (USB stall): unplug it and plug it in again"). The adapter's echo of each sent frame is the send confirmation, never a frame from the bus.
- slcan has no 800 kbit/s: the tools refuse it before opening the adapter.

## Sending frames

`send` and `send-stop` work on an adapter as on a runtime (see [diagnostics.md](diagnostics.md#raw-frames)), with these guards:

- `send` needs `--allow-changes`. It needs `--force` for an identifier the bus uses: NMT, SYNC, TIME and LSS always, and with `send --config canworks.json` the predefined EMCY, PDO, SDO and heartbeat identifiers of the configured nodes. `--force` may stand before or after the command. It also needs `--force` while another master is active or a node's heartbeat says OPERATIONAL. Single frames are limited to 50 per second, cyclic jobs to 8 per adapter (10-60000 ms, at most 10 minutes); a job ends when the command or the configurator connection that started it closes.

## Commissioning one device

A device on the bench, with only the adapter and the device on the bus, from new to ready for the machine. Every step is optional and none runs by itself. In the configurator, **Commission a CANopen device** opens on the Nodes table, whose empty state is the connect form with up to three recent connections (one click each, still with the bit rate check), and shows the connection in the connection bar. It has the pages **Nodes**, **Trace** and **Frame lab**; a node opens on its **Status** tab. Every change made through the page, and the bus events of the session, go into a log in the bottom panel that **Save log** downloads (`node12-commissioning-<time>.txt`: UTC time, node, what was done and the result, with the device's identity and EDS at the top, no host names or tokens; bus events only when **Include bus events** is ticked). A control locked because **Allow changes** is off offers **Unlock…** in place.

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

**Write configuration** (`configure`) writes what the plugin would write to the node at boot (PDO communication and mapping, heartbeat, startup SDOs, the configuration date and time) from a node of a config (`--from-node N --config FILE`) or from any CiA 306 DCF (`--dcf FILE`: a DCF export, a backup, another tool's DCF), for a device that keeps its configuration because no OpenPLC master configures it: a device for another controller, a spare part, a device that only needs its settings. It reads the device first and shows the plan: every write with the source's and the device's value, PDOs as CiA 301 sequences (COB-ID switched off, mapping count 0, entries, count, the other communication entries, COB-ID on), a PDO sequence sent whole when any of its values differs, and the entries left out with the reason (store and restore commands, read-only entries, a fixed mapping, the program download objects 0x1F50-0x1F57). It refuses a device of another vendor or product (`--ignore-identity` writes anyway) and a source made for another node ID. It holds the node in PRE-OPERATIONAL while writing (`--no-hold` does not), starts it again when it was OPERATIONAL, reads every value back and says whether it is verified. A failed write ends its PDO sequence, which stays switched off. `--dry-run` shows the plan only. `--verify-only` compares without writing, for example after a power cycle. `--restore-defaults` first restores the device's defaults (0x1011) and resets it; `--store` stores afterwards (0x1010), only when everything was written and read back. Neither happens without its option. `restore-defaults NODE [--reset]` restores the defaults on its own.

On a runtime, `configure` refuses a node the runtime configures itself: the plugin writes its configuration at every boot, so change the runtime's configuration and reset the node instead. For other nodes the runtime cannot hold the node in PRE-OPERATIONAL (it sends NMT only to the nodes it configures), and the result says so.

**PDO test** (`pdo-test`, in the configurator the node's **PDO test** tab in Commission a CANopen device) shows the node's TPDOs with their decoded values, periods and counts, and sends its RPDOs with the values you set (`--set NAME=VALUE`, by entry name, `0xIIII:SS` or `RPDO1.name`; `--repeat-ms` for an event-driven RPDO). The layout comes from the configuration when the node is in it, otherwise from the device. `--start` sends NMT Start to the node; `--sync MS` sends SYNC from the PC, so RPDOs and TPDOs with synchronous transmission run. The test needs `--allow-changes` and `--force` while another master is active, ends when another master appears unless forced, and ends with the command or when the configurator leaves the tab. It is not offered on a runtime: there the PLC runs the PDOs.
