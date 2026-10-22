## Why

The word "simulator" names four different things today, and the names don't say which is which. `canworks-sim-runtime` is not a simulator at all but the PLC runtime in a container. `canworks-sim` sounds generic but plays only CANopen and plain CAN devices, while J1939 has its own `canworks-j1939-sim`. And docs/simulator.md, titled "Simulator", covers CANopen only. A reader can't tell which tool simulates what, or why J1939 isn't in the configurator's Simulation tab. The project isn't in real use yet, so this is the cheapest time for a clean rename.

## What Changes

- **BREAKING** `canworks-sim-runtime` becomes **`canworks-local-runtime`**: the command, the image `ghcr.io/tonihoohoo/canworks-local-runtime` and the container name. The docs already call it "the local runtime".
- **BREAKING** The runtime-host binary `canworks-sim` becomes **`canworks-canopen-sim`**, paired with `canworks-j1939-sim`. `install-stock.sh` removes the old binary and its `/usr/local/bin` link. The simulation file schemas keep their names (`canworks-sim.v1/v2`), because the plugin reads that file too.
- No aliases, per the not-in-use rule. The repository's name check also reports the two retired names outside archived changes.
- docs/simulator.md becomes **Simulation** and opens with a "what to simulate, which tool, where it runs" table. It explains why CANopen and J1939 have separate simulators. The README command table gets one row per simulator, each with its protocol.
- The configurator's **Standalone simulator** connect target becomes **CANopen simulator**. On a J1939 network the **Simulation** tab no longer disappears: it says the runtime doesn't simulate J1939 and offers the `canworks-j1939-sim` command line for the network's DBC.
- No behaviour changes beyond names and wording. Both simulator engines stay as they are.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `toolkit-names`: new simulator names, the retired-name check, the simulation overview and wording.
- `canopen-local-runtime`: command, image and container are `canworks-local-runtime`.
- `canopen-simulated-bus`: the standalone binary is `canworks-canopen-sim`.
- `canopen-device-simulator`: the control command example uses the new name.
- `canopen-online-diagnostics`: references to the simulator binary and the local runtime.
- `canopen-stock-install`: the new binary name, plus removal of the old binary and link.
- `canopen-virtual-example`: the example runs in `canworks-local-runtime`.
- `canopen-configurator`: the "CANopen simulator" connect target, and Simulation on a J1939 network.

## Impact

- **PC tools:** `pyproject.toml` entry point, `localruntime.py`, `simcli.py`/`simclient.py`/`diag.py` texts, configurator `connection.js`/`sim.js`/`shell.js`/`app.js`, and tests. The tools minor version goes up (0.108.0).
- **Plugin build:** the CMake target and the `tools/sim/*` usage texts. `install-stock.sh` and the plugin version go up.
- **CI and release:** `ci.yml` build targets, `local-runtime.yml` image tags, `release-deploy.yml` image name. The `rename_to_canworks.py` mapping and its check, plus `test/ci/test_rename.py`.
- **Docker:** `docker/local-runtime/Dockerfile` labels and comments.
- **Docs:** README, simulator.md (restructured), local-runtime.md, j1939.md, install-stock.md, install-pc.md, configurator.md, diagnostics.md, development.md, tour.md, raw-can.md, codesys.md, deploy.md, SECURITY.md, tools/deploy/README.md.
- **Bench:** the Pi gets the renamed binary on its next plugin install. On Toni's Mac/Windows an old `canworks-sim-runtime` container, if any, is removed by hand (`docker rm -f canworks-sim-runtime`). The ghcr image under the old name stays until its retention cleans it up.
