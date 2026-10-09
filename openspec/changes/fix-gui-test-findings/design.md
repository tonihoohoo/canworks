# Design: fix-gui-test-findings

## Context

The findings come from a browser bug hunt on main a090986. Bug IDs used below:
- **A**: editing a configuration.
- **B**: exports, start page and folder browser, layout, keyboard.
- **C**: online views.
- **D**: trace, frame lab, simulation.
- **F**: first page crawl.

The hunt ran the real plugin in a container without vcan or Docker: `canopen_host` loaded `libcanworks_plugin.so` with `CANWORKS_FORCE_SIMULATE=1` and served the diagnostics channel on 127.0.0.1. The same setup is the base of the new browser run.

## Goals / Non-Goals

**Goals:**
- Fix every bug of the hunt.
- Add coverage for the three classes of bug that slipped through:
  - checks that are looser than the plugin's;
  - views tested only on small fixtures;
  - plugin behaviour that only the real plugin shows.
- Keep the pull request CI wall time and summed job time at or below the baseline.

**Non-Goals:**
- Live 3D motion of the Machine tab and the examples' ST programs. canopen_host runs a stand-in PLC program.
- Real USB adapters.
- Any change to the config file format. All fixes keep the v1/v2 schemas; only the checks get stricter.

## Decisions

### 1. Input PDO timeout checked by the plugin itself (C17/D4)
`Network::CheckInputPdos` skips PDOs that have been seen and relies on Lely's RPDO deadline after that. On the simulated bus that deadline never fires for a synchronous RPDO. The check will also cover seen PDOs (`now - last_rx >= timeout_ms`) on every bus cycle. `HandleRpdoTimeout` stays as an earlier trigger when Lely does fire, and its "came in after the timer" guard already prevents a double count.
*Alternative:* fix the simulated bus so Lely's deadline fires. Rejected: it would still leave the detection dependent on a timer whose behaviour differs between buses, and the spec states the observable behaviour, not the timer.
*Test:* a sim_tests case with TPDO stop on a synchronous PDO, and the timeout bit in the browser run.

### 2. Power cycle hang (D1), refused simulation spin (D3)
After a simulated device's power off, Lely logs `io_can_net_fini() invoked with pending operations`. After power on, the bus thread spins in the virtual channel's write task. The leading suspect is the powered-off device's CAN net being finalised with queued writes still on the shared virtual bus. The fix:
1. Cancel the device's pending writes before its net is destroyed.
2. Make the bus session loop wait instead of spinning when a channel has nothing to send.

This is to be confirmed with a sim_tests case first: five power cycles, then a status answer within 1 s and a stop within 2 s. The refused-simulation path is to end in the same idle state. If the cause turns out to be elsewhere in the simulated bus, the test and the spec still hold; only the fix moves.

### 3. One source of truth for range and clash checks (A1, A8, A11, A14, D3)
The plugin's loader (`config.cpp`, `add_cob`, the simulation loader) is the reference.
- `contract.py` gets a single `parse_number()` used for every numeric field before its range check, so `0x80` and `128` take the same path. Today hex strings pass the schema pattern and skip the range.
- The missing-interface schema error is no longer dropped as "reported above".
- A COB-ID map per network (explicit and default COB-IDs, with the plugin's predefined connection set) reports duplicates naming both PDOs.
- The simulation check learns the RPDO-written objects and the data type fit of overrides.

The **parity test** feeds `test/fixtures/config/bad/*.json` (new) to `contract.check_config` and to `build/canopen_check --no-dcfgen`, and fails on any disagreement. It runs in the tools job, which already builds `canopen_check`.
*Alternative:* call the plugin's loader from the configurator. Rejected: the PC tools must run without the plugin build.

### 4. Decoding from the v2 config (D2)
`Decoder.from_config` turns the network into v1 and runs `dbcexport.build`, whose v1 schema check rejects gateway-routed entries without `iec_location`, and then drops every PDO. Decoding will build its PDO and EDS model from the network as the configurator's check passed it, without a second schema check. A failure of that build is reported as a plain sentence. The DBC export keeps its own check, which learns that routed entries need no PLC location (the same fix the export needs for a gateway config).

### 5. Online table and OD values (C6, C13, C16, C8)
- The node table is patched cell by cell, keyed by node ID, instead of being replaced each poll. This keeps focus and click targets.
- The OD cache is invalidated per entry after a write, a restore and a compare's reads.
- `SERIES_COLORS` in the watch graph uses the theme's palette (`SERIES_COLORS[theme][i]`).
- While the connection line is in error, the node panel gets a disabled look and a "values from N s ago" note.

### 6. Server robustness (B1-B4)
`server.open()` checks that the folder can be listed and the config read before it changes any state or Recent. `PermissionError` and `OSError` on open, save and create become an error with a sentence naming the folder. `startOpen()` gets separate "open existing" and "create new" paths. Move and New editor project pass `sim_path`, the machine file and `cell_eds.json`, as `cli.py` already does.

### 7. Tests and CI time (canopen-ci)
- **Example sweep.** `tests/test_configurator_examples_page.py` opens each example in one configurator per class and walks network × view at 1280 px. It runs the existing `FIT_CHECK` plus console, page and HTTP error listeners, and fails on a decoding note. It runs once per example, so each class should take about 10-15 s. `Layout.test_every_view_fits` drops its 1440 px pass (its views are a subset of the sweep), which pays for the sweep. Both classes go into `page-test-times.json`.
- **Parity test**: Decision 3.
- **Real-plugin browser run** in a new `browser.yml` workflow (weekly, dispatch, and pull requests on the listed paths):
  - Builds `canworks_plugin` and `canopen_host` with the build-plugin action and starts `canopen_host` on `examples/virtual-plant` with `CANWORKS_FORCE_SIMULATE=1`.
  - Runs `test/browser/run.py`, a Playwright script with one step per scenario in the spec.
  - Needs no vcan or kernel modules.
  - It is a separate workflow because `integration.yml`'s pull request paths are workflow-wide and would start the stock and Docker jobs too.
- **Page tests by path.** `ci_changes.py` prints `ui=true|false` from rules in `.github/ci/ui-paths.txt` (`tools/deploy/canworks/**`, `schema/**`, `examples/**`, `tools/deploy/tests/**`, `.github/**`). `configurator-page` gets `if: needs.changes.outputs.ui == 'true'`. Pushes to `main` and unknown bases are always `ui=true`. C++-only pull requests then skip three page shards, which more than pays for the sweep's time on the pull requests that do run it.

### 8. Low items
Each low item is a local fix in the view named in tasks.md, with a check added to that view's existing page test.

## Risks / Trade-offs

- **The parity corpus can lag new plugin checks.** → The spec makes the test name the entry. New plugin refusals add a corpus file in the same PR, which is a review checklist line in `docs/development.md`.
- **The UI path filter could skip a needed run.** It might miss a module the configurator imports. → The rules list the whole `tools/deploy/canworks/` package, not single files. `main` pushes always run everything.
- **The browser run is outside PR CI.** A regression there shows up later. → It runs on pull requests that touch the online, trace, diagnostics or simulated-bus paths, which is where those regressions come from.
- **The D1 cause is not yet confirmed.** → Its task starts with the failing sim_tests case. The spec states behaviour only.
- **Software WebGL is slow in CI.** → The browser run does not open the Machine tab.

## Migration Plan

No config or data migration; the checks get stricter. A config that saved before and the plugin refused will now show a problem in the configurator. That is the intended outcome, and the project is not in use anywhere yet.
