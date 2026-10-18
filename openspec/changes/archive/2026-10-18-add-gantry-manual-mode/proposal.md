## Why

The gantry cell example only runs in automatic: the PLC program homes, picks and places by itself, and the operator can only watch or inject faults. A real cell also has a manual mode. The operator turns a key switch to MANUAL and jogs the axes, works the gripper and the conveyor from an operator panel, and the PLC does the driving: it reads the panel's buttons, keeps the soft limits and ramps, and decides what moves. The explore (`research/manual-mode-2026-10-18.md` in the project files) found that the simulator can give the same picture without bypassing the PLC. The keyboard becomes a simulated operator panel, a CiA 401 I/O module on the bus, and its buttons reach the program through PDOs like real wired buttons.

## What Changes

- **Operator panel in the machine file:** a new optional `panel` section names buttons and lamps bound to bits of a simulated I/O node, as other machine bindings are:
  - each button has a name, a label, a key and an input binding. It is either `momentary` (on while pressed) or a `switch` that keeps its position (the AUTO / MANUAL key switch);
  - each lamp has a name, a label and an output binding.
- **`sim_panel` request:** a request to press or release a panel button by name, which needs `allow_changes` like the fault buttons. A momentary button pressed this way is held for 500 ms and lets go by itself unless the press is repeated. A browser that closes or loses its connection while a key is down therefore never leaves an axis jogging. A switch keeps its position. `sim_machine` answers also carry the buttons' and lamps' states, and scenario steps can press and release buttons, so CI can test manual mode without a browser.
- **Emergency stop, safety scanner and a virtual safety relay:** a new optional `safety` section in the machine file:
  - an emergency stop is a latching panel button. Pressing it latches it, and pressing it again releases it, as a twist does on a real one. Its auxiliary contact is a panel input, so the PLC and the trace see it;
  - a safety scanner watches the cell's open side, with a warning field and a protective field on the floor. A person can be placed in the cell from the Machine view or from a scenario. The warning field sets an input bit for the PLC;
  - a virtual safety relay opens when an emergency stop is pressed or a person is in a protective field. Its feedback contact drops at once. After a stop delay (stop category 1, 300 ms by default) it switches the drives' power stages off (safe torque off) and cuts the conveyor's power. A joint with a brake holds, and the others coast to a stop. The relay closes again only on its reset button, once every emergency stop is released and every protective field is clear;
  - the simulator does not implement any safety function: the relay is a model for trying the PLC program's reaction, and the docs say so;
  - the drive model gets a safe torque off input: the power stage goes off, the drive drops to "switch on disabled" and needs the enable sequence again.
- **Panel in the Machine view:**
  - a Panel block in the side panel shows the mode switch, the buttons with their keys, and the lamps;
  - while the 3D stage has keyboard focus, which is shown on the stage, the keys press the buttons;
  - the view repeats a held key every 200 ms. It releases every button on key up, on leaving the stage or the tab, and on a lost connection;
  - buttons can also be held with the mouse or by touch;
  - a big red emergency stop on the panel (key E), and the safety relay's state (closed, tripped, waiting for reset);
  - the scanner's fields drawn on the floor and lit while occupied, and a Person tool that places a person on the floor by a click and drags them;
  - the stack light shows red while the relay is tripped;
  - without `allow_changes`, or offline, the panel is shown disabled with the reason.
- **Gantry example with manual mode:**
  - a new node 11 `panel` on the `motion` network. It is an ordinary 16-in / 16-out I/O module, the same made-up CiA 401 device as node 10, shipped as `panel.eds` with a notes file naming its bits;
  - its input bytes come into the program through PDOs, and the program decodes them into named BOOLs (bit channels, change `add-bit-channels`, can name them in the declarations later); both I/O nodes send their inputs on change and every 100 ms;
  - the program's manual mode: the sequence stops with a ramp, each axis jogs while its button is held (slow 20 mm/s, fast 150 mm/s, ramped), soft limits apply once homed, jogging is slow and limit-free before homing, and there are gripper, conveyor, home and reset buttons;
  - back in AUTO, Start runs the existing recovery: Z up, then carry on with the part in hand or go back to the conveyor;
  - lamps for MANUAL, homed, fault and auto running;
  - safety in the program: when the relay feedback drops, the program stops every axis with a quick ramp inside the stop delay and halts the sequence. After the relay's reset it powers the drives again and waits for Start (AUTO) or the operator (MANUAL). While a person is in the scanner's warning field, AUTO runs at reduced speed;
  - the existing `sim_gantry_demo` case in `sim_tests` goes on after its jam: it switches to MANUAL during a move, jogs, checks the soft limit and the lease release, returns to AUTO and places a part; presses the emergency stop during a move and checks that the axes stopped before the power went off and that Z held, then resets and places a part; and walks a person into the warning field and then the protective field;
  - an `emergency-stop` test scenario and a `person-in-cell` scenario in the example's simulation file.
- **Docs:** `docs/simulator.md` (the panel section and `sim_panel`), the gantry example README, a manual mode step in the tour's Simulated machine chapter, and the README feature list.

## Capabilities

### New Capabilities
None.

### Modified Capabilities
- `canopen-machine-model`: operator panel buttons and lamps, `sim_panel` with the hold lease, the emergency stop, safety scanner, virtual safety relay and person (`sim_person`), joint brakes, these in `sim_machine`, and panel and person steps in scenarios.
- `canopen-device-simulator`: a safe torque off input in the CiA 402 drive model.
- `canopen-config-contract`: the machine file's `panel` and `safety` sections, a joint's `brake`, and their checks.
- `canopen-machine-view`: the Panel block, keyboard jog, release on leaving, the emergency stop and relay state, scanner fields and the Person tool.
- `canopen-virtual-example`: the gantry example's manual mode, its CI case and its tour step.

## Non-goals

- No real safety function and no safety PLC. The virtual safety relay is a plain simulation for trying the program's reaction; nothing in canworks is fit for protecting people.
- No scanner field sets switched by the PLC, and no muting.
- No analogue jog (joystick, gamepad). A plain CAN joystick panel is a possible later change.
- No teach-in of positions and no editing of the program's pallet count from the panel.
- No `MC_Jog` library block. The example jogs with `CO402_CyclicPosition` and its own ramp, in ST.
- No keys that move the model directly. Every key goes through the PLC.

## Impact

- Plugin and standalone simulator: `sim_machine.{h,cpp}` (panel, lease, safety relay, scanner, person, brakes), `sim_drive` (safe torque off input), engine requests `sim_panel` and `sim_person`, scenario steps `panel` and `person`.
- Schema `schema/canworks-sim-machine.v1.schema.json` (`panel`, `safety`, `brake`), deploy tool and configurator checks.
- Configurator: `machine_view.js` and `machine_scene.js` (Panel block, keyboard, emergency stop, scanner fields, person), `/api/sim/request` passes `sim_panel` and `sim_person`, page tests.
- `examples/gantry-cell/`: `canworks.json` (node 11), `panel.eds`, `panel.eds.notes.json`, `machine.json`, `pous/programs/main.st`, README.
- No dependency on `add-bit-channels`: the program decodes the panel's bytes itself.
- CI: the `sim_gantry_demo` case grows from about 24 s to about 52 s, and a few page tests in existing jobs; no new job.
