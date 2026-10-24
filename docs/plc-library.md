# The `canworks` function block library

`canworks` is one OpenPLC Editor library with the function blocks and functions a PLC program uses to work with the networks canworks-bridge runs for it ([OpenPLC](modbus-bridge.md#openplc)): SDO transfers of any size, NMT, EMCY, CAN frames, J1939 messages and trouble codes. The blocks talk to the bridge through the registers the generated `canworks_in` and `canworks_out` programs copy every scan, so they need nothing inside the runtime and never make the scan wait, and they work on [another Modbus PLC](#on-another-modbus-plc) too. The library's version is the PC tools' version. In Node-RED the same jobs are nodes of the `node-red-canworks` package, with the same ERROR_IDs ([node-red.md](node-red.md#block-nodes)).

## What it holds

| Family | Blocks | Functions | Reference |
|---|---|---|---|
| CANopen over the bridge | `CO_SDO_READ`, `CO_SDO_WRITE`, `CO_NMT`, `CO_NODE_LIVE` | | [below](#blocks-over-the-bridge) |
| CANopen over the mailboxes | `CO_SDO_READ_BYTES`, `CO_SDO_WRITE_BYTES`, `CO_SDO_READ_STRING`, `CO_SDO_WRITE_STRING`, `CO_SDO_READ_REAL`, `CO_SDO_WRITE_REAL`, `CO_RECV_EMCY` | | [SDO blocks](#sdo-blocks), [EMCY](#every-emcy-co_recv_emcy) |
| CAN frames over the mailboxes | `CAN_SEND`, `CAN_SEND_CYCLIC`, `CAN_RECEIVE`, `CAN_BUS_INFO` | | [Frame blocks](#frame-blocks), [raw-can.md](raw-can.md#frame-blocks) |
| J1939 over the mailboxes | `J1939_SEND`, `J1939_RECEIVE`, `J1939_REQUEST`, `J1939_ECU_INFO`, `J1939_FIND_ECU`, `J1939_DM_READ`, `J1939_DM_CLEAR` | | [J1939 blocks](#j1939-blocks), [j1939.md](j1939.md#program-blocks) |
| The mailboxes' own | `CW_LINK_SERVICE` (called by `canworks_in`), `CW_MB_CALL`, `CW_SDO_XFER`, `CW_REQUEST`, `CW_RX` | `CW_CHAR`, `CW_CHAR_CODE` | [The mailboxes](#the-mailboxes); not called by programs |
| Bit-exact REAL conversions | | `CW_DWORD_TO_REAL`, `CW_REAL_TO_DWORD`, `CW_LWORD_TO_LREAL`, `CW_LREAL_TO_LWORD` | [below](#real-conversions) |
| CAN frame helpers | | `CAN_GET_BITS`, `CAN_SET_BITS`, `CAN_GET_UINT16`, `CAN_SET_UINT16`, `CAN_GET_UINT32`, `CAN_SET_UINT32`, `CAN_J1939_ID`, `CAN_J1939_PGN`, `CAN_J1939_SOURCE` | [raw-can.md](raw-can.md#st-helpers) |
| J1939 helpers | `J1939_NAME_SPLIT`, `J1939_DTC_SPLIT` | `J1939_GET_BITS`, `J1939_SET_BITS`, `J1939_NAME_MAKE`, `J1939_DTC_MAKE` | [j1939.md](j1939.md#program-blocks) |

`canworks-deploy library --list` prints every block and function of the installed tools' library.

The SDO, EMCY, CAN frame and J1939 blocks keep the names and pins the OpenPLC plugin's blocks had, plus the in-out `LINK := canworks.link`, and work through [the bridge's mailboxes](#the-mailboxes). `CO_NETWORK_START`, `CO_NETWORK_STOP` and `CO_GET_STATE` are gone; `CO_NMT` and the status block cover them. A program that used the plugin's blocks gets `LINK := canworks.link` on every call, and its ERROR_ID 1 or 4 "the plugin is not loaded" now means "the network is not running".

## Install and enable

The PC tools carry the library in the version that matches them. On the PC with OpenPLC Editor:

```sh
canworks-deploy library --install
```

installs it into the editor as its Library Manager does; restart the editor if it is open. Or write the file and add it in the editor's Library Manager with "install from file":

```sh
canworks-deploy library --out .      # writes canworks.stlib
```

Each `deploy-v` release also carries `canworks.stlib`. Then enable the library in the project (the editor's Library Manager, or `canworks-deploy library --project <project folder>`). A project made with **Install the canworks library in the project** in the configurator's New editor project dialog has it enabled already, and the library is installed into the editor if it is missing or older.

An entry's [bit channels](config.md#bit-channels) are BOOLs of their own in `canworks`, such as `canworks.dio_door`, at the bit the register map shows for them: `canworks_in` reads each from its entry's register, and `canworks_out` ORs each into its entry's word, so an output bit is on when the entry's value or its BOOL sets it. Bits added to a config reach an editor project with its next Save.

## When the bridge is lost

`canworks.ok` is TRUE while the bridge answers with this program's map and its status counter moves; it goes FALSE within the stale time (3 × the bridge's watchdog, at least 300 ms) after the bridge stops, crashes or loses its network. Gate your outputs and decisions on it. While it is FALSE, the status, state and timeout values (node status bits and state bytes, the master's state and bus state, PDO timeout bits, message status bits) read 0, and the other values keep their last ones, or read 0 when the connection's **Inputs when the bridge is lost** is **Set to 0** (`"inputs_on_loss": "zero"`). `canworks.bus_ok` is TRUE while `canworks.ok` is TRUE and every CAN network of the bridge has its bus up (status byte 7 bit 1 clear): FALSE with a pulled cable, a missing adapter or a bus-off. What the nodes themselves do is in [When the bridge fails](modbus-bridge.md#what-the-nodes-do).

```iecst
IF canworks.ok AND canworks.bus_ok THEN
  canworks.dio_valve_1 := want_open;
ELSE
  alarm := TRUE;
END_IF;
```

## Blocks over the bridge

Every block takes `LINK`, the generated `canworks.link`, as its in-out, and `NETWORK : USINT`, the network's place in the config's `networks` list counting from 0:

```iecst
read_vendor(EXECUTE := start, NETWORK := 0, NODE := 5, INDEX := 16#1018, SUBINDEX := 1, LINK := canworks.link);
IF read_vendor.DONE THEN vendor := read_vendor.DATA; END_IF;
```

| Block | Inputs | Outputs |
|---|---|---|
| `CO_SDO_READ` | `EXECUTE`, `NETWORK`, `NODE`, `INDEX : UINT`, `SUBINDEX : USINT`, `TIMEOUT : TIME` | `BUSY`, `DONE`, `ERROR`, `ERROR_ID : UINT`, `ABORT_CODE : UDINT`, `DATA : UDINT` |
| `CO_SDO_WRITE` | the same and `DATA : UDINT`, `SIZE : USINT` (1-4 bytes) | `BUSY`, `DONE`, `ERROR`, `ERROR_ID`, `ABORT_CODE` |
| `CO_NMT` | `EXECUTE`, `NETWORK`, `NODE` (0: every node), `COMMAND : USINT` (1 start, 2 stop, 128 pre-operational, 129 reset node, 130 reset communication), `TIMEOUT` | `BUSY`, `DONE`, `ERROR`, `ERROR_ID` |
| `CO_NODE_LIVE` | `NETWORK`, `NODE` | `LIVE : BOOL` (the node is OPERATIONAL) |

A rising edge of `EXECUTE` starts one job with the inputs of that call. `BUSY` is TRUE until it ends; then `DONE` or `ERROR` is TRUE for as long as `EXECUTE` stays TRUE, or for one call if it is already FALSE. Call the instance every scan while it is busy. `TIMEOUT` T#0s means 5 s.

The bridge has one SDO request block and one control block, so instances take turns: an instance that finds them in use stays `BUSY` until the one before it ends, in the order they started. The config needs the bridge's SDO registers (with `sdo_bridge_write` for writes), control block and a live list per network the blocks use; the configurator sets them up when a config switches to OpenPLC.

| `ERROR_ID` | Meaning |
|---|---|
| 1 | The node aborted the SDO transfer; `ABORT_CODE` says why. |
| 2 | No answer within `TIMEOUT`. |
| 5 | NMT refused: the network's bus is down, or 16 of its commands still wait. |
| 6 | An input is out of range (node, size, command). |
| 8 | Cancelled: the bridge restarted and did not run the request ([modbus-bridge.md](modbus-bridge.md#after-a-bridge-restart)). Start the block again. |
| 20 | The bridge is not reachable: `canworks.ok` is FALSE at the start or during the job. |
| 21 | SDO writes are not allowed by the config (`ABORT_CODE` 16#08000020). |
| 22 | The config has no SDO registers or no control block for this block. |

## The mailboxes

The blocks below talk to the bridge through `bridge.mailboxes` ([modbus-bridge.md](modbus-bridge.md#function-block-mailboxes)). They are off until a program needs them ([below](#with-or-without-the-mailboxes)); the configurator's defaults when they are turned on are one **request mailbox** (any request with an answer: an SDO transfer, a send, a J1939 request, opening a receiver), the **receive mailbox** (frames, J1939 messages and EMCYs for the receiving blocks), 4 **cyclic jobs** (`CAN_SEND_CYCLIC`) and **network info** (`CAN_BUS_INFO`, `J1939_ECU_INFO`). The configurator sets them in the **Function blocks** section of the Modbus bridge page; after a change there, Save the editor project (or run `canworks-deploy --into-project`) and Build again ([configurator.md](configurator.md#modbus-bridge)).

| Block | Needs | Round trips |
|---|---|---|
| `CO_SDO_READ_BYTES`, `CO_SDO_READ_STRING`, `CO_SDO_READ_REAL` | a request mailbox | 1, plus one per further 128 bytes of the answer |
| `CO_SDO_WRITE_BYTES`, `CO_SDO_WRITE_STRING`, `CO_SDO_WRITE_REAL` | a request mailbox | 1, plus one per 128 bytes before the write when it is longer than 128 |
| `CAN_SEND`, `J1939_DM_READ`, `J1939_DM_CLEAR`, `J1939_FIND_ECU` (per look) | a request mailbox | 1 |
| `J1939_SEND`, `J1939_REQUEST` | a request mailbox | like the SDO writes and reads |
| `CAN_SEND_CYCLIC` | a request mailbox and a cyclic job | 1 to start and to change `DATA`, `DLC` or `PERIOD`; none while it runs |
| `CAN_RECEIVE`, `CO_RECV_EMCY` | the receive mailbox and a request mailbox (to open) | 1 to open; then records come with every batch |
| `J1939_RECEIVE` | the same | as `CAN_RECEIVE`, plus one per 128 bytes of a message longer than 8 bytes |
| `CAN_BUS_INFO`, `J1939_ECU_INFO` | network info (the first 8 networks) | none: read every scan |

A round trip is about two polls of the bridge: the request goes out with the next poll and the answer comes back with the one after, so 20-30 ms at the default 10 ms poll, plus the time on the bus. The receive mailbox shows 9 CAN frames per batch (21 with `receive_blocks: 2`), and the next batch comes once every receiving block has read its records, one batch every two polls: about 450 frames per second at the default 10 ms poll, or 1050 with two receive blocks ([modbus-bridge.md](modbus-bridge.md#receive-throughput)). Frames of one batch share their `TIMESTAMP`. For more, or for frames every few milliseconds, use the config's `rx` and `tx` messages ([raw-can.md](raw-can.md#config-messages)) or `CAN_SEND_CYCLIC`, whose frames the bridge sends from its own timer.

**Sharing.** Blocks that need a request mailbox take a ticket when they start and get a mailbox in that order; an instance keeps it for its whole transfer, so with one request mailbox the blocks take turns. Waiting for a mailbox does not count against `TIMEOUT`. An instance that is no longer called drops out of the order, and loses its mailbox after 100 scans. More request mailboxes (up to 4) let that many transfers run at once.

**Link limits.** 4 request mailboxes, 32 receivers in all (`CAN_RECEIVE`, `J1939_RECEIVE`, `CO_RECV_EMCY` instances that are enabled), up to 16 cyclic jobs, network info for the first 8 networks. Ordering by tickets assumes the blocks run in one task, as OpenPLC's do; in several tasks of another PLC they stay correct, but the order is per task.

**The link stops.** When the PLC stops (the PLC link header says so), its map differs, or the bridge's watchdog fires, the bridge cancels every running operation, stops every cyclic job and closes every receiver: the blocks show `ERROR_ID` 8, and those with `ENABLE` start again by themselves once the link is back. A receiver whose block is no longer called while its records wait is closed after 1 s, so it does not hold up the others.

**The bridge restarts.** A new bridge does not know which request it ran last, so it takes the first request words it gets after its start only as the baseline: a request in them is not run and ends with `ERROR_ID` 8. A restart therefore never repeats a send or an SDO write; a block whose request was written just as the bridge started gets 8 and the program starts it again.

### With or without the mailboxes

Every client polls the mailboxes' registers on every cycle, whether or not a block is called, so they are off by default. They come on when a program needs them:

- **OpenPLC**: Check and Save read the editor project's POUs. A declared mailbox block whose part is off is an error in Problems, with **Turn on what the program uses**, which turns on only the parts the declared blocks need. Mailboxes that neither the program nor a connection's **canworks blocks** choice needs get a warning with **Turn off the mailboxes**. The scan counts arrays of a block with any bounds and dimensions (integers and the project's constants, `ARRAY[1..N, 0..1] OF CAN_SEND_CYCLIC`), `canworks.CAN_RECEIVE` as `CAN_RECEIVE`, and the blocks inside a function block once per instance of it. Ladder, FBD and other non-ST POU files count each block they name, with an unknown number of instances. When a count cannot be worked out, Turn on what the program uses gives that part the most (16 cyclic jobs) and Problems never offers Turn off.
- **Another client** (another PLC, Node-RED): turn them on in the **Function blocks** section of the Modbus bridge page ([configurator.md](configurator.md#modbus-bridge)), with only the parts its program uses. Copy as ST call names a missing part.
- `canworks-diag status` shows how many mailbox operations and receivers the bridge has had since it started, and says when nothing has used them.

**What works without them:** the config's values (PDOs, CAN messages, J1939 PGNs, DM1 codes and lamps), `CO_NMT`, `CO_NODE_LIVE`, the status block, and `CO_SDO_READ` and `CO_SDO_WRITE` for objects of up to 4 bytes on any node.

**What can't be done without them:** SDOs over 4 bytes from the program, every EMCY (without them only the latest code per node), sending or receiving a CAN id that is not in the config, J1939 requests of any PGN, DM2 reads, DM3/DM11 clears and finding an ECU by NAME, and bus load and error counters.

**What they cost** (the example `examples/openplc-modbus`, one network, OpenPLC polling every 10 ms):

| Mailboxes | Input / holding registers | Modbus requests per poll |
|---|---|---|
| Off | 33 / 16 | 5 |
| 1 request mailbox only | 105 / 88 | 5 |
| 1 request mailbox and the receive mailbox | 225 / 91 | 6 |
| Defaults (1 request, receive, 4 cyclic jobs, network info) | 260 / 95 | 7 |
| 4 request mailboxes, 16 cyclic jobs | 524 / 323 | 13 |

`canworks_in` and `canworks_out` also copy every mailbox word on every scan.

That copy is what the PLC feels. On a Raspberry Pi 5 bench with one CANopen node and a 10 ms poll, the OpenPLC runtime used about 9 % CPU without mailboxes, 27-29 % with the request and receive mailboxes and 31 % with the defaults. The bridge stayed at about 2 % either way.

**Without mailboxes, use the config instead:**

| Block | Instead |
|---|---|
| `CAN_RECEIVE`, `J1939_RECEIVE` | a received CAN message or J1939 PGN on `%I` locations ([raw-can.md](raw-can.md#config-messages), [j1939.md](j1939.md)) |
| `CAN_SEND`, `J1939_SEND`, `J1939_REQUEST` | a sent CAN message on change or on a trigger bit; the J1939 network's sent PGNs and requests |
| `CAN_SEND_CYCLIC` | a periodic sent CAN message |
| `CO_RECV_EMCY` | the node's `emcy_code_location` (its latest EMCY) |
| `CAN_BUS_INFO`, `J1939_ECU_INFO` | the network's `bus_state_location` and the J1939 address location |
| `CO_SDO_READ_BYTES` and the other long SDO blocks | SDO variables in the config for numbers of up to 64 bits ([config.md](config.md#sdo-variables)), or `CO_SDO_READ` / `CO_SDO_WRITE` up to 4 bytes; strings and domains need the mailboxes |

Rule of thumb: put everything known when configuring into the config, and use the mailbox blocks only for what the program decides at run time.

### Error IDs of every mailbox block

Each family keeps the numbers of the tables below and in [raw-can.md](raw-can.md#error-ids) and [j1939.md](j1939.md#error-ids). Every mailbox block adds:

| `ERROR_ID` | Meaning |
|---|---|
| 20 | The bridge is not reachable or does not serve this program's map (`canworks.ok` FALSE at the start or during the transfer). |
| 22 | The config has no part of the mailboxes this block needs (see the table above); the block ends in the call that started it. |

"Cancelled" (8) also covers a receiver or job the bridge closed because the link stopped or the receiver stalled, and "no free receiver or job" (5, or 9 for J1939) also covers the 32 receivers and the configured cyclic jobs.

## SDO blocks

| Block | Data | For |
|---|---|---|
| `CO_SDO_READ_REAL` / `CO_SDO_WRITE_REAL` | `VALUE : LREAL`, `SIZE` (write: 4, 8, or 0 for the EDS type) | REAL32 and REAL64 |
| `CO_SDO_READ_STRING` / `CO_SDO_WRITE_STRING` | `VALUE : STRING` | VISIBLE_STRING, up to 254 characters |
| `CO_SDO_READ_BYTES` / `CO_SDO_WRITE_BYTES` | `BUFFER : ARRAY[0..1023] OF BYTE`, `SIZE : UINT` | any object up to 1024 bytes (OCTET_STRING, DOMAIN, records) |

They have the handshake of `CO_SDO_READ` ([above](#blocks-over-the-bridge)) with the inputs `EXECUTE`, `NETWORK`, `NODE` (1..127), `INDEX`, `SUBINDEX` and `TIMEOUT` (`T#0s` means 5 s), and the outputs `BUSY`, `DONE`, `ERROR`, `ERROR_ID` and `ABORT_CODE`:

```iecst
rd_name(EXECUTE := go, NETWORK := 0, NODE := 5, INDEX := 16#1008, SUBINDEX := 0, LINK := canworks.link);
IF rd_name.DONE THEN
  device_name := rd_name.VALUE;
END_IF;
```

`CO_SDO_READ_REAL` reads a 4- or 8-byte reply into `VALUE`. A string reply longer than 254 characters ends with `ERROR_ID` 7 (read it with `CO_SDO_READ_BYTES`); `CO_SDO_WRITE_STRING` sends `VALUE` without a terminating zero. `CO_SDO_READ_BYTES` copies the reply into `BUFFER` and its length into `SIZE`; `CO_SDO_WRITE_BYTES` sends the first `SIZE` bytes of `BUFFER` in one SDO download. The transfers go through the bridge's SDO queue, so they take turns per node with the config's SDO variables, wait while a node boots, and never save anything to the device's non-volatile memory unless the program writes 0x1010 itself.

| `ERROR_ID` | Meaning |
|---|---|
| 1 | The node aborted the transfer; `ABORT_CODE` holds its CiA 301 abort code (for example `16#06020000` object does not exist, `16#06010002` read-only). |
| 2 | No answer within `TIMEOUT`, counted from when the node can be asked. |
| 3 | The node is not available: configured, but lost or failed to boot. |
| 4 | The network is not running, or it is not a CANopen master network. |
| 5 | Too many SDO transfers wait in the bridge. |
| 6 | An input is out of range (node, size, a `SIZE := 0` without an EDS type). |
| 7 | The reply does not fit the block (more than 1024 bytes, 254 characters, or a REAL reply that is not 4 or 8 bytes). |
| 8 | Cancelled: the link stopped, CANopen restarted or the bridge restarted during the transfer. |
| 20, 22 | [As for every mailbox block](#error-ids-of-every-mailbox-block). |

### Every EMCY: `CO_RECV_EMCY`

A node's `emcy_code_location` holds only its latest EMCY. `CO_RECV_EMCY` gives the program every EMCY of the network's nodes, in order, from the bridge's history of the network's last 64, kept from the start of the CANopen session.

- Inputs: `ENABLE`, `NETWORK`, `NODE` (0: every node), `SKIP_OLD` (start at the next EMCY instead of the oldest kept one). In-out: `MSEF : ARRAY[0..4] OF BYTE` and `LINK`.
- Outputs: `ACTIVE`, `RECEIVED`, `EMCY_NODE`, `ERROR_CODE : WORD`, `ERROR_REGISTER : BYTE`, `TIMESTAMP` (UTC microseconds), `QUEUED`, `OVERFLOW`, `LOST`, `ERROR`, `ERROR_ID`.
- Each call gives at most one EMCY; call it again while `RECEIVED` is TRUE to read every waiting one in the scan. Every instance reads from its own place, so two instances both get every EMCY. An instance that falls more than 64 behind counts the lost ones in `LOST`.
- `ERROR_ID` 8 for one call: a new CANopen session started; reading goes on with its EMCYs. 4: CANopen is not running (it tries again while `ENABLE` stays TRUE). 5: no free receiver.

```iecst
rx(ENABLE := TRUE, NODE := 0, MSEF := msef, LINK := canworks.link);
WHILE rx.RECEIVED DO
  faults := faults + 1;   (* rx.EMCY_NODE, rx.ERROR_CODE, rx.ERROR_REGISTER, msef *)
  rx(ENABLE := TRUE, NODE := 0, MSEF := msef, LINK := canworks.link);
END_WHILE;
```

## Frame blocks

`CAN_SEND`, `CAN_SEND_CYCLIC`, `CAN_RECEIVE` and `CAN_BUS_INFO` are described with examples in [raw-can.md](raw-can.md#frame-blocks). Over the mailboxes:

- `CAN_SEND` ends with `DONE` when the bridge reports the frame confirmed on the bus.
- `CAN_SEND_CYCLIC` starts its job when `ENABLE` rises and sends changed `DATA`, `DLC` or `PERIOD` to the bridge only when they change; the bridge sends the frame from its own timer. The block must be called at least once a second (it writes a keepalive), or the bridge stops the frame.
- `CAN_RECEIVE` gives the frames of the current batch, one per call; a `WHILE rx.RECEIVED DO ... END_WHILE` loop reads them all in the scan, and the next batch comes in a later scan.
- `CAN_BUS_INFO` reads the network info, updated every 100 ms, for the first 8 networks.

## J1939 blocks

The J1939 message and trouble code blocks are described with examples in [j1939.md](j1939.md#program-blocks). Over the mailboxes, `J1939_SEND` and `J1939_REQUEST` move messages longer than 128 bytes in 128-byte parts, `J1939_RECEIVE` reads a message longer than 8 bytes whole before it reports `RECEIVED`, `J1939_ECU_INFO` reads the network info, `J1939_FIND_ECU` looks again on every turn it gets while `ENABLE` is TRUE (`VALID` after the first answer), and `J1939_DM_READ` with `PREVIOUS` FALSE gives the bridge's latest DM1 from `SOURCE` without bus traffic.

## On another Modbus PLC

The blocks are plain IEC 61131-3 ST that uses only standard functions and `TON`, with strict typing (typed literals such as `WORD#0`, no reserved words as names), so they build unchanged on STruC++, CODESYS and other strict IEC compilers, and work on any PLC that reads the bridge as a Modbus TCP client and can hold the 1280-word `LINK` array. For a PLC that imports PLCopen XML, `--export-plcopen` writes all of the steps below as one file ([plcopen.md](plcopen.md)); `canworks-deploy library --format plcopen --out lib` writes the library alone as `lib/canworks-library.xml`. By hand:

1. Write the library's sources: `canworks-deploy library --format st --out lib` (one `.st` file per block and function, each with the library version in its first line), and add them to the PLC project.
2. Write the PLC link for the config: `canworks-deploy --config canworks.json --export-modbus-map link.st`, or the **Download** of an **Other PLC** connection with format ST on the configurator's Modbus bridge page. The config needs the PLC link (`bridge.plc_link`; it gives the map hash and the header the bridge checks). The file holds the `canworks` global variable list (`ok`, `link`, the typed values and the channel variables `in_w` and `out_w`), the client channels to create, and the programs `canworks_in` and `canworks_out`.
3. Save the list as a global variable list named `canworks`, create the client channels (function 4 into `canworks.in_w`, function 16 from `canworks.out_w`) at a cycle well below the bridge's watchdog, and call `canworks_in` first and `canworks_out` last in every scan of the task that uses the values and the blocks.
4. Call the blocks with `LINK := canworks.link`, as on OpenPLC.

Export the file again after any config change: the programs carry the map hash.

## REAL conversions

`canworks_in` and `canworks_out` move REAL and LREAL values as their bit patterns. `CW_DWORD_TO_REAL(16#3FC00000)` is 1.5 and `CW_REAL_TO_DWORD(1.5)` is 16#3FC00000; the LWORD pair does the same for LREAL. Unlike `DWORD_TO_REAL`, which converts the number, they keep every bit, including infinities, NaN and subnormal values, and are written in ST, so they work on any IEC 61131-3 runtime.

## Building it

The sources are in `library/modbus/` (the blocks over the bridge and its mailboxes, their helpers and the REAL conversions) and `library/canworks/` (the ST helpers); `library/build.sh` builds `canworks.stlib` into the deploy package with STruC++, CI builds the whole library through the generic PLCopen export with a strict IEC compiler, and `test/plc_modbus/run.sh` runs the blocks against models of the bridge's registers and mailboxes, the generated programs, and builds the PLC link file for another PLC with the library ([development.md](development.md)).
