# Raw CAN: plain CAN messages and frame blocks

Many devices on a machine bus speak neither CANopen nor J1939: joysticks, displays, sensors, battery packs and drives with their own frame layouts, usually described by a DBC file or a data sheet. canworks talks to them in two ways, on any network:

- **Config messages**: a `raw` object on a network lists received and sent messages with their signals mapped to `%I` and `%Q`. No program code is needed, as for PDOs.
- **Frame blocks**: `CAN_SEND`, `CAN_SEND_CYCLIC`, `CAN_RECEIVE` and `CAN_BUS_INFO` in the `canworks` library give the program full control of single frames, and ST functions pack and unpack signals.

Both work next to CANopen or J1939 on the same bus, and on a network with no protocol at all (`"protocol": "none"`). Classic CAN only: frames of up to 8 bytes, 11-bit or 29-bit identifiers, remote frames. CAN FD is not supported.

## Plain CAN networks

A network with `"protocol": "none"` has an `adapter`, an optional `raw` object and nothing else. It still gets everything the plugin gives any bus: bus state and error counters, the bus trace, bit rate detection, diagnostics status and `send_frame`.

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

`"listen_only": true` in the `adapter` of a `none` network makes the PLC a silent observer: it receives, but never acknowledges a frame or sends one. The plugin sets the controller to listen-only (SocketCAN ctrlmode, silent mode on slcan adapters). Where it cannot (`configure_link: false`, vcan, a simulated bus) it says so in the log and only refuses its own sends. A listen-only network may have no `tx` messages; program sends end with `ERROR_ID` 9 and `send_frame` is refused.

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

### Sent messages (`tx`)

| Field | Meaning |
|---|---|
| `id`, `extended`, `rtr`, `dlc` | The frame. `dlc` defaults to the bytes the signals need. |
| `period_ms` | Sent every 1 to 60000 ms. |
| `on_change`, `min_gap_ms` | Also sent when a signal value changes, but not more often than `min_gap_ms`; a change restarts the period. |
| `trigger_location` | `%QX`: a rising edge sends the frame once. |
| `enable_location` | `%QX`: FALSE stops periodic and on-change sends. |
| `fill` | The byte value for bits no signal covers, default 0. |
| `data_location` | `%QL`: the whole 8 bytes from the program; signals are written on top. |
| `override_protocol` | Needed to send an identifier the network's protocol uses (see [Protocol identifiers](#protocol-identifiers)). |
| `signals` | See [Signals](#signals). |

A `tx` message needs at least one of `period_ms`, `on_change` or `trigger_location`. Sending starts when the PLC runs and stops when it stops.

### Signals

| Field | Meaning |
|---|---|
| `name` | Used in declarations, the trace and the configurator. |
| `start_bit`, `length` | Bit numbering as DBC files use it: bit 0 is the least significant bit of byte 0. A little-endian signal starts at its least significant bit, a big-endian one at its most significant bit. |
| `byte_order` | `little` (Intel, default) or `big` (Motorola). |
| `signed` | Two's complement; the value is sign-extended into the location. |
| `scale`, `offset`, `unit`, `minimum`, `maximum`, `comment` | For tools only: declarations, the trace and the configurator show physical values. The PLC always gets the raw integer, as for CANopen and J1939. |
| `iec_location` | Big enough for `length`: `%IX`/`%QX` for 1 bit, then byte, word, double word or long word. |

### Protocol identifiers

On a CANopen or J1939 network some identifiers belong to the protocol: NMT, SYNC, TIME, EMCY, PDO, SDO, LSS and heartbeat COB-IDs of the configured nodes and the master, or any J1939 frame from the PLC's own address. A `tx` message on such an identifier is a config error unless it says `"override_protocol": true`, and a program send on one fails with `ERROR_ID` 4 unless the network has `"raw": { "program_override_protocol": true }`. Receiving them is always allowed. The diagnostics `send_frame` guard names raw messages too ("raw message Lamps"), so an engineer cannot collide with the program by accident.

### From a DBC file

`canworks-config` imports a DBC file on a network's **CAN messages** page (**Import DBC**): pick the messages, choose received or sent, and **Suggest addresses** fills in free locations. The file is kept as the network's `raw.dbc`, so the trace can decode its other messages too.

Messages with J1939 attributes belong on a J1939 network; plain 11-bit and 29-bit messages become raw messages. Multiplexed signals are not supported. The other way round, `canworks-deploy --export-dbc` writes a network's raw messages into its DBC file next to the protocol's frames.

### Declarations

`canworks-deploy --new-project` and the configurator's declarations write a located variable per signal and per location, named `<message>_<signal>` (`<network>_<message>_<signal>` with several networks), with the message, scale and unit in its description:

```
Joystick_X AT %IW304 : INT;
Joystick_status AT %IX300.0 : BOOL;
Lamps_Red AT %QX300.1 : BOOL;
```

## Frame blocks

The blocks are in the `canworks` library next to the [SDO blocks](plc-sdo.md); install and enable it the same way. A project made with `canworks-deploy --new-project ... --blocks` has it enabled. Every block has `NETWORK : USINT` (the network's place in `networks`, 0 the first) and the outputs `ERROR : BOOL` and `ERROR_ID : UINT`. The frame data is `ARRAY[0..7] OF BYTE`, passed as an in-out pin.

### `CAN_SEND`: one frame

```
VAR
  tx : CAN_SEND;
  d : ARRAY[0..7] OF BYTE;
  go : BOOL;
END_VAR

d[0] := 1; d[1] := 2;
tx(EXECUTE := go, ID := 16#510, DLC := 2, DATA := d);
IF tx.DONE THEN go := FALSE; END_IF;
```

A rising edge of `EXECUTE` queues one frame with that call's inputs (`ID`, `EXTENDED`, `RTR`, `DLC`, `DATA`) and sets `BUSY`; edges and input changes while `BUSY` are ignored. `DONE` comes when the frame is confirmed on the bus, `ERROR` with `ERROR_ID` 6 when it is not within `TIMEOUT` (`T#0s` = 100 ms). The outputs stay while `EXECUTE` stays TRUE and for one call after it fell.

What "confirmed" means depends on the adapter. SocketCAN drivers that echo sent frames (most USB adapters and on-chip controllers) echo a frame only once it was acknowledged on the bus, so `DONE` means another device took it. Without echo (vcan, some slcan firmware) `DONE` means the frame was handed to the driver. The diagnostics status shows which (`confirm: echo` or `confirm: write`). On a bus with no other device a frame is never acknowledged, and `CAN_SEND` ends with `ERROR_ID` 6. When the adapter's transmit queue is full meanwhile, the plugin keeps the program's frame and tries again until `TIMEOUT`, and `CAN_SEND_CYCLIC` keeps its job but `COUNT` stops until the bus takes frames again; `CAN_BUS_INFO` shows the state (usually 2, error passive).

### `CAN_SEND_CYCLIC`: a frame on a timer

```
VAR
  hb : CAN_SEND_CYCLIC;
  d : ARRAY[0..7] OF BYTE;
END_VAR

d[0] := d[0] + 1;
hb(ENABLE := TRUE, ID := 16#18FF0080, EXTENDED := TRUE, DLC := 8, PERIOD := T#10ms, DATA := d);
```

While `ENABLE` is TRUE the plugin sends the frame every `PERIOD` (1 ms to 60 s) from its own timer, whatever the PLC cycle. `ID` and `EXTENDED` are taken when `ENABLE` rises; `DATA`, `DLC` and `PERIOD` on every call, used from the next send. `COUNT` counts frames sent since `ENABLE` rose. A network has at most 16 cyclic jobs.

### `CAN_RECEIVE`: a filtered queue

```
VAR
  rx : CAN_RECEIVE;
  frame : ARRAY[0..7] OF BYTE;
  last_temp : INT;
END_VAR

rx(ENABLE := TRUE, ID := 16#600, MASK := 16#780, RX_DATA := frame);  (* 0x600..0x67F *)
WHILE rx.NEW DO
  IF rx.RX_ID = 16#605 THEN
    last_temp := CAN_GET_UINT16(DATA := frame, OFFSET := 2, MOTOROLA := FALSE);
  END_IF;
  rx(ENABLE := TRUE, RX_DATA := frame);
END_WHILE;
```

While `ENABLE` is TRUE the plugin queues every frame of the given format whose `(identifier AND MASK) = (ID AND MASK)`, up to `DEPTH` frames (`0` = 32, at most 256). `MASK` 0 means only `ID` itself; `ANY := TRUE` takes every frame. Each call takes at most one frame: `NEW` TRUE with its `RX_ID`, `RX_EXTENDED`, `RX_RTR`, `RX_DLC`, `RX_DATA` and `TIMESTAMP` (UTC microseconds from the kernel), or `NEW` FALSE with the last frame's outputs kept. Calling it in a `WHILE rx.NEW DO` loop drains the queue in one scan; `QUEUED` says how many frames still wait. A frame arriving at a full queue is dropped, sets `OVERFLOW` until `ENABLE` falls and counts in `DROPPED`. Frames the plugin sends itself are not queued. On a plain CAN network, frames other programs on the PLC host send (`cansend`, for example) are queued like frames from the bus; on a CANopen or J1939 network they are not, because the kernel marks them the same way as the protocol's own frames. A network has at most 32 receivers.

### `CAN_BUS_INFO`

`STATE` (0 error active, 1 warning, 2 error passive, 3 bus-off, 4 interface down or missing), `TX_ERRORS`, `RX_ERRORS`, `BUS_OFF_COUNT`, `BUS_LOAD` (percent over the last second), `RX_COUNT`, `TX_COUNT`, `ERROR_FRAMES`.

`ERROR_FRAMES` and `BUS_OFF_COUNT` count the driver's error frames. Drivers that report no error counters (gs_usb, for example) give `TX_ERRORS` and `RX_ERRORS` from the last error frame that carried them while the bus is not error active, and 0 once it is error active again.

### Error IDs

| ID | Meaning |
|---|---|
| 1 | The plugin is not loaded or too old, or the network is not running. |
| 2 | No such network. |
| 3 | An input is invalid: identifier out of range for its format, `DLC` over 8, `PERIOD` or `DEPTH` out of range. |
| 4 | The identifier belongs to the network's protocol and the network does not allow program overrides. |
| 5 | No free receiver, cyclic job or transmit queue space. |
| 6 | Not confirmed on the bus within `TIMEOUT`. |
| 7 | The network is bus-off or its interface is down. |
| 8 | Cancelled by a PLC stop or a network restart. |
| 9 | The network is listen-only. |

`CAN_SEND_CYCLIC` and `CAN_RECEIVE` whose `ENABLE` stays TRUE try to start again on every call after `ERROR_ID` 1, 7 or 8, so a block enabled from the first scan starts once the network runs, and comes back after a network restart. `ERROR` stays TRUE until it does; other errors need a new rising edge of `ENABLE`.

The blocks never wait on the bus, allocate memory or log on the scan thread. A PLC stop ends every send with `ERROR_ID` 8, closes every receiver and stops every cyclic job.

### ST helpers

These need no plugin and work on any `ARRAY[0..7] OF BYTE`:

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
- **Diagnostics status**: per raw message the frame count, short frames, timeout state and last time; program receivers, cyclic jobs, dropped frames and the confirmation mode.
- **Replay**: `canworks-diag replay FILE --network cab` plays a recorded trace (candump `.log`, `.asc`, `.trc`, pcapng or a canworks trace) onto a network through the plugin, with its original spacing or `--rate N`, once or `--loop`; `--adapter` plays it on a PC adapter instead. It has the `send_frame` guards (`allow_changes`, force on protocol identifiers), stops with Ctrl-C or on disconnect and runs at most 1000 frames per second.
- **Simulator**: a simulation file's `raw_devices` play plain CAN devices on a simulated bus or with `canworks-sim` on an interface; see [Plain CAN devices](simulator.md#plain-can-devices).
