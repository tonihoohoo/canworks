# Machine model

A simulated network can carry a made-up machine on top of its simulated devices: an XYZ gantry with a gripper, belt conveyors with feeders, presence sensors and a pallet with slots. The machine reads the drives' actual positions and the master's output bits, and writes the drives' inputs (home switch, limit switches, blocked), their load torque and the input bits its sensors report. The PLC program does not know it is not a real machine: it sees CiA 402 drives and a CiA 401 I/O module on the bus, as the [simulator](simulator.md) gives them, and its outputs move parts.

The configurator's **Machine** view draws the machine in 3D from the same file and the runtime's state ([The Machine view](#the-machine-view)). [`examples/gantry-cell`](../examples/gantry-cell/README.md) is a complete project, and the [tour](tour.md#15-machine) walks through it.

A machine only runs on a simulated network (`adapter.simulate`). On a network with real devices the plugin logs that it is not used.

## What the model does, and does not

It is kinematic: joints follow their drives, and parts go through a small set of states (on a belt, held, falling, placed, misplaced, on the table). Contacts are axis-aligned boxes. Only gravity acts on a falling part.

- **Joints** take their position from the drive's actual position 0x6064 (`counts_per_mm`, `offset_mm`, `direction`). The home flag sets the drive's home switch input at and below its position; the limit switches set the positive and negative limit inputs at and beyond theirs; at a hard stop, or when the tool or the part in hand would hit the table, the conveyor, the pallet or another part, the joint is blocked in that direction and the drive's following error does the rest, as on a real axis.
- **Load**: each joint gives its drive a load in per mille of rated torque, `hold_permille` plus `per_kg_permille` for the part in hand plus `per_m_s2_permille` for the joint's acceleration. 0x6077 shows it while operation is enabled, and in cyclic synchronous torque mode the drive accelerates by the target torque less the load.
- **Gripper**: its fingers take `stroke_ms` to close or open between `open_mm` and `closed_mm` along `axis`. Closing on a part within `pick_tolerance_mm` of the tool point picks it, and "gripped" comes on. Opening drops it: on a free slot within `place_tolerance_mm` it is placed, elsewhere it falls and lands where it lands.
- **Conveyors** run while their run bit is on, at `speed_mm_s`, and stop each part at the end, the next one `gap_mm` behind it. A feeder puts a part at the start every `every_s` seconds (a random time between the two values, from the machine's `seed`), when there is room.
- **Sensors** are boxes: on while a part (or the tool, `"detects": "tool"`) is in the box.
- **Fixtures** have `count` slots at `pitch` from `origin`. With `change`, a rising request bit takes the pallet away along `move` in `time_s` and brings an empty one back; the ready bit is off while it changes.

Not modelled: friction, part orientation beyond a yaw, stacking on top of parts, more than one gripper, robot arms, and any other kind of machine than `gantry_xyz`. At most 50 parts are on the machine at a time; the feeder waits while there are 50.

The model steps every `tick_ms` (default 2 ms) on the simulator's loop, after the devices, in sub-steps of at most 5 ms when the loop is late. It is deterministic: the same program on the same file places the same parts in the same slots.

## The machine file

The simulation file (version 2) names it per network, relative to itself:

```json
{
  "schema_version": 2,
  "networks": {
    "motion": { "machine": "machine.json", "nodes": { "4": { "tick_ms": 1 } } }
  }
}
```

The deploy tool carries it into the upload with the simulation file. Its JSON Schema is [`schema/canopen-machine.v1.schema.json`](../schema/canopen-machine.v1.schema.json). Units are millimetres: x and y on the table, heights above the table top. An I/O binding is always `{ "node": 10, "object": "0x6200:1", "bit": 1 }`. Outputs (conveyor run, gripper close, change request) must be objects the master writes, inputs (sensors, gripped, change ready) objects it does not write.

| Key | What it is |
|---|---|
| `schema_version` | 1. |
| `name`, `kind` | A name for messages and the view; `kind` is `gantry_xyz`. |
| `units` | `mm` (the only unit). |
| `tick_ms`, `seed` | Model step (1 to 100 ms, default 2) and the feeder's random seed (default 1). |
| `joints` | `x`, `y` and `z`: `node` (a simulated CiA 402 node with an `axis` in the config), `travel` [min, max], `counts_per_mm` (default 1000), `offset_mm`, `direction` (1 or −1), `down` (z: a positive position lowers the tool), `home_flag`, `limits` [negative, positive], `hard_stops` [negative, positive], `load` (`hold_permille`, `per_kg_permille`, `per_m_s2_permille`). |
| `tool` | `type` `gripper`, `close` (output), `gripped` (input), `stroke_ms`, `open_mm`, `closed_mm`, `axis` (`x` or `y`), `offset` [x, y, height] of the tool point at joint positions 0, `pick_tolerance_mm`, `finger` [thickness, width, height]. |
| `parts` | Part kinds by name: `size` [x, y, height], `mass_kg`. |
| `conveyors` | `name`, `from` and `to` [x, y] of the belt's centre line, `width`, `height` (belt top), `speed_mm_s`, `gap_mm`, `run` (output), `feed` (`part`, `every_s` [min, max]). |
| `sensors` | `name`, `at` [x, y, height] and `size` of the box, `detects` (`part` or `tool`), `output` (input bit). |
| `fixtures` | `name`, `slots` (`origin` [x, y] of the first slot's centre, `pitch`, `count` [columns, rows]), `height` (pallet top), `margin`, `place_tolerance_mm`, `change` (`request` output, `ready` input, `time_s`, `move` [x, y]). |
| `visual` | For the Machine view only: floor, table, frame, fence, stack light, colours. The simulator does not read it. |

Element names (conveyors, sensors, fixtures) are unique and not `x`, `y`, `z` or `tool`. The deploy tool's check, the configurator's problems and the plugin check what the schema cannot: joints on simulated nodes with an axis, bound objects in the node's EDS with room for the bit, outputs written by the master and inputs not, no input bound twice, travel, limits and hard stops in order, part kinds defined. Each message names the network and the element.

## Faults and conditions

Machine faults go through the same calls as device faults, with `machine` naming the element instead of `node`:

| Fault | Element | Effect | Cleared by |
|---|---|---|---|
| `{"jam": true}` | a joint | The joint does not move; the drive faults on its following error (EMCY 0x8611). | `jam` |
| `{"stuck": "on"}`, `{"stuck": "off"}` | a sensor | The sensor reports on or off whatever is there. | `stuck` |
| `{"slip": true}` | `tool` | The gripper drops what it holds, once. | (nothing to clear) |
| `{"feeder": "stop"}`, `{"feeder": "empty"}` | a conveyor with a feeder | No new parts until cleared (both act the same; the name says why in the log and the view). | `feeder` |
| `{"misaligned_mm": 15}` | a conveyor with a feeder | The next part fed is that far off the belt's centre line. | `misaligned_mm` (before it is fed) |

`all` clears every fault of the element. In a scenario:

```json
{ "machine": "z", "fault": { "jam": true } },
{ "after_ms": 500, "machine": "z", "clear": "jam" },
{ "expect": { "machine": "placed", "ge": 4 }, "within_ms": 40000 }
```

A condition's `machine` names a counter (`fed`, `picked`, `placed`, `misplaced`, `dropped`, `pallets`), a sensor (0 or 1), a fixture (parts in its slots) or a joint (position in mm). The Machine view has a button for each; on the diagnostics channel they are `sim_fault` and `sim_clear` with `machine` in place of `node` (`{"op": "sim_fault", "machine": "z", "fault": {"jam": true}}`), and `sim_machine` returns the whole state (below). Faults need `allow_changes`, as device faults do.

## State

`sim_machine` (read only) answers with the network, a time stamp `t_us`, a sequence number `seq`, the model's step time (`step_us`, `step_max_us`) and:

- `joints`: per joint `node`, `position` (mm), `velocity`, `demand`, `actual_counts`, the drive's `state`, `mode`, `statusword`, `fault`, `error_code` (0x603F, while it is not 0) and `torque` (0x6077, per mille);
- `tool`: `position` [x, y, height], `opening`, `closed`, `holding`;
- `parts`: `id`, `kind`, `position` [centre x, centre y, bottom height], `yaw`, `state`;
- `sensors`, `conveyors` (`running`, `travel`), `fixtures` (`offset`, `ready`, `changing`, `filled`), `counters` and the `faults` in force.

The snapshot of a machine with 50 parts is about 4 KB. `sim_status` carries the counters and faults too.

## The Machine view

**Machine** in the configurator's sidebar, under Runtime after **Simulation** ([configurator.md](configurator.md#machine-view)); it shows when the network's simulation section names a machine file. It builds the gantry, conveyor, pallet, stack light, fence and floor from the file, and moves them from `sim_machine` answers it polls over the diagnostics connection, interpolating between them so the motion is smooth whatever the poll rate.

- **Quality**: High (soft shadows, ambient occlusion, bloom on lamps, anti-aliasing) or Low; it drops to Low by itself, and says so, when the frame rate stays under 28 per second for 3 s, and remembers your choice on this PC. Without WebGL it shows the side panel with live values and says the 3D view needs WebGL.
- **Labels** on the drives (node, position, mode or EMCY code), sensors and fixtures, the **tool path** (the last few seconds of the tool point) and the current set-point as a marker; an axis in fault turns red, the stack light shows the cell's state and each drive has a lamp.
- **Camera**: **Overview**, **Top** and **Follow tool**; orbit, pan and zoom with mouse or touch. Click a motor or carriage, an axis row of the panel or an axis label to open that node in **Online**.
- **Side panel**: per axis its state, mode, statusword, position in mm and counts, following error against the window (0x6065) and torque; the machine's I/O bits, the counters, the last faults, and buttons for the faults above and **Clear all** (disabled, with the reason, without **Allow changes**).
- Offline, it shows the machine at its home positions as a preview; with no answer for 1 s it holds the last pose and says "no data". It polls only while it is open and the browser tab is visible.

The 3D library, three.js 0.169, ships with the PC tools, so the view needs no internet.
