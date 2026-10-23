## Why

The hardware run of change 1 (`add-openplc-modbus-target`, PR #240) passed, but it turned up six things to fix in the OpenPLC through Modbus route:

1. **Replayed command after a bridge restart.** The bridge starts with control and SDO counters 0, so the first write after a restart runs the PLC's last request again: it re-sent NMT start, and a last stop, reset or SDO write would repeat too. Any client that rewrites its whole output image every poll is affected; OpenPLC's Modbus master does.
2. **Old located variables in `main`.** A plugin project switched to OpenPLC through Modbus keeps `main`'s located variables (`rtd_ok : BOOL AT %IX10.0;` …), which read nothing now. The program builds and runs on stale zeros without a warning. Save leaves the user's POUs alone by design, so this needs its own explicit step.
3. **Library not enabled on Save.** Save writes `canworks_in`/`canworks_out`, which call `CW_*` functions, but neither enables the `canworks` library in the project nor installs it into the editor, though the spec asks for it. The bench project needed it by hand.
4. **No live list after a switch.** The switch adds live lists only for named networks. A config whose network has no name gets none, so `CO_NODE_LIVE` ends with ERROR_ID 22.
5. **Pre-operational on client loss is sent per node.** The spec's scenario says node 0, but the bridge sends one command per configured node. Per node is the safer behaviour on a bus with devices canworks does not manage, so the spec should say so.
6. **Logs.** Pre-operational log lines name "the Modbus control block" and "a diagnostics client" instead of the client loss. Every bridged SDO request is logged at INFO, which floods the journal when a program reads every scan.

## What Changes

- **Restart baseline (OpenPLC configs).** After a bridge start, the first control block and the first SDO request it receives are taken as the baseline and not run. Their counters are echoed with a new result: control result 6 "not run: the bridge restarted"; SDO status 3 with abort code 0x08000021. `CO_NMT`, `CO_SDO_READ` and `CO_SDO_WRITE` report it as ERROR_ID 8 (cancelled), as `add-bridge-mailboxes` does for its mailboxes, so programs check one code for "start again". Counter changes after that run as before.
- **Use canworks.\* in main.** For an OpenPLC project the configurator finds the located declarations in `main.st` whose names are members of the `canworks` list. The Project page shows a warning with the button **Use canworks.\* in main**, Problems lists it, and the switch banner mentions it.
  - The button keeps the old file as `canworks/main-before-move.st` and removes those declarations and the generated comment.
  - It drops a `VAR` block left empty and replaces uses with `canworks.<name>`, outside comments and strings and not after a `.`.
  - Your own hardware I/O, other POUs and CiA 402 lines are left as they are.
- **Save enables the library.** Saving an OpenPLC project enables `canworks` in the editor project and installs it into the editor when it is missing or older, as New editor project already does.
- **Live lists for unnamed networks.** The switch to OpenPLC through Modbus names every unnamed CANopen master network (after its CAN interface, else `net<k>`), so each gets a live list.
- **Pre-operational per configured node.** The spec now says NMT pre-operational and start go to each configured node of every CANopen master network, as the bridge already does.
- **Log wording and level.** Pre-operational and start on client loss are logged as "client loss (on_client_loss preop)". Bridged SDO requests are logged at DEBUG; aborts and timeouts stay at INFO.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `modbus-bridge`: restart baseline for the control block and the SDO registers; pre-operational per configured node.
- `plc-library`: ERROR_ID 8 (cancelled) also when the bridge restarted, the code `add-bridge-mailboxes` uses for a replayed mailbox request.
- `canopen-configurator`: **Use canworks.\* in main**; the switch names unnamed networks; Save enables and installs the library.
- `canopen-editor-project`: the explicit move action is the one exception to "the user's POUs SHALL NOT change".

## Impact

- **Bridge:** `plugin/src/bridge/bridge_blocks.*` (baseline), `bridge_host.cpp` (log level), `canopen/network.cpp` (hold source wording); tests in `test/bridge/`.
- **Library:** `library/modbus/` (ERROR_ID 8); `test/plc_modbus/` model.
- **PC tools:** `openplcmodbus.py` (main scan and move; library on save), `configurator/server.py` (route `POST /api/openplc/move-main`, switch naming), `static/target.js`, checks.
- **Tests:** unit tests, plus extending the existing `test_configurator_openplc_modbus_page.py` and `test/openplc_modbus/run.py` (restart case). No new job or page test file, so CI time stays flat.
- **Docs:** `docs/modbus-bridge.md`, `docs/plc-library.md`, `docs/configurator.md`.
- **Order:** apply after `remove-openplc-plugin` and `add-bridge-mailboxes`, rebased on them. `add-bridge-mailboxes` already ends a replayed mailbox request with ERROR_ID 8, so this change covers only the control block and the SDO registers.
