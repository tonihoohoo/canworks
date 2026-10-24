# Bus trace

A bus trace records every CAN frame on the bridge's CAN interface, received and sent, with its time stamp, and shows it decoded as CANopen: NMT, SYNC, TIME, EMCY with its CiA 301 class, heartbeats with the node state, SDO requests and answers with the object name from the EDS (segmented and block transfers joined into one line when they end), LSS, and PDOs with their signal names and values (the PLC variable names in an editor project). On a [J1939 network](j1939.md#diagnostics-and-trace) the frames are decoded as J1939 instead: priority, PGN, source and destination, signals with the DBC's names, scaled values and units, address claims with their NAME fields, requests, acknowledgements and transport protocol sessions (BAM and RTS/CTS, joined into one message on their last frame). It is read from the bridge's [diagnostics channel](diagnostics.md), so it needs online access set up, but nothing else on the device: no extra software, nothing written to its storage, and the Modbus clients are not touched.

Record from the configurator's [Trace view](configurator.md#trace), or with `canworks-diag trace` on any PC with the deploy tool ([install-pc.md](install-pc.md)).

A trace can also be recorded straight from a USB CAN adapter on the PC, with no bridge: `canworks-diag --adapter slcan:COM5 --bitrate 250 trace -o bench.pcapng`, or the Trace view in [Commission a CANopen device](configurator.md#commission-a-canopen-device) ([pc-adapter.md](pc-adapter.md)). It keeps the same formats, filters and triggers; time stamps are the PC's receive times, and frames the PC itself sends are recorded as sent.

Raw CAN messages ([raw-can.md](raw-can.md)) decode on every network as their message and signals with scale and unit, from the network's `raw` entries; a [plain CAN network](raw-can.md#plain-can-networks) decodes those and shows every other frame as plain CAN. The frame inspector colours a raw message's signal bits with their PLC addresses.

DBC files decode their messages in any trace: **Decoding → Add DBC…** in the configurator, or `--dbc FILE` (repeatable) on `trace`, `convert` and `explain`. The config's own PDOs and raw messages come first, then the DBC files in their order; a message that loses is listed with what decodes its identifier instead. NMT, SYNC, TIME, EMCY, SDO, heartbeat and LSS keep their CANopen decoding and get the DBC's decoding after it (`node 2 OPERATIONAL; pingpong_Heartbeat NMT_State=5`), so the DBC's signals still reach graphs and triggers. On a J1939 network the network's own DBC comes first.

An entry with [bit channels](config.md#bit-channels) decodes as its value with a line per mapped bit under it, named as the bit (the PLC variable name in an editor project), so each bit can be graphed and triggered on like any signal.

### Decoding without a config

Without a config (Commission a CANopen device in the configurator), PDOs decode from the best layout known for their node:

1. **Set on the bus**: SDO writes in the trace to the node's PDO communication (0x1400-0x15FF, 0x1800-0x19FF) and mapping (0x1600-0x17FF, 0x1A00-0x1BFF) objects that the node confirmed. A layout applies from the frame that completed it, so a trace that holds another master's boot decodes the frames before it with the old layout and the ones after with the new. Disabling a PDO (COB-ID bit 31, or mapping count 0) stops its decoding from there.
2. **Read from the device**: on a live connection the configurator reads each heard node's PDO objects (see [Commission a CANopen device](configurator.md#commission-a-canopen-device)); the layout applies to frames recorded after the read, never to opened files. A PDO whose mapping objects could not be read gets no layout from the read; the Decoding panel names the object and the reason. Answers to SDO reads of those objects in the trace (a PDO test, another tool's Read all) count as read from the device too, from the answer that completed them.
3. **EDS defaults**: the default COB-IDs and mappings of the node's EDS, shown with the **assumed** tag, since a master may have changed them.

Signal names and types come from the node's EDS; without one, from the built-in CiA 301, 401 and 402 object names, else the object's index and subindex as an unsigned value of its mapped length. Rows read `TPDO1 node 5 Statusword=567, Modes of operation display=8`, and the signals can be graphed as `node5.TPDO1.<name>`. A PDO nothing describes stays as its node and bytes.

A trace records one network. With several CAN networks in the config (`schema_version: 2`) pick it in the trace view or with `--network NAME`; the trace command without it exits naming the networks. The frames are decoded with that network's nodes from the config, so node 2 on `io` and node 2 on `drives` each get their own PDO mapping and object names. To watch two networks, record two traces.

## Recording

The bridge keeps the newest 65536 frames in memory while a client traces, and the PC fetches what is new every 100 ms. If the PC falls behind by more than that (a network hiccup on a busy bus), the frames it missed are counted as lost and marked in the trace. Frames the device's kernel dropped before the bridge read them are counted separately ("dropped by the PLC's kernel"; through an adapter on another machine, "dropped by the adapter machine's kernel (HOST)"). A trace on the PC holds up to 2 million frames (about 70 MB of memory); past that the oldest tenth is dropped at once, and the view says how many frames it holds and how many were dropped. `canworks-diag trace` says so too when it ends ("the oldest N frames were dropped"), and the file then holds only the last part of the recording: record a shorter time, or with `--filter`.

Capture filters (ID and mask, up to 16) are applied on the bridge and limit what is recorded, for example `0x180/0x780` for all TPDO1s or `0x717/0x7FF` for node 23's heartbeat. Error frames (bus errors, error-passive, bus-off) are recorded on request; with an slcan adapter such as the CANable they need Linux 6.0 or later and adapter firmware that reports them.

When the CAN interface goes away (the adapter is unplugged) the trace keeps going and gets a gap mark where the capture restarted. A trace ends 10 seconds after the PC stops fetching. In the configurator, a recording that loses its connection (the runtime does not answer for 10 seconds, or the PC's adapter is unplugged or goes bus-off) ends with "connection ended" and its reason; **Continue this trace** on the next Start adds the new frames after a gap marker.

## Modbus requests

On a [Modbus bridge](modbus-bridge.md#seeing-the-modbus-traffic) the recording can hold the bridge's Modbus requests on the same timeline as the frames. In the configurator, **Capture…** has **Modbus requests** (on by default), **Only changes** (on by default: unchanged requests are counted, not recorded; the bridge's heartbeat, mailbox keepalives and clock words alone do not count as a change) and a client, all clients or one of the config's connections. Through a USB adapter or an adapter server there are no Modbus requests, and the option is greyed out with the reason; a runtime that is not a bridge records the frames and says so in the header.

- **Chronological** shows each request as a row marked **Modbus** between the frames: read (Rd) or write (Wr), table and range, the client's name and the values by name (a bit output such as `%QX6.0` also by its name when a client writes it as part of a holding register). **Filters** has a source filter: **CAN and Modbus**, **CAN only** or **Modbus only**; the line under the buttons says how many rows show and how many Modbus requests the trace holds.
- A Modbus row opens in the inspector with the client, function, range, unit, transaction, result, the requests skipped before it, the request and answer PDUs, each value by name, and the hints. Per changed value it gives the delay to the bus (a write: the first frame with the new value) or from the bus (a read: the first frame that carried the value), with **Select the frame**, which selects that frame in the list.
- **By identifier** has a **By request** table: one row per client, function and range, with the request count (skipped ones included), the average cycle, the minimum, average and maximum delay to or from the bus, the last values by name and the last exception. A row with a hint is marked and shows the hint on hover.

A trace saved as pcapng keeps the requests as a second interface (IPv4, `canworks-modbus`) carrying Modbus/TCP, with a JSON comment per request (client, skipped count); Wireshark and tshark decode them as Modbus/TCP. The other formats keep the CAN frames only, and **Save** and **Download** say so. When the config on the PC is not the one the bridge runs (its map hash differs), the requests show undecoded with a warning.

## Sending frames while recording

With `allow_changes` on, the configurator's transmit list ([configurator.md](configurator.md#transmit-list)) and `canworks-diag send` put frames on the bus by hand ([diagnostics.md](diagnostics.md#raw-frames)). They show in the trace marked Tx, followed by whatever the devices answer, so a hand-made SDO request and its response can be read side by side.

## Time stamps

Time stamps are the device's kernel receive times in microseconds, shown relative to the start of the trace or as UTC clock time. With a USB slcan adapter (CANable) they jitter by about 1 ms, and frames the PLC sends are stamped when they are queued, not when they are on the wire. Cycle times of PDOs and SDO response times are accurate to about a millisecond; bit-level timing needs a dedicated analyzer. Bus load is estimated from the frames' lengths (with an allowance for stuff bits), not measured.

## File formats

| Format | Extension | Opens in | Notes |
|---|---|---|---|
| pcapng | `.pcapng` | Wireshark (with a CANopen dissector), tshark, scapy; the configurator and `convert` open it again | The native format: keeps direction per frame, markers, lost-frame notes, gaps, the network name, interface and bit rate, and the trigger. |
| candump log | `.log` | can-utils (`canplayer`, `log2asc`), SavvyCAN, python-can, cantools | Plain text, one frame per line with `T`/`R` for the direction; opened again by the configurator. |
| Vector ASC | `.asc` | CANalyzer, CANoe, SavvyCAN, python-can | Plain text; opened again by the configurator, `base hex` or `base dec` and absolute or relative timestamps. |
| Vector BLF | `.blf` | CANalyzer, CANoe, python-can | Binary, compressed; written only. |
| PEAK TRC 2.1 | `.trc` | PCAN-View, PCAN-Explorer, python-can | Written only. |
| CSV | `.csv` | Spreadsheets | One row per frame with time, direction, ID, data and the decoded text. |
| Signals CSV | `.csv` | Spreadsheets | The configurator's graph series (PDO signals, polled status values), one row per change. |

A pcapng or pcap file opens only when it has a SocketCAN interface (link type 227); a capture of another link type is refused instead of showing as empty. A damaged file is refused with the line or byte where it went wrong. Files are checked against python-can and Wireshark in the tests; the hardware check opens them in Wireshark and SavvyCAN. CANalyzer, CANoe and PCAN-View were not available for checking.

### Wireshark: decode as CANopen

Wireshark shows the frames as plain CAN until told the bus is CANopen: **Analyze → Decode As…**, add a row, set the field to **CAN next level dissector** and the value to **CANopen**. tshark: `tshark -r run.pcapng -d can.subdissector,canopen`. The pcapng's section comment (**Statistics → Capture File Properties**) holds the trace's metadata as JSON: markers, lost frames, the network name (with several networks), the interface, the bit rate and the trigger.

## Triggers

A trigger watches the trace while it is recorded, on the PC, and fires when its condition matches. It is one condition, or two joined by AND (both within a time window, 100 ms by default; `a && b` on the command line) or THEN (the second after the first, within the window; window 0: any time after; `a -> b`).

| Condition | Matches | CLI form |
|---|---|---|
| Frame | an ID (and mask), optionally data bytes (and a data mask) and the direction | `frame id=0x197 data=10 data_mask=F0 dir=rx` |
| EMCY | an emergency message, optionally from one node or with one code | `emcy node=23 code=0x5010` |
| Node state | a node's heartbeat or boot-up showing a state (bootup, stopped, operational, preop, any change) | `state node=23 state=stopped` |
| Heartbeat lost | a configured node's status bit falls | `heartbeat_lost node=23` |
| Boot error | a configured node gets a boot error | `boot_error node=23` |
| SDO abort | an SDO transfer is aborted | `sdo_abort node=23` |
| Signal | a decoded PDO signal `>`, `<`, `=`, `!=` a value, crosses a value up or down, or a bit rises or falls | `signal NAME>3`, `signal key=NAME op=cross_up value=100`, `signal key=NAME op=rising` |
| Bus state | the bus reaches error-warning, error-passive or bus-off | `bus state=passive` |
| Error frame | a CAN error frame | `error_frame` |

A signal is named by its key, `<PDO>.<signal>` (for example `valve_RPDO1.Output_1`), or by the signal name alone when only one PDO has it. The command line needs `--config` for signal conditions and uses the signal names from the EDS, as in its CSV; the configurator uses the PLC variable names of the editor project, as in its graph list. A name the config does not decode is refused with the list of signals, so a trigger never waits for a signal that cannot come.

On a J1939 network the configurator offers the frame, signal, bus state and error frame conditions; the others are CANopen's. Heartbeat lost, boot error and bus state come from the bridge's status, which the PC reads every 500 ms. A count N fires on every Nth match.

In **single** mode the recording stops once the post-trigger time (0-600 s) has passed after the first hit; the trace then holds only the window around the hit, the pre-trigger time before it and the post-trigger time after it, and the frames outside it are removed. In **normal** mode every hit puts a marker in the trace and the graph and recording goes on; with auto-save on, the pre/post window around each hit is written to its own file, named `<project>-trace-<UTC time>.<ext>`. The configurator writes them to the `traces` folder in its settings folder unless another folder is chosen, which must exist and be given as a full path; it refuses the project's `canworks/` folder, which travels with the PLC program.

## Explaining frames

The configurator's frame inspector explains any frame of a trace bit by bit, with the trace's SDO context and bit rate, and its Sequences tab shows SDO conversations, boot stories and SYNC cycles; `canworks-diag explain --trace FILE --index N` does the same for one frame in a terminal ([frame-inspector.md](frame-inspector.md)).

## Command line

```sh
export CANWORKS_TOKEN=...
# One minute, decoded names in the CSV from the project's config
canworks-diag --runtime plc.local trace -o run.pcapng --duration 60
canworks-diag --runtime plc.local trace -o run.csv --duration 10 --config canworks/canworks.json
# Only TPDO1s, plus error frames, until Ctrl-C
canworks-diag --runtime plc.local trace -o tpdo.log --filter 0x180/0x780 --error-frames
# Wait for an EMCY from node 23, keep 5 s before and 2 s after it, then stop
canworks-diag --runtime plc.local trace -o emcy.blf --trigger "emcy node=23" --pre 5 --post 2
# Mark every heartbeat loss of node 23 and save each window as candump log next to the output
canworks-diag --runtime plc.local trace -o long.pcapng --trigger "heartbeat_lost node=23" --mode normal --autosave log
# With several networks: trace one of them, decoded with its nodes
canworks-diag --runtime plc.local trace -o drives.pcapng --network drives --config canworks/canworks.json
# Convert between formats (reads .pcapng, .pcap, .log and .asc)
canworks-diag convert run.pcapng run.asc
# Decode with a config of several networks: the network the pcapng names, or --network
canworks-diag convert drives.pcapng drives.csv --config canworks/canworks.json
canworks-diag convert drives.log drives.csv --config canworks/canworks.json --network drives
# Decode with DBC files as well (repeatable); with a config, its own PDOs come first
canworks-diag convert bench.log bench.csv --dbc machine.dbc --dbc valves.dbc
canworks-diag explain --trace bench.log --index 12 --dbc machine.dbc
```

`trace` prints how many frames it recorded, the rate, any lost or dropped frames, and a warning when the oldest frames were dropped past the 2 million frame limit, when it ends. Ctrl-C ends a recording and still writes the file.
