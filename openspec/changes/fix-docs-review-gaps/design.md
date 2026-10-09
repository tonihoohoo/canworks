## Context

The findings come from `docs/review-refresh` (2026-10-09). Each was checked against `main` (5b0c7dd) before this proposal:
- `docexport.build()` sends every non-slave network through `_network()`, which reads `master` and `nodes`; `contract.networks()` gives a J1939 network empty ones, so the section shows a master with node ID 1 and nothing else.
- `PlcRequests::validate()` checks only `network < networks_`. A J1939 network has a slot index but no CANopen runtime calls `take()` for it, so the job waits for its timeout. A slave network already refuses by polling `take()` in `PlcSlave::RefusePlcRequests()`.
- `bustrace/j1939.load_dbc()` imports cantools outside its try block, and its caller catches only `OSError`/`ValueError`.

## Decisions

### 1. J1939 section is built from the config alone
The J1939 section uses the config's `j1939` object, plus the DBC file only for names and comments the config lacks (the same loader the trace uses, so a missing cantools only drops those). No EDS, no PLC. Frame bits use the 29-bit formula (extended identifier, worst-case stuffing, interframe space). Bus load counts each `tx` at its `period_ms`. A received message counts only when the DBC gives its cycle time (`GenMsgCycleTime`); guessing a rate from `timeout_ms` would be wrong as often as right, so the total says instead how many received messages had no known rate. Multi-packet messages (more than 8 bytes) count as their transport protocol frames (BAM: 1 announce + ceil(n/7) data frames).

Alternative: show J1939 networks as "not supported" in the document. Rejected: the config already holds everything a reviewer needs, and the doc is the place people print for commissioning.

### 2. `doc_schema_version` 2
Networks gain `protocol`, and J1939 networks have different keys (`ecu`, `messages`, `requests`) instead of `nodes`. Scripts reading version 1 would misread a J1939 network, so the version goes up together with the id change. No version 1 output is kept (project not in use).

### 3. Refuse at `start()`, not by polling
`open()` takes a list of the CANopen master network indexes. `validate()` returns `ERROR_ID` 6 for any other index. The slave network's `RefusePlcRequests()` then has nothing to do and is removed. Error 6 matches what the docs already promise for "a `NETWORK` the config does not have"; a J1939 network has no SDO, so to a block it is not there.

Alternative: error 4 (CANopen not running). Rejected: CANopen may be running on another network, and 4 tells the programmer to look at the plugin rather than at their `NETWORK` input.

### 4. Which `CANOPEN_` names change
Rule: a name someone sets from outside the code (environment variable, `-D` CMake option, Docker build argument, compile definition given by CMake) is project-level and becomes `CANWORKS_`, even when it is about a CANopen tool (`CANWORKS_DCFGEN`, `CANWORKS_EDSLINT`), because users look for one prefix. Names only code sees stay: header guards, the C SDO API (`CANOPEN_PLC_*`, which the PLC library mirrors), and Python constants like `CANOPEN_KEYS`. The list for the rename script:

| Old | New |
|---|---|
| `CANOPEN_STATE_DIR`, `CANOPEN_DCFGEN`, `CANOPEN_GENERATED_CONF`, `CANOPEN_BUS_NO_FIFO` | `CANWORKS_…` (plugin, run time) |
| `CANOPEN_PLUGIN_VERSION`, `CANOPEN_PREFIX`, `CANOPEN_BUILD_TESTS`, `CANOPEN_STLIB_DIR`, `CANOPEN_IMAGE`, `CANOPEN_IMAGE_ID` | `CANWORKS_…` (build and install) |
| `CANOPEN_CHECK`, `CANOPEN_CHROMIUM`, `CANOPEN_EDSLINT`, `CANOPEN_EDITOR_CLI`, `CANOPEN_REQUIRE_BROWSER`, `CANOPEN_REQUIRE_PARITY`, `CANOPEN_REQUIRE_STRUCPP`, `CANOPEN_REQUIRE_TSHARK`, `CANOPEN_SCREENSHOTS`, `CANOPEN_UPDATE_GOLDEN`, `CANOPEN_AXE_REPORT` | `CANWORKS_…` (tests and CI) |

The `canopen_check` binary and `canopen_plugin` namespace keep their names (CANopen-specific, per the rename's own rule).

### 5. Fault kind `nmt-state`
`canworks-sim` and the simulation file already use `nmt-state`/`nmt_state`; only the diag client differs. `nmt` in `canworks-diag` is also the NMT command to a real node, so the longer name avoids two meanings.

### 6. Start page wording
Name OpenPLC where the choice depends on it (the Editor project, "before an OpenPLC Editor project exists", "no OpenPLC runtime"), and not elsewhere: the header stays "canworks configurator", since the tools also work with no PLC. Commissioning is CANopen only today (no J1939 in `commission.js`), so its card says so. A 2 × 2 grid (`repeat(2, 1fr)`, one column below the narrow breakpoint) keeps four cards even instead of 3 + 1; four in a row would squeeze the longer texts at 1000 px.

### 7. Commissioning stays on the USB adapter
`onlineSetup()` shows the Runtime/adapter choice in every mode, and with the Runtime target and no config it links to `showView("bus")`; in commission mode `render()` sends any view outside Online, Scan, Trace and Frame lab back to Online, so the link only redraws the same page. The fix forces the adapter target in commission mode (without changing the saved setting, so a config opened later keeps its Runtime choice) and hides the choice.

Alternative: let commissioning connect to a runtime with only host and token, no config. Rejected for this change: the spec defines the mode as PC-direct on an adapter, the start card says "no OpenPLC runtime", and through a runtime the plugin's own master would be running on the same bus. It can be proposed on its own if wanted.

## Risks / Trade-offs

- [Docs branch conflicts] → this change does not edit `docs/` or README until `docs/review-refresh` is merged; then it changes only the lines its own behaviour makes wrong (plc-sdo error 6 row, network-docs JSON id and J1939, slave.md state dir variable, development.md test variables, simulator fault kind).
- [CI time] → new tests are unit tests in existing jobs (doc export of `examples/j1939`, a `validate()` case in the plugin's ctest, a no-cantools case); no new job.
