## 0. Before

- [x] 0.1 Apply after PR #44 (rename to canworks) has merged; start the branch from main. Note the CI baseline: median wall and summed job time of the last 5 green `main` push runs with code changes (278 s wall, 1983 s summed, runs for a6a60a6, e896df4, 27ebc0e, 305c643, b228d1a).

## 1. Configurator

- [x] 1.1 `sim.js`: a fourth tab `machine` ("Machine") after Live values, Simulation file and Scenarios, shown only when the open network's section names a machine file; selecting it renders the Machine view (`machine_view.js`) and gives it the whole content area.
- [x] 1.2 `index.html`, `app.js`: remove the `nav-machine` sidebar item and the `machine` view; links that opened it (problems, tour hints) open Simulation on the Machine tab; switching networks falls back to Live values when the new network has no machine.
- [x] 1.3 Page tests: the machine page tests open Simulation → Machine; add a check that the sidebar has no Machine item and that a network without a machine file has no Machine tab.

## 2. PC tools and schema

- [x] 2.1 Move `canworks/machine.py` to `canworks/simmachine.py` and update its importers (`simfile.py`, configurator, bundle, CLI).
- [x] 2.2 Rename `schema/canworks-machine.v1.schema.json` and the copy in `canworks/schema/` to `canworks-sim-machine.v1.schema.json` (with its `$id`); update `canworks-sim.v2.schema.json`, the loader and `test/ci/test_rename.py` (it keeps its case for the earlier rename script's mapping, which is still what that script does).
- [x] 2.3 Rename tests: `test_machine.py` → `test_sim_machine.py`, `test_configurator_machine.py` → `test_configurator_sim_machine.py`, `test_configurator_machine_page.py` → `test_configurator_sim_machine_page.py`, `fake_machine.py` → `fake_sim_machine.py`; rename the keys in `.github/ci/page-test-times.json`.

## 3. Docs

- [x] 3.1 `docs/simulator.md`: title "Simulator", parts "Simulated devices" (today's content) and "Simulated machine" (today's `docs/machine.md`, its sections one level down); remove `docs/machine.md`.
- [x] 3.2 `docs/configurator.md`: the Machine section becomes the Machine tab of the Simulation view section.
- [x] 3.3 `docs/tour.md` chapter 15 "Simulated machine" (opens Simulation → Machine); `docs/cia402.md`, `README.md` (feature bullet, layout, docs list, schema name) and `examples/gantry-cell/README.md` link the new section.
- [x] 3.4 Check every Markdown link in the repository (outside `openspec/changes/archive/`) resolves to a file and anchor, with a one-off script; nothing links to `docs/machine.md` or `#machine-view`.

## 4. Verify

- [x] 4.1 Local: tools tests, page tests, `ctest`, `openspec validate --all --strict`, banned-word check.
- [x] 4.2 CI green; wall and summed job time at or under the baseline from 0.1, both stated in the PR description. PR #46: 220 s wall, 1671 s summed.
- [ ] 4.3 By hand on a PC: open the gantry example in the configurator, Simulation shows the Machine tab and the 3D view works offline and against the local simulator runtime. Offline part passed 2026-10-09 on Windows (Chrome, integrated Intel GPU); it found intermittent module-load failures, fixed by a larger listen backlog in 0.43.1. The live part waits for Docker on that PC.
