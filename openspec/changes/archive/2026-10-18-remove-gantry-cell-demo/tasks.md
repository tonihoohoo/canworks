# Tasks

## 1. Example and plugin

- [x] 1.1 Delete `examples/gantry-cell/`.
- [x] 1.2 Delete `plugin/src/canopen/sim/sim_machine.cpp`/`.h` and its `plugin/CMakeLists.txt` entry; remove the machine from `sim_engine` (model, step, relay, `sim_machine`, `sim_panel`, `sim_person`, machine faults and conditions, the machine part of `sim_status`) and the `machine` key from `sim_file`.
- [x] 1.3 Drive model: remove the joint load torque, machine-set inputs (keep user-set inputs through faults) and the safe torque off input.
- [x] 1.4 Test: a version 2 section with `machine` is refused naming the section and the key.

## 2. Schemas and PC tools

- [x] 2.1 Delete `schema/canworks-sim-machine.v1.schema.json` and `tools/deploy/canworks/schema/` copy; drop `machine` from both copies of the simulation v2 schema.
- [x] 2.2 Delete `simmachine.py`; remove machine handling from `simfile.py`, `bundle.py`, `project.py`, `cli.py`, `simclient.py`, `configurator/simulation.py` and `tools/editor-hook/canworks_hook/snapshot.py`.

## 3. Configurator

- [x] 3.1 Delete `machine_view.js`, `machine_scene.js` and `static/three/`; remove the Machine tab from `sim.js` and `app.js` (`stopMachine`), the machine styles from `style.css`, the `/api/sim/machine` routes and the three.js note in `server.py`, and the three.js entries in `pyproject.toml` package-data.
- [x] 3.2 Check the in-app tour and the Simulation view's tabs and empty states read right without Machine.

## 4. Tests and CI

- [x] 4.1 Delete `sim_gantry_demo`, the gantry program build in `test/CMakeLists.txt`, `test/sim_unit/sim_machine_tests.cpp`, `test_sim_machine.py`, `test_configurator_sim_machine.py`, `test_configurator_sim_machine_page.py`, `fake_sim_machine.py`, and machine cases in the fake sim and sim page tests.
- [x] 4.2 Move borrowed fixtures to `examples/virtual-plant` or own fixtures: `test_codesys.py` (drop `gantry-cell.json` golden; multi-drive override tests get a fixture), `test_notes.py`, `test_configurator_bits_page.py`, `test_configurator_server.py`, `test_project.py`, `tools/editor-hook/tests/test_snapshot.py`, `test/ci/test_rename.py`.
- [x] 4.3 Remove the `GantryCell` page sweep class and the gantry/machine entries in `.github/ci/page-test-times.json`, `tool-test-times.json` and the `sim_tests` timing list in `test/CMakeLists.txt`.
- [x] 4.4 `rg -i "gantry|sim_machine|machine file|machine tab|three\.js|sim_panel|sim_person|safe_torque"` outside `openspec/changes/archive` finds nothing left over (generic uses of "machine" excepted).

## 5. Docs

- [x] 5.1 `docs/simulator.md`: remove Simulated machine and the machine mentions in the simulation file and control protocol parts; `docs/configurator.md`: remove the Machine tab; `docs/tour.md`: remove chapter 15; `docs/cia402.md`: remove the `sim_gantry_demo` line; `docs/development.md`: remove the example from the sweep and layout.
- [x] 5.2 README: remove the Simulated machine bullet and the example from the layout block.
- [x] 5.3 Bump the PC tools version (minor).

## 6. CI time

- [ ] 6.1 Compare the PR's CI wall and summed job time with the main baseline and note both in the PR.
