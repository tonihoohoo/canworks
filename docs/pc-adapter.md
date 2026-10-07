# Commissioning from the PC with a USB CAN adapter

`openplc-canopen-diag` and the configurator can talk to the bus straight through a CAN adapter plugged into the PC, with no runtime and no PLC: scan the bus, read and write objects, browse a device's object dictionary, back up, compare and restore parameters, give devices node IDs with LSS, and record a trace. Use it to set up devices on the bench before they go into a machine, to check a device that a PLC does not reach, or on a bus where another master (a PLC, a drive controller) already runs.

The PC is a guest on the bus, not its master. It sends nothing until you act, and never sends SYNC, heartbeats, TIME, or NMT commands to all nodes. It does not configure nodes at boot, run PDOs or simulated devices: that is the plugin's job on the runtime.

## Adapters

| Adapter | `--adapter` | Windows 10 and 11 | macOS | Linux |
|---|---|---|---|---|
| slcan adapters (CANable and CANable 2.0 with stock firmware, and other USB serial adapters that speak slcan) | `slcan:PORT` | `COM5`; the built-in USB serial driver, nothing to install | `/dev/tty.usbmodem14101`; nothing to install | `/dev/ttyACM0`; join the `dialout` group once (`sudo usermod -aG dialout $USER`, then log in again) |
| SocketCAN interfaces (CAN HATs, candleLight firmware, PEAK USB on Linux, `vcan0`) | `socketcan:can0` | - | - | built into the kernel |

Other interfaces python-can knows (`gs_usb`, `pcan`, `kvaser`, `ixxat`, `vector`, ...) are passed through untested: `--adapter pcan:PCAN_USBBUS1` works when python-can and the vendor's driver do, and the tools say the type is untested. Their options go in `--adapter-option KEY=VALUE` (repeatable).

`openplc-canopen-diag adapters` lists what is plugged in: serial ports with USB IDs (recognised slcan adapters named), SocketCAN interfaces on Linux, and what python-can finds for the other types. Each line starts with the `--adapter` value to use.

A SocketCAN interface that is already up is used at its own bit rate. One that is down is brought up at the given bit rate when the user may; otherwise the message gives the `sudo ip link set ...` command to run first.

## The bit rate

There is no default: a wrong bit rate disturbs every device on the bus. Give `--bitrate KBIT`, or `--config` with a `canopen.json`, whose network's `adapter.bitrate` is then used (`--network` picks one of several networks). The configurator starts with the config's bit rate and says when the chosen one differs.

## First steps

```sh
openplc-canopen-diag adapters
openplc-canopen-diag --adapter slcan:COM5 --bitrate 250 status                 # what the bus shows: heartbeats, EMCY, another master
openplc-canopen-diag --adapter slcan:COM5 --bitrate 250 scan --config canopen/canopen.json
openplc-canopen-diag --adapter slcan:COM5 --bitrate 250 sdo-read 5 0x1018 4 --type UNSIGNED32
openplc-canopen-diag --adapter slcan:COM5 --bitrate 250 backup 5 -o node5.dcf --config canopen/canopen.json
openplc-canopen-diag --adapter slcan:COM5 --bitrate 250 --allow-changes lss-find
openplc-canopen-diag --adapter slcan:COM5 --bitrate 250 --allow-changes lss-set-id 0x360 0x1 0 0x1234 12
openplc-canopen-diag --adapter slcan:COM5 --bitrate 250 trace -o bench.pcapng --duration 60
```

The commands are the ones of [diagnostics.md](diagnostics.md), with `--adapter` in place of `--runtime`; no token is needed. In the configurator, pick **USB adapter on this PC** in the online view's connect box (see [configurator.md](configurator.md#usb-adapter-on-this-pc)), or press **Commission a device** on the start page to work with a device without any project.

## Changes are off until you allow them

Without `--allow-changes` (in the configurator: **Allow changes** in the connection banner, asked each time and never saved) the adapter only reads: status, scan, SDO reads, the object dictionary, backup, compare and trace. SDO writes, NMT commands, restore and every LSS command are refused with "changes not allowed".

Saving to a device's non-volatile memory (0x1010, `store`, and LSS **Store in the device** or `--store`) is never part of anything else and always needs its own command or tick, also with changes allowed: each store wears the device's flash memory.

## Another master on the bus

The tools listen for a second before their first frame. A bus that carries NMT commands, SYNC, TIME or SDO requests the PC did not send has another master; `status` and the configurator say so ("another master is active on this bus") for 30 seconds after the last such frame.

- SDO requests to a node wait while that master is talking to the same node.
- LSS commands are refused while another master is active, because LSS addresses every device at once and the master may be using LSS itself. `--force` (in the configurator, **Run anyway** in the question) runs them anyway.
- `lss-set-id` refuses a node ID the bus already shows (by heartbeat) unless forced.
- NMT goes to one node at a time; the other master may start the node again.

## Limits

- No NMT master, no node configuration at boot, no PDOs, no SYNC: the plugin does that on the runtime.
- No simulated devices, no CiA 402 axes, no PLC values: those need the runtime.
- `status` shows only what the bus showed since connecting: node states from heartbeats, the last EMCY per node. No bus error counters; the adapter's own state (active, passive) shows when python-can reports it.
- One tool per adapter: a second configurator or CLI on the same adapter gets "adapter ... in use". The configurator keeps the adapter open while its online view is open; the CLI for one command.
- Types other than `slcan` and `socketcan` are untested.
- Raw CAN frames and finding a bus's bit rate are not part of these commands.
