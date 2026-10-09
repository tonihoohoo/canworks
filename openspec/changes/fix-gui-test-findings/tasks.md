# Tasks

Bug IDs refer to the browser bug hunt of 2026-10-09 (design.md, Context). Each group lands its own tests and docs.

## 1. Plugin: input PDO timeout, power cycle, EMCY count, Tx direction

- [x] 1.1 `Network::CheckInputPdos`: also time out seen PDOs (`now - last_rx >= timeout_ms`) while the node is up; keep `HandleRpdoTimeout` as an early trigger without double counting (C17/D4). Verify with a new sim_tests case: TPDO stop on a synchronous TPDO with `timeout_ms` 200 → timed out within 300 ms, one warning, timeout bit TRUE, node still OPERATIONAL; the existing PDO timeout tests still pass.
- [x] 1.2 Add a sim_tests case for five power off/on cycles of a simulated node, then a status answer within 1 s and a plugin stop within 2 s; confirm it fails today (D1).
- [x] 1.3 Fix the bus-thread spin after a power cycle (pending writes of the powered-off device; no busy loop in the bus session) and after a refused simulation (D3 second half); verify the 1.2 case and a refused-simulation case pass.
- [x] 1.4 EMCY count: report the number received, not the history length (C14, `network.cpp` status); unit test with 20 EMCYs → count 20, history 16.
- [x] 1.5 Simulated bus trace tap: frames from the master and `send_frame` are Tx, simulated devices' frames Rx (D10); verify in the simulated-bus trace test that SYNC and RPDOs are Tx.
- [x] 1.6 Simulator control protocol: refuse an override or `set` value that does not fit the object's data type (D3); simulator unit test.

## 2. Checks: the configurator refuses what the plugin refuses

- [x] 2.1 `contract.py`: one `parse_number()` for every numeric field before its range check (node ID, heartbeat, identity, COB-IDs, TIME COB-ID, master vendor ID) (A8, A14); tests with hex and decimal values on both sides of each range.
- [x] 2.2 Report a missing adapter interface (and slcan device) instead of dropping the schema error (A1); test: Add network with an empty interface → problem, Save disabled.
- [x] 2.3 Per-network COB-ID map with default and explicit COB-IDs; report duplicates naming both PDOs (A11); also fix the misleading "'auto' was expected" message for 2048; tests.
- [x] 2.4 Axis scale numerator/denominator 0 refused (A14); heartbeat consumer timeout shorter than the period is refused (A6); tests.
- [x] 2.5 Plain messages: map schema errors (required, pattern, enum, minItems, range) to sentences in the user's terms; no regex or schema text in Problems or next to fields; Problems doesn't repeat the place (A7, also the J1939 and simulation messages); page test over a set of invalid fields.
- [x] 2.6 Simulation check (`simulation.py` and `/api/sim/check`): refuse a value source or override on an RPDO-written object, a value that does not fit the data type, and a scenario step, fault, pin or TPDO number on an unknown node or PDO (D3, D19); tests.
- [x] 2.7 Parity test: corpus `test/fixtures/config/bad/*.json` covering 2.1-2.4 and 2.6, each checked by `contract.check_config` and `build/canopen_check --no-dcfgen`; fails on disagreement; runs in the tools job; `docs/development.md` says that a new plugin refusal adds a corpus file.

## 3. Configurator server and project files

- [x] 3.1 `server.open()`: check that the folder can be read before changing state or Recent; `PermissionError`/`OSError` on open, save and create become one sentence naming the folder (B1, B2, B15 "[Errno 13]"); page tests with an unreadable folder and a read-only folder (skipped when running as root).
- [x] 3.2 `startOpen()`: separate "open existing" (refuse a missing folder or missing `canworks.json`) and "create new" (refuse an existing config, offer to open it) (B4); page tests.
- [x] 3.3 Move into project… and New editor project…: take `simulation.json`, the machine file and the slave EDS description along; the replace question names `canworks/` (B3, B14); tests check the files in the new project.
- [x] 3.4 Slave "Build the EDS" loads the project's EDS description (`cell_eds.json` as well as `cell.eds.json`); Generate keeps the slave's EDS name and bindings; fix "Bind all 0 objects … ()?" (A15); page test on the virtual-plant cell network.
- [x] 3.5 Folder browser: clear the old list on a failed Go, clear the error on a later success, a Remove action for Recent entries, aria-pressed on the start choices (B15); page test.
- [x] 3.6 Serve a favicon (F2); the page tests' console listener no longer needs a favicon exception.

## 4. Editing

- [x] 4.1 Network rename and node ID change update the gateway routes (A4); removing the gateway's upper network asks about the gateway (A20); page tests.
- [x] 4.2 Rename network dialog: focus the name field; Enter renames; the dialog promise always resolves (A2); also fix the "network network 5" heading and the warning that names network "" (A3); page test.
- [x] 4.3 PDOs: a Remove PDO action; an empty PDO no longer stays behind (A9); the same startup SDO object twice is marked (A12); clearing a receive timeout is one undo step (A10); page tests.
- [x] 4.4 J1939: a second DBC import asks before replacing (A17); page test.
- [x] 4.5 Variable declarations: say to paste into the program's VAR block, not a global list (A5); docs/configurator.md matches.
- [x] 4.6 Save keeps the file's key order, so a one-field change is a one-line diff (A18); test compares a saved file with the original after one edit.
- [x] 4.7 A field edited back to its saved value makes the page clean again (A19, B's typed-back finding); page test.

## 5. Layout, keyboard and exports

- [x] 5.1 The gateway routes table fits at 1280 px and scrolls inside its box below 1000 px (F1, B13); the slave objects table (B12) and J1939 signal tables (A16) fit at 1280 px; the gateway route inputs get labels (F1); covered by the 8.1 sweep.
- [x] 5.2 Keyboard: Recent and folder entries are buttons (B5); "Add node from EDS…" is keyboard-usable (visually hidden input, not `display:none`) (B6); page test.
- [x] 5.3 Focus return: after node Enter/Space, after Escape in dialogs opened from menu items, after ↑ reaches "/", after reorder ↑/↓ and Add (B7, A13); menus close on focus leaving and on Escape (B11); page test with a keyboard walk.
- [x] 5.4 Grid rows don't stretch at 1100 px and below (B8); covered by the sweep at 1000 px in the layout test.
- [x] 5.5 Exports: a running state while an export runs (B10); findings of a failed export replace the previous ones (B9); DCF/DBC not offered on slave and J1939 networks, and All DCFs not on a J1939-only config (B9); page tests.

## 6. Online view

- [x] 6.1 Node table patched in place, keyed by node ID (C16); page test: focus on a row survives 5 s of polls.
- [x] 6.2 Watch list graph colours from the theme palette (C8); page test checks that the plot has drawn paths.
- [x] 6.3 OD values refreshed after a write, a restore and a compare (C6); "set by config" mark right after Keep in configuration (C4); page tests with FakePlugin.
- [x] 6.4 Writing an RPDO-mapped object warns; Keep in configuration keeps the written value (C9); page test.
- [x] 6.5 Connection lost: node panel greyed with "values from N s ago" (C13); PDO timeout lines don't say "receiving" while the node is not OPERATIONAL (C5); page tests.
- [x] 6.6 "Connection…" works for every target kind (C1); recheck against main after the start-page change; page test.
- [x] 6.7 Wording: no "(status 2)" after a good SDO variable read (C2); "simulates every network" without "the local simulator runtime" unless the runtime says so (C3); Verify names the draft or saves first (C7); page tests updated.
- [x] 6.8 Slave network: the "In a PDO" filter works; the gateway status objects in its PDOs are named; a simulated note (C10); page test.
- [x] 6.9 LSS and scan: "Back to the scan" only when coming from the scan; an invalid node ID keeps the dialog open with the error (C11); a just-added node is shown as configured (C12); changing the EDS library folder re-matches shown results (C15); page tests.
- [x] 6.10 Commissioning: "Add to a config…" stays when the config already has the node and says so; "Compare against the configuration" only with a configuration (C18); commissioning page test.

## 7. Trace, Frame lab, sending, Simulation

- [x] 7.1 Decoding from the v2 config without a second schema check; routed entries need no PLC location in the DBC export either; a decoding note only for a real config problem, without paths (D2); test: virtual-plant io decodes node 5 TPDO 1 and offers its PDO signals.
- [x] 7.2 Identifier filters read hex with or without `0x` (D5); cyclic jobs show hex IDs (D6); tests in `test_configurator_trace.py` and the trace page test.
- [x] 7.3 On network switch drop the graph series (D7), the Frame lab result (D18), the Simulation node and pins (pins keyed by network and node) (D8); page tests.
- [x] 7.4 "Send this frame" opens the Send panel (D9); Send and Frame lab messages without Python internals (D17); Inject form closes after success (D22); page tests.
- [x] 7.5 J1939 networks show only J1939 kinds, sequences, triggers, graph group name, inspector wording and Frame lab examples; CANopen networks don't show J1939 kinds; a TP ID is named after its message, not the last frame (D15); J1939 trace page test.
- [x] 7.6 Trigger tab: "canworks folder"; auto-save refuses a missing or relative folder (D16); single trigger keeps only the pre/post window (D21); page tests.
- [x] 7.7 Signals CSV: one row per change (D13); the dropped-frames note states what is held (D14); first click after a drag-zoom sets cursor A (D12); tests.
- [x] 7.8 Error banners cleared on a tab or view switch; the tick field compares as a number; each tick problem listed once (D20); page test.
- [x] 7.9 Standalone simulator "port closed" message names the simulator, not the runtime (D11); test.

## 8. Browser coverage and CI time

- [x] 8.1 `tools/deploy/tests/test_configurator_examples_page.py`: for virtual-plant, gantry-cell and j1939, visit every network × view at 1280 px with `FIT_CHECK`, console, page-error and HTTP listeners, and no decoding note; add to `page-test-times.json`; verify it fails on main before groups 5 and 7 and passes after.
- [x] 8.2 `test_configurator_layout.Layout.test_every_view_fits`: drop the 1440 px pass; measure the configurator-page jobs' summed time before and after.
- [x] 8.3 `ci_changes.py` prints `ui=` from `.github/ci/ui-paths.txt`; `configurator-page` runs only when `ui` is true (always on `main` pushes and unknown bases); tests in `test/ci`.
- [x] 8.4 `test/browser/run.py` and `.github/workflows/browser.yml` (weekly, dispatch, pull requests on the online, trace, diagnostics and simulated-bus paths): build `canworks_plugin` and `canopen_host`, start the host on virtual-plant with `CANWORKS_FORCE_SIMULATE=1`, run the spec's steps in Chromium; verify with a manual run on the branch.
- [x] 8.5 `docs/development.md`: how to run the plugin and the configurator in a container without vcan or Docker (the 8.4 setup), the example sweep, the parity corpus and the browser workflow.
- [ ] 8.6 CI time: wall and summed job time of the pull request run vs the median of the last 5 green `main` runs with code changes, both at or below, stated in the PR body.

## 9. Release

- [x] 9.1 docs/configurator.md, docs/trace.md and docs/simulator.md updated where behaviour changed; README if a listed feature changed.
- [x] 9.2 PC tools minor version bump; golden doc models refreshed (`UPDATE_GOLDEN=1`).
- [ ] 9.3 Banned-word check on the branch (`--files` and `--range origin/main..HEAD`).
- [ ] 9.4 Re-run the browser bug hunt crawl (every view of the three examples against the plugin on its simulated bus) and confirm no listed bug remains; list any leftovers in the PR.
