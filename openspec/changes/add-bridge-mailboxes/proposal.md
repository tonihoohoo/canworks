## Why

Changes 1 and 2 of the Modbus-only plan (research/modbus-only-2026-10-22.md) move OpenPLC onto the Modbus TCP bridge and delete the OpenPLC plugin with its C++ function blocks. Change 1 (`add-openplc-modbus-target`) brings back short SDO reads and writes (up to 4 bytes) and NMT as ST blocks over the bridge's existing registers. Everything else the program could do on the bus is gone after change 2: long SDO (strings, byte arrays, 8-byte reals), raw CAN frames, J1939 messages, trouble codes, ECU lookup and EMCY. Toni wants those blocks back over Modbus (2026-10-22), working with any Modbus PLC, not only OpenPLC.

The bridge's register blocks today carry one fixed-size request at a time and no queue, so anything longer than 4 bytes, anything that arrives between two polls and anything that must run faster than the poll needs new bridge support.

This is change 3 of 3. It builds on change 1's design (PLC link header, map hash, `canworks_in`/`canworks_out`, the `canworks.link` word array, the slot sharing of its blocks) and on change 2 (plugin and CiA 402 removed). No CiA 402.

## What Changes

- **Request mailboxes in the bridge.** A bridge config may have `bridge.mailboxes` with 1 to 4 request mailboxes. Each is a 72-register request block (holding registers) and a 72-register response block (input registers) with the counter handshake of the SDO bridge registers, carrying up to 128 data bytes per round trip. Longer data goes in chunks through a per-mailbox staging buffer (writes) and result buffer (reads), up to 1785 bytes. Operations: long SDO upload and download, CAN frame send, cyclic frame start, update and stop, receiver open and close, J1939 send and request, DM1/DM2 read, DM3/DM11 clear, ECU lookup by NAME, and fetching a long received message.
- **Receive mailbox with queues.** One shared receive block (120 input registers) shows a batch of received records (CAN frames, J1939 messages, EMCYs) from per-receiver FIFOs in the bridge, so nothing is lost between polls. The program acknowledges a batch through three holding registers; the bridge then shows the next one. Up to 32 receivers in total. A receiver whose records are not taken within 1 s is closed, so a block that is no longer called cannot stall the others.
- **Network info and cyclic job blocks.** Per network, an 18-register input block with bus state, error counters, bus load, frame counters and (J1939) the claimed address, NAME and ECU count. A table of up to 16 cyclic jobs with their frame counts and states. Cyclic frames are sent by the bridge's own timer, whatever the poll or scan time.
- **Program-owned resources end with the program.** When the PLC link header goes to stopped or mismatch, or the output watchdog fires, the bridge cancels pending jobs, stops cyclic jobs and closes receivers, as a PLC stop did for the plugin's blocks.
- **ST blocks over the mailboxes** in the `canworks` library, pins and ERROR_IDs kept close to the plugin's blocks with the in-out `LINK`: `CO_SDO_READ_BYTES`, `CO_SDO_WRITE_BYTES`, `CO_SDO_READ_STRING`, `CO_SDO_WRITE_STRING`, `CO_SDO_READ_REAL`, `CO_SDO_WRITE_REAL`, `CO_RECV_EMCY`, `CAN_SEND`, `CAN_SEND_CYCLIC`, `CAN_RECEIVE`, `CAN_BUS_INFO`, `J1939_SEND`, `J1939_RECEIVE`, `J1939_REQUEST`, `J1939_DM_READ`, `J1939_DM_CLEAR`, `J1939_ECU_INFO`, `J1939_FIND_ECU`. Instances share the mailboxes and are served in the order they started. Plain ST only, no runtime interface.
- **`canworks.link` grows** from `ARRAY[0..88] OF WORD` to `ARRAY[0..1023] OF WORD`; words 0-88 keep change 1's meaning, so change 1's blocks only get the new array bound.
- **Any Modbus PLC.** `canworks-deploy library --format st` writes the bridge blocks and helpers as plain ST sources for CODESYS and other IEC 61131-3 tools, with pure ST versions of the REAL word helpers. The ST map export (`--export-modbus-map OUT.st`) also writes the `canworks_in`/`canworks_out` code for that PLC. PLCopen XML export and import is the next change, `add-plcopen-export`, not this one.
- **Configurator.** The Project page of a bridge or OpenPLC config gets a **Function blocks** section (request mailboxes, receivers, cyclic jobs, network info) with the register and request cost shown. New OpenPLC configs have it on with one request mailbox.
- **Tests and docs.** STruC++ block tests against a scripted mailbox model, bridge C++ tests, a few block checks added to change 1's OpenPLC Modbus integration job; `docs/plc-library.md`, `docs/modbus-bridge.md`, `docs/raw-can.md`, `docs/j1939.md`, `docs/plc-sdo.md` and README.

## Capabilities

### New Capabilities

- `modbus-bridge-mailboxes`: the bridge's request mailboxes, receive mailbox, network info and cyclic job blocks, their queues and limits.
- `bridge-plc-blocks`: the ST function blocks over the mailboxes, their pins, handshake, sharing and ERROR_IDs.

### Modified Capabilities

- `modbus-bridge-map`: mailbox blocks in the map, Pack for Modbus, the OpenPLC remote device groups, the map hash, `canworks.link` copy code in the ST export.
- `canopen-config-contract`: `bridge.mailboxes` in the schema.
- `canopen-configurator`: Function blocks section on the Project page.
- `canopen-editor-project`: the larger `canworks.link` and its copy code.
- `plc-library`: library contents and the portable ST source output.
- `canopen-ci`: block and mailbox tests.

## Impact

- Bridge: new `plugin/src/bridge/mailboxes.{h,cpp}` (request and receive mailboxes, info and cyclic tables), `bridge_host.cpp` (link-state hooks), `config.cpp` (`mailboxes`). Backends are the engine services the plugin's blocks used (SDO queue in `canopen/plc_api.cpp`, EMCY history in `canopen/plc_emcy.cpp`, raw jobs and receivers in `can/raw/plc_frames.cpp`, J1939 jobs in `j1939/j1939_plc_msgs.cpp`, DM store in `j1939/dm.cpp`). Change 2 deletes the C ABI tables over them; this change needs the services themselves (see design, Decision 9).
- PC tools: `modbusmap.py` (mailbox items, pack, hash), `openplcmodbus.py` (groups, link copy code), `bridgecheck.py`, configurator Project page, `library` command (`--format`).
- Library: `library/modbus/` new ST blocks; change 1's blocks get the new `LINK` bound; `library/generate.py`, `build.sh`, ST source output.
- Tests: `test/plc_modbus/` (mailbox model, block tests), `test/bridge/`, change 1's integration job.
- Not in scope: CiA 402; CAN FD; ISO-TP; blocks that run inside the PLC scan.
