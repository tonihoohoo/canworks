# Development

Building canworks-bridge and the CAN engine, running the tests, and how CI is set up. For using the toolkit, start at the [README](../README.md).

## Build and test

```sh
sudo scripts/dev-setup.sh                       # Lely into /opt/canworks, dcfgen, vcan0
cmake -B build
cmake --build build -j
ctest --test-dir build --output-on-failure -j4  # unit and virtual-bus tests (one test per sim case)
build/test/sim_tests --exact sim_sdo_variables  # one sim case on its own
build/test/sim_unit_tests                       # simulator unit tests
python3 -m unittest discover -s tools/deploy/tests -t tools/deploy   # deploy tool and configurator (needs jsonschema;
                                                                     # the page tests also need playwright)
python3 .github/scripts/test_shard.py --shard 1/1 --start tools/deploy/tests --top tools/deploy  # the same, one worker per CPU
python3 -m unittest discover -s test/ci -t test/ci  # CI rules: no runtime header, change classification
test/pingpong/run.sh                            # the engine against the ping-pong slave on vcan0
test/sensor/run.sh                              # ... against the simulated RTD module
test/fixed/run.sh                               # ... against a device with a fixed PDO mapping
test/lss/run.sh                                 # LSS node ID assignment
test/params/run.sh                              # device parameter backup, compare and restore
test/commissioning/run.sh                       # write a configuration to one device, PDO test
test/localbus/run.sh                            # the PC tools on vcan0 without a runtime
test/simulator/run.sh                           # canworks-canopen-sim against the engine (needs vcan1)
test/trace/run.sh                               # bus trace and its export formats
test/rawframes/run.sh                           # raw frames sent by hand, raw messages, replay, removed bit rate detection ops
test/bus/run.sh                                 # bus state byte with vcan0 taken down and up
test/slcan/run.sh                               # slcan adapter (needs the slcan module and vcan1)
test/j1939/run.sh                               # the J1939 ECU against the J1939 simulator (needs can-j1939)
test/plc_modbus/run.sh                          # the library's blocks and the generated OpenPLC programs, compiled with STruC++ (needs Node 22)
```

`-DCANWORKS_WITH_CANOPEN=OFF` or `-DCANWORKS_WITH_J1939=OFF` builds one protocol only; a J1939-only build needs no Lely. The build needs no OpenPLC runtime sources: `test/ci/test_no_plugin.py` fails when an engine or tool source includes a runtime header or a build file asks for one.

The configurator and the bridge refuse the same configs: `tools/deploy/tests/test_parity.py` runs every entry of `test/fixtures/config/bad/` (a config, and optionally its simulation file) through the deploy tool's checks and through `build/canopen_check --no-dcfgen`, and fails naming the entry when one of them accepts it. An entry's optional `message` is a text both refusals must contain; `config_text` in place of `config` gives the file as text, for what a parsed config cannot hold (a repeated key); `eds_files` (`{"name.eds": "text"}`) adds EDS files next to `test/fixtures/eds`, for EDS-level entries. It skips without the build unless `CANWORKS_REQUIRE_PARITY=1`. In CI the tools job keeps the classes that need `build/canopen_check` (`test_parity`, `test_dcfexport.Parity`, `test_project.IntoProject`) on one shard with `test_shard.py --together`, and only that shard builds it and sets `CANWORKS_REQUIRE_PARITY=1`. A new test class that runs the build joins that `--together` pattern in `.github/workflows/ci.yml`. Both test jobs split by recorded class times (`.github/ci/tool-test-times.json`, `.github/ci/page-test-times.json`); refresh them from the shards' "class times:" lines when the shards drift apart. On each runner `test_shard.py --jobs auto` runs the shard in one worker process per CPU (the runners have 4), each with its own temporary folder and its number in `CANWORKS_TEST_WORKER`; each worker's log is printed whole when it ends, and the shard fails when any worker fails or dies. The tests mostly wait (the browser, servers, timers), so 4 workers take about a third of the time. A test that opens a machine-wide resource (an adapter lock, a fixed port, a named file outside the temporary folder) must give it a name of its own, for example with the process ID. `--split-over 30` cuts a class recorded as longer than 30 s into parts of whole test methods that can run on different workers or runners; each part runs the class's `setUpClass` again, and the `--together` classes are never cut. `--serial REGEX` runs matching classes alone after the workers, for a test that proves too timing-sensitive on a busy runner. A Playwright test file is named `test_*_page.py`: the page jobs select that pattern (plus `test_configurator_layout.py`) and the tools jobs leave it out. **A pull request that makes the bridge refuse something new adds a corpus file for it**, and the configurator's check that refuses it too.

Python versions: the deploy tool also runs on the Linux device (EDS lint, the remote link), on Python 3.11 there, so the package needs 3.11 or newer and may not use anything newer. CI runs the jobs that test code the device runs (engine, vcan, tools) on 3.11 and the PC-only jobs (configurator pages, browser run, local runtime, PC tools on Windows and macOS) on 3.14, the one-line installer's Python.

The OpenPLC connection end to end, the pinned upstream runtime's own Modbus master against `canworks-bridge` (needs the runtime's `pymodbus`):

```sh
git clone -b $(cat docker/local-runtime/runtime-version) https://github.com/Autonomy-Logic/openplc-runtime ../openplc-runtime
test/openplc_modbus/run.py --bridge build/bin/canworks-bridge --runtime ../openplc-runtime
```

CI (`.github/workflows/ci.yml`) runs all of these on every pull request and push to `main` that changes code, the deploy tool, page and vcan tests spread over several runners (a new vcan test goes into the vcan group with the least test time, listed above the job; package installs go through `.github/scripts/apt_install.py`, which skips installed packages and retries a stalled mirror); its last job, `ci-ok`, is the one check a branch ruleset needs. A change that touches only documentation or specs runs just the OpenSpec validation; the build and test jobs are skipped. The vcan steps of one protocol are skipped when a change touches only the other protocol's files (`.github/ci/areas.txt`). The configurator page tests run only when a change touches what the configurator uses: the PC tools package, the schemas, the shipped examples, the deploy tool tests or the CI files (`.github/ci/ui-paths.txt`); a push to `main` always runs them. When the PLCopen export, the copy programs or the library change (`.github/ci/plcopen-paths.txt`), the tools job also imports the generic PLCopen export with the whole library and every mailbox into a pinned truST release and builds it (`test/plcopen/fetch-trust.sh`, `tests.test_plcopen.TrustImport`): truST serves only as a strict IEC compiler there, not as a target.

## Browser coverage

Three kinds of test check the configurator in ways the small page-test fixtures do not:

- **Example sweep.** `tools/deploy/tests/test_configurator_examples_page.py` opens `examples/virtual-plant` and `j1939` and visits every view of every network at 1280 px. It fails on a clipped field or button, a table or view that scrolls sideways, a console or page error, an HTTP error answer, or a "decoding without the config's PDOs" note, and names the example, network and view of each. It runs in the configurator page jobs; a new page-test class goes into `.github/ci/page-test-times.json` so the shards stay balanced.
- **Validation parity.** A corpus of bad configs under `test/fixtures/config/bad/` goes through both the configurator's check and the bridge's loader (`canopen_check`) in the tools job; both must refuse each one.
- **Browser run against the real bridge.** `test/browser/run.py`, below.

## The bridge and the configurator without a CAN interface

With `CANWORKS_FORCE_SIMULATE=1` every network of the config runs on the bridge's simulated bus with its simulated devices, so no vcan, Docker or CAN adapter is needed (a container works). Build the bridge, copy an example, and start it and the configurator:

```sh
cmake -B build
cmake --build build -j --target canworks-bridge
cp -r examples/virtual-plant /tmp/vp
CANWORKS_FORCE_SIMULATE=1 build/bin/canworks-bridge --config /tmp/vp/canworks/canworks.json > /tmp/vp-bridge.log 2>&1 &
PYTHONPATH=tools/deploy python3 -m canworks.configurator.server --foreground /tmp/vp   # in this terminal; Ctrl-C stops it
```

The diagnostics channel listens on 127.0.0.1 at the config's `diagnostics.port` (7531 by default; set another port in the copy to run several bridges). In the configurator, Online → host `127.0.0.1:7531`, token `virtual-plant-demo` (the example's demo token). The Simulation view then drives the simulated devices: faults, power off and on, TPDO stop. `PYTHONPATH=tools/deploy python3 -m canworks.diag --runtime 127.0.0.1 --token virtual-plant-demo status` (or `canworks-diag` when the PC tools are installed) reads the same channel from the command line. `build/test/canopen_host` runs the same engine with a stand-in program instead of the Modbus server, for the vcan scripts.

## Browser run against the real bridge

`test/browser/run.py` does the setup above on a temporary copy of `examples/virtual-plant` (on a free diagnostics port) and drives the configurator in Chromium through these steps:

1. Connect.
2. Nodes 5, 6 and 7 OPERATIONAL in the node table.
3. An SDO read and write on node 6.
4. A heartbeat stop on node 6 seen online, then cleared.
5. A TPDO stop on node 5 raising its timeout.
6. A trace started, stopped and downloaded.
7. A power off and on of node 5, after which the status still answers.
8. The bridge stopping on SIGTERM.

A failed step is reported with a screenshot and the run goes on. Locally (needs Playwright: `pip install jsonschema playwright`, and a Chromium from `python -m playwright install chromium` or named by `CANWORKS_CHROMIUM`):

```sh
cmake --build build -j --target canworks-bridge
test/browser/run.py --out /tmp/browser-run      # logs, screenshots and the downloaded trace in --out
test/browser/run.py --headed                    # watch it
```

`.github/workflows/browser.yml` runs it weekly, on "Run workflow", and on pull requests that change the configurator's online or trace code, the diagnostics, the engine's bus, network and diagnostics sources, or the simulator. It is a workflow of its own, so CI's time and `ci-ok` are unaffected; on a failure it keeps the logs and screenshots as the run's `browser-run` artifact.

## Local runtime image

`.github/workflows/local-runtime.yml` builds the bridge image (`docker/bridge/Dockerfile`) and runs `canworks-local-runtime` with it and the pinned upstream runtime image (`docker/local-runtime/runtime-version`), with a PLC program compiled by STruC++ that reaches the bridge through the runtime's own Modbus master; then it deploys the virtual example and runs its test scenarios (`test/virtual-example/run.sh`). It runs on pull requests that change what goes into the bridge image, the command or the example, weekly and on "Run workflow"; an arm64 runner builds the arm64 image. Locally (needs Docker and Node 22):

```sh
docker build -f docker/bridge/Dockerfile --build-arg TOOLS_VERSION=dev -t canworks-bridge:dev .
test/local-runtime/run.sh --image canworks-bridge:dev --strucpp "$(scripts/fetch-strucpp.sh)"
test/virtual-example/run.sh --image canworks-bridge:dev --strucpp "$(scripts/fetch-strucpp.sh)"
```

`.github/workflows/runtime-watch.yml` compares upstream's newest runtime and editor releases with the pinned ones, and the files the OpenPLC connection follows, once a month; when upstream is newer it keeps one open `runtime-update` issue.

## Repository layout

```
CMakeLists.txt     builds canworks-bridge, canworks-canopen-sim and the tests; no OpenPLC sources needed
plugin/            the native engine: src/can/ the shared CAN core (config, adapters, trace,
                   raw frames, diagnostics server, byte image), src/canopen/ the
                   CANopen master, slave and gateway on Lely, src/j1939/ the J1939 ECU (address claim,
                   kernel sockets, signals), src/can/raw/ raw CAN messages, plain networks
                   and the frame blocks' interface, src/canopen/sim/ the device simulator
                   engine (simulated devices, value sources, expressions, faults,
                   scenarios), used by the bridge and canworks-canopen-sim; src/bridge/
                   canworks-bridge, the Modbus TCP bridge (Modbus server, bridge
                   registers, the host that runs the engine)
schema/            the config contract (JSON Schema 2020-12): canworks.v1.schema.json (one network),
                   canworks.v2.schema.json (several networks, slave networks, the gateway), and
                   canworks-sim.v1/v2.schema.json for the simulation file (v2: a section per network)
examples/          virtual-plant/: the fully virtual example project of docs/tour.md (four simulated
                   networks, an OpenPLC Editor project with a demo program, a simulation file with
                   test scenarios); openplc-modbus/: a small config with an OpenPLC connection; j1939/: a J1939
                   ECU config and its DBC file (docs/j1939.md); raw-can/: a plain CAN network with
                   its DBC file and simulated devices (docs/raw-can.md); modbus-bridge/: a bridge
                   config with simulated devices (docs/modbus-bridge.md); pdo-link/: two nodes
                   joined by a PDO link
config/            example configurations: config/pingpong/ (the ping-pong slave),
                   config/rtd-sensor/ (a simulated 8-channel RTD module, CiA 404), each with
                   an example simulation.json, config/two-networks/ (two ping-pong networks on
                   vcan0 and vcan1),
                   config/slave/ (the bridge as slave node 10 and its EDS description),
                   config/gateway/ (the ping-pong node on a field network, the bridge as a gateway above it)
tools/             canopen_check.cpp: validates a config and its EDS files without starting a bridge;
                   tools/sim/: canworks-canopen-sim, the CANopen simulator for a Linux device
tools/deploy/      the PC tools (Python, one package): canworks-deploy, canworks-config
                   (the configurator), canworks-diag (online diagnostics, parameters, trace),
                   canworks-j1939-sim (the J1939 ECU simulator)
docker/bridge/     the canworks-bridge image (docs/modbus-bridge.md)
docker/local-runtime/ the pinned upstream runtime and bootloader releases (the local runtime
                   and the OpenPLC tests use them)
library/           the canworks function block library (docs/plc-library.md): modbus/ the blocks
                   over the bridge, canworks/ the ST helpers; build.sh builds the .stlib the deploy
                   tool carries
test/unit/         unit tests: config validation, EDS checks, dcfgen, byte image
test/can_raw/       raw CAN tests: config messages, the frame service, signal packing, ST helpers
test/j1939_unit/   J1939 unit tests: NAME, signals, address claim, the engine on a fake socket
test/j1939/        the J1939 ECU against canworks-j1939-sim on vcan0, and two simulators
test/sim/          master against Lely slaves and simulated devices on an in-process virtual CAN bus
test/slave/        the master against canworks' own slave and gateway on virtual buses, and
                   run.sh for a master on vcan0 and the slave on vcan1 joined by cangw, and
                   simulated.sh for both on one simulated bus (a ctest)
test/sim_unit/     simulator unit tests: expressions (shared corpus), sources, file loader, control
test/pingpong/     the Lely tutorial ping-pong slave and run.sh for vcan0
test/sensor/       sensor_slave (a measuring device from any EDS) and run.sh for vcan0
test/fixed/        a fixed-mapping I/O module against the engine on vcan0
test/lss/          LSS node ID assignment to a slave without a node ID on vcan0
test/params/       device parameter backup, compare and restore on vcan0
test/commissioning/ writing a configuration to one device from the PC on vcan0
test/localbus/     the PC tools straight on a SocketCAN interface (no runtime) on vcan0
test/simulator/    canworks-canopen-sim against the engine on vcan0 and vcan1
test/trace/        bus trace recording, filters and export formats on vcan0
test/rawframes/    raw frames sent by hand (guards, cyclic jobs), raw messages and replay on vcan0 and the simulated bus
test/bus/          the bus state byte while vcan0 goes down and up
test/networks/     two networks on vcan0 and vcan1, one of them losing its node
test/slcan/        the slcan adapter against a fake CANable on a pseudo-terminal, bridged to vcan1
test/bridge/       the Modbus server and bridge registers, canworks-bridge against simulated devices,
                   config upload and install-bridge.sh with a stub systemctl
test/plc_modbus/   the library's blocks and the generated OpenPLC programs compiled with STruC++
test/openplc_modbus/ the pinned runtime's Modbus master against canworks-bridge, end to end
test/library/      the ST helpers against Python models
test/host/         canopen_host: the engine with a stand-in program over the byte image
test/browser/      run.py: the configurator in Chromium against canworks-bridge on the simulated bus
test/link/         link_check: the SocketCAN link setup on a real interface
test/dump/         canopen_check --dump-writes against a checked-in list (DCF export parity)
test/common/       helpers shared by the C++ tests (checks, a fake host over the byte image, bridge configs)
test/fixtures/     config and EDS fixtures shared by the engine's and the deploy tool's tests
                   (test/fixtures/config/bad/: configs both must refuse, the parity test's corpus)
                   (test/fixtures/eds/drives/: made-up CiA 402 drives for the notes and trace tests)
test/local-runtime/ canworks-local-runtime with the bridge image and a compiled PLC program (run.sh)
test/virtual-example/ the virtual example on the image: checks, exports, every node up, test scenarios
test/pc-tools/     the release tag check; test/ci/: the CI change classification, areas and the no-runtime-header rule
scripts/           dev-setup.sh (Lely, dcfgen, vcan0), build-lely.sh, install-bridge.sh/.ps1, install-link.sh,
                   install-pc.sh/.ps1 (the one-line installers, run from GitHub),
                   fetch-strucpp.sh (the editor's ST compiler, for the library and OpenPLC tests)
docs/              tour.md (the guided tour of the virtual example), config.md (the config format), configurator.md, deploy.md, diagnostics.md,
                   frame-inspector.md, gateway.md, install-pc.md, j1939.md, local-runtime.md, modbus-bridge.md, network-docs.md, plc-library.md, raw-can.md, simulator.md, slave.md,
                   trace.md, development.md (this page)
openspec/          specs (openspec/specs/) and changes, done ones under openspec/changes/archive/
```
