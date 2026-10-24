# Proposal: fix-recent-bug-hunt-findings

## Why

A bug hunt of main bc777a2 (2026-10-24) covered everything merged in the two days after the plugin removal: the Modbus-only chain, PLCopen and truST exports, Modbus connections, mailboxes on demand, the Node-RED package, bridge hardening, PC tools self-update, the canworks-only Devices page, the remote CAN adapter from Devices and CODESYS import. It found 3 high, 22 medium and 37 low issues. The register maps of the PC tools and the bridge still agree, every generated program still compiles, PLCopen XML validates and the CODESYS round trip holds.

The real problems:
- **A bridge with several CANopen networks dies on every stop and every upload.** Only the first network sends its stop NMT, an uploaded config is lost, and the next start reports an unclean stop.
- **Node-RED loses its receivers and writes the wrong value.** Every reconnect or full Deploy leaks a bridge receiver slot until all are gone. An SDO write node triggered by an inject writes the inject's timestamp. A cyclic node's frame is never stopped on close.
- **Mailbox detection misses real programs.** Arrays with named or several bounds, namespaced types and blocks inside user function blocks are not counted, so the program fails at run time with ERROR_ID 22 and Problems even offers to turn the mailboxes off.
- **The bridge repeats a stale request after a restart.** The request mailbox's "first words only set the counter" baseline is taken from a zeroed image.
- **Device jobs report success when nothing happened.** A failed script download ends as Done, and an Update turns a switched-off remote link and discovery back on.
- **Misleading texts.** Adding OpenPLC says it turns the mailboxes on (it does not), "Update declarations" names an action that no longer exists, and docs still describe the removed CiA 402 drive fault and runtime installs.

Evidence, repro steps and the full finding table are in design.md.

## What Changes

**Bridge**
- The bridge stops cleanly and applies uploads with any number of CANopen networks, and a network whose interface drops does not take the process down.
- A request mailbox ignores its first request words after a start only once the client has written them.
- Idle (control command 2) ends the program's receivers, cyclic jobs and mailbox operations with the reason "idle", like the other off states, instead of a false "block stopped calling".
- A cancelled SDO or CAN send still queued is dropped; one already running finishes with its result discarded, and the docs say so.
- `mailboxes` with `receive` or `cyclic_jobs` but no request mailbox is refused in both checks.
- Mailbox use counts reads of the network info and cyclic table, so diag does not advise turning off mailboxes that info blocks use.
- A CANopen session restart ends that network's mailbox operations, receivers and jobs.
- The bridge answers Modbus Read Device Identification (function 43/14) with its version and map hash, for every config.

**Node-RED package**
- Receivers close the slots of the previous connection after a reconnect and on Deploy; "no free receiver" is retried after the cleanup.
- An SDO write uses the form's value when the form has one; `msg.payload` sets it only when the form leaves it empty.
- Closing or re-setting a cyclic node stops its old job on the bridge; a reconnect takes the old slot over.
- An output value set while the connection is silently dead is written again after the reconnect.
- Jobs end at once with "writes refused" while the bridge refuses Node-RED's writes.
- Receive fetches go ahead of other mailbox jobs.
- The bridge node reads the bridge's map hash at connect and refuses writes on a mismatch ("export the flow again").
- Smaller fixes: ERROR_ID 10 with no J1939 network, J1939 source 0-253, default port 502, receiver help, finite REAL outputs, SDO timeout from the layout.

**PLC programs and exports**
- Mailbox detection counts arrays with any bounds and dimensions, namespaced block types, blocks in user function blocks (times their instances) and blocks in non-ST POU files; when a count cannot be worked out it assumes the most and never offers "Turn off".
- The "Turn off the mailboxes" warning counts the connections' canworks blocks choices too.
- "Trim the mailboxes for truST" is offered only when the trimmed map fits; otherwise Problems offers canworks blocks None.
- Bit channels of a PDO entry get their own BOOL in the generated declarations and `canworks_in`/`canworks_out` on the bridge.
- The generic PLCopen dialect declares `canworks` as VAR_EXTERNAL and uses the TC6 2.01 namespace.
- The CODESYS build names the CAN bus object after the network, and the import takes the network name from it.
- Exports and checks no longer end with "nothing was uploaded".

**Configurator and Devices**
- Simulated networks do not lock the remote CAN adapter's bit rate.
- Any second connection that writes next to a PLC link gets a warning; the Add dialog leaves Writes off then.
- A connection's Download is refused while the check has an error on that connection; READMEs never tell a remote client to use 127.0.0.1.
- Devices names a running instance before starting another and offers to stop it; a clash of Modbus port, diagnostics port or CAN interface is a warning.
- A finished job's text names the instance it ran for.
- Device jobs fail when their script download fails, on the page and in `install-bridge.sh --ssh`/`.ps1`.
- Update and reinstall keep the device's current remote link and discovery settings and the link's instance.
- The LAN advertisement carries the config's diagnostics port.
- Removing a device clears its running job; the plan compares every uploaded file, not only canworks.json; the probe reports the last job's exit code.
- Self-update: Check now keeps the menu open and shows its result, is disabled when updates are turned off, and the re-check before updating waits for a running check.
- Smaller UI fixes: New editor project disabled without openplc-cli, connection address required, CODESYS import clash reason, Devices layout below 1000 px, project name kept in the header chip, a restarted configurator's old tab says so and stops polling, wording.

**Docs and specs**
- The texts above, the release notes, README, deploy tool README, install-pc, diagnostics, simulator, configurator, local-runtime, j1939 and SECURITY pages, schema descriptions and CLI help drop removed features.
- Spec scenarios that use removed options (`--runtime`, `--host`) or name "Update declarations" are corrected.
- The doc reference test checks options and anchors in every doc page and example README.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `modbus-bridge`: clean stop and upload with several networks; device identification with the map hash.
- `modbus-bridge-mailboxes`: request baseline after a client write, idle ends program resources, cancel semantics, receive needs a request mailbox, info reads count as use, session restart ends a network's resources.
- `nodered-blocks`: receiver cleanup, SDO value from the form, cyclic stop on close, outputs after a silent outage, writes refused, fetch priority, map hash check, small fixes.
- `modbus-connections`: mailbox warning counts connections, any second writer warned, Download refused on errors, address required, OpenPLC add text.
- `plcopen-export`: truST trim offered only when it fits; generic dialect VAR_EXTERNAL and TC6 2.01.
- `canopen-pdo-io`: bit channels reach the generated programs on the bridge.
- `canopen-configurator`: mailbox detection rules; Function blocks text without "Update declarations"; New editor project without openplc-cli; restarted configurator; header chip.
- `canopen-editor-project`: Save rewrites the link array programs (no "Update declarations").
- `bridge-plc-blocks`: scenario wording without "Update declarations".
- `codesys-export`, `codesys-import`: network name kept through build and import; clash reason in the import.
- `canopen-deploy`: no "nothing was uploaded" for commands that never upload.
- `device-install`: failed downloads fail the job, link and discovery kept on update, running instance named, job text per instance, phantom jobs, plan over every uploaded file, probe exit, simulated networks and the adapter row, layout and wording.
- `runtime-discovery`: the advertisement carries the configured diagnostics port.
- `pc-tools-self-update`: Check now result, disabled when off, re-check waits.
- `canopen-config-contract`, `canopen-local-runtime`, `toolkit-names`: scenarios without removed options.
- `canopen-ci`: multi-network stop and upload test; doc reference checks over every page.

## Impact

- canworks-bridge: `plugin/src/bridge` (bridge_main, bridge_host, mailboxes, mailbox_engine, modbus_server), `plugin/src/can/config.cpp`, `test/canopen_host`.
- PC tools: `mailboxuse.py`, `connections.py`, `bridgecheck.py`, `plcopen.py`, `plcopen_targets.py`, `configurator/declare.py`, `openplcmodbus.py`, `codesys/`, `cli.py`, `devices/` (jobs, service, plan, device-probe.sh), `configurator/server.py`, `configurator/update.py`, static UI files, `nodered_package/`, `nodered.py`.
- Scripts: `install-bridge.sh`, `install-bridge.ps1`, `install-link.sh`.
- Docs: README, docs/*.md, tools/deploy/README.md, release-notes.md, SECURITY.md, schema descriptions, examples READMEs.
- Map: no register moves; the map hash is unchanged. Generated OpenPLC programs gain BOOLs for bit channels, so existing editor projects need Save. The generic PLCopen namespace changes.
- Tests: new parity corpus entries, a multi-network SIGTERM/upload test, Node-RED package tests, page tests for the UI fixes, extended doc reference test.
- Hardware: a bench check on the device with a real and a simulated network (stop, upload, interface down), and a Safari check on the Mac.
