## Context

EMCY reception today: Lely calls `Network::OnEmcy` (plugin/src/canopen/network.cpp:1397) with the master lock held; it defers to `HandleEmcy` (network.cpp:1418), which drops messages from unconfigured node IDs after one warning, calls `SetEmcy` (network.cpp:1404) to update the latest-EMCY inputs and the gateway, appends to the per-node 16-entry ring `NodeState::emcy_hist` (plugin/src/canopen/network.h:240-251, `kEmcyHistory` at network.h:173) and logs with the 5-per-second throttle. The diagnostics `emcy` operation returns that ring (`Network::DiagEmcy`, plugin/src/canopen/network_diag.cpp:257); the configurator shows it in the online node page (tools/deploy/canworks/configurator/static/app.js:4073-4093, route `/api/online/emcy` in configurator/server.py:2160).

Which COB-IDs the master hears is fixed when the master DCF is generated: dcfgen writes a 0x1028 consumer entry for configured slaves whose EDS has 0x1014, and `add_emcy_consumers` (plugin/src/canopen/dcf_gen.cpp:536) adds 0x80 + node ID for every other node ID. Nothing reads the node's 0x1014 at runtime, and the raw-frame guard names 0x80 + node ID as the node's EMCY (plugin/src/can/frame_tx.cpp:57).

The program's library talks to the plugin through one C entry point, `canopen_plc_api(version)` (plugin/src/canopen/canopen_plc_api.h), implemented by `plc_api_table` (plugin/src/canopen/plc_api.cpp:203) over a static slot table (`PlcRequests`, plugin/src/canopen/plc_api.h). The library's copy of the table is in library/src/common.inc, which checks `size >= sizeof(api_v1)` (common.inc:69). The CAN frame blocks use a separate entry point with per-instance receivers (library/canworks/CAN_RECEIVE.cpp, docs/raw-can.md); `CO_RECV_EMCY` follows that block's ENABLE/NEW/QUEUED/OVERFLOW pattern.

Manual SDO reads and writes already exist in the diagnostics channel with the guards this change needs: writes need `allow_changes`, and `force` when the node is OPERATIONAL (network_diag.cpp:70-117); the local bus backend offers the same `sdo_read`/`sdo_write` (tools/deploy/canworks/localbus/client.py:173-176).

## Goals / Non-Goals

**Goals:**
- Every EMCY of a configured node reaches the program, in order, including a fault and its reset within one scan, with a count of what a slow reader missed.
- The device's own error history (0x1003) can be read and, with the usual permissions, cleared from the command line and the online view.
- A device whose EMCY COB-ID differs from the EDS default is heard, and a COB-ID the master cannot use is reported instead of silently missed.
- Keep `emcy_code_location` / `error_register_location`, the log and the diagnostics history exactly as they are.

**Non-Goals:**
- Reading 0x1003 from the program through a dedicated block (the program can use `CO_SDO_READ` on 0x1003 today; the docs show how).
- Writing a node's 0x1014 from the plugin (moving the COB-ID is the user's choice, through a startup SDO).
- EMCYs from node IDs that are not in the configuration in the queue (they stay ignored after one warning, as today).
- A full CiA 405 function block set (`RECV_EMCY` and `RECV_EMCY_DEV` with their exact pins); the block takes their idea, not their interface.
- The configurator's trace decoding of a COB-ID that only the device knows (see open questions).

## Decisions

1. **One queue per network with a cursor per reader, not one queue per block.** The plugin keeps, per network, a ring of the last 64 EMCYs of configured nodes with a sequence number each, filled in `HandleEmcy` right after `SetEmcy` and before the log throttle, so throttled messages are queued too. A block instance holds its own cursor (the next sequence number it wants) in its instance data. Reading copies the oldest entry at or after the cursor that matches the block's `NODE` filter and moves the cursor past it. Consequences: any number of block instances, no plugin-side registration or limit, no instance takes another's messages, and the scan path copies one entry under a mutex held only for that copy (as `PlcRequests`). A reader whose cursor is older than the ring's oldest entry has lost the difference: the read adds it to the reader's `LOST` and sets `OVERFLOW`. With a node filter the lost count includes other nodes' messages; it cannot know which were for its node, and the docs say so. Alternative considered: per-instance receivers like `CAN_RECEIVE` (rx_open with a depth). Rejected because a receiver only sees messages from its opening on, so EMCYs sent during the first boot, before the program's first scan enables the block, would be lost, and because it needs a plugin-side receiver limit.

2. **Where a new reader starts.** On the rising edge of `ENABLE` the cursor goes to the oldest entry still in the ring, so a program that enables the block in its first scan also gets the EMCYs sent while the nodes booted. `SKIP_OLD := TRUE` starts at the next new message instead. The ring is emptied when a CANopen session starts (the same moment the diagnostics history starts); the cursor carries the session number, and a cursor of an earlier session ends that call with `ERROR_ID` 8 once and restarts at the oldest entry of the new session, without counting `LOST`.

3. **Depth 64, fixed.** At the throttle's 5 logged messages per second a flooding node fills it in about a second while any program that calls the block every scan drains it in milliseconds. 64 entries of 24 bytes per network, 8 networks at most (`kMaxNetworks`, plugin/src/can/config.h:438), are allocated once at plugin load, nothing at run time.

4. **Block interface.** `CO_RECV_EMCY` inputs `ENABLE : BOOL`, `NETWORK : USINT`, `NODE : USINT` (0 all nodes, 1..127 one node: the `RECV_EMCY_DEV` case), `SKIP_OLD : BOOL`; in-out `MSEF : ARRAY[0..4] OF BYTE` (as `CAN_RECEIVE` passes `RX_DATA`); outputs `ACTIVE`, `NEW : BOOL`, `EMCY_NODE : USINT`, `ERROR_CODE : WORD`, `ERROR_REGISTER : BYTE`, `TIMESTAMP : ULINT` (UTC microseconds, the clock `CAN_RECEIVE` uses), `QUEUED : UINT` (matching entries still waiting for this instance), `OVERFLOW : BOOL` (until `ENABLE` falls), `LOST : UDINT`, `ERROR : BOOL`, `ERROR_ID : UINT`. Each call takes at most one message; `WHILE rx.NEW DO` drains the queue in one scan, as with `CAN_RECEIVE`. Error IDs reuse the SDO blocks' numbers: 4 CANopen not running (retried on every call while `ENABLE` stays TRUE), 6 invalid input (`NODE` above 127, or a `NETWORK` that is not a CANopen master network), 8 the session restarted. An error reset (code 0) is a message like any other.

5. **API version 2 as a superset, asked for only by the new block.** `canopen_plc_api_v2` starts with the version 1 fields (so its `size` is larger) and adds `emcy_begin(network, node, skip_old, cursor*, error_id*)` and `emcy_read(network, node, cursor*, entry*, info*)`. `plc_api_table` returns the v1 table for 1 and the v2 table for 2. The SDO blocks keep `api_version = 1` in common.inc, so a project built with the new library still runs its SDO blocks on an older plugin; `CO_RECV_EMCY` on an older plugin ends with `ERROR_ID` 4, and the plugin's existing "needs a newer plugin" log line names the versions. test/plc_sdo's header comparison covers the new structures.

6. **0x1003 is read by the clients, through the existing SDO operations.** A shared Python helper reads sub-index 0 (UNSIGNED8 count), then sub-indices 1..count (UNSIGNED32 each; at most 254), and decodes each entry as CiA 301 does: error code in the low 16 bits with its class from the existing `emcy_class` (tools/deploy/canworks/diag.py:351), manufacturer-specific information in the high 16 bits. Sub-index 1 is the newest. An abort 0x06020000 on sub-index 0 means the device has no error history and is shown as such; an abort on an entry ends the list there and says so. The clear writes UNSIGNED8 0 to sub-index 0 with the manual write operation, so the plugin's existing guards apply unchanged: "changes not allowed" without `allow_changes`, "force needed" while the node is OPERATIONAL, and the write is logged with the peer address. No new plugin operation is needed, it works with older plugins and on a local adapter, and the configurator and CLI cannot disagree. Alternative: a plugin-side `error_field` operation returning a snapshot. Rejected: it gives no better consistency (the device can add an entry between two reads either way) and needs new guard code.

7. **EMCY COB-ID: read after each boot by default.** `emcy_cob_id` on a node: left out or `"device"`, the master reads 0x1014 sub-index 0 once after each successful boot, in `HandleBoot` (network.cpp:515) before `OnBooted` starts the SDO variables' boot reads, through the node's normal SDO turn (so it never overlaps another transfer to the node); only for nodes whose EDS has 0x1014 and that the master boots. A number (an 11-bit COB-ID, checked as in decision 9) fixes the COB-ID: `add_emcy_consumers` writes it into the master DCF's 0x1028 entry and no read is made. `"eds"` is today's behaviour. When the node has a startup SDO to 0x1014 sub-index 0 and no number, that value is used in the DCF as if given as a number, and the read after boot checks it. A read that is aborted or times out keeps the current COB-ID, logs one info line per boot result change, and does not fail the boot. Reading by default (instead of opt-in) is chosen because the failure it fixes is invisible: nobody who has not found it would set an option; the cost is one expedited SDO per boot, and when the device uses the default nothing else changes and nothing is logged.

8. **Applying a read COB-ID.** The master writes the new value to its own 0x1028 sub-index <node ID> through Lely's local dictionary write, so Lely's EMCY consumer re-binds its receiver (spike 1.1 confirms that the pinned Lely re-binds on a local write, or names the call that does). The entry another node ID had on that COB-ID (an unconfigured node's predefined 0x80 + ID, see `add_emcy_consumers`) is disabled (bit 31) for as long as the moved COB-ID is in use. A master NMT reset reloads 0x1028 from the DCF; the next boot reads 0x1014 again.

9. **Values the master does not take**, each with one warning naming the node, the value and the reason, keeping the COB-ID already in use: bit 31 set (the device's EMCY is not valid: the device sends none; the status reports `valid: false`); bit 29 set (29-bit identifier, not supported by this change); a restricted CAN-ID (CiA 301: 0x000, 0x001-0x07F, 0x101-0x180, 0x581-0x5FF, 0x601-0x67F, 0x6E0-0x6FF, 0x701-0x7FF); a COB-ID another identifier of the network uses (another configured node's EMCY, a configured PDO, SDO or heartbeat COB-ID, NMT, SYNC, TIME, LSS: the same map the raw-frame guard uses, plugin/src/can/frame_tx.cpp). The same rules reject a configured number at load, naming the node and `emcy_cob_id`.

10. **Status and guard follow the COB-ID in use.** Each node in the status answer gets `emcy_cob_id: {value, source: "default"|"eds"|"config"|"device", valid}`; the CLI prints it only when it is not 0x80 + node ID. The raw-frame guard and frame naming in frame_tx.cpp use the COB-ID in use, so a moved EMCY is still guarded as the node's EMCY.

## Risks / Trade-offs

- [The extra 0x1014 read lengthens every boot by one SDO round trip] → Expedited, about 1 ms at 500 kbit/s; it runs after the boot is reported, so boot time and the boot error byte are unchanged; `"eds"` turns it off.
- [A device that answers 0x1014 with a wrong value would make the master stop hearing its real EMCYs] → Only values that pass the checks of decision 9 are taken, the change is logged, and status shows the source; `"eds"` or a number overrides.
- [Lely may not re-bind the EMCY receiver on a local 0x1028 write] → Spike first (task 1.1); fallback is a plugin-side CAN receiver on the moved COB-ID that feeds `HandleEmcy` directly.
- [A program that never drains the queue] → Nothing grows; old entries are overwritten and only that reader's `LOST` counts them; nothing is logged from the scan path.
- [Clearing 0x1003 loses the device's history] → Needs `allow_changes`, `force` on a running node, and a confirmation in the configurator; the panel shows the entries before the Clear button.

## Migration Plan

None for the config: one new optional field within `schema_version` 1 and 2. The one behaviour change for existing configs is the 0x1014 read after a boot, which changes nothing when the device uses the COB-ID the master already listens on. Rollback: `"emcy_cob_id": "eds"` per node, or an older plugin. A library built with this change runs its SDO blocks on older plugins; `CO_RECV_EMCY` needs this plugin.

## Open Questions

- Should the 0x1014 read be opt-in instead (default `"eds"`), to keep the boot sequence of existing configs byte-identical on the bus? The proposal reads by default (decision 7).
- Should nodes with `boot: false` also get the read, the first time they are heard? Left out: the master does not talk to them during boot.
- Should EMCYs of unconfigured node IDs go into the queue (CiA 405 `RECV_EMCY` sees every node)? Left out for consistency with the history and the log.
- Queue depth: fixed 64, or a `master.emcy_queue_depth` field? Fixed until someone needs more.
- 29-bit EMCY COB-IDs: does the pinned Lely support them in 0x1028? Rejected with a warning until checked.
- The configurator's trace decodes EMCY by 0x80 + node ID or a configured number; should it ask the runtime for COB-IDs read from devices?
- Should `canworks-diag errors` also be offered on slave networks for the plugin's own 0x1003 (the slave's EMCY producer)? Not in this change.

## Resolved in the implementation

The open questions above were settled with the proposal's defaults:

- The 0x1014 read is on by default (`"device"`); `"eds"` turns it off.
- No read for `boot: false` nodes; EMCYs of unconfigured node IDs are not queued; the queue depth is fixed at 64; 29-bit EMCY COB-IDs are rejected; the configurator's trace keeps decoding by 0x80 + node ID or a configured number; `canworks-diag errors` is not offered on slave networks.

Details the design left open:

- `emcy_begin` returns `-ERROR_ID` instead of taking an `error_id` pointer, like `emcy_read`; an entry is 24 bytes (time, sequence number, code, node, error register, manufacturer bytes).
- A startup SDO to 0x1014 sub-index 0 with bit 31 set (the first half of moving a COB-ID) is not taken as a COB-ID; the last one without bit 31 counts. Its value goes through the same load-time checks as a number, with "from the startup SDO to 0x1014" in the message.
- dcfgen's binary master DCF (`master.bin`) is loaded after the text DCF and sets the EDS default of 0x1028 again, so the master also writes a configured COB-ID into its own 0x1028 when it starts and after its own NMT reset (decision 8's local write); the text DCF is edited too.
- A device that reports its EMCY switched off (bit 31) keeps the master on the COB-ID it already uses; one that is back on the master's COB-ID, or on its default, is followed back.
- The status `source` is `default` when the COB-ID in use is 0x80 + node ID and nothing configured it, `eds` for another EDS default, `config` for a number or startup SDO, `device` after a read was taken.
- The runtime log for an older library or plugin now says "asks for CANopen block API version N" (it named only SDO blocks before).
