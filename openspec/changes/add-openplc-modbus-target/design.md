## Context

Research: research/modbus-only-2026-10-22.md (project files), checked against canworks main, OpenPLC Runtime v4.3.1 (`core/src/drivers/plugins/python/modbus_master`) and the current OpenPLC Editor source.

Runtime facts this design relies on:
- `conf/modbus_master.json` lists devices (TCP: host, port, slave id, timeout) with I/O points `fc`, `offset`, `iec_location` (first element), `len`, `cycle_time_ms`, `error_handling` (`keep-last-value` | `set-to-zero`). One thread per endpoint polls at the GCD of the point cycle times.
- Reads of one poll round are written into the image under one `image_lock`; write points are read from the image under one lock and sent every due cycle, changed or not.
- The master runs between the runtime's `start_loop` and `stop_loop`, so only while the PLC runs. On stop, v4.3.1 zeroes `%Q`, runs one more cycle and waits 500 ms before `stop_loop`, so one write round with zeroed outputs reaches the bridge.
- `%D`/`%L` points are decoded low word first.

Editor facts:
- Each remote device is a file `devices/remote/<name>.json`; the compile step turns Modbus TCP devices into `conf/modbus_master.json`, and Build and upload sends it.
- The editor's own UI gives every register one `%IW`/`%QW` and every bit one `%IX`/`%QX`, with an optional alias per point. A group's `iec_location` is its first point's.

## Goals / Non-Goals

Goals: OpenPLC reaches canworks only through upstream's Modbus master; setup is automatic from the configurator; the program uses typed, named values; a program and a bridge config that do not match cannot drive outputs; PLC stop behaves as configured; SDO and NMT from the program keep working.

Non-goals: deleting the plugin (change 2), the PC simulator runtime (change 2), mailboxes for long SDO, raw CAN, J1939 and EMCY (change 3), using the runtime's `%D` points.

## Decisions

### 1. Target marker: `bridge.openplc`

A bridge config with `"openplc": {}` inside `bridge` targets OpenPLC. Fields: `poll_ms` (5-1000, default 10), `remote_device` (file name, default `canworks`), `iec_base` (first `%IW`/`%QW` index, default: the lowest free run from 100 found by the existing project scan). Implied and checked: `listen` `127.0.0.1:1502` unless set, `writers` `["127.0.0.1"]` unless set, `word_order` `low_first` (refused otherwise), `status_location` at input byte 4, `watchdog_ms` default 5 × `poll_ms` (at least 50), `on_client_loss` default `"stop"`. Inputs and outputs are packed with "Pack for Modbus" starting after the header (input byte 12, output byte 6).

Alternative: a new top-level `openplc` object. Rejected: the bridge must refuse or accept the config by itself, and every other bridge rule applies unchanged.

### 2. Everything as registers

Every value goes through input or holding registers (FC 4 and FC 16); bits are taken from or put into words by `canworks_in`/`canworks_out`. Coils and discrete inputs (FC 1, 2, 15) would double the requests per poll for no gain, since one program owns all outputs.

Groups: one read group per input PDO's register range and one write group per output PDO's range, merged with the next range of the same node when contiguous and the result stays within 125 (read) or 123 (write) registers. The bridge's own blocks: one read group for header + status (+ live lists, SDO response), one write group for the output header, one for the control block and SDO request. Header and status groups use `set-to-zero`, data groups `keep-last-value`. All groups use `poll_ms`. The configurator warns above 40 requests per poll (CPU budget, to be confirmed by the hardware test).

### 3. PLC link header and map hash

Output registers 0-2: running (1 while the program scans), map hash high word, map hash low word. Input registers 0-1: the bridge's map hash (high, low), registers 2-5: the status block.

Map hash: CRC-32 (IEEE 802.3) of a canonical text, computed the same way by the bridge (C++) and the PC tools (Python), with a shared test vector set over the shipped examples. The text has one line per located value of the config, sorted by direction then first byte: `<I|Q> <first byte> <byte count> <bit or -> <CANopen or signal type>`, then a line `word_order low_first`. Names are not part of it, so renaming a value does not invalidate the program; moving or retyping one does.

Bridge rules for an `openplc` config:
- A write that covers output register 0 updates the header state: `ok` when running is 1 and the hash matches, `stopped` when running is 0, `mismatch` otherwise. The registers of the header are not part of the output image.
- Writes to other output registers are applied only while the state is `ok`; otherwise they are answered normally and dropped (a Modbus exception would make the runtime log every poll).
- `stopped` enters outputs off at once with the `on_client_loss` action. The zeroed values of the stop round never reach the image, so `"hold"` holds the last real values. The watchdog keeps working for a lost connection.
- `mismatch` enters outputs off (state 4 in the status block, a new value) and logs once "PLC program built for map 0x…, bridge serves 0x…: outputs stay off".
- The runtime writes the header group first (it is first in the file); a single request never mixes header and data.

Alternative: put the hash into the config and let the bridge compare without computing. Rejected: a hand-edited or older config would carry a stale hash and pass.

### 4. `on_client_loss: "preop"`

Outputs stop as with `"stop"` and NMT enter pre-operational goes to all nodes of every CANopen master network (node 0). Leaving outputs off sends NMT start the same way. Available on every bridge config, not only `openplc`.

### 5. Generated program side

The editor project gets:
- global variable list `canworks`: one typed variable per located value, named like today's declarations (`dio_door_open`), plus `canworks_ok : BOOL`, `canworks_link : CW_LINK` (the blocks' mailbox view);
- program `canworks_in`: copies `%IW` words into typed variables (INT/UINT/WORD direct, BOOL by bit, DINT/UDINT/DWORD from two words low first, REAL through `CW_WORDS_TO_REAL`, LINT/LREAL from four words), fills `canworks_link` from the status, live list and SDO response words, sets `canworks_ok` (status counter changed within 3 × `watchdog_ms` and the input hash equals the generated constant);
- program `canworks_out`: the reverse for outputs, the request words of `canworks_link`, then the header (running 1 and the generated hash constant);
- task instances in the order `canworks_in`, `main`, `canworks_out` in the project's one task.

The raw words are declared with their locations inside the two programs only, so the user's code sees names and types, never Modbus words. Update declarations rewrites the list and both programs; the user's own POUs are not touched.

Alternative: `%ID` points for 32-bit values. The runtime would accept them, but the editor's UI never creates them and may rewrite them; left as a later improvement once checked (task 1.3).

### 6. Writing the remote device

Save writes `devices/remote/<remote_device>.json` in the editor's format (protocol `modbus-tcp`, `modbusTcpConfig` with host, port, slave id 1, timeout 1000, `ioGroups` with points and aliases) through `replace_file`. It touches no other editor file; the global list and programs are written by Update declarations or project creation, as declarations are today. Before writing, Save compares the file on disk with what canworks last wrote (hash kept in `canworks/.remote-device.sha256`): a file changed by someone else is replaced only after a confirm that names it. After writing, the message says that an open OpenPLC Editor must reopen the project before Build.

### 7. Function blocks

ST blocks in the `canworks` library, built with the existing `library/build.sh` (STruC++). Pins as today's blocks where they make sense: `CO_SDO_READ` (EXECUTE, NETWORK, NODE, INDEX, SUBINDEX, TIMEOUT → BUSY, DONE, ERROR, ERROR_ID, ABORT_CODE, DATA : UDINT, SIZE) and `CO_SDO_WRITE`, `CO_NMT` (EXECUTE, NETWORK, NODE, COMMAND), `CO_NODE_LIVE` (NETWORK, NODE → LIVE), each with `LINK : CW_LINK` in-out. One SDO request and one control block exist in the bridge, so a block claims the slot in `LINK` (an owner number taken on its first call) and waits while another owns it; ERROR_IDs keep today's meanings, plus 20 "bridge not reachable" (`canworks_ok` false). `CW_WORDS_TO_REAL`/`CW_REAL_TO_WORDS` are small C++ functions (a byte copy, no runtime interface). Library data type `CW_LINK` (spike task 1.4: STruC++ library types usable from a project).

The library from this change on holds only these blocks, the pure ST helpers (`CAN_GET_*`, `CAN_SET_*`, `CAN_J1939_*`, `J1939_*_BITS`, `J1939_DTC_*`, `J1939_NAME_*`) and the two REAL helpers.

### 8. Devices

OpenPLC project: rows for the runtime (pinned version) and the bridge. Main action: **Install OpenPLC Runtime and the bridge X** (no runtime), **Install the bridge X** (runtime, no bridge), **Update A → X** (bridge), **Start this project's bridge**, else Up to date. `install-runtime.sh --with-openplc --bridge` installs the pinned runtime and the bridge, no plugin; a plugin already on the device is left alone and the page says it is no longer used, with Uninstall in its row.

### 9. CI

New job in `integration.yml` (same path filter as the runtime jobs): pinned runtime image, vcan0, bridge built in the job, one simulated CANopen node, a PLC program built by STruC++ as `test/local-runtime` does, uploaded with its `conf/modbus_master.json`. Checks: values both ways, a 32-bit counter never torn within a PDO, PLC stop → outputs off with `"hold"` keeping the last real values, a program with another hash → outputs off. Its time is paid by dropping the plugin jobs in change 2; until then the job runs only on changes to `plugin/src/bridge/`, `tools/deploy/canworks/openplcmodbus.py` or `library/`.

## Risks / Trade-offs

- Latency: one poll each way (about 5 ms mean, 10 ms worst at 10 ms) on top of a scan and a SYNC. Measured in the hardware test.
- Consistency is per request: each PDO arrives whole, two PDOs may come from different moments.
- Python poll thread: CPU and jitter depend on the number of requests; the budget warning and the hardware test bound it.
- Editor format: `devices/remote/*.json` is the editor's saved format. A change there breaks only the generator, which is a PC tool and a CI test, not the runtime.
- Editor open during Save: the editor may write its own copy back. Mitigated by the changed-file check and the message; verified in task 1.2.

## Migration Plan

New OpenPLC configs use the Modbus route. Existing plugin configs switch with one button. The bench Linux device keeps its plugin until change 2; an upload without `conf/canworks.json` disables it, so the bridge can own the CAN interface.

## Open Questions

None from Toni (10 ms poll accepted, CiA 402 dropped in change 2, blocks rebuilt over Modbus).
