# Design: fix-recent-bug-hunt-findings

## Context

The bug hunt of main bc777a2 (2026-10-24) ran in six areas: bridge, exports, Node-RED, configurator UI, installers and docs. Most findings were reproduced by running them: the bridge with `CANWORKS_FORCE_SIMULATE=1` and a raw Modbus client, the Node-RED package in Node-RED 4.0.9 against the real bridge, the configurator in Chromium against the examples, and the Devices page against the tests' fake SSH device. No hardware was used, and WebKit was not available, so the Safari fixes of #282 were not rechecked.

Checked and found sound: the PC and bridge register maps and map hashes, mailbox and record layouts, register range edges, the writers allowlist, PLC link states, the parity corpus and 23 edge configs; STruC++ builds of every block and generated program; PLCopen XML against the TC6 2.01 schema; the CODESYS export and import round trip; the Node-RED Modbus client, `.tgz` and flow JSON; version comparison, updater rollback, SSH quoting and shellcheck; a sweep of every view of every example at 800 and 1280 px.

## Findings

Severity H = wrong data on the bus or PLC, a crash or lost safety behaviour; M = a real bug with a workaround or a misleading UX; L = cosmetic or stale text. C = reproduced, S = read from the code.

| ID | Sev | | Finding | Where |
| --- | --- | --- | --- | --- |
| BRIDGE-1 | H | C | A bridge with several CANopen networks dies with SIGUSR1 on SIGTERM (8/8) and on every upload: the first network's poll restores the default SIGUSR1 action while the others still signal each other. Only one network sends its stop NMT, the upload is lost, the next start says unclean. Suspected also when one network's interface drops. | bridge_main.cpp:80-87 |
| BRIDGE-2 | M | C | The request mailbox baseline is taken from the zeroed image of the first live round, so a client's stale request runs after a restart. | bridge_host.cpp:680, mailboxes.cpp:185-193 |
| BRIDGE-3 | M | C | Mailbox scan misses `ARRAY[0..N]`, 2-D arrays, `canworks.CAN_RECEIVE`, and counts blocks in user FBs once. | mailboxuse.py:51-53 |
| BRIDGE-4 | M | C | Idle stops cyclic jobs as "block stopped calling" while keepalives arrive; receivers not drained (385 dropped), requests unanswered. | bridge_host.cpp:680, mailboxes.cpp:152-158 |
| BRIDGE-5 | L | C | diag advises turning mailboxes off for a program that only reads network info. | mailboxes.cpp, diag.py:1367 |
| BRIDGE-6 | L | S | Cancelled SDO and CAN send operations still go out. | mailbox_engine.cpp:48-89 |
| BRIDGE-7 | L | C | `requests: 0` with `receive: true` accepted, unusable. | config.cpp:3329, bridgecheck.py |
| BRIDGE-8 | L | C | Stray `tools/deploy/OUT.csv` committed. | tools/deploy/OUT.csv |
| BRIDGE-9 | L | C | `Mailboxes::end_network` never called. | mailboxes.cpp:676 |
| NODERED-1 | H | C | Receivers leak a bridge slot per reconnect and per full Deploy; quiet receivers never cleaned; ERROR_ID 5 for good after the 32 slots. | lib/bridge.js:882, :633-651 |
| NODERED-2 | H | C | SDO write triggered by an inject writes the timestamp, not the form value. | nodes/canworks.js:233 |
| NODERED-3 | M | C | Closing a cyclic node never sends the stop; double frames for ~1 s, ERROR_ID 5 with `cyclic_jobs: 1`. | lib/bridge.js:983-993 |
| NODERED-4 | M | C | A value set during an undetected outage is overwritten by the reconnect's read-back. | lib/bridge.js:386, :218-235 |
| NODERED-5 | M | C | Jobs wait out their timeout with "no answer" while writes are refused. | lib/bridge.js:408 |
| NODERED-6 | M | S | Long J1939 fetch queues behind other jobs past the 1 s stall; every receiver in the batch closes. | lib/bridge.js:662 |
| NODERED-7 | M | S | The flow's map hash is never checked against the bridge. | lib/bridge.js |
| NODERED-8 | L | C | No J1939 network gives ERROR_ID 2 "name the network". | lib/bridge.js:395 |
| NODERED-9 | L | S | J1939 receive source accepts 254. | nodes/canworks.js:381 |
| NODERED-10 | L | C | Default port 1502 in the editor, emcy help lists SDO errors, NaN on REAL, unused `sdoTimeoutMs`. | canworks.html, codec.js, nodered.py |
| EXPORTS-1 | M | C | "Turn off the mailboxes" ignores the connections' blocks; its fix brings back the connection's error. | server.py:2248 |
| EXPORTS-2 | M | C | truST trim cannot fit a medium map (144 > 125) and repeats the hint. | plcopen_targets.py:113 |
| EXPORTS-3 | M | C | PDO-entry bit channels have no BOOL on the PLC side in bridge configs. | declare.py:165-193 |
| EXPORTS-4 | M | C | Same as BRIDGE-3 (named and 2-D bounds). | mailboxuse.py:51 |
| EXPORTS-5 | L | S | Only `.st` POUs scanned for mailbox blocks. | mailboxuse.py:103 |
| EXPORTS-6 | L | S | Generic PLCopen uses the resource global without VAR_EXTERNAL; namespace tc6_0200. | plcopen.py:340 |
| EXPORTS-7 | L | C | Single network renamed "CANbus" through CODESYS build and import. | codesys/xmlimport.py:680 |
| EXPORTS-8 | L | C | Failed exports end with "nothing was uploaded". | cli.py:1062 |
| UI-1 | M | C | Remote CAN adapter locked to a simulated network's bit rate, false master note. | server.py:381 |
| UI-2 | M | C | truST or Other PLC next to the PLC link get Writes ticked, no warning. | bridge.js:773, bridgecheck.py:261 |
| UI-3 | M | C | Connection Download goes through with errors, README says 127.0.0.1, row "In sync". | server.py:3264, plcopen_targets.py:262 |
| UI-4 | M | C | Devices starts a second instance on the same ports with no warning. | devices/plan.py:224 |
| UI-5 | M | C | Finished job text reworded for the project open now. | devices.js:597 |
| UI-6 | M | C | Settings → Check now closes the menu; result never seen. | index.html:59 |
| UI-7..15 | L | C | Check now enabled when off; sudo field layout; New editor project without openplc-cli; empty address; CODESYS clash reason; Devices at 800 px; header chip "pr…"; stale tab polls 403; wording. | see tasks |
| INSTALLERS-1 | M | C | `curl \| bash` without pipefail: a failed download ends as exit 0 / Done; same in `--ssh` and `.ps1`. | devices/jobs.py:83, install-bridge.sh:316, .ps1:126 |
| INSTALLERS-2 | M | C | Update re-enables a switched-off link and discovery and moves the link's instance. | devices.js:329, service.py:257 |
| INSTALLERS-3 | M | C | Advertisement always says diagnostics port 7531. | install-link.sh:44 |
| INSTALLERS-4..7 | L | C/S | Phantom job after remove; re-check uses stale version; plan hashes only canworks.json; probe exit always null. | service.py:147, update.py:296, plan.py:212, device-probe.sh:145 |
| DOCS-1 | M | C | Add OpenPLC says the mailboxes are turned on. | bridge.js:761, :812 |
| DOCS-2 | M | C | "Update declarations" named in UI, docs, generated headers and specs. | bridge.js:350, openplcmodbus.py:68 |
| DOCS-3 | M | C | Removed `drive-input` fault still documented. | docs/diagnostics.md:168 |
| DOCS-4..13 | L | C/S | README runtime switch text, release-notes `--with-openplc`, Build only, `master.diagnostics`, `--runtime`/`--host` in specs, j1939 anchor and duplicate, `canworks-deploy check`, plugin wording, doc test gap. | see tasks |

## Decisions

**BRIDGE-1: one process-wide SIGUSR1 handler.** `main()` of the bridge and `canopen_host` install a no-op SIGUSR1 handler before any network starts, so every Lely poll saves and restores a handler, never the default action. Tried locally: 3 of 3 stops exit 0 and the upload applies. A CI test starts a two-network config, stops it with SIGTERM and checks exit 0, both stop NMTs and no run marker; the same for an upload.

**BRIDGE-2: baseline after the client writes.** The request mailbox takes its baseline the first time the client writes the request words, as the control and SDO blocks do. Until then the mailbox answers nothing.

**BRIDGE-4: idle ends program resources.** Idle turns outputs off, and a CAN send or SDO write from a mailbox is an output. So idle ends receivers, cyclic jobs and mailbox operations with ERROR_ID 8 and the log reason "idle", as PLC stop does. Serving requests in idle was the alternative; it would let a program send frames while its outputs are off.

**BRIDGE-6: cancel drops what is queued.** A cancelled operation still waiting in the SDO or CAN queue is dropped. One already on the bus finishes and its result is discarded; docs/modbus-bridge.md says that "cancelled" means the result is discarded and the frame may have gone out.

**BRIDGE-7: refused, not warned.** `receive` or `cyclic_jobs` above 0 without `requests` of at least 1 is refused by both checks with a parity corpus entry. The page's controls keep requests at least 1 while either is on.

**BRIDGE-9: call it.** A CANopen session restart calls `end_network` for that network, which is what its comment says.

**Mailbox detection (BRIDGE-3, EXPORTS-4, EXPORTS-5).** `ARRAY[...] OF <block>` with any bounds and dimensions counts the product of the bounds when all are integer literals or constants declared in the project; otherwise it counts the block as "unknown count". Namespaced types (`canworks.X`) count as `X`. A user function block's mailbox blocks count once per instance of that FB, through nested FBs. Non-ST POU files are scanned for block type names as `scan.py` does. With any "unknown count", "Turn on what the program uses" gives the maximum for that part and Problems never offers "Turn off".

**NODERED-1: close what the last session opened.** The bridge node keeps the slot numbers it opened and, after `_seed` on a new connection, closes every receiver slot with a generation that no current receiver owns, even when no batch is present. On Deploy, `stop()` waits up to 500 ms for queued closes before it tears down the connection. ERROR_ID 5 is retried once after the cleanup.

**NODERED-2: the form wins.** A configured value in the form is used; `msg.payload` sets the value only when the form's value is empty. The same rule for every job node with a form value.

**NODERED-7: map hash by device identification.** Without `plc_link` the image has no hash, and adding one would move registers for every client. Instead the bridge answers Modbus function 43/14 (Read Device Identification) with vendor "canworks", product "canworks-bridge", its version, and a private object 0x80 holding the map hash as 8 hex digits. The bridge node reads it at connect; on a mismatch it refuses every write and job with "map mismatch: export the flow again" and shows it in its status. A bridge that answers 43 with exception 1 (older) gives a warning only. Other clients can use the same object.

**EXPORTS-2: compute before offering.** The truST fix computes the trimmed map size first. When it fits, "Trim the mailboxes for truST" is offered; when it does not, the refusal says "with a request mailbox this map needs N input registers, more than 125" and offers canworks blocks None.

**EXPORTS-3: bits on the PLC side.** In a bridge config every bit channel is declared as a BOOL at the location the map row shows (`modbusmap.bit_byte()`); `canworks_in` reads it from its entry's register and `canworks_out` ORs it into the entry's word. The map hash does not change (bits are part of their entry), but the generated declarations do, so existing editor projects need Save.

**EXPORTS-6: standard IEC for generic.** The generic dialect adds `VAR_EXTERNAL canworks : canworks_values END_VAR` to each program that uses it and writes the TC6 2.01 namespace. The truST dialect keeps its form unless truST accepts the same file (checked during apply; if it does, both use it).

**EXPORTS-7: the network name travels.** The CODESYS build names the CAN bus object after the canworks network; the import takes the network name from the bus object unless it is the CODESYS default name, then from the interface.

**UI-2: any second writer.** With `plc_link` true, any connection with `writes` other than the one with the PLC link gets the Problems warning, and the Add dialog leaves Writes off for a new connection when a PLC link exists.

**UI-3: no download with errors.** A connection's Download is refused while the check has an error on that connection's addresses or on `bridge.listen` for it, with the same "fix it first" text as the CODESYS download. A README for a non-loopback connection names the bridge's listen address, never 127.0.0.1.

**UI-4: name the running instance.** When another bridge instance is active on the device, the Start or Update confirmation names it and offers **Stop A and start B** as the main button, with **Start next to A** as the second. A clash of the Modbus listen port, the diagnostics port or a CAN interface is shown as a warning in the confirmation.

**INSTALLERS-1: download to a file.** Every job and the `--ssh` forms download the script to a temporary file with `curl -fLsS -o`, then run it; a failed download ends the job with curl's exit code and the text "could not download <script> <version>".

**INSTALLERS-2: keep the device's settings.** The job options default to what the probe shows: the link on only when it is installed, its instance unchanged on an update, discovery on only when the device advertises now. The Options box shows those values unfolded when they differ from the defaults of a new install.

**INSTALLERS-3: port from the config.** `install-link.sh` reads `diagnostics.port` from `--config` when `--diag-port` is not given.

**INSTALLERS-6: hash every uploaded file.** The probe and the plan compare a sorted list of `name sha256` for every file the job uploads.

**Specs.** Spec text that names removed options or "Update declarations" is corrected under MODIFIED. The rest are ADDED requirements, as in earlier fix changes.

## Risks / Trade-offs

- The Node-RED map hash check adds function 43 to the bridge; an HMI scanning functions sees one more supported function. Acceptable.
- Mailbox "unknown count" turns on the maximum, which costs Modbus requests for programs with computed array sizes. Better than ERROR_ID 22 at run time.
- Idle now ends receivers; a client that used idle as "pause outputs, keep receiving" has to reopen them. Not in real use.
- EXPORTS-3 changes generated declarations; existing editor projects need Save (already the rule after any map change).

## Open questions

None. Hardware: the multi-network stop, upload and interface-down checks run on the bench device with one real and one simulated network; the Safari check of #282 runs on the Mac.
