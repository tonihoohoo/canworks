# Tasks

## 1. Spike

- [ ] 1.1 On the pinned Lely, check whether a local write of the master's 0x1028 sub-index <node ID> (C++ `Device::Write`, or the C `co_sub_dn_ind_val` path) re-binds the EMCY consumer's receiver to the new COB-ID, whether a value with bit 31 set disables it, and whether bit 29 (29-bit) is accepted. Verify: in-process test with one Lely slave whose 0x1014 is changed by an SDO write; the master's `OnEmcy` fires for an EMCY on the new COB-ID and not on the old one. Note the result here; if no re-bind, use the fallback of design decision 8 (plugin-side receiver feeding `HandleEmcy`).
- [ ] 1.2 Check that the simulated device's EMCY producer follows a write to its 0x1014 (the simulator is a Lely slave), so tests can move a COB-ID without hardware. Note the result here.

## 2. EMCY queue in the plugin

- [ ] 2.1 New `plugin/src/canopen/plc_emcy.h`/`plc_emcy.cpp`: static ring of 64 entries per network (`kMaxNetworks`), each with sequence number, node, code, error register, manufacturer bytes and UTC time in microseconds; session number; `push` (bus thread), `begin` and `read` (scan thread) under one mutex held only for one copy; lost count for a cursor older than the ring. Verify: unit tests for order, node filter, two readers on one ring, overflow and `LOST`, `SKIP_OLD`, session change (`ERROR_ID` 8 once, no `LOST`).
- [ ] 2.2 `network.cpp`: `HandleEmcy` (network.cpp:1418) pushes every EMCY of a configured node to its network's ring after `SetEmcy`, before the log throttle; the ring is emptied at session start (where `emcy_hist` starts). Verify: in-process test, 50 EMCYs in one second all queued while the log shows the summary line.
- [ ] 2.3 `canopen_plc_api.h`, `plc_api.cpp`: `CANOPEN_PLC_API_VERSION` 2, `canopen_plc_api_v2` as a superset of v1 with `emcy_begin`/`emcy_read` and the entry and info structures; `plc_api_table` returns v1 for 1 and v2 for 2. Verify: an SDO block asking for version 1 still works; test/plc_sdo's header comparison covers the new structures.

## 3. Library block

- [ ] 3.1 `library/src/common.inc`: the v2 table (SDO blocks keep asking for version 1); `library/generate.py` and `library/canworks/CO_RECV_EMCY.cpp` with the pins of design decision 4, following `CAN_RECEIVE.cpp`. Verify: the library builds into `canworks.stlib`, and a project that calls `CO_RECV_EMCY` and `CO_SDO_READ` builds for the runtime.
- [ ] 3.2 Linked block tests (as the SDO block tests): fault and reset within one scan both delivered in order; `WHILE rx.NEW DO` drains the queue in one scan; `NODE` filter; enabled in the first scan sees EMCYs sent during the first boot; `SKIP_OLD`; overflow after 70 EMCYs undrained gives `LOST` 6 and `OVERFLOW`; `NETWORK` of a J1939 network gives `ERROR_ID` 6; no plugin gives 4; block against a plugin offering only version 1 gives 4 and the SDO blocks still work.
- [ ] 3.3 Regression: `emcy_code_location` and `error_register_location` behave as before in all existing tests (fault, reset, boot-up, lost node).

## 4. EMCY COB-ID

- [ ] 4.1 `config.h`/`config.cpp`: node field `emcy_cob_id` (`"device"` default, `"eds"`, or a number); load-time checks of design decision 9 for a number (bit 31, bit 29, restricted CAN-ID, clash with the network's identifiers), naming the node and the field; startup SDO to 0x1014 sub-index 0 taken as the configured value. `eds_check.cpp`: a number or `"device"` needs nothing from the EDS; the read is skipped for an EDS without 0x1014. Verify: unit tests per rule and for an unchanged config.
- [ ] 4.2 `dcf_gen.cpp` `add_emcy_consumers` (dcf_gen.cpp:536): a configured COB-ID replaces the node's 0x1028 entry and disables another node ID's predefined entry on the same COB-ID. Verify: master DCF byte-identical for configs without a number or a 0x1014 startup SDO.
- [ ] 4.3 `network.cpp` `HandleBoot` (network.cpp:515): read 0x1014 sub-index 0 after a successful boot, in the node's SDO turn, before `OnBooted`'s SDO variable reads; apply per spike 1.1; checks of decision 9; one warning or info per change of result; abort or timeout keeps the COB-ID in use and does not fail the boot. Verify: in-process test with a simulated device whose 0x1014 is moved by a startup SDO and one moved by a manual write before a reset: its EMCYs are logged, queued and in the history; bit 31 and a clashing value each give one warning and keep the old COB-ID.
- [ ] 4.4 `frame_tx.cpp` and `network_diag.cpp`: the raw-frame guard and frame names use the COB-ID in use; the status answer has `emcy_cob_id` (`value`, `source`, `valid`) per node. Verify: `send_frame` on a moved EMCY COB-ID needs `force` and names it as the node's EMCY.

## 5. Device error history in the tools

- [ ] 5.1 Shared helper (new `tools/deploy/canworks/errorfield.py`): read 0x1003 sub-index 0 and entries 1..count (at most 254) through a client's `sdo_read`, decode code, CiA 301 class (`emcy_class`, diag.py:351) and manufacturer information; "no error history" on abort 0x06020000; partial list on a later abort; `clear` writes UNSIGNED8 0 through `sdo_write` with the caller's `force`. Verify: unit tests with a fake client, including count 0, abort on sub-index 0, abort on entry 3.
- [ ] 5.2 `diag.py`: `errors NODE [--clear] [--force] [--json]` with `--network`; works against a runtime and a local adapter; refusals ("changes not allowed", "force needed") exit non-zero with the reason. Verify: tests against a simulated device with entries in 0x1003, read-only channel, OPERATIONAL node with and without `--force`.
- [ ] 5.3 Configurator: routes `/api/online/error_field` and `/api/online/error_field_clear` in `configurator/server.py` (next to `/api/online/emcy`, server.py:2160); in the online node page (app.js:4073-4093) an "Error history (0x1003)" fieldset under the EMCY history with count, table (sub-index, code, class, manufacturer information), Refresh and Clear; Clear disabled with the reason when changes are not allowed, confirmation naming the node and the number of entries, and a second confirmation offering force when the node is OPERATIONAL. Verify: page tests for read, no history, clear refused, clear forced.
- [ ] 5.4 Configurator node page: `emcy_cob_id` under **Emergency (EMCY)** (app.js near the EMCY code field, ~1899): Device (default, saved as no field), EDS, or a number; the Check gives the plugin's messages. Online view: node row shows the COB-ID in use when it is not 0x80 + node ID. Verify: page tests.

## 6. Contract, docs and release

- [ ] 6.1 JSON Schema (v1 and v2 share the node definition) and `contract.py` with the same rules for `emcy_cob_id`; fixtures in test/fixtures/config/cases.json; parity test.
- [ ] 6.2 docs/plc-sdo.md: a section on `CO_RECV_EMCY` (pins, queue, `LOST`, example with `WHILE rx.NEW DO`, reading 0x1003 with `CO_SDO_READ_BYTES`), the block table and the API version note. docs/config.md "Emergency messages" (~line 631-660): replace "Only the latest EMCY is visible..." and the COB-ID paragraph with the queue, the error history commands and `emcy_cob_id`; add `emcy_cob_id` to "Node options" and "What is rejected". docs/diagnostics.md: `errors` command, `emcy_cob_id` in the status, protocol table unchanged (no new operation). docs/configurator.md: error history panel and the node field.
- [ ] 6.3 README.md: "Status for the program" line (every EMCY through `CO_RECV_EMCY`, device error history) and "From the program" line (the block), in the same PR. Deploy tool minor version bump; library version follows it.
- [ ] 6.4 Regression: all existing tests pass; master DCFs of the example configs unchanged.

## 7. Hardware (runtime device, CAN adapter, one real node with EMCY and 0x1003)

- [ ] 7.1 Program with `CO_RECV_EMCY` on the real node: provoke a fault that the device resets quickly (for example a sensor input open and closed), and check that the program sees the EMCY and its reset in order while `emcy_code_location` shows the latest, and that `LOST` stays 0. Put the template project back afterwards.
- [ ] 7.2 `canworks-diag errors NODE` and the online panel on the real node: entries match the device's own error history; `--clear` refused read-only, refused without `--force` while OPERATIONAL, and clears with it (count 0 after).
- [ ] 7.3 Move the real node's EMCY COB-ID (0x1014: write with bit 31 set, then the new value, as CiA 301 requires), reset the node: after the boot the log names the new COB-ID, its EMCYs are heard; then set bit 31 only and check the one warning. Restore the device's original 0x1014 (and its saved parameters, if it was stored) afterwards.
