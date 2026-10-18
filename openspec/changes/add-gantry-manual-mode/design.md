## Context

What is there today (main at f3701ba):
- The machine model reads drive positions and I/O output bits and writes drive inputs and I/O input bits (node 10, `0x6000:1`). The PLC program sees only CANopen devices.
- The Machine view polls `sim_machine` about 30 times a second and sends `sim_fault` / `sim_clear` through `POST /api/sim/request`, which needs `allow_changes`.
- `sim_override` can hold any input object of a simulated node, but it holds the value until it is released, so it has no answer for a browser that goes away while a key is down.
- The library has no `MC_Jog`. The demo runs all three axes in cyclic synchronous position mode (8). `CO402_CyclicPosition` follows one set-point per cycle with a step limit, which is what a jog needs.
- `main.st` step 95 (recover) lifts Z and then carries on with the part in hand or goes back to the conveyor.

## Goals / Non-Goals

**Goals:** manual operation and an emergency stop and safety scanner that behave like a real cell. The keyboard is a panel on the bus, the PLC decides what moves, a lost browser cannot leave an axis moving, and CI can test it.

**Non-Goals:** real safety functions or a safety PLC, analogue jog, teach-in, keys that move the model directly.

## Decisions

### The panel is an ordinary I/O module on the bus
Node 11 `panel` is the same made-up 16-in / 16-out CiA 401 device as node 10, shipped under its own file name `panel.eds` so it gets its own notes file (`panel.eds.notes.json`, device notes are per EDS file) naming each bit. On real cells, panel buttons are usually wired to a generic I/O module, and the button names live in the program. The notes and bit channels (`add-bit-channels`) give the same names in the configurator, the trace and the generated declarations.

The other ways considered: writing PLC variables directly skips the bus and would not work the same on a real machine. A plain CAN joystick device would make the program decode frames, and is left for analogue jog later. Using node 10's second byte mixes machine wiring with panel wiring.

Panel bits (TPDO1 maps both input bytes, event-driven; RPDO1 maps output byte 1):

| Object | Bit | Name | Kind | Key |
|---|---|---|---|---|
| 0x6000:1 | 0 | `manual` | switch | M |
| 0x6000:1 | 1 / 2 | `jog_x_plus` / `jog_x_minus` | momentary | → / ← |
| 0x6000:1 | 3 / 4 | `jog_y_plus` / `jog_y_minus` | momentary | ↑ / ↓ |
| 0x6000:1 | 5 / 6 | `jog_z_up` / `jog_z_down` | momentary | Page Up / Page Down |
| 0x6000:1 | 7 | `fast` | momentary | Shift |
| 0x6000:2 | 0 | `gripper` | momentary | G |
| 0x6000:2 | 1 | `conveyor` | momentary | C |
| 0x6000:2 | 2 | `home` | momentary | H |
| 0x6000:2 | 3 | `start` | momentary | Enter |
| 0x6000:2 | 4 | `stop` | momentary | S |
| 0x6000:2 | 5 | `reset` | momentary | R |
| 0x6000:2 | 6 | `enable` | momentary | Space |
| 0x6000:2 | 7 | `estop` (auxiliary contact, on while pressed) | latching | E |
| 0x6200:1 | 0-3 | lamps `manual`, `homed`, `fault`, `auto` | lamp | |

The safety relay's feedback and the scanner's warning field come in on node 10, the machine's I/O module, which has free bits: 0x6000:1 bit 6 `safety_ok` (on while the relay is closed) and bit 7 `scanner_warning` (on while someone is in the warning field). With 16 inputs used, the panel has no separate relay reset button. `reset` is wired to both the relay's reset input and the PLC, as on many small cells: one press resets the relay and the drives.

The keys live in the machine file, so another machine can use another map. A key the view needs for itself (Tab, Escape) is refused by the check.

### Momentary buttons are a lease in the simulator
`sim_panel {network, button, pressed}` presses a momentary button for 500 ms. The view repeats the press every 200 ms while the key is down, and sends a release on key up. If the browser closes, the tab hides, the machine closes or the connection drops, the simulator releases the button by itself within 500 ms. A switch keeps its position with no lease. Over a lost connection, MANUAL stays MANUAL, which keeps the machine from starting by itself.

Scenario `panel` steps hold buttons until the scenario releases them, with no lease, so tests are deterministic on a virtual clock.

Alternative: plain `sim_override` from the view, with no plugin change. It was rejected because a stuck key keeps an axis jogging until a limit switch stops it.

### A virtual safety relay in the machine model, not in the PLC
On a real cell the emergency stop and the scanner do not go through the standard PLC. They are wired to a safety relay that removes the drives' power, and the PLC only reads the relay's feedback to react properly. The machine model copies that. A `safety` section has:
- `relay`: its inputs (emergency stop buttons and scanner protective fields, by name), the reset button, `stop_delay_ms` (stop category 1, default 300), the joints it switches off (safe torque off on their drives) and the conveyors it cuts, and the feedback input binding;
- `scanners`: per scanner, a name, a mounting point, and a warning field and a protective field as boxes on the floor, plus the warning output binding;
- a joint's `brake: true` (here on Z), so the joint holds when its drive's power stage is off.

Sequence on a trip: feedback off at once; the PLC has `stop_delay_ms` to stop the axes; then safe torque off on every listed drive and the conveyor stops. A braked joint holds, and the others coast down at the drive model's coast deceleration. A part on the belt stops with it, and the gripper keeps its state (a pneumatic valve holds its position). The relay closes on a rising edge of its reset button only while every emergency stop is released and every protective field is clear. There is no automatic restart, as for a scanner guarding an opening a person can walk through.

The gantry's scanner sits at the front right corner of the frame and covers the open front and right sides of the fence. Its warning field is 1200 mm deep and its protective field 600 mm.

The person is a point on the floor with a 300 mm radius. `sim_person {network, at: [x, y] | null}` places or removes them (`allow_changes`), and a scenario step `person` does the same. Several people are not modelled.

The drive model's new safe torque off input sits next to the existing switch inputs. While it is on, operation is impossible: the statusword drops to "switch on disabled" with "voltage enabled" off, the demand stops, and the actual velocity falls at the coast deceleration (a drive setting, default 2000 units/s² scaled by counts). There is no EMCY, as many drives only report safe torque off in a status. `sim_status` shows it. When the input goes off, the drive stays in "switch on disabled" until the master runs the enable sequence.

### Enabling is the program's choice
`enable` (Space) is a panel button like the others. The example program has `needEnable : BOOL := FALSE`. When it is TRUE, the jog buttons only act while `enable` is held as well, as with a real enabling switch. When FALSE, jogging needs only the jog keys, which is easier on a keyboard.

### The example program in MANUAL
- **Entering MANUAL** from any step: every axis goes to the jog logic with its jog velocity starting from the axis's actual velocity, so a running move ramps down to a stop (deceleration 1000 mm/s²) instead of the set-point freezing. The conveyor stops. The gripper keeps its state.
- **Jog:** per axis, the target velocity is ±20 mm/s (±150 mm/s with `fast`) while exactly one of its two buttons is held, and 0 otherwise. The velocity ramps at 1000 mm/s². The set-point advances by velocity × cycle time and goes to `CO402_CyclicPosition` with `MaxVelocity` 200 mm/s. Several axes can jog at once.
- **Soft limits:** once homed, the set-point stays inside the joint's travel (0-900, 0-600, 0-300 mm), and the ramp starts slowing early enough to stop at the limit. Before homing, jogging is limited to 20 mm/s with no soft limits; the limit switches and hard stops still stop and fault the drive as on a real machine.
- **Buttons:** `gripper` and `conveyor` toggle on a rising edge. `home` runs the homing sequence (Z, then X and Y). `reset` resets faulted drives (no automatic reset in MANUAL).
- **Back to AUTO:** the program waits with the `auto` lamp off until `start`. Then, if not homed, it homes; otherwise it goes to step 95 (recover). `stop` in AUTO clears `start`, so the cell stops after the part in hand. A part placed by hand is not counted; the pallet slot count stays the program's.
- **Lamps:** `manual` in MANUAL, `homed` once homed, `fault` while any drive is in FAULT or the relay is open (blinking at 1 Hz while waiting for reset), `auto` while the sequence runs.
- **Safety stop:** when `safety_ok` drops, in any mode, every axis goes to the jog logic with target velocity 0 and the quick-stop deceleration of 4000 mm/s², so the axes stop within the 300 ms delay from 600 mm/s. The conveyor output goes off and the sequence remembers where it was. When `safety_ok` comes back, the program powers the drives again (MC_Power off and on) and stays stopped. AUTO needs Start (then step 95, recover); MANUAL jogs at once. The homing is kept, because the drives keep their position with the power stage off.
- **Warning field:** while `scanner_warning` is on in AUTO, the XY and Z velocities are cut to 25 % for new moves.

### The Machine view
- A Panel block in the side panel, built from the machine file, shows the mode switch, the buttons (label and key), and the lamps, each lit from `sim_machine`.
- Keys act only while the 3D stage has focus. A click on the stage gives it focus, the stage outline and a "Keyboard on" label show it, and Escape or a click outside takes it away. Browser key repeat is ignored; the view repeats presses itself.
- Releases happen on keyup, blur, `visibilitychange`, tab or view switch, and on a failed `sim_machine` poll.
- The emergency stop is drawn as a red mushroom button, larger than the others, with its state. The relay shows as closed, tripped or waiting for reset, and the stack light shows red while the relay is open.
- The scanner is drawn at its mounting point, with its two fields on the floor as translucent areas: yellow for warning, red for protective, brighter while occupied. The Person tool places a person figure where the floor is clicked, drags them while the button is held (sending `sim_person` at most every 100 ms), and removes them with a second click on the tool.
- Without `allow_changes` the buttons are disabled with the reason, as the fault buttons are. Offline, the panel shows the machine file's buttons, disabled.

## Risks / Trade-offs

- **Latency:** key → configurator → diagnostics channel → panel TPDO → PLC scan (10 ms) → RPDO → drive on SYNC. Expected tens of milliseconds, which is enough for a jog. A manual task measures it on the local simulator runtime.
- **The drawing delay:** the view draws a fixed delay behind the newest snapshot, so on screen the response looks a little slower than the PLC's. That is accepted.
- **Safety wording:** the relay, scanner and emergency stop are models for trying a program. The docs say plainly that nothing in canworks is a safety function and that a real cell needs certified safety devices.
- **Dependency:** the example's BOOL names come from bit channels. If `add-bit-channels` changes shape, only the example's declarations change.

## Migration Plan

None. A machine file without `panel` works as before.
