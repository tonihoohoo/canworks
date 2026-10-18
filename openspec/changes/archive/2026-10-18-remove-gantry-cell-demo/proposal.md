# Proposal: remove-gantry-cell-demo

## Why

Toni (2026-10-18): "remove gantry cell demo completely", "also documentation and gui". The gantry cell example (`examples/gantry-cell`) is the only user of the simulated machine: the machine model in the plugin's simulator, the machine file and its schema, the operator panel and virtual safety relay, and the configurator's 3D **Machine** tab. The machine kind is `gantry_xyz` only and nothing else names a machine file, so the machine simulator goes with the demo. The project is not in real use, so this is a clean cut with no compatibility left behind.

## What Changes

- **Example:** delete `examples/gantry-cell/` (config, EDS files, machine file, simulation file, program, README).
- **Plugin simulator:** delete the machine model (`sim/sim_machine.*`) and its glue in `sim_engine` and `sim_file`: the `machine` key of a simulation file section, machine faults and machine conditions in scenarios, the `sim_machine`, `sim_panel` and `sim_person` requests and the machine part of `sim_status`. The CiA 402 drive model loses what only a machine fed it: the joint load torque, the machine-set home, limit and blocked inputs (a user still sets them through faults) and the safe torque off input. **BREAKING** (clean cut): a section with `machine` is refused as an unknown key.
- **Schema:** delete `schema/canworks-sim-machine.v1.schema.json` and its copy in the PC tools; drop `machine` from the simulation file version 2 schema.
- **PC tools:** delete `simmachine.py`; remove machine-file handling from `simfile.py`, `bundle.py`, `project.py`, `cli.py`, `simclient.py` and the editor hook's `snapshot.py` (no machine file carried into uploads, projects or editor snapshots).
- **Configurator GUI:** delete the Simulation view's **Machine** tab (`machine_view.js`, `machine_scene.js`), its server routes (`/api/sim/machine`), its styles, and the vendored three.js (`static/three/`, used only by that tab) with its package-data entry.
- **Tests and CI:** delete `sim_gantry_demo` and its STruC++ build of the gantry program, `sim_machine_tests.cpp`, `test_sim_machine.py`, `test_configurator_sim_machine*.py`, `fake_sim_machine.py`, the page sweep's `GantryCell` class and the CI timing entries. Tests that only borrowed the example's files (CODESYS golden plan and motion overrides, notes, bit channels page, server move tests, project and snapshot tests, rename test) move to `examples/virtual-plant` or their own fixtures; the `gantry-cell.json` CODESYS golden goes.
- **Docs:** remove the Simulated machine part of `docs/simulator.md` (machine file, operator panel and safety, machine faults and conditions, state, the Machine tab), the Machine tab section of `docs/configurator.md`, tour chapter 15, the `sim_gantry_demo` line in `docs/cia402.md`, the example in `docs/development.md`, and the README's Simulated machine bullet and layout line.

Kept: the CiA 402 drive model and its user-set inputs, scenarios, bit channels and device notes (generic), `examples/virtual-plant` and its `servo402.eds` and `dio16.eds`, and spec scenarios that merely use a node named `panel` as an example.

## Capabilities

### Removed Capabilities
- `canopen-machine-model`: the whole simulated machine.
- `canopen-machine-view`: the configurator's Machine tab.

### Modified Capabilities
- `canopen-config-contract`: simulation file version 2 without `machine`; machine file contract and checks removed.
- `canopen-device-simulator`: drive model without machine inputs, load and safe torque off; scenarios without machine faults and conditions.
- `canopen-virtual-example`: the tour has no Simulated machine chapter; the gantry manual mode requirement goes.
- `canopen-ci`: the page sweep covers `virtual-plant` and `j1939`.
- `toolkit-names`: no machine schema.
- `codesys-export`: the script's CI run uses the virtual-plant plan.
- `canopen-configurator`: moving a config has no machine file; the message-bar scenario names the Simulation view.

## Impact

- About 9,000 lines and ~1 MB (three.js) leave the repository and the PC tools package; CI loses the gantry demo run (52 s) and one page-sweep class (~9 s).
- PC tools minor version bump.
- No config file format change outside simulation files; no bench impact (nothing on the Pi, Mac or Windows PC runs the gantry example). No hardware tasks.
