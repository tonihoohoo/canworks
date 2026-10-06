# openplc-canopen

> **Experimental.** All code, tests and documentation in this repository were written by Claude (Anthropic's AI model), directed and tested by a person. Treat everything here as experimental: it has run on a test bench, not in production, and comes with no warranty (see [LICENSE](LICENSE)). Do not use it to control machinery where a fault could hurt people or damage equipment.

A CANopen master plugin for the [OpenPLC Runtime v4](https://github.com/Autonomy-Logic/openplc-runtime), built on [Lely CANopen](https://gitlab.com/lely_industries/lely-core) over Linux SocketCAN.

The plugin reads a JSON file that lists the slave nodes, their EDS files and PDO entries, and binds each PDO entry to an explicit PLC address (`%IX`, `%IB`, `%IW`, `%ID`, `%IL` and the `%Q` equivalents). At every PLC start it validates the file against the EDS files, generates the device configuration with Lely's `dcfgen`, boots and configures every slave over SDO, and exchanges PDOs with the PLC image once per scan. A slave that is missing or drops off the bus never stops the PLC; its status bit goes FALSE and the master keeps trying to bring it back.

## On the PLC

The plugin's behaviour is set in the config file; [docs/config.md](docs/config.md) describes each field.

- **Adapters:** any SocketCAN interface (CAN HAT, candleLight/gs_usb, PEAK, vcan), with bit rate and link set up by the plugin, and serial-line `slcan` adapters such as a CANable with stock firmware, driven directly without `slcand`. A CANable that is unplugged and plugged back in is picked up again.
- **PDOs:** mapping from the config, or the device's own fixed or default mapping for devices whose mapping cannot be written; transmission type, inhibit time, event timer and SYNC start value, defaulting to the EDS's own values.
- **SYNC:** from a timer, from the PLC cycle (one SYNC every N scans, so synchronous PDOs line up with the program's scan), or none for event-driven PDOs only; SYNC count, interval and late PDOs show in the diagnostics.
- **Node bring-up:** startup SDO writes, identity check (0x1018), mandatory nodes, heartbeat or node guarding, program download, a configurable SDO timeout for boot and configuration, and an opt-in configuration check (0x1020) that skips an unchanged download. Saving to the device's non-volatile memory (0x1010) only happens when a node asks for it.
- **LSS node ID assignment:** devices without DIP switches get their node ID over the bus from their serial number at every start and after a device is replaced; storing it on the device is opt-in.
- **EDS checks:** every EDS goes through Lely's CiA 306 lint at load, and every PDO entry and SDO is checked against the EDS for type and access before anything is sent.
- **Status to the PLC:** a status bit and a state byte per node, the bus state and error counters, and the last EMCY code and error register per node.
- **From the program:** SDO variables (read and write node objects while running), NMT commands per node, and SDO function blocks (`CO_SDO_READ`, `CO_SDO_WRITE`, ... in the `openplc_canopen` editor library) that read or write any object of any node when the program decides, including REAL, strings and byte blocks ([docs/plc-sdo.md](docs/plc-sdo.md)).
- **CiA 402 drives as PLCopen axes:** a node marked as an axis is driven with the editor's built-in motion blocks (`MC_Power`, `MC_MoveAbsolute`, `MC_MoveVelocity`, `MC_Home`, ...) in profile position, profile velocity and homing mode; the generated program holds the glue ([docs/cia402.md](docs/cia402.md)).
- **Everything `dcfgen` can set:** SYNC, heartbeat, error behaviour and the other master and slave options of Lely's dcf-tools, plus a TIME producer that sends the runtime host's clock (UTC).
- **Online diagnostics** (opt-in, token protected): a TCP channel for the PC tools below. Nothing a client does touches the PLC scan.
- **Simulated devices** ([docs/simulator.md](docs/simulator.md)): any node, or the whole network, can be simulated from its EDS, so a project and its PLC program run without the real devices or any CAN hardware. Simulated devices boot, answer SDO, exchange PDOs, send heartbeats and EMCY and store parameters as their EDS describes; their values can follow waveforms, formulas across devices, recorded CSV data, a CiA 401 loopback, a CiA 404 slow movement or a CiA 402 drive model; faults (EMCY, lost heartbeat, power loss, SDO aborts and delays, wrong identity, ...) come on command or from timed scenarios that also test the program's reaction. Two switches in the config pick what is simulated: the network (`adapter.simulate`) and each node (`simulate`), in any mix with real devices.

## On the engineering PC

Three commands in one package, for Windows, macOS and Linux. They install with uv without a Python on the PC: [docs/install-pc.md](docs/install-pc.md).

- **`openplc-canopen-config`**, a configurator in a local web page ([docs/configurator.md](docs/configurator.md)): add nodes from their EDS, map PDO entries to PLC addresses, startup SDOs and SDO variables, with every address checked against the editor project. It writes the project's `canopen/` folder, exports DCF and DBC files, and creates a new editor project with the I/O already declared. Its **Online** view shows the live network: node and bus state, EMCY history, SDO read and write, NMT, a bus scan, LSS commissioning, an object dictionary browser with watch, and device parameter backup, compare and restore. Its **Trace** view records the bus with CANopen decoding, graphs and triggers ([docs/trace.md](docs/trace.md)).
- **`openplc-canopen-deploy`** ([docs/deploy.md](docs/deploy.md)): adds the config to an editor build and uploads it to the runtime, checks a config without a runtime, puts the config into an editor project, creates a new editor project from a config (`--new-project`, with `--sdo-blocks` to enable the SDO function blocks), writes or installs the `openplc_canopen` editor library (`library`), and exports DCF (`--export-dcf`) and DBC (`--export-dbc`) files.
- **`openplc-canopen-diag`** ([docs/diagnostics.md](docs/diagnostics.md)): the online functions from a terminal, including `backup`, `compare`, `restore` and `store` of device parameters (a CiA 306 DCF, so a replaced device gets its settings back), LSS commands, `trace` with export to pcapng, candump, ASC, BLF, TRC or CSV, and `sim` to drive simulated devices and run scenarios as tests.

The configurator's **Simulated** switches and **Simulation** view set up and drive simulated devices. On the runtime host, `openplc-canopen-sim` runs simulated devices on a SocketCAN interface for any CANopen master, with a `test` mode that runs scenarios and writes a JUnit report ([docs/simulator.md](docs/simulator.md#openplc-canopen-sim)).

## Scope

- Master role only. The slave role is out of scope for now.
- Linux with SocketCAN (`can0`, `vcan0`, ...; serial `slcan` adapters need Linux 6.0 or later), OpenPLC v4 native installs (`install.sh --native`) and upstream's managed Docker install ([docs/install-stock.md](docs/install-stock.md#docker-installs)).
- Stock runtime only (unmodified upstream): `scripts/install-stock.sh` installs the plugin and an editor hook next to the runtime. A program then gets its CANopen config either from a `canopen/` folder in the editor project, carried by the editor's own **Build and upload**, or from `openplc-canopen-deploy`, which uploads an editor build together with the config. Either way the runtime switches the plugin on. See [docs/install-stock.md](docs/install-stock.md) and [docs/deploy.md](docs/deploy.md).

## Layout

```
CMakeLists.txt     builds libcanopen_plugin.so; the runtime's install.sh builds it from here
plugin/            native plugin source
plugin/sim/        the device simulator engine (simulated devices, value sources, expressions,
                   CiA 402 drive model, faults, scenarios), used by the plugin and openplc-canopen-sim
schema/            the config contract: canopen.v1.schema.json, and canopen-sim.v1.schema.json for
                   the simulation file (JSON Schema 2020-12)
config/            example configurations: config/pingpong/ (the ping-pong slave),
                   config/rtd-sensor/ (a simulated 8-channel RTD module, CiA 404), each with
                   an example simulation.json,
                   config/cia402-drive/ (a made-up CiA 402 drive as a PLCopen axis, with a demo program)
tools/             canopen_check: validates a config and its EDS files without starting the PLC
tools/deploy/      the PC tools (Python, one package): openplc-canopen-deploy, openplc-canopen-config
                   (the configurator), openplc-canopen-diag (online diagnostics, parameters, trace)
tools/editor-hook/ the runtime-side hook that keeps CANopen on with the editor's Build and upload
library/           the openplc_canopen editor library (SDO function blocks): generate.py writes the
                   block sources, build.sh builds the .stlib the deploy tool carries
test/unit/         unit tests: config validation, EDS checks, dcfgen, process image
test/sim/          master against Lely slaves and simulated devices on an in-process virtual CAN bus
test/sim_unit/     simulator unit tests: expressions (shared corpus), sources, file loader, drive model
test/drive/        a simulated CiA 402 drive (Lely slave) for the virtual bus
test/cia402/       ST tests of the CiA 402 axis glue with STruC++ (run.sh) and its host for sim_tests
test/pingpong/     the Lely tutorial ping-pong slave and run.sh for vcan0
test/sensor/       sensor_slave (a measuring device from any EDS) and run.sh for vcan0
test/fixed/        a fixed-mapping I/O module against the plugin on vcan0
test/lss/          LSS node ID assignment to a slave without a node ID on vcan0
test/params/       device parameter backup, compare and restore on vcan0
test/trace/        bus trace recording, filters and export formats on vcan0
test/bus/          the bus state byte while vcan0 goes down and up
test/slcan/        the slcan adapter against a fake CANable on a pseudo-terminal, bridged to vcan1
test/plc_sdo/      the SDO blocks compiled as the editor does, finding the real plugin in-process
test/host/         canopen_host: loads the plugin .so with a stand-in PLC scan; plugin lifecycle tests
test/link/         link_check: the SocketCAN link setup on a real interface
test/dump/         canopen_check --dump-writes against a checked-in list (DCF export parity)
test/fixtures/     config and EDS fixtures shared by the plugin's and the deploy tool's tests
                   (test/fixtures/eds/drives/: two made-up CiA 402 drives)
test/stock/        install-stock.sh, the editor hook and the upstream runtime's upload rules, end to end
test/docker/       install-stock.sh in Docker mode and the runtime spec edits
test/pc-tools/     the release tag check; test/ci/: the CI change classification
scripts/           dev-setup.sh (Lely, dcfgen, vcan0), build-lely.sh, install-stock.sh,
                   fetch-strucpp.sh (the editor's ST compiler, for the CiA 402 tests)
docs/              config.md (the config format), cia402.md, configurator.md, deploy.md, diagnostics.md,
                   install-pc.md, install-stock.md, plc-sdo.md, simulator.md,
                   trace.md
openspec/          specs (openspec/specs/) and changes, done ones under openspec/changes/archive/
```

## Development build

```sh
sudo scripts/dev-setup.sh                       # Lely into /opt/openplc-canopen, dcfgen, vcan0
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
test/trace/run.sh                               # bus trace and its export formats
test/bus/run.sh                                 # bus state byte with vcan0 taken down and up
test/slcan/run.sh                               # slcan adapter (needs the slcan module and vcan1)
```

The CiA 402 tests use the editor's ST compiler, STruC++ (needs Node 22):

```sh
test/cia402/run.sh                              # ST tests of the generated axis glue against a drive model
cmake -B build -DOPENPLC_ROOT=../openplc-runtime -DSTRUCPP=$(scripts/fetch-strucpp.sh)
cmake --build build -j && build/test/sim_tests --exact sim_cia402_demo   # the demo program on the virtual bus
```

CI (`.github/workflows/ci.yml`) runs all of these on every pull request and push to `main` that changes code, the deploy tool and page tests spread over several runners; its last job, `ci-ok`, is the one check a branch ruleset needs. A change that touches only documentation or specs runs just the OpenSpec validation; the build and test jobs are skipped.

### Integration tests (by hand, weekly, or locally)

Two end-to-end installs test against things outside this repository and mostly catch upstream drift, so they are not in the pull request run. `.github/workflows/integration.yml` runs them weekly, on "Run workflow", and on pull requests that change the install routes (`install-stock.sh`, `test/stock/`, `test/docker/`, the editor hook). On a Linux machine with the development build above:

```sh
pip install jsonschema python-dotenv
test/stock/run.sh ../openplc-runtime build      # stock runtime install, upload rules and editor hook (upstream development)
sudo test/docker/run.sh --image ghcr.io/autonomy-logic/openplc-runtime:latest   # Docker route; needs Docker and vcan0
```

Use a development machine, not one running your PLC: the stock test installs into `/opt/openplc-canopen` and the runtime checkout, and the Docker test starts runtime containers on the host network.

### PC tools on Windows and macOS

`.github/workflows/pc-tools.yml` installs the PC tools with uv on Windows and macOS on version bumps on `main` (the release waits for it), on `deploy-v<version>` tags and on "Run workflow" (start it on a pull request's branch when a change needs those systems checked). On your own PC, from a checkout (bash; Git Bash on Windows):

```sh
uv build --wheel --out-dir dist tools/deploy && uv tool install --force --python 3.12 dist/*.whl
uv run --no-project --python 3.12 --with jsonschema --with cantools python -m unittest discover -s tools/deploy/tests -t tools/deploy
uv run --no-project --python 3.12 python test/pc-tools/smoke.py "$(sed -n 's/^version = "\(.*\)"/\1/p' tools/deploy/pyproject.toml)"
```

A `deploy-v<version>` release publishes the tools as a wheel on GitHub (`release-deploy.yml`).

## Installing it

`scripts/install-stock.sh` builds the plugin against the runtime checkout's headers, installs it to `/opt/openplc-canopen/lib/` and registers it in the runtime's `plugins.conf`; uploads then switch it on and off. See [docs/install-stock.md](docs/install-stock.md). Without a config file the plugin logs a warning and stays inactive; a config with errors is logged and also leaves it inactive. The PLC runs normally in both cases. See [docs/config.md](docs/config.md) for the configuration format.

## Specs

The behaviour is specified with [OpenSpec](https://github.com/Fission-AI/OpenSpec) in `openspec/specs/`, one folder per capability: master bring-up, node supervision, PDO I/O, SDO variables, bus diagnostics, online diagnostics, device parameters, bus trace, the slcan adapter, the config contract, the stock install, the Docker install, the deploy tool, the editor upload, the editor project, the configurator, DCF export, DBC export, the PC install and CI. New work starts as a change under `openspec/changes/` and is archived into the specs once it is merged.

## License

Apache License 2.0, see [LICENSE](LICENSE). Bundled third-party code keeps its own license: Lely's `dcf` package in `tools/deploy/openplc_canopen_deploy/_lely_dcf/` (Apache 2.0, with its NOTICE) and uPlot in `tools/deploy/openplc_canopen_deploy/configurator/static/uplot/` (MIT). The ping-pong slave's EDS follows the [Lely CANopen C++ tutorial](https://opensource.lely.com/canopen/docs/cpp-tutorial/). Every other EDS file in this repository describes a made-up device written for the tests.
