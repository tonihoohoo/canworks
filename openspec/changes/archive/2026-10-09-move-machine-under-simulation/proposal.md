## Why

The machine model lives in the simulator (`plugin/sim/sim_machine.cpp`, stepped in the simulator's tick, only on simulated networks), but nothing a user sees says so: the configurator has **Machine** as its own sidebar item next to **Simulation**, the docs have a separate `docs/machine.md` titled "Machine model", the tour chapter is "Machine", the PC tools module is `machine.py` and the schema is `canworks-machine.v1.schema.json`. A reader looking for what the simulator can do does not find the machine, and a reader who finds the machine does not learn it only runs simulated.

## What Changes

- **Configurator**: the Machine view becomes a **Machine** tab of the **Simulation** view, after **Live values**, **Simulation file** and **Scenarios**, shown when the network's simulation section names a machine file. The separate **Machine** sidebar item goes away. When the Machine tab is open the 3D scene and its panel use the whole content area, as the Machine view does now.
- **Docs**: `docs/machine.md` becomes a part of `docs/simulator.md`, which is retitled "Simulator" with two parts, "Simulated devices" (today's content) and "Simulated machine" (today's `machine.md`). Every link moves to the new anchors; `docs/machine.md` is removed (no redirect: the project is not in use yet).
- **Tour and example**: tour chapter 15 becomes "Simulated machine"; the README feature bullet, the layout list and `examples/gantry-cell/README.md` link the new section and say "simulated machine".
- **PC tools**: `canworks/machine.py` moves to `canworks/simmachine.py`, next to `simfile.py`, `simcli.py` and `simclient.py`. Tests follow: `test_machine.py` → `test_sim_machine.py`, `test_configurator_machine*.py` → `test_configurator_sim_machine*.py`, `fake_machine.py` → `fake_sim_machine.py`, and the page test time table is updated so the shards stay balanced.
- **BREAKING (bench only)**: the schema file `canworks-machine.v1.schema.json` becomes `canworks-sim-machine.v1.schema.json` (repository and the copy shipped with the PC tools). The machine file's content, its `schema_version` and the simulation file key `"machine"` do not change, so no project needs editing.
- Not changed: the plugin code (already `plugin/sim/`), the diagnostics ops (`sim_machine`, `sim_fault`/`sim_clear` with `machine`), the machine file format, the OpenSpec capability names.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `canopen-machine-view`: the view is a tab of the Simulation view, not its own sidebar item.
- `toolkit-names`: the machine schema file name.
- `canopen-virtual-example`: the tour chapter is "Simulated machine" and opens the Machine tab of Simulation.

## Impact

- Code: `tools/deploy/canworks/configurator/static/` (`index.html`, `app.js`, `sim.js`, `machine_view.js` hook-up), `tools/deploy/canworks/machine.py` and its importers, schema files, `test/ci/test_rename.py` (schema list).
- Docs: `docs/simulator.md`, `docs/machine.md` (removed), `docs/configurator.md`, `docs/tour.md`, `docs/cia402.md`, `README.md`, `examples/gantry-cell/README.md`.
- Tests: renamed files, same tests; `.github/ci/page-test-times.json` class names.
- CI time: no new tests, so wall and summed job time stay at or under the baseline.
