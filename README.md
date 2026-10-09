# canworks

An open CAN toolkit: configure, commission, diagnose, trace and simulate **CANopen**, **J1939** and plain **CAN** networks, from a PC on its own or with an [OpenPLC Runtime v4](https://github.com/Autonomy-Logic/openplc-runtime) PLC driving the bus.

> **Experimental.** All code, tests and documentation in this repository were written by Claude (Anthropic's AI model), directed and tested by a person. Treat everything here as experimental: it has run on a test bench, not in production, and comes with no warranty (see [LICENSE](LICENSE)). Do not use it to control machinery where a fault could hurt people or damage equipment.

canworks has two halves:

- **A runtime plugin for OpenPLC v4** that makes the PLC a CANopen master, slave or gateway, or a J1939 ECU, with plain CAN messages on any network, over SocketCAN. It is built on [Lely CANopen](https://gitlab.com/lely_industries/lely-core) and the Linux kernel's J1939 stack, and installs next to an unmodified upstream runtime.
- **PC tools for Windows, macOS and Linux**: a configurator in the browser, a deploy tool, command-line diagnostics, a bus trace, device simulators and a local runtime in a container. They work through the PLC or straight through a USB CAN adapter on the PC, with no PLC at all.

## How it works

You describe the network in one JSON file (`canworks.json`, usually written by the configurator): the nodes, their EDS files, and which PDO entry goes to which PLC address (`%IX`, `%IB`, `%IW`, `%ID`, `%IL` and the `%Q` equivalents). The file travels with the PLC program, either in the editor project's `canworks/` folder or through `canworks-deploy`.

At every PLC start the plugin checks the file against the EDS files, generates the device configuration with Lely's `dcfgen`, boots and configures every node over SDO, and then exchanges PDOs with the PLC image once per scan. A node that is missing or drops off the bus never stops the PLC: its status bit goes FALSE and the master keeps trying to bring it back. A config with errors is logged and leaves the plugin inactive; the PLC still runs.

## Quick start

**Try it without hardware.** [docs/tour.md](docs/tour.md) walks through [`examples/virtual-plant`](examples/virtual-plant/README.md): one editor project with four simulated networks that shows the features working together on a PC. You need a container engine, the PC tools and the OpenPLC Editor; no CAN hardware.

**Install the PC tools** with [uv](https://docs.astral.sh/uv/), which brings its own Python ([docs/install-pc.md](docs/install-pc.md)):

```sh
uv tool install --python 3.12 canworks-<version>-py3-none-any.whl   # from the Releases page
canworks-config                                                      # opens the configurator
```

**Install the plugin on the PLC** (Linux with an OpenPLC v4 native or managed Docker install, [docs/install-stock.md](docs/install-stock.md)):

```sh
git clone https://github.com/tonihoohoo/canworks
cd canworks
sudo scripts/install-stock.sh             # CANopen and J1939; --without-canopen or --without-j1939 builds one
sudo systemctl restart openplc-runtime    # native installs: once, so the runtime loads the plugin
```

**Configure and upload.** Build the network in `canworks-config` ([docs/configurator.md](docs/configurator.md)); it writes the editor project's `canworks/` folder, and the editor's own **Build and upload** carries it to the PLC. `canworks-deploy` does the same from a terminal ([docs/deploy.md](docs/deploy.md)).

## Features

### CANopen on the PLC

Every field is described in [docs/config.md](docs/config.md).

- **Networks and adapters:** up to 8 CAN networks from one PLC, each with its own adapter, master, bit rate, SYNC and nodes; a network that fails does not stop the others. Any SocketCAN interface works (CAN HAT, candleLight/gs_usb, PEAK, vcan), as do serial `slcan` adapters such as a CANable, driven directly without `slcand` and picked up again after a replug.
- **PDOs:** mapping from the config, or the device's own fixed or default mapping. Transmission type, inhibit time, event timer and SYNC start value default to the EDS's own values.
- **SYNC:** from a timer, from the PLC cycle (one SYNC every N scans), or none for event-driven PDOs only.
- **Node bring-up:** startup SDO writes, identity check (0x1018), mandatory nodes, heartbeat or node guarding, program download, configurable SDO timeouts, and an opt-in configuration check (0x1020) that skips an unchanged download. Saving to the device's non-volatile memory (0x1010) only happens when a node asks for it.
- **LSS:** devices without DIP switches get their node ID from their serial number at every start and after a replacement.
- **EDS checks:** every EDS goes through Lely's CiA 306 lint, and every PDO entry and SDO is checked for type and access before anything is sent.
- **Status for the program:** a status bit and state byte per node, bus state and error counters, the last EMCY per node, and an optional receive timeout per input PDO.
- **From the program:** SDO variables, NMT commands, and SDO function blocks (`CO_SDO_READ`, `CO_SDO_WRITE`, ...) that read or write any object of any node when the program decides ([docs/plc-sdo.md](docs/plc-sdo.md)).
- **CiA 402 drives as PLCopen axes:** drive a node with the editor's motion blocks (`MC_Power`, `MC_MoveAbsolute`, `MC_Home`, ...) in profile position, velocity and homing mode, or in the cyclic synchronous modes (CSP, CSV, CST) ([docs/cia402.md](docs/cia402.md)).
- **Everything `dcfgen` can set**, plus a TIME producer that sends the runtime host's clock.
- **OpenPLC as a slave:** the PLC becomes a node on a network another master runs, with a generated EDS for that master's tool ([docs/slave.md](docs/slave.md)).
- **Gateway:** a slave network above master networks, with routes that copy values between them without the PLC program, plus node status, EMCY forwarding and an SDO bridge ([docs/gateway.md](docs/gateway.md)).
- **Online diagnostics:** an opt-in channel for the PC tools, encrypted with TLS; the token never crosses the network, and nothing a client does touches the PLC scan.

### J1939 on the PLC

A network with `"protocol": "j1939"` makes the PLC an ECU ([docs/j1939.md](docs/j1939.md)): its own NAME and address claim, received PGNs on `%I` locations with not-available and timeout bits, sent PGNs from `%Q` locations periodically or on change, request handling, and messages up to 1785 bytes through the kernel's transport protocol. Signal scaling lives in a DBC file the tools use. J1939 and CANopen networks run side by side in one config.

### Raw CAN on the PLC

Plain CAN messages run on any network, next to CANopen or J1939, or on a plain CAN network (`"protocol": "none"`, optionally listen-only) that carries nothing else ([docs/raw-can.md](docs/raw-can.md)). Received messages put DBC-style signals on `%I` locations with a timeout bit, counter and last frame; sent ones come from `%Q` locations periodically, on change or on a trigger bit. Identifiers the protocol uses need an explicit override. From the program, `CAN_SEND`, `CAN_SEND_CYCLIC`, `CAN_RECEIVE` and `CAN_BUS_INFO` and ST bit and byte helpers in the `canworks` library send and receive any frame when the program decides. [`examples/raw-can`](examples/raw-can/canworks.json) is a plain network with its DBC file and simulated devices.

### Simulation

- **Simulated devices** ([docs/simulator.md](docs/simulator.md)): any node, or a whole network, can be simulated from its EDS, so a project and its program run without the real devices or CAN hardware. Values can follow waveforms, formulas, recorded CSV data or a CiA 402 drive model; faults (EMCY, lost heartbeat, power loss, SDO aborts, wrong identity, ...) come on command or from timed scenarios that test the program's reaction.
- **Simulated machine:** an XYZ gantry with a gripper, a conveyor, sensors and a pallet on top of the simulated drives and I/O, shown in 3D in the configurator. [`examples/gantry-cell`](examples/gantry-cell/README.md) is a complete pick-and-place project.
- **Local runtime:** `canworks-sim-runtime` runs the stock OpenPLC Runtime with the plugin in a container on the PC, every network simulated, so the editor uploads to `localhost` and debugs there ([docs/local-runtime.md](docs/local-runtime.md)).

### PC tools

Five commands in one package, for Windows, macOS and Linux ([docs/install-pc.md](docs/install-pc.md)). They reach the bus through the runtime, or straight through a USB adapter on the PC (slcan adapters everywhere, gs_usb/candleLight on macOS, SocketCAN on Linux), so a single device can be commissioned on the bench or as a guest on another master's bus, read-only until changes are allowed ([docs/pc-adapter.md](docs/pc-adapter.md)).

| Command | What it does |
| --- | --- |
| `canworks-config` | The configurator, a local web page ([docs/configurator.md](docs/configurator.md)). Add nodes from their EDS, map PDO entries to PLC addresses checked against the editor project, set up slave, gateway, J1939 and plain CAN networks, and raw CAN messages with DBC import. Device notes explain objects (text, unit, scale, value meanings, bit names): built-in for CiA 301/401/402, plus a notes file per EDS you fill from the manual; they show in the object dictionary browser, the SDO lists, the HTML docs and the DBC export. Its **Online** view shows the live network (states, EMCY, SDO, NMT, bus scan, LSS, object dictionary browser, parameter backup and restore, PDO test, bit rate detection); **Trace** records and decodes the bus ([docs/trace.md](docs/trace.md)); the frame inspector and **Frame lab** explain every bit of a frame ([docs/frame-inspector.md](docs/frame-inspector.md)); **Commission a CANopen device** works on a USB adapter without any project. |
| `canworks-deploy` | Adds the config to an editor build and uploads it ([docs/deploy.md](docs/deploy.md)); checks a config offline; creates an editor project from a config (`--blocks` enables the SDO and CAN frame blocks); installs the `canworks` editor library; exports DCF, DBC and an offline HTML documentation of the CANopen and J1939 networks ([docs/network-docs.md](docs/network-docs.md)). |
| `canworks-diag` | The online functions from a terminal ([docs/diagnostics.md](docs/diagnostics.md)): parameter backup, compare and restore as CiA 306 DCF, writing a configuration to a device, LSS, raw frames, `replay` of a recorded trace, bit rate detection, trace with export to pcapng, candump, ASC, BLF, TRC or CSV, simulator control, and `explain` for a frame bit by bit. |
| `canworks-sim-runtime` | The local simulator runtime in a container (Docker Engine, Podman or Colima; amd64 and arm64) ([docs/local-runtime.md](docs/local-runtime.md)). |
| `canworks-j1939-sim` | Plays one node of a J1939 DBC file on a SocketCAN interface or USB adapter, with address claim, cycle times, ramps and scenarios ([docs/j1939.md](docs/j1939.md#simulator)). |

On the runtime host, `canworks-sim` runs simulated CANopen devices on a SocketCAN interface for any master, with a `test` mode that writes a JUnit report ([docs/simulator.md](docs/simulator.md#canworks-sim)).

## Requirements and limits

- **PLC side:** Linux with SocketCAN (`slcan` adapters need Linux 6.0 or later), OpenPLC Runtime v4 as a native install (`install.sh --native`) or upstream's managed Docker install ([docs/install-stock.md](docs/install-stock.md#docker-installs)). The runtime stays unmodified; `install-stock.sh` also installs an editor hook so the editor's **Build and upload** keeps the plugin on.
- **CANopen:** master and slave roles, one role per CAN interface; no flying master, MPDO or SRDO, and no program download into OpenPLC as a slave.
- **Raw CAN:** classic CAN only (no CAN FD), raw integer signals, no multiplexed DBC messages.
- **J1939:** one ECU per interface, raw integer signals, no diagnostic messages (DM1 ...) or multiplexed DBC messages yet ([docs/j1939.md](docs/j1939.md#limits)).

## Documentation

| Topic | Page |
| --- | --- |
| Guided tour without hardware | [tour.md](docs/tour.md) |
| Installing the plugin on the PLC | [install-stock.md](docs/install-stock.md) |
| Installing the PC tools | [install-pc.md](docs/install-pc.md) |
| The config file | [config.md](docs/config.md) |
| Configurator | [configurator.md](docs/configurator.md) |
| Deploy tool and exports | [deploy.md](docs/deploy.md), [network-docs.md](docs/network-docs.md) |
| Diagnostics and USB adapters on the PC | [diagnostics.md](docs/diagnostics.md), [pc-adapter.md](docs/pc-adapter.md) |
| Bus trace and frame inspector | [trace.md](docs/trace.md), [frame-inspector.md](docs/frame-inspector.md) |
| SDO blocks and CiA 402 axes in the program | [plc-sdo.md](docs/plc-sdo.md), [cia402.md](docs/cia402.md) |
| Slave and gateway | [slave.md](docs/slave.md), [gateway.md](docs/gateway.md) |
| J1939 | [j1939.md](docs/j1939.md) |
| Raw CAN messages and frame blocks | [raw-can.md](docs/raw-can.md) |
| Simulation and the local runtime | [simulator.md](docs/simulator.md), [local-runtime.md](docs/local-runtime.md) |
| Building, testing, CI and the repository layout | [development.md](docs/development.md) |

## Development

[docs/development.md](docs/development.md) covers the development build, the test suites, CI and the repository layout. The configurator's page tests drive it in Chromium, and a separate browser workflow runs it against the real plugin on its simulated bus, with no CAN hardware or vcan. The behaviour is specified with [OpenSpec](https://github.com/Fission-AI/OpenSpec) in `openspec/specs/`, one folder per capability; new work starts as a change under `openspec/changes/` and is archived into the specs once merged.

### PC tools on Windows, macOS and Linux

`.github/workflows/pc-tools.yml` installs the PC tools with uv on Windows, macOS and Linux (x86_64 and ARM64) on version bumps on `main` (the release waits for it), on `deploy-v<version>` tags and on "Run workflow" (start it on a pull request's branch when a change needs those systems checked). On your own PC, from a checkout (bash; Git Bash on Windows):

```sh
uv build --wheel --out-dir dist tools/deploy && uv tool install --force --python 3.12 dist/*.whl
uv run --no-project --python 3.12 --with jsonschema --with cantools python -m unittest discover -s tools/deploy/tests -t tools/deploy
uv run --no-project --python 3.12 python test/pc-tools/smoke.py "$(sed -n 's/^version = "\(.*\)"/\1/p' tools/deploy/pyproject.toml)"
```

A `deploy-v<version>` release publishes the tools as a wheel on GitHub and the local simulator runtime image `ghcr.io/tonihoohoo/canworks-sim-runtime:<version>` (`release-deploy.yml`).

## License

Apache License 2.0, see [LICENSE](LICENSE). Bundled third-party code keeps its own license: Lely's `dcf` package in `tools/deploy/canworks/_lely_dcf/` (Apache 2.0, with its NOTICE), uPlot in `tools/deploy/canworks/configurator/static/uplot/` (MIT) and three.js 0.169.0 in `tools/deploy/canworks/configurator/static/three/` (MIT). The ping-pong slave's EDS follows the [Lely CANopen C++ tutorial](https://opensource.lely.com/canopen/docs/cpp-tutorial/). Every other EDS file in this repository describes a made-up device written for the tests.
