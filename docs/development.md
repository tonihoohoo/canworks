# Development

Building the plugin, running the tests, and how CI is set up. For using the toolkit, start at the [README](../README.md).

## Build and test

```sh
sudo scripts/dev-setup.sh                       # Lely into /opt/canworks, dcfgen, vcan0
git clone -b development https://github.com/Autonomy-Logic/openplc-runtime ../openplc-runtime
cmake -B build -DOPENPLC_ROOT=../openplc-runtime
cmake --build build -j
ctest --test-dir build --output-on-failure -j4  # unit and virtual-bus tests (one test per sim case)
build/test/sim_tests --exact sim_sdo_variables  # one sim case on its own
build/test/sim_unit_tests                       # simulator unit tests
python3 -m unittest discover -s tools/deploy/tests -t tools/deploy   # deploy tool and configurator (needs jsonschema;
                                                                     # the page tests also need playwright)
PYTHONPATH=tools/editor-hook:tools/deploy python3 -m unittest discover -s tools/editor-hook/tests -t tools/editor-hook
test/pingpong/run.sh                            # the real plugin against the ping-pong slave on vcan0
test/sensor/run.sh                              # ... against the simulated RTD module
test/fixed/run.sh                               # ... against a device with a fixed PDO mapping
test/lss/run.sh                                 # LSS node ID assignment
test/params/run.sh                              # device parameter backup, compare and restore
test/commissioning/run.sh                       # write a configuration to one device, PDO test
test/localbus/run.sh                            # the PC tools on vcan0 without a runtime
test/simulator/run.sh                           # canworks-sim against the plugin (needs vcan1)
test/trace/run.sh                               # bus trace and its export formats
test/rawframes/run.sh                           # raw frames sent by hand, raw messages, replay, bit rate detection refusals
test/bus/run.sh                                 # bus state byte with vcan0 taken down and up
test/slcan/run.sh                               # slcan adapter (needs the slcan module and vcan1)
test/j1939/run.sh                               # the J1939 ECU against the J1939 simulator (needs can-j1939)
```

`-DCANWORKS_WITH_CANOPEN=OFF` or `-DCANWORKS_WITH_J1939=OFF` builds one protocol only; a J1939-only build needs no Lely.

The configurator and the plugin refuse the same configs: `tools/deploy/tests/test_parity.py` runs every entry of `test/fixtures/config/bad/` (a config, and optionally its simulation file) through the deploy tool's checks and through `build/canopen_check --no-dcfgen`, and fails naming the entry when one of them accepts it. It skips without the build unless `CANWORKS_REQUIRE_PARITY=1`. In CI the tools job keeps the classes that need `build/canopen_check` (`test_parity`, `test_dcfexport.Parity`, `test_project.IntoProject`) on one shard with `test_shard.py --together`, and only that shard builds it and sets `CANWORKS_REQUIRE_PARITY=1`. A new test class that runs the build joins that `--together` pattern in `.github/workflows/ci.yml`. Both test jobs split by recorded class times (`.github/ci/tool-test-times.json`, `.github/ci/page-test-times.json`); refresh them from the shards' "class times:" lines when the shards drift apart. **A pull request that makes the plugin refuse something new adds a corpus file for it**, and the configurator's check that refuses it too.

The CiA 402 tests use the editor's ST compiler, STruC++ (needs Node 22):

```sh
test/cia402/run.sh                              # ST tests of the generated axis glue against a drive model
cmake -B build -DOPENPLC_ROOT=../openplc-runtime -DSTRUCPP=$(scripts/fetch-strucpp.sh)
cmake --build build -j && build/test/sim_tests --exact sim_cia402_demo   # the demo program on the virtual bus
```

CI (`.github/workflows/ci.yml`) runs all of these on every pull request and push to `main` that changes code, the deploy tool, page and vcan tests spread over several runners (a new vcan test goes into the vcan group with the least test time, listed above the job; package installs go through `.github/scripts/apt_install.py`, which skips installed packages and retries a stalled mirror); its last job, `ci-ok`, is the one check a branch ruleset needs. A change that touches only documentation or specs runs just the OpenSpec validation; the build and test jobs are skipped. The vcan steps of one protocol are skipped when a change touches only the other protocol's files (`.github/ci/areas.txt`). The configurator page tests run only when a change touches what the configurator uses: the PC tools package, the schemas, the shipped examples, the deploy tool tests or the CI files (`.github/ci/ui-paths.txt`); a push to `main` always runs them.

## Browser coverage

Three kinds of test check the configurator in ways the small page-test fixtures do not:

- **Example sweep.** `tools/deploy/tests/test_configurator_examples_page.py` opens `examples/virtual-plant`, `gantry-cell` and `j1939` and visits every view of every network at 1280 px. It fails on a clipped field or button, a table or view that scrolls sideways, a console or page error, an HTTP error answer, or a "decoding without the config's PDOs" note, and names the example, network and view of each. It runs in the configurator page jobs; a new page-test class goes into `.github/ci/page-test-times.json` so the shards stay balanced.
- **Validation parity.** A corpus of bad configs under `test/fixtures/config/bad/` goes through both the configurator's check and the plugin's loader (`canopen_check`) in the tools job; both must refuse each one.
- **Browser run against the real plugin.** `test/browser/run.py`, below.

## The plugin and the configurator without a CAN interface

`canopen_host` loads the plugin the way the runtime does, with a stand-in PLC scan. With `CANWORKS_FORCE_SIMULATE=1` every network of the config runs on the plugin's simulated bus with its simulated devices, so no vcan, Docker or CAN adapter is needed (a container works). The stand-in scan does not run the example's ST program. Build the two targets, copy an example (the plugin writes its generated files next to the config), and start the host and the configurator:

```sh
cmake -B build -DOPENPLC_ROOT=../openplc-runtime
cmake --build build -j --target canworks_plugin canopen_host
cp -r examples/virtual-plant /tmp/vp
CANWORKS_FORCE_SIMULATE=1 build/test/canopen_host build/plugins/libcanworks_plugin.so \
    /tmp/vp/canworks/canworks.json 3600 > /tmp/vp-host.log 2>&1 &
PYTHONPATH=tools/deploy python3 -c 'from canworks.configurator.server import main; main()' /tmp/vp
```

The diagnostics channel listens on 127.0.0.1 at the config's `diagnostics.port` (7531 by default; set another port in the copy to run several hosts). In the configurator, Online → host `127.0.0.1:7531`, token `virtual-plant-demo` (the example's demo token). The Simulation view then drives the simulated devices: faults, power off and on, TPDO stop. `PYTHONPATH=tools/deploy python3 -m canworks.diag --runtime 127.0.0.1 --token virtual-plant-demo status` (or `canworks-diag` when the PC tools are installed) reads the same channel from the command line.

## Browser run against the real plugin

`test/browser/run.py` does the setup above on a temporary copy of `examples/virtual-plant` (on a free diagnostics port) and drives the configurator in Chromium through these steps:

1. Connect.
2. Nodes 5, 6 and 7 OPERATIONAL in the node table.
3. An SDO read and write on node 6.
4. A heartbeat stop on node 6 seen online, then cleared.
5. A TPDO stop on node 5 raising its timeout.
6. A trace started, stopped and downloaded.
7. A power off and on of node 5, after which the status still answers.
8. The host stopping on SIGTERM.

A failed step is reported with a screenshot and the run goes on. Locally (needs Playwright: `pip install jsonschema playwright`, and a Chromium from `python -m playwright install chromium` or named by `CANWORKS_CHROMIUM`):

```sh
cmake --build build -j --target canworks_plugin canopen_host
test/browser/run.py --out /tmp/browser-run      # logs, screenshots and the downloaded trace in --out
test/browser/run.py --headed                    # watch it
```

`.github/workflows/browser.yml` runs it weekly, on "Run workflow", and on pull requests that change the configurator's online or trace code, the diagnostics, the plugin's bus, network and diagnostics sources, or the simulator. It is a workflow of its own, so CI's time and `ci-ok` are unaffected; on a failure it keeps the logs and screenshots as the run's `browser-run` artifact.

## Integration tests (by hand, weekly, or locally)

Two end-to-end installs test against things outside this repository and mostly catch upstream drift, so they are not in the pull request run. `.github/workflows/integration.yml` runs them weekly (with the single-protocol builds), on "Run workflow", and on pull requests that change the install routes (`install-stock.sh`, `test/stock/`, `test/docker/`, the editor hook). On a Linux machine with the development build above:

```sh
pip install jsonschema python-dotenv
test/stock/run.sh ../openplc-runtime build      # stock runtime install, upload rules and editor hook (upstream development)
sudo test/docker/run.sh --image ghcr.io/autonomy-logic/openplc-runtime:latest   # Docker route; needs Docker and vcan0
```

Use a development machine, not one running your PLC: the stock test installs into `/opt/canworks` and the runtime checkout, and the Docker test starts runtime containers on the host network.

## Local simulator runtime image

`.github/workflows/local-runtime.yml` builds the image of [local-runtime.md](local-runtime.md) from the pinned upstream runtime (`docker/local-runtime/runtime-version`) and runs `canworks-sim-runtime` against it with a PLC program compiled by STruC++, then deploys the virtual example to it and runs its test scenarios (`test/virtual-example/run.sh`), on pull requests that change the image, the plugin, the command or the example, weekly and on "Run workflow"; an arm64 runner builds the arm64 image. Locally (needs Docker and Node 22):

```sh
docker build -f docker/local-runtime/Dockerfile --build-arg RUNTIME_IMAGE=ghcr.io/autonomy-logic/openplc-runtime:$(cat docker/local-runtime/runtime-version) -t canworks-sim-runtime:dev .
test/local-runtime/run.sh --image canworks-sim-runtime:dev --strucpp "$(scripts/fetch-strucpp.sh)"
test/virtual-example/run.sh --image canworks-sim-runtime:dev --strucpp "$(scripts/fetch-strucpp.sh)"
```

## Repository layout

```
CMakeLists.txt     builds libcanworks_plugin.so; the runtime's install.sh builds it from here
plugin/            native plugin source: src/can/ the shared CAN core (config, adapters, bit rate
                   detection, trace, raw frames, diagnostics server, entry points), src/canopen/ the
                   CANopen master, slave and gateway on Lely, src/j1939/ the J1939 ECU (address claim,
                   kernel sockets, signals), src/can/raw/ raw CAN messages, plain networks
                   and the frame blocks' interface, src/canopen/sim/ the device simulator
                   engine (simulated devices, value sources, expressions, CiA 402 drive model, faults,
                   scenarios, the machine model), used by the plugin and canworks-sim; src/bridge/
                   canworks-bridge, the Modbus TCP bridge (Modbus server, byte image, bridge
                   registers, the host that runs the shared engine without OpenPLC)
schema/            the config contract (JSON Schema 2020-12): canworks.v1.schema.json (one network),
                   canworks.v2.schema.json (several networks, slave networks, the gateway), and
                   canworks-sim.v1/v2.schema.json for the simulation file (v2: a section per network),
                   canworks-sim-machine.v1.schema.json for the machine file
examples/          virtual-plant/: the fully virtual example project of docs/tour.md (four simulated
                   networks, a demo program, a simulation file with test scenarios); gantry-cell/: a
                   simulated XYZ gantry with a pick-and-place program (docs/simulator.md); j1939/: a J1939
                   ECU config and its DBC file (docs/j1939.md); raw-can/: a plain CAN network with
                   its DBC file and simulated devices (docs/raw-can.md); modbus-bridge/: a bridge
                   config with simulated devices (docs/modbus-bridge.md)
config/            example configurations: config/pingpong/ (the ping-pong slave),
                   config/rtd-sensor/ (a simulated 8-channel RTD module, CiA 404), each with
                   an example simulation.json, config/two-networks/ (two ping-pong networks on
                   vcan0 and vcan1),
                   config/cia402-drive/ (a made-up CiA 402 drive as a PLCopen axis, with a demo program),
                   config/slave/ (OpenPLC as slave node 10, its EDS description and a demo program),
                   config/gateway/ (the ping-pong node on a field network, OpenPLC as a gateway above it)
tools/             canopen_check.cpp: validates a config and its EDS files without starting the PLC;
                   tools/sim/: canworks-sim, the standalone device simulator for the runtime host
tools/deploy/      the PC tools (Python, one package): canworks-deploy, canworks-config
                   (the configurator), canworks-diag (online diagnostics, parameters, trace),
                   canworks-j1939-sim (the J1939 ECU simulator)
docker/bridge/     the canworks-bridge image (docs/modbus-bridge.md)
docker/local-runtime/ the local simulator runtime image (stock runtime + plugin, forced simulation) and
                   the pinned upstream runtime version
tools/editor-hook/ the runtime-side hook that keeps CANopen on with the editor's Build and upload
library/           the canworks editor library (SDO, CAN frame and CiA 402 blocks, ST helpers): generate.py writes the
                   block sources, build.sh builds the .stlib the deploy tool carries
test/unit/         unit tests: config validation, EDS checks, dcfgen, process image
test/can_raw/       raw CAN tests: config messages, the frame blocks' interface, signal packing, ST helpers
test/j1939_unit/   J1939 unit tests: NAME, signals, address claim, the engine on a fake socket
test/j1939/        the plugin's J1939 ECU against canworks-j1939-sim on vcan0, and two simulators
test/sim/          master against Lely slaves and simulated devices on an in-process virtual CAN bus
test/slave/        the plugin's master against its own slave and gateway on virtual buses, and
                   run.sh for a master on vcan0 and the slave on vcan1 joined by cangw, and
                   simulated.sh for both on one simulated bus (a ctest)
test/sim_unit/     simulator unit tests: expressions (shared corpus), sources, file loader, drive model, machine model
test/drive/        a simulated CiA 402 drive (Lely slave) for the virtual bus
test/cia402/       ST tests of the CiA 402 axis glue with STruC++ (run.sh) and its host for sim_tests
test/pingpong/     the Lely tutorial ping-pong slave and run.sh for vcan0
test/sensor/       sensor_slave (a measuring device from any EDS) and run.sh for vcan0
test/fixed/        a fixed-mapping I/O module against the plugin on vcan0
test/lss/          LSS node ID assignment to a slave without a node ID on vcan0
test/params/       device parameter backup, compare and restore on vcan0
test/commissioning/ writing a configuration to one device from the PC on vcan0
test/localbus/     the PC tools straight on a SocketCAN interface (no runtime) on vcan0
test/simulator/    canworks-sim against the plugin on vcan0 and vcan1
test/trace/        bus trace recording, filters and export formats on vcan0
test/rawframes/    raw frames sent by hand (guards, cyclic jobs), raw messages and replay on vcan0 and the simulated bus
test/bus/          the bus state byte while vcan0 goes down and up
test/networks/     two networks on vcan0 and vcan1, one of them losing its node
test/slcan/        the slcan adapter against a fake CANable on a pseudo-terminal, bridged to vcan1
test/bridge/       the Modbus server and bridge registers, canworks-bridge against simulated devices,
                   config upload and install-bridge.sh with a stub systemctl
test/plc_sdo/      the SDO blocks compiled as the editor does, finding the real plugin in-process
test/host/         canopen_host: loads the plugin .so with a stand-in PLC scan; plugin lifecycle tests
test/browser/      run.py: the configurator in Chromium against canopen_host on the simulated bus
test/link/         link_check: the SocketCAN link setup on a real interface
test/dump/         canopen_check --dump-writes against a checked-in list (DCF export parity)
test/common/       helpers shared by the C++ tests (checks, a fake runtime)
test/fixtures/     config and EDS fixtures shared by the plugin's and the deploy tool's tests
                   (test/fixtures/config/bad/: configs both must refuse, the parity test's corpus)
                   (test/fixtures/eds/drives/: two made-up CiA 402 drives)
test/stock/        install-stock.sh, the editor hook and the upstream runtime's upload rules, end to end
test/docker/       install-stock.sh in Docker mode and the runtime spec edits
test/local-runtime/ canworks-sim-runtime against the image with a compiled PLC program (run.sh)
test/virtual-example/ the virtual example on the image: checks, exports, every node up, test scenarios
test/pc-tools/     the release tag check; test/ci/: the CI change classification and areas
scripts/           dev-setup.sh (Lely, dcfgen, vcan0), build-lely.sh, install-stock.sh, install-bridge.sh,
                   fetch-strucpp.sh (the editor's ST compiler, for the CiA 402 tests)
docs/              tour.md (the guided tour of the virtual example), config.md (the config format), cia402.md, configurator.md, deploy.md, diagnostics.md,
                   frame-inspector.md, gateway.md, install-pc.md, install-stock.md, j1939.md, local-runtime.md, modbus-bridge.md, network-docs.md, plc-sdo.md, raw-can.md, simulator.md, slave.md,
                   trace.md, development.md (this page)
openspec/          specs (openspec/specs/) and changes, done ones under openspec/changes/archive/
```
