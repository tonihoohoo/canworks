## Why

The project has grown to cover several networks, a slave role and a gateway, CiA 402 axes, LSS, online diagnostics, a trace with a frame inspector, a device simulator and a local simulator runtime, but each feature is shown on its own in a small `config/` example or a doc page. Someone new has no single place to see what the whole thing does, and no way to try it all without a Raspberry Pi, a CAN adapter and devices.

Almost all of it can already run on a PC: the local simulator runtime runs the stock runtime with the plugin and every network simulated, and the editor uploads to it. What is missing is one project that puts the features together and a guide that walks through them. One limit stands in the way: the simulation file serves only a config with one network, so a project with several networks loses its waveforms, start-up faults, scenarios and extra (LSS) devices.

## What Changes

- **Example project** `examples/virtual-plant/`: an OpenPLC Editor 4.3.2 project with a `canopen/` folder, made by the project generator and extended with a demo program. All networks have `adapter.simulate: true`, so the project runs the same in the local simulator runtime and on any runtime without CAN hardware. Only made-up devices:
  - `io` (simulated bus `sim0`, master, SYNC from a timer, TIME producer): RTD-8 temperature module (node 5, blank default mapping, startup SDOs, input PDO receive timeout), a new made-up CiA 401 I/O module DIO-16 (node 6: identity check, mandatory, EMCY, configuration check 0x1020, opt-in store 0x1010, SDO variables), and an extra simulated device without a node ID for LSS assignment.
  - `motion` (`sim1`, master, SYNC from the PLC cycle): the SD-402 drive as a cyclic synchronous axis (CSP, CSV, CST).
  - `cell` (`sim2`, slave, node ID 20): OpenPLC as a slave with its own objects and the gateway's upper network (routes from `io`, field node status, EMCY forwarding, SDO bridge, behaviour on upper loss).
  - `host` (`sim2`, master): a stand-in for the machine controller above the gateway, so the slave and gateway have a master in a container with nothing else on its bus.
  - Demo program: temperature scaling and alarm, I/O loopback, the drive sequence, SDO function blocks, an NMT restart, reactions to node status, PDO timeout and EMCY, and the gateway status.
  - Simulation file: waveforms and a formula per network, an autostart fault timeline, and scenarios marked `test` that check the program's reactions.
- **Guide** `docs/tour.md`: a step-by-step tour of the example, one chapter per feature group (install, configurator and checks, exports, editor upload and debugger, online diagnostics and parameters, simulation and faults, LSS, motion, slave and gateway, trace and frame inspector, raw frames, automated scenario tests), each saying what to do, what to see and which doc has the details. A closing section lists what needs hardware: bit rate detection, slcan adapters and hot-plug, bus error states, commissioning straight from the PC through a USB adapter, program download, real-time timing, and the install on a Pi.
- **Simulation file per network**: simulation file `schema_version` 2 with a `networks` object keyed by network name, each holding what a version 1 file holds (`nodes`, `extra_devices`, `scenarios`), plus a shared `tick_ms`. The plugin, the deploy tool's check and the configurator's Simulation view read and write it; a version 1 file keeps working for a config with one network. A several-network project's simulation file is then used instead of ignored.
- **Gateway self-loop**: a test that a gateway's upper slave network and a master network of the same config share one simulated bus, with the gateway status and routes working; any fix it needs.
- **CI**: the example is checked, its program compiled with STruC++ and run in the local simulator runtime image, and its `test` scenarios run with `openplc-canopen-diag sim test`, so the example and the guide's commands stay in step with the code.
- README: the example and the guide at the top of the documentation list.

## Capabilities

### New Capabilities
- `canopen-virtual-example`: the example project, what it must show, that it runs fully virtual, the guide and its hardware section, and the CI check that keeps it working.

### Modified Capabilities
- `canopen-simulated-bus`: the simulation file serves configs with several networks, one section per network.
- `canopen-config-contract`: simulation file version 2 and its checks.
- `canopen-configurator`: the Simulation view edits and saves the section of the network it shows.

## Non-goals

- No virtual CAN adapter for the PC tools (commissioning straight from the PC stays hardware only), no simulated bus error states, no program download in the simulator. The guide lists them as needing hardware; each can be a later change.
- No new runtime or editor behaviour beyond the simulation file.

## Impact

- New: `examples/virtual-plant/` (editor project, `canopen/` with EDS files, `canopen.json`, `simulation.json`, slave EDS description), `config/io-module/` or the DIO-16 EDS generator next to the example, `docs/tour.md`, `test/virtual-example/run.sh`.
- Plugin: simulation file loader (`plugin/src/sim_config.cpp`) for version 2 and per-network sections.
- Schema: `schema/canopen-sim.v2.schema.json` (version 1 schema kept).
- Deploy tool: `simfile.py` check per network, configurator Simulation view per network; deploy tool minor version bump.
- CI: a job in `local-runtime.yml` (it already builds the image) running the example; docs-only paths unchanged.
- Docs: `docs/tour.md`, `docs/simulator.md`, `docs/configurator.md`, `docs/local-runtime.md`, README.
