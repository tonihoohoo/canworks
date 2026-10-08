# openplc-canopen

> **Experimental.** All code, tests and documentation in this repository were written by Claude (Anthropic's AI model), directed and tested by a person. Treat everything here as experimental: it has run on a test bench, not in production, and comes with no warranty (see [LICENSE](LICENSE)). Do not use it to control machinery where a fault could hurt people or damage equipment.

A CANopen master (and slave) plugin for the [OpenPLC Runtime v4](https://github.com/Autonomy-Logic/openplc-runtime), built on [Lely CANopen](https://gitlab.com/lely_industries/lely-core) over Linux SocketCAN.

The plugin reads a JSON file that lists the slave nodes, their EDS files and PDO entries, and binds each PDO entry to an explicit PLC address (`%IX`, `%IB`, `%IW`, `%ID`, `%IL` and the `%Q` equivalents). At every PLC start it validates the file against the EDS files, generates the device configuration with Lely's `dcfgen`, boots and configures every slave over SDO, and exchanges PDOs with the PLC image once per scan. A slave that is missing or drops off the bus never stops the PLC; its status bit goes FALSE and the master keeps trying to bring it back.

**Try it without hardware:** [docs/tour.md](docs/tour.md) walks through [`examples/virtual-plant`](examples/virtual-plant/README.md), one editor project with four simulated networks that shows the features below working together on a PC, with only a container engine, the PC tools and the editor.

## On the PLC

The plugin's behaviour is set in the config file; [docs/config.md](docs/config.md) describes each field.

- **Several networks:** up to 8 CAN networks from one PLC, each on its own adapter with its own master, bit rate, SYNC and nodes (`schema_version` 2, [docs/config.md](docs/config.md#several-networks-schema_version-2)). A network that fails does not stop the others.
- **Adapters:** any SocketCAN interface (CAN HAT, candleLight/gs_usb, PEAK, vcan), with bit rate and link set up by the plugin, and serial-line `slcan` adapters such as a CANable with stock firmware, driven directly without `slcand`. A CANable that is unplugged and plugged back in is picked up again.
- **PDOs:** mapping from the config, or the device's own fixed or default mapping for devices whose mapping cannot be written; transmission type, inhibit time, event timer and SYNC start value, defaulting to the EDS's own values.
- **SYNC:** from a timer, from the PLC cycle (one SYNC every N scans, so synchronous PDOs line up with the program's scan), or none for event-driven PDOs only; SYNC count, interval and late PDOs show in the diagnostics.
- **Node bring-up:** startup SDO writes, identity check (0x1018), mandatory nodes, heartbeat or node guarding, program download, a configurable SDO timeout for boot and configuration, and an opt-in configuration check (0x1020) that skips an unchanged download. Saving to the device's non-volatile memory (0x1010) only happens when a node asks for it.
- **LSS node ID assignment:** devices without DIP switches get their node ID over the bus from their serial number at every start and after a device is replaced; storing it on the device is opt-in.
- **EDS checks:** every EDS goes through Lely's CiA 306 lint at load, and every PDO entry and SDO is checked against the EDS for type and access before anything is sent.
- **Status to the PLC:** a status bit and a state byte per node, the bus state and error counters, the last EMCY code and error register per node, and an optional receive timeout per input PDO with its own bit, for a PDO that stops coming while its node stays up ([docs/config.md](docs/config.md#receive-timeout)).
- **From the program:** SDO variables (read and write node objects while running), NMT commands per node, and SDO function blocks (`CO_SDO_READ`, `CO_SDO_WRITE`, ... in the `openplc_canopen` editor library) that read or write any object of any node on any network when the program decides, including REAL, strings and byte blocks ([docs/plc-sdo.md](docs/plc-sdo.md)).
- **CiA 402 drives as PLCopen axes:** a node marked as an axis is driven with the editor's built-in motion blocks (`MC_Power`, `MC_MoveAbsolute`, `MC_MoveVelocity`, `MC_Home`, ...) in profile position, profile velocity and homing mode, and in the cyclic synchronous modes (CSP, CSV, CST) with the `CO402_Cyclic*` blocks and SYNC from the PLC cycle; the generated program holds the glue ([docs/cia402.md](docs/cia402.md)).
- **Everything `dcfgen` can set:** SYNC, heartbeat, error behaviour and the other master and slave options of Lely's dcf-tools, plus a TIME producer that sends the runtime host's clock (UTC).
- **OpenPLC as a slave:** a network with `"role": "slave"` makes the PLC a node of a network another master runs, with the objects the master writes on `%I` locations and those it reads on `%Q`, the PDO mapping left to that master, store and restore, LSS, and the slave's own state and EMCY for the program ([docs/slave.md](docs/slave.md)). Its EDS is generated from a short object list and is the file the other master's tool imports. On the simulated bus, one config runs the plugin's own master against its own slave without any CAN hardware.
- **Gateway:** a slave network and master networks in one config, with routes that copy values between upper-network objects and field PDO entries in the plugin, without the PLC program, plus field node status, EMCY forwarding, behaviour on loss of the upper master and an SDO bridge ([docs/gateway.md](docs/gateway.md)).
- **Online diagnostics** (opt-in, encrypted with TLS; the token never crosses the network): a channel for the PC tools below. Nothing a client does touches the PLC scan.
- **Simulated devices** ([docs/simulator.md](docs/simulator.md)): any node, or the whole network, can be simulated from its EDS, so a project and its PLC program run without the real devices or any CAN hardware. Simulated devices boot, answer SDO, exchange PDOs, send heartbeats and EMCY and store parameters as their EDS describes; their values can follow waveforms, formulas across devices, recorded CSV data, a CiA 401 loopback, a CiA 404 slow movement or a CiA 402 drive model; faults (EMCY, lost heartbeat, power loss, SDO aborts and delays, wrong identity, ...) come on command or from timed scenarios that also test the program's reaction. Two switches in the config pick what is simulated: the network (`adapter.simulate`) and each node (`simulate`), in any mix with real devices.

## On the engineering PC

Four commands in one package, for Windows, macOS and Linux. They install with uv without a Python on the PC: [docs/install-pc.md](docs/install-pc.md).

They reach the bus through the runtime, or straight through a USB CAN adapter on the PC (slcan adapters such as a CANable on Windows, macOS and Linux, gs_usb/candleLight adapters on macOS, SocketCAN on Linux) with no runtime at all: scan, object dictionary, parameters, LSS, trace, writing a node's configuration to a device that keeps its own, a PDO test with SYNC from the PC and bit rate detection of a lone device, for commissioning devices on the bench or as a guest on a bus another master runs, read-only until changes are allowed ([docs/pc-adapter.md](docs/pc-adapter.md#commissioning-one-device)).

- **`openplc-canopen-config`**, a configurator in a local web page ([docs/configurator.md](docs/configurator.md)): add nodes from their EDS, map PDO entries to PLC addresses, startup SDOs and SDO variables, with every address checked against the editor project, and one tab per CAN network, each a master or a slave network, with the slave's EDS built and exported in the page and a gateway page for routes. It writes the project's `canopen/` folder, exports DCF and DBC files and an HTML documentation of the network, and creates a new editor project with the I/O already declared. Its **Online** view shows the live network: node and bus state, EMCY history, SDO read and write, NMT, a bus scan, LSS commissioning, an object dictionary browser with watch, device parameter backup, compare and restore, writing a configuration to a device from a config node or a DCF, restore defaults, a PDO test tab on a USB adapter, and bit rate detection on an unknown bus, also with a lone device on the bench; on a slave network, the plugin's own device, its PDO mappings and the gateway's status. Its **Trace** view records the bus with CANopen decoding, graphs and triggers, and sends single or cyclic frames by hand ([docs/trace.md](docs/trace.md)); its frame inspector and **Frame lab** explain every bit of a frame: meaning, identifier, data bits with their PLC addresses and the frame on the wire, plus SDO conversations, boot stories, SYNC cycles and an arbitration demo ([docs/frame-inspector.md](docs/frame-inspector.md)). **Commission a device** opens the online view on a USB adapter without any project, with a Steps panel, a commissioning log to save, and **Add to a config…** to carry the device into a config. The page works fully from the keyboard, has undo for every edit of the draft, puts the safe choice first in every dialog, and its browser tests audit every view for accessibility.
- **`openplc-canopen-deploy`** ([docs/deploy.md](docs/deploy.md)): adds the config to an editor build and uploads it to the runtime, checks a config without a runtime, puts the config into an editor project, creates a new editor project from a config (`--new-project`, with `--sdo-blocks` to enable the SDO function blocks), writes or installs the `openplc_canopen` editor library (`library`), generates a slave's EDS (`slave-eds`), exports DCF (`--export-dcf`) and DBC (`--export-dbc`) files, per network or for one with `--network`, and writes an HTML documentation of the networks (`--export-html`, [docs/network-docs.md](docs/network-docs.md)): topology, COB-ID map, bus load estimate, and per node its identity, PDO layouts, boot SDO writes and PLC addresses, in one offline, printable file.
- **`openplc-canopen-diag`** ([docs/diagnostics.md](docs/diagnostics.md)): the online functions from a terminal, including `backup`, `compare`, `restore` and `store` of device parameters (a CiA 306 DCF, so a replaced device gets its settings back), `configure` to write a node's configuration to a device with read-back and `--verify-only`, `restore-defaults`, `pdo-test` on a USB adapter, LSS commands, `send` for raw frames and `detect-bitrate` (both guarded, [docs/diagnostics.md](docs/diagnostics.md#raw-frames-and-bit-rate)), `--network` to pick one of several networks, `trace` with export to pcapng, candump, ASC, BLF, TRC or CSV, `sim` to drive simulated devices and run scenarios as tests, and `explain` to explain a frame bit by bit without a runtime; `--adapter` runs the same commands through a USB adapter on the PC, and `adapters` lists the adapters found.
- **`openplc-canopen-sim-runtime`** ([docs/local-runtime.md](docs/local-runtime.md)): try a project without any hardware. It runs the stock OpenPLC Runtime v4 with the CANopen plugin in a container on the PC (Docker Engine, Podman or Colima; no Docker Desktop needed; amd64 and arm64, so M-series Macs too), with every network simulated. The editor uploads to `localhost` and debugs the program there, and the other tools reach it as `--runtime local`. The editor's own OpenPLC Simulator cannot run runtime plugins, so this takes its place for CANopen projects.

The configurator's **Simulated** switches and **Simulation** view set up and drive simulated devices. On the runtime host, `openplc-canopen-sim` runs simulated devices on a SocketCAN interface for any CANopen master, with a `test` mode that runs scenarios and writes a JUnit report ([docs/simulator.md](docs/simulator.md#openplc-canopen-sim)).

## Scope

- Master and slave roles, one role per CAN interface; no flying master, MPDO or SRDO, and no program download into OpenPLC as a slave.
- Linux with SocketCAN (`can0`, `vcan0`, ...; serial `slcan` adapters need Linux 6.0 or later), OpenPLC v4 native installs (`install.sh --native`) and upstream's managed Docker install ([docs/install-stock.md](docs/install-stock.md#docker-installs)).
- Stock runtime only (unmodified upstream): `scripts/install-stock.sh` installs the plugin and an editor hook next to the runtime. A program then gets its CANopen config either from a `canopen/` folder in the editor project, carried by the editor's own **Build and upload**, or from `openplc-canopen-deploy`, which uploads an editor build together with the config. Either way the runtime switches the plugin on. See [docs/install-stock.md](docs/install-stock.md) and [docs/deploy.md](docs/deploy.md).

## Layout

```
CMakeLists.txt     builds libcanopen_plugin.so; the runtime's install.sh builds it from here
plugin/            native plugin source
plugin/sim/        the device simulator engine (simulated devices, value sources, expressions,
                   CiA 402 drive model, faults, scenarios), used by the plugin and openplc-canopen-sim
schema/            the config contract (JSON Schema 2020-12): canopen.v1.schema.json (one network),
                   canopen.v2.schema.json (several networks, slave networks, the gateway), and
                   canopen-sim.v1/v2.schema.json for the simulation file (v2: a section per network)
examples/          virtual-plant/: the fully virtual example project of docs/tour.md (four simulated
                   networks, a demo program, a simulation file with test scenarios)
config/            example configurations: config/pingpong/ (the ping-pong slave),
                   config/rtd-sensor/ (a simulated 8-channel RTD module, CiA 404), each with
                   an example simulation.json, config/two-networks/ (two ping-pong networks on
                   vcan0 and vcan1),
                   config/cia402-drive/ (a made-up CiA 402 drive as a PLCopen axis, with a demo program),
                   config/slave/ (OpenPLC as slave node 10, its EDS description and a demo program),
                   config/gateway/ (the ping-pong node on a field network, OpenPLC as a gateway above it)
tools/             canopen_check: validates a config and its EDS files without starting the PLC
tools/deploy/      the PC tools (Python, one package): openplc-canopen-deploy, openplc-canopen-config
                   (the configurator), openplc-canopen-diag (online diagnostics, parameters, trace)
docker/local-runtime/ the local simulator runtime image (stock runtime + plugin, forced simulation) and
                   the pinned upstream runtime version
tools/editor-hook/ the runtime-side hook that keeps CANopen on with the editor's Build and upload
library/           the openplc_canopen editor library (SDO function blocks): generate.py writes the
                   block sources, build.sh builds the .stlib the deploy tool carries
test/unit/         unit tests: config validation, EDS checks, dcfgen, process image
test/sim/          master against Lely slaves and simulated devices on an in-process virtual CAN bus
test/slave/        the plugin's master against its own slave and gateway on virtual buses, and
                   run.sh for a master on vcan0 and the slave on vcan1 joined by cangw, and
                   simulated.sh for both on one simulated bus (a ctest)
test/sim_unit/     simulator unit tests: expressions (shared corpus), sources, file loader, drive model
test/drive/        a simulated CiA 402 drive (Lely slave) for the virtual bus
test/cia402/       ST tests of the CiA 402 axis glue with STruC++ (run.sh) and its host for sim_tests
test/pingpong/     the Lely tutorial ping-pong slave and run.sh for vcan0
test/sensor/       sensor_slave (a measuring device from any EDS) and run.sh for vcan0
test/fixed/        a fixed-mapping I/O module against the plugin on vcan0
test/lss/          LSS node ID assignment to a slave without a node ID on vcan0
test/params/       device parameter backup, compare and restore on vcan0
test/commissioning/ writing a configuration to one device from the PC on vcan0
test/trace/        bus trace recording, filters and export formats on vcan0
test/rawframes/    raw frames sent by hand (guards, cyclic jobs) on vcan0 and the simulated bus
test/bus/          the bus state byte while vcan0 goes down and up
test/networks/     two networks on vcan0 and vcan1, one of them losing its node
test/slcan/        the slcan adapter against a fake CANable on a pseudo-terminal, bridged to vcan1
test/plc_sdo/      the SDO blocks compiled as the editor does, finding the real plugin in-process
test/host/         canopen_host: loads the plugin .so with a stand-in PLC scan; plugin lifecycle tests
test/link/         link_check: the SocketCAN link setup on a real interface
test/dump/         canopen_check --dump-writes against a checked-in list (DCF export parity)
test/fixtures/     config and EDS fixtures shared by the plugin's and the deploy tool's tests
                   (test/fixtures/eds/drives/: two made-up CiA 402 drives)
test/stock/        install-stock.sh, the editor hook and the upstream runtime's upload rules, end to end
test/docker/       install-stock.sh in Docker mode and the runtime spec edits
test/local-runtime/ openplc-canopen-sim-runtime against the image with a compiled PLC program (run.sh)
test/virtual-example/ the virtual example on the image: checks, exports, every node up, test scenarios
test/pc-tools/     the release tag check; test/ci/: the CI change classification
scripts/           dev-setup.sh (Lely, dcfgen, vcan0), build-lely.sh, install-stock.sh,
                   fetch-strucpp.sh (the editor's ST compiler, for the CiA 402 tests)
docs/              tour.md (the guided tour of the virtual example), config.md (the config format), cia402.md, configurator.md, deploy.md, diagnostics.md,
                   frame-inspector.md, gateway.md, install-pc.md, install-stock.md, local-runtime.md, network-docs.md, plc-sdo.md, simulator.md, slave.md,
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
test/commissioning/run.sh                       # write a configuration to one device, PDO test
test/trace/run.sh                               # bus trace and its export formats
test/rawframes/run.sh                           # raw frames sent by hand, bit rate detection refusals
test/bus/run.sh                                 # bus state byte with vcan0 taken down and up
test/slcan/run.sh                               # slcan adapter (needs the slcan module and vcan1)
```

The CiA 402 tests use the editor's ST compiler, STruC++ (needs Node 22):

```sh
test/cia402/run.sh                              # ST tests of the generated axis glue against a drive model
cmake -B build -DOPENPLC_ROOT=../openplc-runtime -DSTRUCPP=$(scripts/fetch-strucpp.sh)
cmake --build build -j && build/test/sim_tests --exact sim_cia402_demo   # the demo program on the virtual bus
```

CI (`.github/workflows/ci.yml`) runs all of these on every pull request and push to `main` that changes code, the deploy tool, page and vcan tests spread over several runners (a new vcan test goes into the vcan group with the least test time, listed above the job; package installs go through `.github/scripts/apt_install.py`, which skips installed packages and retries a stalled mirror); its last job, `ci-ok`, is the one check a branch ruleset needs. A change that touches only documentation or specs runs just the OpenSpec validation; the build and test jobs are skipped.

### Integration tests (by hand, weekly, or locally)

Two end-to-end installs test against things outside this repository and mostly catch upstream drift, so they are not in the pull request run. `.github/workflows/integration.yml` runs them weekly, on "Run workflow", and on pull requests that change the install routes (`install-stock.sh`, `test/stock/`, `test/docker/`, the editor hook). On a Linux machine with the development build above:

```sh
pip install jsonschema python-dotenv
test/stock/run.sh ../openplc-runtime build      # stock runtime install, upload rules and editor hook (upstream development)
sudo test/docker/run.sh --image ghcr.io/autonomy-logic/openplc-runtime:latest   # Docker route; needs Docker and vcan0
```

Use a development machine, not one running your PLC: the stock test installs into `/opt/openplc-canopen` and the runtime checkout, and the Docker test starts runtime containers on the host network.

### Local simulator runtime image

`.github/workflows/local-runtime.yml` builds the image of [docs/local-runtime.md](docs/local-runtime.md) from the pinned upstream runtime (`docker/local-runtime/runtime-version`) and runs `openplc-canopen-sim-runtime` against it with a PLC program compiled by STruC++, then deploys the virtual example to it and runs its test scenarios (`test/virtual-example/run.sh`), on pull requests that change the image, the plugin, the command or the example, weekly and on "Run workflow"; an arm64 runner builds the arm64 image. Locally (needs Docker and Node 22):

```sh
docker build -f docker/local-runtime/Dockerfile --build-arg RUNTIME_IMAGE=ghcr.io/autonomy-logic/openplc-runtime:$(cat docker/local-runtime/runtime-version) -t openplc-canopen-sim-runtime:dev .
test/local-runtime/run.sh --image openplc-canopen-sim-runtime:dev --strucpp "$(scripts/fetch-strucpp.sh)"
test/virtual-example/run.sh --image openplc-canopen-sim-runtime:dev --strucpp "$(scripts/fetch-strucpp.sh)"
```

### PC tools on Windows, macOS and Linux

`.github/workflows/pc-tools.yml` installs the PC tools with uv on Windows, macOS and Linux (x86_64 and ARM64) on version bumps on `main` (the release waits for it), on `deploy-v<version>` tags and on "Run workflow" (start it on a pull request's branch when a change needs those systems checked). On your own PC, from a checkout (bash; Git Bash on Windows):

```sh
uv build --wheel --out-dir dist tools/deploy && uv tool install --force --python 3.12 dist/*.whl
uv run --no-project --python 3.12 --with jsonschema --with cantools python -m unittest discover -s tools/deploy/tests -t tools/deploy
uv run --no-project --python 3.12 python test/pc-tools/smoke.py "$(sed -n 's/^version = "\(.*\)"/\1/p' tools/deploy/pyproject.toml)"
```

A `deploy-v<version>` release publishes the tools as a wheel on GitHub and the local simulator runtime image `ghcr.io/tonihoohoo/openplc-canopen-sim-runtime:<version>` (`release-deploy.yml`).

## Installing it

`scripts/install-stock.sh` builds the plugin against the runtime checkout's headers, installs it to `/opt/openplc-canopen/lib/` and registers it in the runtime's `plugins.conf`; uploads then switch it on and off. See [docs/install-stock.md](docs/install-stock.md). Without a config file the plugin logs a warning and stays inactive; a config with errors is logged and also leaves it inactive. The PLC runs normally in both cases. See [docs/config.md](docs/config.md) for the configuration format.

## Specs

The behaviour is specified with [OpenSpec](https://github.com/Fission-AI/OpenSpec) in `openspec/specs/`, one folder per capability: master bring-up, node supervision, PDO I/O, SDO variables, bus diagnostics, online diagnostics, device parameters, bus trace, the slcan adapter, the config contract, the stock install, the Docker install, the deploy tool, the editor upload, the editor project, the configurator, DCF export, DBC export, the network documentation, frame explanations, the PC install, the local simulator runtime and CI. New work starts as a change under `openspec/changes/` and is archived into the specs once it is merged.

## License

Apache License 2.0, see [LICENSE](LICENSE). Bundled third-party code keeps its own license: Lely's `dcf` package in `tools/deploy/openplc_canopen_deploy/_lely_dcf/` (Apache 2.0, with its NOTICE) and uPlot in `tools/deploy/openplc_canopen_deploy/configurator/static/uplot/` (MIT). The ping-pong slave's EDS follows the [Lely CANopen C++ tutorial](https://opensource.lely.com/canopen/docs/cpp-tutorial/). Every other EDS file in this repository describes a made-up device written for the tests.
