# Bus trace

A bus trace records every CAN frame on the runtime's CAN interface, received and sent, with its time stamp, and shows it decoded as CANopen: NMT, SYNC, TIME, EMCY with its CiA 301 class, heartbeats with the node state, SDO requests and answers with the object name from the EDS (segmented and block transfers joined into one line when they end), LSS, and PDOs with their signal names and values (the PLC variable names in an editor project). On a [J1939 network](j1939.md#diagnostics-and-trace) the frames are decoded as J1939 instead: priority, PGN, source and destination, signals with the DBC's names, scaled values and units, address claims with their NAME fields, requests, acknowledgements and transport protocol sessions (BAM and RTS/CTS, joined into one message on their last frame). It is read from the plugin's [diagnostics channel](diagnostics.md), so it needs online access set up, but nothing else on the PLC: no extra software on the Raspberry Pi, nothing written to its SD card, and the PLC scan is not touched.

Record from the configurator's [Trace view](configurator.md#trace), or with `canworks-diag trace` on any PC with the deploy tool ([install-pc.md](install-pc.md)).

A trace can also be recorded straight from a USB CAN adapter on the PC, with no runtime: `canworks-diag --adapter slcan:COM5 --bitrate 250 trace -o bench.pcapng`, or the Trace view on a [USB adapter connection](configurator.md#usb-adapter-on-this-pc) ([pc-adapter.md](pc-adapter.md)). It keeps the same formats, filters and triggers; time stamps are the PC's receive times, and frames the PC itself sends are recorded as sent.

A trace records one network. With several CAN networks in the config (`schema_version: 2`) pick it in the trace view or with `--network NAME`; the trace command without it exits naming the networks. The frames are decoded with that network's nodes from the config, so node 2 on `io` and node 2 on `drives` each get their own PDO mapping and object names. To watch two networks, record two traces.

## Recording

The plugin keeps the newest 65536 frames in memory while a client traces, and the PC fetches what is new every 100 ms. If the PC falls behind by more than that (a network hiccup on a busy bus), the frames it missed are counted as lost and marked in the trace. Frames the Pi's kernel dropped before the plugin read them are counted separately ("dropped by the PLC's kernel"). A trace on the PC holds up to 2 million frames (about 70 MB of memory); past that the oldest are dropped and the view says so.

Capture filters (ID and mask, up to 16) are applied on the runtime and limit what is recorded, for example `0x180/0x780` for all TPDO1s or `0x717/0x7FF` for node 23's heartbeat. Error frames (bus errors, error-passive, bus-off) are recorded on request; with an slcan adapter such as the CANable they need Linux 6.0 or later and adapter firmware that reports them.

When the CAN interface goes away (the adapter is unplugged) the trace keeps going and gets a gap mark where the capture restarted. A trace ends 10 seconds after the PC stops fetching.

## Sending frames while recording

With `allow_changes` on, the configurator's **Send** panel and `canworks-diag send` put frames on the bus by hand ([diagnostics.md](diagnostics.md#raw-frames-and-bit-rate)). They show in the trace marked Tx, followed by whatever the devices answer, so a hand-made SDO request and its response can be read side by side.

## Time stamps

Time stamps are the Pi's kernel receive times in microseconds, shown relative to the start of the trace or as UTC clock time. With a USB slcan adapter (CANable) they jitter by about 1 ms, and frames the PLC sends are stamped when they are queued, not when they are on the wire. Cycle times of PDOs and SDO response times are accurate to about a millisecond; bit-level timing needs a dedicated analyzer. Bus load is estimated from the frames' lengths (with an allowance for stuff bits), not measured.

## File formats

| Format | Extension | Opens in | Notes |
|---|---|---|---|
| pcapng | `.pcapng` | Wireshark (with a CANopen dissector), tshark, scapy; the configurator and `convert` open it again | The native format: keeps direction per frame, markers, lost-frame notes, gaps, the network name, interface and bit rate, and the trigger. |
| candump log | `.log` | can-utils (`canplayer`, `log2asc`), SavvyCAN, python-can, cantools | Plain text, one frame per line with `T`/`R` for the direction; opened again by the configurator. |
| Vector ASC | `.asc` | CANalyzer, CANoe, SavvyCAN, python-can | Plain text; opened again by the configurator. |
| Vector BLF | `.blf` | CANalyzer, CANoe, python-can | Binary, compressed; written only. |
| PEAK TRC 2.1 | `.trc` | PCAN-View, PCAN-Explorer, python-can | Written only. |
| CSV | `.csv` | Spreadsheets | One row per frame with time, direction, ID, data and the decoded text. |
| Signals CSV | `.csv` | Spreadsheets | The configurator's graph series (PDO signals, polled status values), one row per change. |

Files are checked against python-can and Wireshark in the tests; the hardware check opens them in Wireshark and SavvyCAN. CANalyzer, CANoe and PCAN-View were not available for checking.

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

Heartbeat lost, boot error and bus state come from the plugin's status, which the PC reads every 500 ms. A count N fires on every Nth match.

In **single** mode the recording stops once the post-trigger time (0-600 s) has passed after the first hit; the trace then holds what was recorded before (the pre-trigger time) and after it. In **normal** mode every hit puts a marker in the trace and the graph and recording goes on; with auto-save on, the pre/post window around each hit is written to its own file, named `<project>-trace-<UTC time>.<ext>`. The configurator writes them to the `traces` folder in its settings folder unless another folder is chosen; it refuses the project's `canworks/` folder, which travels with the PLC program.

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
```

`trace` prints how many frames it recorded, the rate, and any lost or dropped frames when it ends. Ctrl-C ends a recording and still writes the file.
