## Why

The CiA 402 drive model, the cyclic synchronous modes and the PLCopen axis glue let a PLC program drive simulated axes. But a simulated axis is only numbers: nothing turns its position into a home switch, a limit, a part in a gripper or a collision. A motion program can't be tried against a machine, and nobody can see what it does. The explore (`research/3d-motion-sim-option-b-2026-10-08.md` in the project files; prototype page linked there) found that this needs two things. A machine model inside the simulator, so the PLC sees the machine through its normal CANopen I/O. And a 3D view in the configurator that shows the machine as it moves.

## What Changes

- **Machine model in the simulator:** a network's simulation file section can name a machine file (`machine.json`). The model then runs inside that network's simulator, on the simulator's clock, next to the drive model:
  - joints bound to CiA 402 axes (counts per unit, travel, home flag, limit switches, hard stops) feed each drive's home, limit and blocked inputs;
  - a gravity and payload load on a vertical joint shows in the drive's actual torque (0x6077) and slows cyclic torque mode;
  - a gripper tool driven by a CiA 401 output, with a "gripped" input;
  - belt conveyors started by an output, with a part feeder;
  - presence sensors that set inputs;
  - a slotted pallet fixture with a pallet change (request output, ready input);
  - parts that move on belts, are held, fall with gravity and rest in slots or on the table;
  - contacts that block a moving joint, so the drive raises its own following error.

  The model is kinematic, with simple rules and no physics engine. It is deterministic, the same in the plugin and the standalone simulator, and it works only on simulated networks.
- **Machine faults and conditions:**
  - faults: joint jam, sensor stuck on or off, gripper slip, feeder stop or empty, part misaligned on the belt;
  - scenario conditions on machine counters (placed, dropped, misplaced) and sensor states;
  - live control and scenario steps for both, as for device faults.
- **Machine state over diagnostics:** a read-only `sim_machine` request returns the whole machine in one answer (time stamp, joints, tool, parts, sensors, fixtures, counters) for a viewer polling about 30 times a second.
- **Machine view in the configurator:**
  - a 3D view of the machine, built from the machine file (built-in parametric gantry: T-slot profiles, rails, carriages, servo motors, energy chains, belt conveyor, pallet, stack light, guarding) with physically based lighting, soft shadows, ambient occlusion and anti-aliasing;
  - a light preset with automatic fallback on slow graphics, and a panel-only fallback without WebGL;
  - live labels on drives, sensors and fixtures, a tool-path trail with the current move's target, and fault highlighting;
  - camera presets (overview, top, follow tool) and a side panel with axes (state, mode, statusword, position, following error, torque), I/O bits, counters and the last EMCY;
  - machine faults injected from the view;
  - motion smoothed by interpolating between snapshots by their time stamps.

  The 3D library is shipped with the PC tools so the view works offline.
- **Example** `examples/gantry-cell/`: a made-up XYZ gantry pick-and-place cell on one simulated network. It has three SD-402 drives in cyclic synchronous position (nodes 4, 5, 6), one DIO-16 gripper I/O module (node 10), SYNC from a 4 ms PLC cycle, and device tick 1 ms. A demo program powers up, homes, makes coordinated straight-line XY moves with a jerk-limited profile in CSP, blends Z into the end of the move, uses the gripper handshake and the pallet change, reacts to faults and recovers after a reset. A simulation file holds `test` scenarios. A "Machine" chapter goes in the tour.
- **CI with no increase in total time:** the new tests run in time the run already has, and the change saves at least as much as it adds:
  - new tests: machine model unit tests on a virtual clock, one short simulated-bus case, the example's program compiled with STruC++ and run on a virtual clock against the drive and machine models, schema and check tests, and a configurator page test of the Machine view without WebGL rendering;
  - no new job, no new vcan test and no new step in another workflow;
  - savings: a compiler cache for the plugin build, the vcan jobs build only the targets they run, and the configurator page shards split by measured time.

  The change's pull request shows the wall time and summed job time against the median of the five green `main` runs before it. Both must be equal or lower.
- README: the machine view and the gantry example in the feature list and the docs list.

## Capabilities

### New Capabilities
- `canopen-machine-model`: the machine file, what the model does with joints, tool, conveyors, sensors, fixtures, parts, contacts and loads, its faults and conditions, and the `sim_machine` state.
- `canopen-machine-view`: the configurator's 3D Machine view, its quality presets and fallbacks, labels, path, camera, panel, fault injection and smooth motion.

### Modified Capabilities
- `canopen-device-simulator`: the drive model takes home, limit and blocked inputs and a load torque from the machine model as well as from faults; scenarios get machine conditions.
- `canopen-config-contract`: the machine file, its JSON Schema and its checks; the simulation file section may name it.
- `canopen-ci`: a compiler cache for the plugin build, vcan jobs build only their targets, configurator page shards balanced by time, and a change adding tests shows its CI time against the baseline.
- `canopen-virtual-example`: the tour links the gantry example and has a Machine chapter.

## Non-goals

- No physics engine, no dynamics beyond the simple load torque, no robot arm kinematics. SCARA, rotary tables and a generic link tree are later kinds.
- No import of the user's own CAD (glTF) and no live view of a real machine from the bus trace. Both are follow-up changes (B2), as is 3D replay of a saved trace (B3).
- No machine model on a real network (it never drives real devices' inputs).
- No new PLC library blocks unless the example shows a profile block is worth it. Coordination stays in the example's ST.

## Impact

- Plugin: new machine model in `plugin/sim/`, drive model inputs and load torque, `sim_machine` and machine fault handling in the simulator's control requests, the simulation file loader names the machine file.
- Schema: `schema/canopen-machine.v1.schema.json`; the simulation file schema v2 gets the `machine` key.
- Deploy tool: machine file check (nodes, axes, objects, bits, geometry), bundle carries `machine.json`, configurator API for `sim_machine` and machine faults, Machine view (static JS, vendored 3D library with its MIT licence in the notices), deploy tool minor version bump.
- Example: `examples/gantry-cell/` (editor project, `canopen/` with EDS files, config, simulation file, machine file, demo program, README).
- CI: `.github/actions/build-plugin` compiler cache and per-job targets, `ci.yml` vcan targets and page shard timing table; no new jobs.
- Docs: `docs/machine.md` (new), `docs/simulator.md`, `docs/configurator.md`, `docs/tour.md`, `docs/cia402.md` (pointer), README.
