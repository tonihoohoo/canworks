# Commissioning from the PC with a USB CAN adapter

`openplc-canopen-diag` and the configurator can talk to the bus straight through a CAN adapter plugged into the PC, with no runtime and no PLC: scan the bus, read and write objects, browse a device's object dictionary, back up, compare and restore parameters, give devices node IDs with LSS, and record a trace. Use it to set up devices on the bench before they go into a machine, to check a device that a PLC does not reach, or on a bus where another master (a PLC, a drive controller) already runs.

The PC is a guest on the bus, not its master. It sends nothing until you act, and never sends heartbeats, TIME, or NMT commands to all nodes, nor SYNC except in a PDO test you start with a SYNC period. It does not configure nodes at boot, run PDOs for a program or simulate devices: that is the plugin's job on the runtime. It can write a node's configuration to a device once, for a device that keeps its own configuration (see [Commissioning one device](#commissioning-one-device)).

## Adapters

| Adapter | `--adapter` | Windows 10 and 11 | macOS | Linux |
|---|---|---|---|---|
| slcan adapters (CANable and CANable 2.0 with stock firmware, and other USB serial adapters that speak slcan) | `slcan:PORT` | `COM5`; the built-in USB serial driver, nothing to install | `/dev/tty.usbmodem14101`; nothing to install | `/dev/ttyACM0`; join the `dialout` group once (`sudo usermod -aG dialout $USER`, then log in again) |
| SocketCAN interfaces (CAN HATs, candleLight firmware, PEAK USB on Linux, `vcan0`) | `socketcan:can0` | - | - | built into the kernel |
| gs_usb adapters (candleLight firmware and compatible adapters, USB ID 1D50:606F) | `gs_usb:0` (the first) | untested | `brew install libusb` once; the tools bring the Python driver | use `socketcan:can0`: the kernel driver makes them a SocketCAN interface |

Other interfaces python-can knows (`pcan`, `kvaser`, `ixxat`, `vector`, ...) are passed through untested: `--adapter pcan:PCAN_USBBUS1` works when python-can and the vendor's driver do, and the tools say the type is untested. Their options go in `--adapter-option KEY=VALUE` (repeatable).

`openplc-canopen-diag adapters` lists what is plugged in: serial ports with USB IDs (recognised slcan adapters named), SocketCAN interfaces on Linux, gs_usb adapters by USB ID on macOS and Windows (numbered from 0 in USB order), and what python-can finds for the other types. Each line starts with the `--adapter` value to use.

A SocketCAN interface that is already up is used at its own bit rate. One that is down is brought up at the given bit rate when the user may; otherwise the message gives the `sudo ip link set ...` command to run first.

## The bit rate

There is no default: a wrong bit rate disturbs every device on the bus. Give `--bitrate KBIT`, or `--config` with a `canopen.json`, whose network's `adapter.bitrate` is then used (`--network` picks one of several networks). The configurator starts with the config's bit rate and says when the chosen one differs; under **Commission a device**, which has no config, no rate is picked until you pick one or press **Detect**.

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

- SDO requests to a node wait while that master is talking to the same node. An answer the node gives that master meanwhile is not taken for the tool's own and does not abort the transfer.
- LSS commands are refused while another master is active, because LSS addresses every device at once and the master may be using LSS itself. `--force` (in the configurator, **Run anyway** in the question) runs them anyway.
- `lss-set-id` refuses a node ID the bus already shows (by heartbeat) unless forced.
- NMT goes to one node at a time; the other master may start the node again.

## Limits

- No NMT master, no node configuration at boot, no PDOs for a program: the plugin does that on the runtime. The PDO test sends a device's RPDOs and SYNC only while it runs, for checking one device.
- No simulated devices, no CiA 402 axes, no PLC values: those need the runtime.
- `status` shows only what the bus showed since connecting: node states from heartbeats, the last EMCY per node. No bus error counters; the adapter's own state (active, passive) shows when python-can reports it.
- One tool per adapter: a second configurator or CLI on the same adapter gets "adapter ... in use". The configurator keeps the adapter open while its online view is open; the CLI for one command.
- Types other than `slcan` and `socketcan` are untested, except `gs_usb` on macOS (scan, object dictionary, watch and backup read-only on one adapter). gs_usb has no listen-only mode here, so `detect-bitrate` does not take it.

## Sending frames and finding the bit rate

`send`, `send-stop` and `detect-bitrate` work on an adapter as on a runtime (see [diagnostics.md](diagnostics.md#raw-frames-and-bit-rate)), with these guards:

- `send` needs `--allow-changes`. It needs `--force` for an identifier the bus uses: NMT, SYNC, TIME and LSS always, and with `send --config canopen.json` the predefined EMCY, PDO, SDO and heartbeat identifiers of the configured nodes. `--force` may stand before or after the command. It also needs `--force` while another master is active or a node's heartbeat says OPERATIONAL. Single frames are limited to 50 per second, cyclic jobs to 8 per adapter (10-60000 ms, at most 10 minutes); a job ends when the command or the configurator connection that started it closes.
- `detect-bitrate` opens the adapter in listen-only mode at each rate, so it sends nothing, not even an acknowledge (so a single device on the bus needs a second device that acknowledges its frames, see [diagnostics.md](diagnostics.md#finding-the-bit-rate)), and needs neither `--allow-changes` nor `--force`. It needs the adapter to itself: another connection of the same tool on the adapter gets "busy", and in the configurator the Send panel's cyclic jobs end. Afterwards the adapter is opened again at the connection's bit rate. Listen-only works on slcan, PCAN and SocketCAN. On slcan the tool first asks for the firmware's silent mode (`m1`, then `O`), because some firmware takes `L` and then receives nothing; firmware that refuses `m1` with an error gets `L`, and the mode is set back with `m0` afterwards. Some firmware answers no command at all and may ignore `m1`: it then joins the bus at each wrong rate and its error frames can disturb the other devices, even push one to bus-off. With such firmware `detect-bitrate` stops before listening and says so; `--disturb-bus` (in the configurator, **Sweep anyway**) sweeps anyway, best when nothing on the bus must keep running; on SocketCAN the tool sets the link listen-only with `ip`, which needs root (`sudo`) or CAP_NET_ADMIN, and sets it back afterwards. Other adapter types answer "the adapter's driver has no listen-only mode". Rates the adapter cannot be set to are not tried and the result names them: python-can's slcan driver has no 800 kbit/s, so an slcan sweep listens at the other seven.

- `detect-bitrate --lone-device` is for one device on the bench, alone with the adapter: listen-only finds nothing then, because nothing acknowledges the device's frames, and a device that sends nothing until it is asked stays quiet. The sweep opens the adapter in normal mode at each rate, so it acknowledges, and at half time sends a probe: `--probe lss` (the default, an LSS identity query every CiA 305 device answers) or `--probe sdo:NODE` (an SDO read of 0x1000). It stops at the first rate where frames come through. At each wrong rate the adapter's error frames reach every device on the bus, so it needs `--allow-changes`, is refused while another master is active or when more than one node was heard in the last 30 s, and works only on a USB adapter. A result that shows more than one node ID warns that the device may not be alone. A `silent` result of the plain sweep suggests `--lone-device`.

In the configurator, **Detect** next to the bit rate in the USB adapter connect box runs the sweep before connecting and picks the rate it finds. **Only this device is on the bus** next to it runs the lone-device sweep after asking; on the Scan page it also needs Allow changes.

## Commissioning one device

A device on the bench, with only the adapter and the device on the bus, from new to ready for the machine. Every step is optional and none runs by itself; in the configurator, **Commission a device** shows them as a Steps panel, and every change made through the page goes into a log that **Save log** downloads (`node12-commissioning-<time>.txt`: UTC time, node, what was done and the result, with the device's identity and EDS at the top, no host names or tokens).

```sh
D="openplc-canopen-diag --adapter slcan:COM5"
$D --bitrate 250 --allow-changes detect-bitrate --lone-device         # 1. the device's bit rate
$D --bitrate 250 --allow-changes lss-find                             # 2. find it (no node ID yet)
$D --bitrate 250 --allow-changes lss-set-id 0x360 0x1 0 0x1234 12     # 3. node ID 12 (--store to keep it)
$D --bitrate 250 scan --config canopen/canopen.json                   # 4. identity and EDS
$D --bitrate 250 --allow-changes configure 12 --from-node 12 --config canopen/canopen.json
                                                                      # 5. write the configuration
$D --bitrate 250 --allow-changes pdo-test 12 --config canopen/canopen.json --start --sync 100
                                                                      # 6. PDO test (Ctrl-C ends it)
$D --bitrate 250 --allow-changes store 12 --config canopen/canopen.json  # 7. store on the device
$D --bitrate 250 configure 12 --from-node 12 --config canopen/canopen.json --verify-only
                                                                      # 8. after a power cycle: still there?
$D --bitrate 250 backup 12 -o node12.dcf --config canopen/canopen.json  # 9. back it up
```

**Write configuration** (`configure`) writes what the plugin would write to the node at boot (PDO communication and mapping, heartbeat, startup SDOs, the configuration date and time) from a node of a config (`--from-node N --config FILE`) or from any CiA 306 DCF (`--dcf FILE`: a DCF export, a backup, another tool's DCF), for a device that keeps its configuration because no OpenPLC master configures it: a device for another controller, a spare part, a device that only needs its settings. It reads the device first and shows the plan: every write with the source's and the device's value, PDOs as CiA 301 sequences (COB-ID switched off, mapping count 0, entries, count, the other communication entries, COB-ID on), a PDO sequence sent whole when any of its values differs, and the entries left out with the reason (store and restore commands, read-only entries, a fixed mapping, program download). It refuses a device of another vendor or product (`--ignore-identity` writes anyway) and a source made for another node ID. It holds the node in PRE-OPERATIONAL while writing (`--no-hold` does not), starts it again when it was OPERATIONAL, reads every value back and says whether it is verified. A failed write ends its PDO sequence, which stays switched off. `--dry-run` shows the plan only. `--verify-only` compares without writing, for example after a power cycle. `--restore-defaults` first restores the device's defaults (0x1011) and resets it; `--store` stores afterwards (0x1010), only when everything was written and read back. Neither happens without its option. `restore-defaults NODE [--reset]` restores the defaults on its own.

On a runtime, `configure` refuses a node the runtime configures itself: the plugin writes its configuration at every boot, so change the runtime's configuration and reset the node instead. For other nodes the runtime cannot hold the node in PRE-OPERATIONAL (it sends NMT only to the nodes it configures), and the result says so.

**PDO test** (`pdo-test`, in the configurator the node's **PDO test** tab on a USB adapter) shows the node's TPDOs with their decoded values, periods and counts, and sends its RPDOs with the values you set (`--set NAME=VALUE`, by entry name, `0xIIII:SS` or `RPDO1.name`; `--repeat-ms` for an event-driven RPDO). The layout comes from the configuration when the node is in it, otherwise from the device. `--start` sends NMT Start to the node; `--sync MS` sends SYNC from the PC, so RPDOs and TPDOs with synchronous transmission run. The test needs `--allow-changes` and `--force` while another master is active, ends when another master appears unless forced, and ends with the command or when the configurator leaves the tab. It is not offered on a runtime: there the PLC runs the PDOs.
