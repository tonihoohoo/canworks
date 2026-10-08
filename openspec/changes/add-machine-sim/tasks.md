## 0. CI baseline

- [ ] 0.1 Record the baseline: wall time and summed job time of the five last green `CI` runs on `main` before the branch (Actions API), and their median; put the table in the PR description.

## 1. CI savings first (so the new tests land on a faster base)

- [ ] 1.1 Build action: install `ccache`, restore and save its directory (`main` saves, pull requests only restore), set `CMAKE_CXX_COMPILER_LAUNCHER` and `CMAKE_C_COMPILER_LAUNCHER`, print `ccache -s` after the build, cap 300 MB; verify a second push to the branch shows cache hits and a shorter build step.
- [ ] 1.2 vcan jobs: pass `targets` with the plugin, the standalone simulator and the helper programs the vcan steps start; verify every vcan step still passes and `unit_tests`, `sim_tests`, `sim_unit_tests` are not built there.
- [ ] 1.3 `test_shard.py --timings FILE`: split whole classes by recorded seconds (largest first onto the lightest shard, unknown classes as the median); add `.github/ci/page-test-times.json` from a run's per-class times; use it for the `configurator-page` shards; add unit tests for the split; verify every page test runs once and the shards are within about a third of each other.

## 2. Machine model (plugin)

- [ ] 2.1 `schema/canopen-machine.v1.schema.json` and the `machine` key in the simulation file v2 schema.
- [ ] 2.2 `plugin/sim/sim_machine.{h,cpp}`: load the file (checks the schema can't express, with network and element in each message), joints from actual positions, home flags, limit switches and hard stops into the drive's second input set, load torque, gripper, conveyors and seeded feeder, presence sensors, slotted fixture with pallet change, parts state machine with gravity, contacts that block the moving joint, counters.
- [ ] 2.3 Drive model: second input set OR-ed with the fault's, `load_permille` in 0x6077 and in CST acceleration; precedence level `machine` for I/O objects.
- [ ] 2.4 Engine: step the machine in `Tick()` after the devices at its own `tick_ms`; refuse a machine on a real network with a log line; `sim_machine`; `sim_fault`/`sim_clear` with `machine` targets (jam, sensor stuck, slip, feeder stop or empty, misaligned part); machine conditions in `wait` and `expect`; active machine faults in `sim_status`.
- [ ] 2.5 Unit tests in `sim_unit_tests` on a virtual clock: each rule above, a full 3 × 3 pallet with change in simulated 60 s, determinism (two runs give the same counters), and step time for 50 parts.
- [ ] 2.6 `sim_tests` case `sim_gantry_demo` (needs STruC++, as the CiA 402 cases): the example program on the simulated bus with its machine; home, place two parts, jam Z (EMCY 0x8611), reset and recover; under 15 s.

## 3. Deploy tool and configurator

- [ ] 3.1 Machine file check in the deploy tool's check, the configurator's problems and the bundle (carry `machine.json`); unit tests for each check message in the contract spec.
- [ ] 3.2 Configurator server: `/api/sim/machine` over a kept-open diagnostics connection, machine fault calls; tests with the stub runtime.
- [ ] 3.3 Vendor three.js 0.169 core and the addons the view uses into `configurator/static/three/` with an import map; licence in the notices.
- [ ] 3.4 `machine_scene.js`: build the gantry, conveyor, pallet, stack light, fence and floor from the machine file (T-slot profiles, rails, carriages, servo motors, energy chains, gripper, belt, sensor beam, slots), pose from a snapshot, snapshot interpolation; no renderer.
- [ ] 3.5 `machine_view.js`: renderer with the High and Low pipelines and the automatic fall back, saved preset, no-WebGL panel-only mode, labels, tool path and move target, fault marking, stack light and drive lamps, camera presets and follow tool, click to open a node, side panel, fault buttons (disabled without `allow_changes`), offline preview at home positions, "no data" after 1 s.
- [ ] 3.6 Page tests (no WebGL): scene from the example file has every named part; pose for a recorded snapshot puts the tool where the joints say; interpolation over uneven snapshots is smooth with no step back; panel values; fallback message; disabled fault buttons; put the new classes' times into the page timing file.

## 4. Example

- [ ] 4.1 `examples/gantry-cell/`: config (network `motion` on `sim1`, simulated; nodes 4, 5, 6 SD-402 axes with cyclic CSP, node 10 DIO-16; SYNC from the PLC cycle; diagnostics with a token verifier and changes allowed), simulation file v2 (device `tick_ms` 1, start positions near home, `test` scenarios: throughput, jam and recovery, PLC stop, stuck sensor), machine file, README.
- [ ] 4.2 Demo program `gantry_demo.st` from the generated project: power, homing, minimum-jerk straight-line XY in CSP on both axes, Z blended into the end of the XY move, gripper handshake, pallet change, fault reaction and recovery; verify it compiles with STruC++ and passes the `test` scenarios on the local simulator runtime by hand.

## 5. Docs

- [ ] 5.1 `docs/machine.md` (machine file reference, what the model does and doesn't, faults and conditions, the Machine view, presets and fallbacks); updates to `docs/simulator.md`, `docs/configurator.md`, `docs/cia402.md` (pointer), `docs/tour.md` (Machine chapter), README (feature list, docs list, example).
- [ ] 5.2 Bump the deploy tool minor version (next free at apply time).

## 6. CI time check

- [ ] 6.1 Compare the PR's green CI run with the baseline from 0.1: wall time and summed job time both equal or lower; put the numbers and where the time was saved in the PR description. If not, trim per the design before asking for merge.

## 7. Checks by hand

- [ ] 7.1 Machine view on a real GPU: Windows (Chrome or Edge) and macOS (Safari or Chrome) at High; Low and the automatic fall back on an integrated GPU; WebGL turned off shows the panel only.
- [ ] 7.2 Tour Machine chapter end to end on the local simulator runtime.
- [ ] 7.3 Pi (simulated network, no hardware needed): run the example on the bench runtime and log the machine step time; it stays under 5 % of the step.
