## Why

The docs review of 2026-10-09 (branch `docs/review-refresh`) checked every page against the code and found six things the code gets wrong or leaves half done. The docs branch only fixes text, so these need a code change of their own:

1. `--export-html` (and the configurator's documentation export) does not know J1939. A J1939 network comes out as an empty CANopen master network with node ID 1 and no messages (checked with `examples/j1939/canworks.json`).
2. An SDO block whose `NETWORK` names a J1939 network is queued and nobody takes it, so it ends with `ERROR_ID` 2 (timeout) after `TIMEOUT` instead of being refused at once.
3. The rename to canworks left project-level `CANOPEN_*` names behind: about 20 environment variables, CMake options and Docker build arguments (`CANOPEN_STATE_DIR`, `CANOPEN_PLUGIN_VERSION`, `CANOPEN_IMAGE`, `CANOPEN_BUILD_TESTS`, the test switches, ...), the Dockerfile comment "canopen-local-runtime", the HTML document's `id="canopen-doc"` and its theme key, and `--config` help texts that call the config `canopen_config.json`. The rename script's check does not catch any of them.
4. The simulator fault that changes a device's NMT state is `nmt-state` in `canworks-sim` but `nmt` in `canworks-diag sim fault`, although the spec says the two take the same arguments.
5. `canworks-diag explain` (and `trace` decoding) with a J1939 config whose DBC is set ends in a Python traceback when cantools is missing, instead of decoding without the DBC and saying why.

6. The configurator's start page ([screenshot](screenshots/start-page-before.png)) does not say what the tool is for and never mentions OpenPLC: "Open editor project" does not say which editor, and the standalone choices do not say they come before an OpenPLC project. Its four choices sit in a three-column grid, so "Commission a device" is left alone on a second row. Its page token also still sits in a `<meta name="canopen-token">`.

The project is not in real use, so renames are clean cuts with no aliases.

## What Changes

- **HTML documentation for J1939 networks**: a J1939 network gets its own section: the ECU (NAME fields, preferred address, address range, state and address locations), the DBC file, one table per direction of messages (PGN, name, priority, source or destination, period, timeout, minimum gap) with their signals (start bit, length, sign, scale, offset, unit, PLC address, valid bit), the periodic requests, a 29-bit identifier map and a bus-load estimate with extended frames. Its PLC addresses join the cross-reference. The summary shows the protocol per network, and the default title becomes "CAN network documentation". The embedded JSON becomes `id="canworks-doc"` with `doc_schema_version` 2 (networks carry `protocol`).
- **SDO blocks refuse non-CANopen networks**: a `NETWORK` that is a J1939 network (or a slave network) ends with `ERROR_ID` 6 in the same call, like a network the config does not have. The plugin tells the request slots which networks are CANopen master networks, so the slave network's polling refusal goes away.
- **Old names**: every environment variable, CMake option or cache variable and Docker build argument the project reads gets the `CANWORKS_` prefix. Internal C identifiers stay (header guards, the `CANOPEN_PLC_*` SDO API, which is CANopen's own). The Dockerfile comment, the HTML id and theme key, and the `--config` help of `canworks-deploy`, `canworks-sim` and `canopen_check` follow. `rename_to_canworks.py --check` learns the old variable names so they cannot come back.
- **Fault kind**: `canworks-diag sim fault <node> nmt-state <state>`, the name `canworks-sim` uses. The `nmt` kind goes.
- **Missing cantools**: loading the J1939 DBC without cantools gives the usual "decoding without the DBC" warning, naming cantools, and decoding goes on with the config's own signals.

- **Configurator start page**: a purpose line under the header ("Configure CANopen and J1939 networks for OpenPLC Runtime v4, or commission a CANopen device from this PC"), and choice texts that name OpenPLC where it applies:
  - **Open OpenPLC Editor project**: "Edit the canworks/ folder of an OpenPLC Editor project. PLC addresses are checked against the project's program."
  - **Open standalone config**: "A folder with canworks.json and its EDS or DBC files, before an OpenPLC Editor project exists."
  - **New standalone config**: "Start an empty config in a folder. Move it into an OpenPLC Editor project when you have one."
  - **Commission a CANopen device**: "A USB CAN adapter on this PC, no OpenPLC runtime and no config: scan, LSS, object dictionary, parameter backup, trace."

  The folder browser title and the "not an editor project" message say "OpenPLC Editor project". The choices become a 2 × 2 grid (one column at phone width). The token meta becomes `canworks-token`.

**Not changed:**
- The example configs keep their file names (`config/*/canopen_config.json`); the rename kept them on purpose.
- Docs pages and README are left to `docs/review-refresh`. This change's PR updates only the lines its own changes make wrong, after that branch is merged.
- Documenting `canworks-diag send-stop` is a docs fix and belongs to the docs branch.

## Capabilities

### New Capabilities
None.

### Modified Capabilities
- `canopen-network-docs`: J1939 network section, protocol in the summary, generic default title, `canworks-doc` id and `doc_schema_version` 2.
- `canopen-plc-sdo`: error 6 for a `NETWORK` that is not a CANopen master network.
- `toolkit-names`: every environment variable, CMake option and build argument uses `CANWORKS_`; the old-name check covers them.
- `canopen-online-diagnostics`: `canworks-diag sim fault` uses the simulator's fault kind names.
- `canopen-configurator`: the start page's purpose line, OpenPLC wording, four choices in a 2 × 2 grid.
- `j1939-trace`: decoding without cantools warns instead of failing.

## Impact

- PC tools: `docexport.py`, `docwriter.py` (and the configurator's docs page through them), `diag.py`/`simcli.py`, `bustrace/j1939.py`, help texts in `cli.py`; minor version bump.
- Configurator: `static/index.html`, `static/style.css`, `static/app.js` (browser title, messages, token meta); its layout and page tests.
- Plugin: `plc_api.cpp/h`, `plugin.cpp`, `canopen_runtime.cpp`, `plc_slave.cpp`, `slave_state.cpp`, `dcf_gen.cpp`, `bus.cpp`, `config.cpp`, `eds_lint.cpp`, CMake files, `canworks-sim` help.
- Build and CI: `CMakeLists.txt`, `install-stock.sh`, `docker/local-runtime/Dockerfile`, workflows and test scripts that set the renamed variables.
- Bench: nothing on the bench sets any renamed variable; a normal redeploy picks up the plugin fix.
