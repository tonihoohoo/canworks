## Context

Explore notes and a working prototype page (made-up gantry, the drive model, PLC sequence and machine model all in the browser) are in the project files: `research/3d-motion-sim-option-b-2026-10-08.md` and `research/3d-motion-sim/gantry-cell.html`. What the engine has today:
- one `Simulator` per network on that network's Lely loop. `Tick()` steps each device on its own `tick_ms` (default 10 ms, minimum 1), then value sources, overrides and scenarios;
- the drive model's inputs `DriveInputs{blocked, positive_limit, negative_limit, home_switch}`, set only by the `drive_input` fault;
- expressions that read other devices of the same network;
- `sim_*` requests that reach the engine on the bus loop.

Nothing turns an axis position into machine events, and nothing draws it.

CI baseline (Actions API, `CI` workflow on `main`): runs on c7212d1 and 60d5338 (2026-10-08) took 4 min 14 s and 4 min 04 s wall, and 1881 s and 1766 s of summed job time:

| Job (seconds) | c7212d1 | 60d5338 |
|---|---|---|
| plugin | 159 | 185 |
| vcan 1/2/3 | 199 / 210 / 204 | 206 / 227 / 222 |
| tools 1/2/3 | 151 / 143 / 206 | 177 / 192 / 169 |
| configurator-page 1/2/3 | 164 / 185 / 237 | 135 / 89 / 142 |

Inside a job, the shared build action takes 63-89 s, of which the cmake build is about 55 s for a full build. The page shards are split by test count, not time: 89 s against 237 s across those two runs.

## Goals / Non-Goals

**Goals:**
- a PLC motion program can be tried against a machine that reacts through ordinary CANopen I/O and drive inputs;
- the machine can be watched in a 3D view that looks like a real cell;
- a CI test shows the example program works;
- CI wall time and summed job time do not grow.

**Non-Goals:**
- physics or dynamics beyond a simple load term;
- robot arm kinematics;
- importing the user's own CAD;
- a live 3D view of a real machine;
- 3D replay of traces;
- a machine model on real networks.

## Decisions

### The machine model lives in the simulator engine
`plugin/sim/sim_machine.{h,cpp}`: a `MachineModel` owned by the `Simulator` of the network whose section names a machine. `Tick()` steps it after `TickDevice` (actual positions are fresh) and before `RunSources`, at its own `tick_ms` (default 2 ms; the engine's loop timer runs at the smallest tick it has). It reads drive actual positions through the engine's object access and writes:
- drive inputs, through a second input set on `DriveModel` that is OR-ed with the fault's set;
- a new `load_permille`;
- I/O input objects, at a new precedence level `machine`, between value sources and the drive model.

So an override or `set` from a test still wins over a sensor. Because the model is part of the engine, the standalone `openplc-canopen-sim` runs it unchanged.

Alternative: run the model in the configurator and push values with `sim_override`. Rejected: a PC-to-runtime round trip per step can't keep step with a 4 ms SYNC, it stops when the configurator closes, and CI would need a browser.

### Kinematic rules, no physics engine
- joints follow drive positions;
- parts have a state machine: belt → held → falling → placed, table or belt;
- falling uses gravity on the vertical axis only;
- contacts are axis-aligned boxes: tool, fingers and held part against parts, fixtures and table top. A contact clamps the moving joint by setting `blocked` on its drive, so the drive model makes the following error itself.

Deterministic for a given input sequence, cheap (tens of µs per step for 50 parts), and portable. MuJoCo or Bullet would make the image and CI heavier and make tests depend on solver tuning; nothing in a pick-and-place demo needs contact dynamics.

### Machine file separate from the simulation file
`canopen/machine.json`, named from the network's section (`"machine": "machine.json"`). The configurator needs it offline to draw the scene, it has its own schema, and the `visual` part means nothing to the plugin, which ignores it. The deploy tool and the editor upload carry it next to `simulation.json`.

```json
{ "schema_version": 1, "name": "Gantry cell", "kind": "gantry_xyz", "units": "mm", "tick_ms": 2,
  "joints": {
    "x": { "node": 4, "travel": [0, 900], "counts_per_mm": 1000, "home_flag": 0, "limits": [-5, 905], "hard_stops": [-12, 912] },
    "y": { "node": 5, "travel": [0, 600], "counts_per_mm": 1000, "home_flag": 0, "limits": [-5, 605], "hard_stops": [-12, 612] },
    "z": { "node": 6, "travel": [0, 300], "counts_per_mm": 1000, "home_flag": 0, "down": true,
           "load": { "hold_permille": 165, "per_kg_permille": 140, "per_m_s2_permille": 60 } } },
  "tool": { "type": "gripper", "close": { "node": 10, "object": "0x6200:1", "bit": 1 },
            "gripped": { "node": 10, "object": "0x6000:1", "bit": 4 }, "stroke_ms": 120, "open_mm": 96 },
  "parts": { "box": { "size": [80, 60, 50], "mass_kg": 0.4 } },
  "conveyors": [ { "name": "infeed", "from": [-610, 480], "to": [160, 480], "speed_mm_s": 160,
                   "run": { "node": 10, "object": "0x6200:1", "bit": 0 }, "feed": { "part": "box", "every_s": [2.4, 4.0] } } ],
  "sensors": [ { "name": "part_at_pick", "at": [120, 480], "size": [20, 120, 60], "detects": "part",
                 "output": { "node": 10, "object": "0x6000:1", "bit": 3 } } ],
  "fixtures": [ { "name": "pallet", "slots": { "origin": [640, 280], "pitch": [120, 120], "count": [3, 3] }, "place_tolerance_mm": 12,
                  "change": { "request": { "node": 10, "object": "0x6200:1", "bit": 2 },
                              "ready": { "node": 10, "object": "0x6000:1", "bit": 5 }, "time_s": 3.3 } } ],
  "visual": { "frame": [1100, 900], "table_height": 800, "colors": { "carriage": "#d9951f" } } }
```

`kind` selects the built-in kinematics and the built-in drawing. `gantry_xyz` is the only kind in this change. The feeder's random intervals use a seeded generator (seed in the file, default fixed) so runs repeat.

### `sim_machine`: one answer per frame, smoothed in the view
Read-only, token only, served on the bus loop like the other `sim_` requests. About 1-2 KB for the example, at most 16 KB for 50 parts. The configurator server keeps one diagnostics connection per runtime open for it (the online view's connection, not a new TLS login per poll). The page polls `/api/sim/machine` about every 33 ms with one request in flight at a time. The page draws a fixed 100 ms behind the newest snapshot and interpolates between the two snapshots around that time by `t_us`: positions linearly, parts by id, state changes at the snapshot that has them. Jitter in the network and the event loop then never shows as stutter.

### The 3D view: three.js, vendored, scene apart from rendering
- **Library:** three.js 0.169 (MIT) core module and the addons the view uses (OrbitControls, RoomEnvironment, EffectComposer with RenderPass, GTAOPass, UnrealBloomPass, SMAAPass, OutputPass, RoundedBoxGeometry, CSS2DRenderer), copied into `configurator/static/three/` with an import map, about 0.9 MB. Its licence goes into the package's notices. No CDN, so the view works offline as the rest of the configurator does.
- **Look:** taken from the prototype:
  - `MeshPhysicalMaterial` with clearcoat for paint and metalness for aluminium and steel;
  - PMREM room environment for reflections, AgX tone mapping;
  - key light with 2048 PCF soft shadows, rim and fill lights, emissive ceiling strips;
  - GTAO, bloom thresholded so only lamps glow, SMAA;
  - geometry from code: T-slot profiles extruded from a real 40×40 slot outline, energy chains as instanced links on the bend curve, canvas textures (belt, floor, boxes).
- **Code layout:** `machine_scene.js` builds the scene graph from the machine file and poses it from a snapshot, with no renderer. `machine_view.js` adds the renderer, post-processing, camera, labels and panel. Page tests drive `machine_scene.js` without WebGL (three.js builds geometry without a GL context). Software WebGL in headless Chromium takes about 12 s for the first frame, which CI can't afford, so no CI test renders. A rendering check is a manual task.
- **Quality presets:** High as above; Low without GTAO and bloom, with 1024 PCF shadows. Automatic fall back after 3 s under 28 fps. The preset is kept in local storage.
- **Interaction:**
  - clicking objects through a raycast on named groups opens a drive's node in the online view;
  - fault buttons call `sim_fault` with machine targets, disabled without `allow_changes`.

### Machine faults and conditions use the existing requests
`sim_fault` and `sim_clear` take `"machine": "<element>"` instead of `node`, for example `{"machine": "z", "fault": {"jam": true}}`. Scenario steps carry the same objects. Conditions take `{"machine": "placed", "ge": 9}` or `{"machine": "part_at_pick", "eq": 1}`. `sim_status` lists active machine faults under `machine`.

### Example: one network, short start-up
`examples/gantry-cell/` rather than more networks in `virtual-plant`. The gantry is a whole topic, one network keeps the example readable, and the tour links it. Network `motion` on `sim1`, SYNC from the PLC cycle (task 4 ms), device `tick_ms` 1. Drive start positions are set close to home in the simulation file and the home speed is high, so the first part is placed about 8 s after PLC start. That keeps the CI case short.

### CI: add little, save more, measure
Added test time (estimated, summed over jobs):

| Test | Where | Added |
|---|---|---|
| machine model unit tests on a virtual clock (joints, flags, gripper, conveyor queue, slots, change, contacts, load, faults, full pallet in simulated 60 s) | `sim_unit_tests`, plugin job | ~2 s |
| `sim_tests` case `sim_gantry_demo`: the example program compiled by STruC++, plugin + simulated bus + machine, home and place two parts, jam then reset, 15 s limit | plugin job, ctest -j4 in parallel with the other cases | ~5 s of the step's wall |
| new sources compiled in every full build | plugin, vcan ×3 | ~4 s ×4 (cold cache) |
| schema, check, bundle and `/api/sim/machine` tests | tools shards | ~3 s |
| Machine view page tests without WebGL (scene from file, pose from snapshot, interpolation, panel, fallback message, fault buttons disabled) | lightest page shard | ~6 s |
| **total** | | **about +30 s summed, +5-10 s on the plugin job** |

Saved:

| Saving | How | Saved |
|---|---|---|
| compiler cache | `ccache` through `CMAKE_CXX_COMPILER_LAUNCHER` in the build action; cache restored by prefix, saved only by `main` runs (key: runner image, compiler and the CMake files' hash, plus the commit), size cap 300 MB | ~35-45 s on each of 4 full builds when sources barely change: ~150 s summed, ~40 s wall on plugin and vcan |
| vcan jobs build only their targets (`canopen_plugin`, `openplc-canopen-sim`, the slaves and helpers the steps start) | `targets` input already exists; listed per vcan job | the unit and simulation test binaries on a cold cache, ~15-20 s ×3 |
| page shards split by recorded time | `test_shard.py --timings .github/ci/page-test-times.json`; unknown classes count as the median; times refreshed when a shard drifts | no summed change; the slowest page shard ~237 s → ~195 s wall |
| **net** | | **about −120 s summed, −30 to −40 s wall** |

The PR shows both numbers against the median of the five last green `main` runs. If the savings come in lower than estimated, the change does not merge until the totals are equal or better. Options then: drop `sim_gantry_demo` to one part, or move the machine unit tests' full-pallet case to virtual time only. No test moves to another workflow and none is skipped.

## Risks / Trade-offs

- [ccache restores a cache from another compiler or flags] → the key includes the runner image and the CMake files' hash; ccache's own hashing of the compiler and the arguments catches the rest. A stale cache can only miss.
- [Actions cache space (10 GB per repo)] → saved only from `main` and capped at 300 MB; older keys age out.
- [Bus thread load from the machine model] → measured in `sim_gantry_demo` (step time in the log) and on the Pi as a hardware task; with 50 parts it must stay under 5 % of a 2 ms step.
- [No CI test renders] → `machine_scene.js` is tested without WebGL; a manual check on a real GPU (Windows, macOS) is a task; the prototype page already shows the pipeline works in today's browsers.
- [0.9 MB more in the PC tools] → accepted; the view is the feature.
- [Public repo] → made-up machine and devices only, geometry from code, no vendor CAD, no bench details.

## Open Questions

- Should the machine faults also be offered in the existing Simulation view, or only in the Machine view? The proposal says the Machine view. The Simulation view can list them read-only.
