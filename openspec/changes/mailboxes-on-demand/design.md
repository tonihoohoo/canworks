## Context

`bridge.mailboxes` gives the library's mailbox blocks their registers (`modbus-bridge-mailboxes`). Every client polls every register of the map: OpenPLC's Modbus master, the PLCopen copy code (truST, other PLCs) and the Node-RED config node. So the mailboxes cost the same whether or not a block is called.

Measured on `examples/openplc-modbus` (one network, main 23031b3):

| Setting | Input / holding registers | OpenPLC requests per poll | Copy assignments per scan |
|---|---|---|---|
| Off | 33 / 16 | 5 | 41 |
| 1 request only | 105 / 88 | 5 | 187 |
| 1 request + receive | 225 / 91 | 6 | 310 |
| Default (1 request, receive, 4 jobs, info) | 260 / 95 | 7 | 349 |
| 4 requests, 16 jobs | 524 / 323 | 13 | 841 |

With faster-mailboxes, a second receive block adds 120 registers and one request.

## Goals / Non-Goals

**Goals:**
- No mailbox cost unless a program uses mailbox blocks.
- The user sees, before choosing, what works without the mailboxes, what each part costs and what each part enables.
- A program that calls a mailbox block never meets `ERROR_ID` 22 by surprise when canworks can know about it (OpenPLC). When it can't (file connections), the user states it once on the connection.

**Non-Goals:**
- No change to the mailbox layout, the bridge's mailbox behavior or the blocks. `ERROR_ID` 22 stays as it is.
- No scan of programs canworks doesn't write: truST, CODESYS-side or Node-RED flows the user edited.
- No migration of configs with mailboxes.

## Decisions

### 1. Off by default, on by need

Nothing turns the mailboxes on by itself any more: not New config, not adding an OpenPLC connection, not a target switch. They come on in three ways:
- through the Function blocks switch (as today);
- through **Turn on what the program uses** (OpenPLC, Decision 2);
- through a connection's **canworks blocks** choice (Decision 3).

Why not keep them on for OpenPLC "so the blocks work out of the box"? A normal program pays 40 % more Modbus requests for nothing. With Decision 2, the first OpenPLC program that calls a block gets a one-click fix at Check/Save, before a Build, so out of the box still holds where canworks can see the program.

### 2. POU scan for the OpenPLC connection

`mailboxuse.py` reads the editor project's ST POUs (`pous/programs`, `pous/function_blocks` and `pous/functions` `.st` files, excluding the canworks generated `canworks_in`/`canworks_out`). It strips comments and strings, and finds variable declarations whose type is a mailbox block (`CAN_RECEIVE`, `CO_SDO_READ_STRING`, ...). It returns `{block: [POU names]}`. A declaration, not a call, is the signal: an instance in VAR is what makes the block run. It is cheap and has no false positives from comments.

Block → part (one table, shared with the configurator's Needs table and `stNeeds`):
- request: the SDO `_BYTES`/`_STRING`/`_REAL` blocks, `CAN_SEND`, `J1939_SEND`, `J1939_REQUEST`, `J1939_FIND_ECU`, `J1939_DM_READ`, `J1939_DM_CLEAR`;
- request + receive: `CAN_RECEIVE`, `J1939_RECEIVE`, `CO_RECV_EMCY`;
- request + cyclic: `CAN_SEND_CYCLIC`;
- network info: `CAN_BUS_INFO`, `J1939_ECU_INFO`.

Problems:
- **error** per missing part: "main declares CAN_RECEIVE, which needs the receive mailbox". The fix **Turn on what the program uses** sets exactly the needed parts: requests 1, `receive` as needed, `cyclic_jobs` 4 if any `CAN_SEND_CYCLIC` (more if more instances are declared, up to 16), `network_info` as needed. It places the areas, in one undo step; Save updates the declarations.
- **info** when the mailboxes are on and no POU declares a mailbox block: "The program uses no mailbox block: turning the mailboxes off saves N Modbus requests per poll", with **Turn off the mailboxes**. It is an info, not a warning, because another connection may use them (Decision 3 takes the union).

Alternative considered: scanning only on Build. Rejected, because Save is where canworks already touches the editor project, and Check runs on every change.

### 3. Connection blocks choice

`trust`, `plc` and `nodered` connections get `blocks`: `none` (default), `sdo_send`, `receive` or `all`. The mailboxes have one owner (request words, tickets and receivers assume one client, as modbus-connections' "Only the PLC writes with a PLC link" already says for writes). So at most one connection may choose something other than None, and none next to an OpenPLC connection, whose program owns them. The config's mailboxes are that owner's needs, plus anything set by hand. A connection change rewrites `bridge.mailboxes` in the same undo step, as `writers` follow the connections today. Parts set by hand are kept: the union only adds. Removing a connection's need asks nothing. Problems then shows the "unused" info when nothing needs the mailboxes any more.

- `sdo_send`: requests 1.
- `receive`: requests 1, receive.
- `all`: requests 1, receive, cyclic jobs 4, network info.

truST offers only `none` and `sdo_send`: the trimmed mailboxes fit its one request each way, and the PLCopen export's refusal stays for configs edited by hand. Node-RED offers the choice once `add-nodered-blocks` has given it block nodes. HMI has none.

### 4. Function blocks section

The switch label becomes "Mailboxes for the canworks mailbox blocks". The section shows whether on or off:
- **Works without mailboxes**: values, `CO_NMT`, `CO_NODE_LIVE`, `CO_SDO_READ`/`CO_SDO_WRITE` up to 4 bytes.
- **Needs mailboxes**: the current table (part → blocks) with a third column "Without mailboxes", the config-only alternative:
  - an `rx` message for `CAN_RECEIVE`;
  - a `tx` message on change or trigger for `CAN_SEND`;
  - a periodic `tx` message for `CAN_SEND_CYCLIC`;
  - `emcy_code_location` (the latest code per node) for `CO_RECV_EMCY`;
  - the J1939 config's `tx`, `rx` and `requests`;
  - `bus_state_location` for the info blocks;
  - "none" for SDOs over 4 bytes and for J1939 DM2/DM3/DM11.
- **Cost** from the map, as a difference: with the switch on, "The mailboxes take +227 input / +79 holding registers: 7 instead of 5 Modbus requests per poll"; with it off, what turning them on with the defaults would add. The server computes both maps (with and without), which is cheap.
- **Who needs them**: one line per connection or POU scan result, for example "OpenPLC program: receive (CAN_RECEIVE in main)" or "Line PLC (truST): SDO and send".

### 5. Bridge status

The bridge's status JSON gets `bridge.mailboxes`, with `operations` (mailbox operations started since the bridge started) and `receivers_opened`. `diag` prints "mailboxes: N operations, N receivers opened since start". With both 0 after more than a minute of a running PLC link, it adds "nothing has used the mailboxes: turn them off to save Modbus requests". This works for every client, including those canworks can't scan. The opposite case (a block without mailboxes) is invisible to the bridge and stays covered by Decisions 2-3 and Copy as ST call.

## Risks / Trade-offs

- **POU scan misses**: an instance declared in a library or a global list the scan doesn't read. → Scan global variable lists in `project.json` too. The block still says `ERROR_ID` 22, and the info wording is soft.
- **Union with hand-set parts** may keep mailboxes on that nobody needs. → The "unused" info and the bridge-status hint show it.
- **Order**: three changes before this one rewrite the same spec text. → Task 0 rewrites the deltas against the archived text before applying.
