# Raw CAN: plain CAN messages and frame blocks

Many devices on a machine bus speak neither CANopen nor J1939: joysticks, displays, sensors, battery packs and drives with their own frame layouts, usually described by a DBC file or a data sheet. canworks talks to them in two ways, on any network:

- **Config messages**: a `raw` object on a network lists received and sent messages with their signals mapped to `%I` and `%Q`. No program code is needed, as for PDOs.
- **Frame blocks**: `CAN_SEND`, `CAN_SEND_CYCLIC`, `CAN_RECEIVE` and `CAN_BUS_INFO` in the `canworks` library give the program full control of single frames, and ST functions pack and unpack signals.

Both work next to CANopen or J1939 on the same bus, and on a network with no protocol at all (`"protocol": "none"`). Classic CAN only: frames of up to 8 bytes, 11-bit or 29-bit identifiers, remote frames. CAN FD is not supported.

## Plain CAN networks

A network with `"protocol": "none"` has an `adapter`, an optional `raw` object and nothing else. It still gets everything the bridge gives any bus: bus state and error counters, the bus trace, diagnostics status and `send_frame`.

```json
{
  "schema_version": 2,
  "networks": [
    { "name": "cab", "protocol": "none",
      "adapter": { "type": "socketcan", "interface": "can1", "bitrate": 250000 },
      "raw": { "rx": [], "tx": [] } }
  ]
}
```

A config with `raw` or a `none` network is version 2; the configurator and the deploy tool write it so.

### Listen-only

`"listen_only": true` in the `adapter` of a `none` network makes the bridge a silent observer: it receives, but never acknowledges a frame or sends one. The bridge sets the controller to listen-only (SocketCAN ctrlmode, silent mode on slcan adapters). Where it cannot (`configure_link: false`, vcan, a simulated bus) it says so in the log and only refuses its own sends. A listen-only network may have no `tx` messages; program sends end with `ERROR_ID` 9 and `send_frame` is refused.

## Config messages

```json
"raw": {
  "dbc": "cab.dbc",
  "rx": [
    { "name": "Joystick", "id": 291, "dlc": 8, "timeout_ms": 300,
      "status_location": "%IX300.0", "counter_location": "%IW302",
      "signals": [ { "name": "X", "start_bit": 0, "length": 12, "signed": true,
                     "scale": 0.1, "unit": "%", "iec_location": "%IW304" } ] },
    { "name": "AnyBattery", "id": 1536, "mask": 2032,
      "id_location": "%ID308", "data_location": "%IL312" }
  ],
  "tx": [
    { "name": "Lamps", "id": 1281, "dlc": 2, "period_ms": 100,
      "on_change": true, "min_gap_ms": 10, "enable_location": "%QX300.0",
      "signals": [ { "name": "Red", "start_bit": 0, "length": 1, "iec_location": "%QX300.1" } ] },
    { "name": "Wake", "id": 1282, "rtr": true, "dlc": 0, "trigger_location": "%QX300.2" }
  ]
}
```

Identifiers are numbers in the file (the configurator shows and takes hex). `extended: true` makes an identifier 29-bit.

### Received messages (`rx`)

| Field | Meaning |
|---|---|
| `id`, `extended` | The identifier and its format. |
| `mask` | A frame matches when `(frame id AND mask) = (id AND mask)`. Default: every bit (only `id`). Entries that overlap all get the frame. |
| `rtr` | Match remote frames instead of data frames. |
| `dlc` | The expected length. A shorter frame that does not hold every signal is not applied and counts as a short frame in the status. |
| `timeout_ms` | The status bit goes FALSE when no matching frame came for this long. |
| `status_location` | `%IX`: TRUE while frames arrive in time (without a timeout: after the first frame). |
| `counter_location` | `%IW`: counts matching frames, wrapping at 65535. More than one frame can arrive per scan; the PLC sees the last one, and the counter tells it how many came. |
| `id_location`, `dlc_location` | `%ID` / `%IB`: the identifier and length of the last frame, useful with a mask. |
| `data_location` | `%IL`: the whole 8 bytes, byte 0 in the lowest byte. |
| `signals` | See [Signals](#signals). |

When the CAN interface goes away (an adapter unplugged, the interface down), every `status_location` and `valid_location` goes FALSE at once, whatever `timeout_ms`; the values hold. They come back with the next frames once the interface is open again.

### Sent messages (`tx`)

| Field | Meaning |
|---|---|
| `id`, `extended`, `rtr`, `dlc` | The frame. `dlc` defaults to the bytes the signals need. |
| `period_ms` | Sent every 1 to 60000 ms. |
| `on_change`, `min_gap_ms` | Also sent when a signal value changes, but not more often than `min_gap_ms`; a change restarts the period. |
| `trigger_location` | `%QX`: a rising edge sends the frame once. With `on_change` too, a change is sent also before the first edge: the first outputs after the bridge starts (or the outputs gate opens) are the values changes are compared with, and are not sent themselves. |
| `enable_location` | `%QX`: FALSE stops periodic and on-change sends. |
| `fill` | The byte value for bits no signal covers, default 0. |
| `data_location` | `%QL`: the whole 8 bytes from the program; signals are written on top. |
| `override_protocol` | Needed to send an identifier the network's protocol uses (see [Protocol identifiers](#protocol-identifiers)). |
| `signals` | See [Signals](#signals). |

A `tx` message needs at least one of `period_ms`, `on_change` or `trigger_location`. Sending starts when the bridge runs and stops when it stops, or while the bridge's outputs are off.

A send the interface refuses (its transmit queue is full, or it is down) does not count as sent. An on-change or trigger send stays pending and goes out with the current values on a later 1 ms tick, still no more often than `min_gap_ms`. A refused periodic send waits for its next period; missed periods are not sent in a burst.

### Signals

| Field | Meaning |
|---|---|
| `name` | Used in the variable names, the trace and the configurator. |
| `start_bit`, `length` | Bit numbering as DBC files use it: bit 0 is the least significant bit of byte 0. A little-endian signal starts at its least significant bit, a big-endian one at its most significant bit. |
| `byte_order` | `little` (Intel, default) or `big` (Motorola). |
| `signed` | Two's complement; the value is sign-extended into the location. |
| `scale`, `offset`, `unit`, `minimum`, `maximum`, `comment` | For tools only: the variable descriptions, the trace and the configurator show physical values. The PLC always gets the raw integer, as for CANopen and J1939. |
| `iec_location` | Big enough for `length`: `%IX`/`%QX` for 1 bit, then byte, word, double word or long word. |
| `multiplexer`, `mux` | Multiplexing; see [Multiplexed messages](#multiplexed-messages). |
| `valid_location` | `%IX`, received signals only: TRUE while frames carrying this signal arrive within `timeout_ms`. |

### Multiplexed messages

A multiplexed message reuses its bytes: a switch signal (the DBC's `M`) says which other signals a frame carries, so one identifier can send temperature in one frame and pressure in the next. A switch has `"multiplexer": true`, is unsigned and has at most 32 bits. A signal with `mux` is in a frame only when its switch has one of `values` (whole numbers or `[low, high]` ranges); signals with neither are in every frame. The set of signals a switch value selects is a *page*.

```json
{ "name": "Sensor", "id": 912, "dlc": 4, "timeout_ms": 300,
  "signals": [
    { "name": "Page", "start_bit": 0, "length": 8, "multiplexer": true, "iec_location": "%IB300" },
    { "name": "Temp", "start_bit": 8, "length": 8, "mux": { "values": [1] },
      "iec_location": "%IB301", "valid_location": "%IX300.5" },
    { "name": "Press", "start_bit": 8, "length": 16, "mux": { "values": [2] },
      "iec_location": "%IW303", "valid_location": "%IX300.6" },
    { "name": "Counter", "start_bit": 24, "length": 8, "iec_location": "%IB302" } ] }
```

A message may have several switches, also nested (the DBC's `mNM` with `SG_MUL_VAL_`): a switch can itself depend on another one, and `mux.on` names the switch a signal depends on (needed when there is more than one). Signals on different pages may use the same bits; the configuration check only reports overlaps of signals that can be in one frame, and a frame's length is checked against the signals of its page.

**Receiving.** A frame updates its switches, the signals of its page and the signals of every page; the other signals keep their last values. A frame whose switch selects no known page updates only the switches and the always-present signals, and counts in the status as an unknown page (`unknown_pages`). A signal's `valid_location` goes FALSE when no frame carried it for `timeout_ms`, so the program can tell a page that stopped while the others still arrive; the message's `status_location` still means "some frame arrives".

**Sending.** A sent message with a switch has `pages`:

| `pages` | Behaviour |
|---|---|
| `program` (default) | The switch has an `iec_location` and the program picks the page: each send carries the page the switch outputs select. A switch output wider than the switch is cut to the switch's length first (17 on a 4-bit switch is page 1), as on J1939. A switch value that selects no page sends the switches and the always-present signals and shows `unknown_page` in the status. |
| `all` | Every page is sent each period, one frame per page, in switch-value order. The bridge sets the switch, so it has no `iec_location`. |
| `rotate` | One page per period, the next one each time. The bridge sets the switch. |

`all` and `rotate` take at most 64 pages; a message with more needs `program`. With `on_change` a page goes out when one of its own signals changes (in `rotate`, the next changed page); `trigger_location` sends every page in `all`, the next page in `rotate` and the program's page in `program`. A refused paged send is retried as in [Sent messages](#sent-messages-tx).

**Frame blocks.** Without config messages, the program reads the switch first and then the page's signals:

```
rx(ENABLE := TRUE, ID := 16#390, RX_DATA := frame);
WHILE rx.RECEIVED DO
  CASE LINT_TO_USINT(CAN_GET_BITS(DATA := frame, START_BIT := 0, BIT_LENGTH := 8, MOTOROLA := FALSE, SIGNED := FALSE)) OF
    1: temp := LINT_TO_INT(CAN_GET_BITS(DATA := frame, START_BIT := 8, BIT_LENGTH := 8, MOTOROLA := FALSE, SIGNED := FALSE));
    2: press := LINT_TO_INT(CAN_GET_BITS(DATA := frame, START_BIT := 8, BIT_LENGTH := 16, MOTOROLA := FALSE, SIGNED := FALSE));
  END_CASE;
  rx(ENABLE := TRUE, ID := 16#600, MASK := 16#780, RX_DATA := frame, LINK := canworks.link);
END_WHILE;
```

### Protocol identifiers

On a CANopen or J1939 network some identifiers belong to the protocol: NMT, SYNC, TIME, EMCY, PDO, SDO, LSS and heartbeat COB-IDs of the configured nodes and the master, or any J1939 frame from the PLC's own address. A `tx` message on such an identifier is a config error unless it says `"override_protocol": true`, and a program send on one fails with `ERROR_ID` 4 unless the network has `"raw": { "program_override_protocol": true }`. Receiving them is always allowed. The diagnostics `send_frame` guard names raw messages too ("raw message Lamps"), so an engineer cannot collide with the program by accident.

### From a DBC file

`canworks-config` imports a DBC file on a network's **CAN messages** page (**Import DBC…**): pick the messages, choose received or sent, and each signal gets a free location. The file is copied into the config folder on save and named in the network's `raw.dbc`; the bridge does not read it.

Messages with J1939 attributes belong on a J1939 network; plain 11-bit and 29-bit messages become raw messages. Multiplexed messages keep their switches and pages, simple (`M`, `m1`) and extended (`m1M`, `SG_MUL_VAL_`) alike. The other way round, `canworks-deploy --export-dbc` writes a network's raw messages into its DBC file next to the protocol's frames, with their multiplexing.

### In the program

For a config with an OpenPLC connection, `canworks-deploy --new-project` or `--into-project` and the configurator's **New editor project…** put a variable per signal and per location in the project's `canworks` list, named `<message>_<signal>` (`<network>_<message>_<signal>` with several networks), with the message, scale and unit in its description: `canworks.Joystick_X : INT`, `canworks.Joystick_status : BOOL`, `canworks.Lamps_Red : BOOL`. A received signal's `valid_location` becomes `<message>_<signal>_valid`, for example `canworks.Sensor_Temp_valid : BOOL`. Other Modbus clients get the same names from `--export-modbus-map` ([modbus-bridge.md](modbus-bridge.md)).

## Frame blocks

The blocks are in the [`canworks` function block library](plc-library.md); install and enable it as [plc-library.md](plc-library.md#install-and-enable) describes. A project made with `canworks-deploy --new-project ... --blocks` has it enabled. They work through the bridge's [mailboxes](plc-library.md#the-mailboxes), which are off until a program uses them ([with or without the mailboxes](plc-library.md#with-or-without-the-mailboxes)): `CAN_SEND` needs a request mailbox, `CAN_SEND_CYCLIC` also a cyclic job, `CAN_RECEIVE` the receive mailbox, `CAN_BUS_INFO` network info. Every block has `NETWORK : USINT` (the network's place in `networks`, 0 the first), the in-out `LINK := canworks.link` and the outputs `ERROR : BOOL` and `ERROR_ID : UINT`. The frame data is `ARRAY[0..7] OF BYTE`, passed as an in-out pin.

Each `CAN_SEND` costs a round trip to the bridge, about two polls (20-30 ms at the default 10 ms poll), so one request mailbox sends about 50 frames per second. `CAN_RECEIVE` gets 9 frames per batch (21 with `receive_blocks: 2`) and a batch every two polls, about 450 frames per second at the default 10 ms poll (1050 with two receive blocks; [modbus-bridge.md](modbus-bridge.md#receive-throughput)). Frames the program sends often or on a fixed period belong in the config's `tx` messages or in `CAN_SEND_CYCLIC`, whose frames the bridge sends from its own timer.

### `CAN_SEND`: one frame

```
VAR
  tx : CAN_SEND;
  d : ARRAY[0..7] OF BYTE;
  go : BOOL;
END_VAR

d[0] := 1; d[1] := 2;
tx(EXECUTE := go, ID := 16#510, DLC := 2, DATA := d, LINK := canworks.link);
IF tx.DONE THEN go := FALSE; END_IF;
```

A rising edge of `EXECUTE` sends one frame with that call's inputs (`ID`, `EXTENDED`, `RTR`, `DLC`, `DATA`) to the bridge and sets `BUSY`; edges and input changes while `BUSY` are ignored. `DONE` comes when the bridge reports the frame confirmed on the bus, `ERROR` with `ERROR_ID` 6 when it is not within `TIMEOUT` (`T#0s` = 1 s). The outputs stay while `EXECUTE` stays TRUE and for one call after it fell.

What "confirmed" means depends on the adapter. SocketCAN drivers that echo sent frames (most USB adapters and on-chip controllers) echo a frame only once it was acknowledged on the bus, so `DONE` means another device took it. Without echo (vcan, some slcan firmware) `DONE` means the frame was handed to the driver. The diagnostics status shows which (`confirm: echo` or `confirm: write`). On a bus with no other device a frame is never acknowledged, and `CAN_SEND` ends with `ERROR_ID` 6. When the adapter's transmit queue is full meanwhile, the bridge keeps the program's frame and tries again until `TIMEOUT`, and `CAN_SEND_CYCLIC` keeps its job but `COUNT` stops until the bus takes frames again; `CAN_BUS_INFO` shows the state (usually 2, error passive). While the bus is off, `CAN_SEND_CYCLIC` and `CAN_RECEIVE` also show it (see [Error IDs](#error-ids)).

### `CAN_SEND_CYCLIC`: a frame on a timer

```
VAR
  hb : CAN_SEND_CYCLIC;
  d : ARRAY[0..7] OF BYTE;
END_VAR

d[0] := d[0] + 1;
hb(ENABLE := TRUE, ID := 16#18FF0080, EXTENDED := TRUE, DLC := 8, PERIOD := T#10ms, DATA := d, LINK := canworks.link);
```

While `ENABLE` is TRUE the bridge sends the frame every `PERIOD` (1 ms to 60 s) from its own timer, whatever the PLC cycle and the poll. `ID` and `EXTENDED` are taken when `ENABLE` rises; `DATA`, `DLC` and `PERIOD` go to the bridge when they change (one round trip, so a change reaches the bus within about two polls). `COUNT` counts frames sent since `ENABLE` rose. Call the block at least once a second: it writes a keepalive, and the bridge stops a job whose keepalive stands still for 1 s, so a block the program no longer calls does not leave its frame running. A `DLC` over 8 or a `PERIOD` out of range ends the job (the frame stops on the bus) and shows `ERROR_ID` 3 with `ACTIVE` FALSE; fix the input and give `ENABLE` a new rising edge to start again. The config's `mailboxes.cyclic_jobs` (up to 16) says how many jobs run at once.

### `CAN_RECEIVE`: a filtered queue

```
VAR
  rx : CAN_RECEIVE;
  frame : ARRAY[0..7] OF BYTE;
  last_temp : INT;
END_VAR

rx(ENABLE := TRUE, ID := 16#600, MASK := 16#780, RX_DATA := frame, LINK := canworks.link);  (* 0x600..0x67F *)
WHILE rx.RECEIVED DO
  IF rx.RX_ID = 16#605 THEN
    last_temp := CAN_GET_UINT16(DATA := frame, OFFSET := 2, MOTOROLA := FALSE);
  END_IF;
  rx(ENABLE := TRUE, ID := 16#600, MASK := 16#780, RX_DATA := frame, LINK := canworks.link);
END_WHILE;
```

While `ENABLE` is TRUE the bridge queues every frame of the given format whose `(identifier AND MASK) = (ID AND MASK)`, up to `DEPTH` frames (`0` = 32, at most 256), and shows them in batches in its receive mailbox. `MASK` 0 means only `ID` itself; `ALL_IDS := TRUE` takes every frame. Each call takes at most one frame of the current batch: `RECEIVED` TRUE with its `RX_ID`, `RX_EXTENDED`, `RX_RTR`, `RX_DLC`, `RX_DATA` and `TIMESTAMP` (UTC microseconds from the kernel: the receive time of the batch's first frame, shared by all frames of the batch, so it is accurate to about one poll; use a [bus trace](trace.md) for frame-to-frame timing), or `RECEIVED` FALSE with the last frame's outputs kept. Calling it in a `WHILE rx.RECEIVED DO` loop reads the batch's frames in one scan; the next batch comes in a later scan, and `QUEUED` says how many frames still wait in the bridge. A frame arriving at a full queue is dropped, sets `OVERFLOW` until `ENABLE` falls and counts in `DROPPED`. Frames the bridge sends itself are not queued. Call every enabled receiver every scan: a receiver whose frames wait unread for 1 s is closed (`ERROR_ID` 8, it opens again on the next call), so it does not hold up the others. On a plain CAN network, frames other programs on the PLC host send (`cansend`, for example) are queued like frames from the bus; on a CANopen or J1939 network they are not, because the kernel marks them the same way as the protocol's own frames. All networks together have at most 32 receivers (`CAN_RECEIVE`, `J1939_RECEIVE` and `CO_RECV_EMCY`).

### `CAN_BUS_INFO`

`STATE` (0 error active, 1 warning, 2 error passive, 3 bus-off, 4 interface down or missing), `TX_ERRORS`, `RX_ERRORS`, `BUS_OFF_COUNT`, `BUS_LOAD` (percent over the last second), `RX_COUNT`, `TX_COUNT`, `ERROR_FRAMES`.

The block reads the bridge's network info, so it needs `mailboxes.network_info` and works for the first 8 networks. `ERROR_FRAMES` and `BUS_OFF_COUNT` count the driver's error frames. The bridge reads the state every 100 ms; `BUS_OFF_COUNT` also catches a bus-off the adapter left between two readings. Some USB adapters (gs_usb, for example) leave bus-off by themselves within milliseconds, so a wrong bit rate shows as `STATE` moving between 3, 2 and 0 and a fast-rising `BUS_OFF_COUNT`; others stay bus-off until the kernel restarts them (`adapter.restart_ms`, see [config.md](config.md)). On a plain CAN network the bridge logs every state change, as the CANopen master does for its network. Drivers that report no error counters (gs_usb, for example) give `TX_ERRORS` and `RX_ERRORS` from the last error frame that carried them while the bus is not error active, and 0 once it is error active again.

### Error IDs

| ID | Meaning |
|---|---|
| 1 | The network is not running. |
| 2 | No such network. |
| 3 | An input is invalid: identifier out of range for its format, `DLC` over 8, `PERIOD` or `DEPTH` out of range. |
| 4 | The identifier belongs to the network's protocol and the network does not allow program overrides. |
| 5 | No free receiver (32 in all), cyclic job (as configured) or transmit queue space. |
| 6 | Not confirmed on the bus within `TIMEOUT`. |
| 7 | The network is bus-off or its interface is down. |
| 8 | Cancelled by a PLC stop, a network restart, the bridge's watchdog or a bridge restart, or a receiver closed because its frames waited unread for 1 s. |
| 9 | The network is listen-only. |
| 20 | The bridge is not reachable (`canworks.ok` FALSE). |
| 22 | The config has no request mailbox, receive mailbox, cyclic jobs or network info that the block needs. |

While the bridge's outputs are off ([the watchdog and client loss](modbus-bridge.md#outputs-the-watchdog-and-client-loss)), program frames stop like the `tx` messages: a running `CAN_SEND_CYCLIC` job sends nothing and goes on at its period when they are back on (no burst of the missed frames), and a frame `CAN_SEND` queued meanwhile ends with `ERROR_ID` 1.

`CAN_SEND_CYCLIC` and `CAN_RECEIVE` whose `ENABLE` stays TRUE try to start again on every call after `ERROR_ID` 1, 7, 8 or 20, so a block enabled from the first scan starts once the network runs, and comes back after a network restart. `ERROR` stays TRUE until it does; other errors need a new rising edge of `ENABLE`.

While the bus is off or the interface is down (`STATE` 3 or 4), a running `CAN_SEND_CYCLIC` or `CAN_RECEIVE` shows `ERROR` with `ERROR_ID` 7 but stays `ACTIVE`: the cyclic job keeps its `COUNT` and sends again once the bus is back, and the receiver keeps its queue. `ERROR` clears by itself when the bus is back.

The blocks never wait: they write requests into `canworks.link` and read the answers in later scans. Each send goes out once with its own frame, and each receiver and cyclic job has its own slot. A PLC stop ends every send with `ERROR_ID` 8, closes every receiver and stops every cyclic job; enabled blocks start again after the next start.

### ST helpers

These need no bridge and work on any `ARRAY[0..7] OF BYTE`:

| Function | Result |
|---|---|
| `CAN_GET_BITS(DATA, START_BIT, BIT_LENGTH, MOTOROLA, SIGNED) : LINT` | A signal, numbered as DBC files do (`MOTOROLA` FALSE: little-endian). |
| `CAN_SET_BITS(DATA, START_BIT, BIT_LENGTH, MOTOROLA, VALUE) : BOOL` | Writes a signal; FALSE and nothing written when a bit falls outside the 8 bytes. |
| `CAN_GET_UINT16` / `CAN_GET_UINT32(DATA, OFFSET, MOTOROLA)` | A byte-aligned value at a byte offset. |
| `CAN_SET_UINT16` / `CAN_SET_UINT32(DATA, OFFSET, MOTOROLA, VALUE) : BOOL` | Writes one. |
| `CAN_J1939_ID(PRIORITY, PGN, SOURCE, DESTINATION) : UDINT` | A 29-bit J1939 identifier (`DESTINATION` used for PDU1 PGNs). |
| `CAN_J1939_PGN(ID) : UDINT`, `CAN_J1939_SOURCE(ID) : USINT` | The parts of one. |

```
x := LINT_TO_INT(CAN_GET_BITS(DATA := frame, START_BIT := 0, BIT_LENGTH := 12, MOTOROLA := FALSE, SIGNED := TRUE));
```

The configurator's CAN messages page has **Copy as ST call** on each message: a `CAN_RECEIVE` or `CAN_SEND` declaration and call with the identifier filled in and one `CAN_GET_BITS`/`CAN_SET_BITS` line per signal.

## Tools

- **Bus trace**: frames that match a raw message (or a message of the network's `dbc`) show its name and signal values in the trace rows and the [frame inspector](frame-inspector.md).
- **Diagnostics status**: per raw message the frame count, short frames, unknown pages, timeout state and last time; program receivers, cyclic jobs, dropped frames and the confirmation mode.
- **Replay**: `canworks-diag replay FILE --network cab` plays a recorded trace (candump `.log`, `.asc`, `.trc`, pcapng or a canworks trace) onto a network through the bridge, with its original spacing or `--rate N`, once or `--loop`; `--adapter` plays it on a PC adapter instead. It has the `send_frame` guards (`allow_changes`, force on protocol identifiers), stops with Ctrl-C or on disconnect and runs at most 1000 frames per second.
- **Simulator**: a simulation file's `raw_devices` play plain CAN devices on a simulated bus or with `canworks-canopen-sim` on an interface; see [Plain CAN devices](simulator.md#plain-can-devices).
