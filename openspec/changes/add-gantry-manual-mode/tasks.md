## 0. Before starting

- [x] 0.1 Decide on `add-bit-channels`: not merged yet, so the example decodes the panel's and node 10's bytes with masks; bit channels can name them later.

## 1. Simulator (plugin and standalone)

- [x] 1.1 `sim_drive`: safe torque off input (switch on disabled, voltage enabled off, enable refused, coast at the drive model's maximum acceleration, no EMCY, shown in `sim_status`); unit tests for the three drive scenarios.
- [x] 1.2 `sim_machine`: panel buttons (momentary, switch, latching) and lamps; `sim_panel` with the 500 ms hold lease; refused without `allow_changes` and for an unknown button.
- [x] 1.3 `sim_machine`: safety relay (inputs, stop delay, safe torque off on listed joints' drives, conveyors cut, feedback, reset only when clear), joint brake, scanners with warning and protective fields, the person and `sim_person`.
- [x] 1.4 `sim_machine` answer: buttons, lamps, relay state, field occupancy, person, safe torque off per joint; check the 16 KB limit with 50 parts still holds.
- [x] 1.5 Scenario steps `panel` and `person` (no lease), and conditions on relay, buttons, lamps and fields.
- [x] 1.6 `sim_unit_tests` on a virtual clock: lease release, held key, reset while pressed, reset after release, Z holds, coasting X, walking into the cell, leaving does not restart.

## 2. Contract and checks

- [x] 2.1 `schema/canworks-sim-machine.v1.schema.json`: `panel`, `safety`, joint `brake`.
- [x] 2.2 Checks in the plugin, the deploy tool and the configurator's problems with the same messages: unique names and keys, no Tab or Escape, relay inputs latching, reset momentary, joints and conveyors exist, protective inside warning, panel and safety inputs counted in "bound twice"; shared fixtures.

## 3. Configurator

- [x] 3.1 `/api/sim/request` passes `sim_panel` and `sim_person`.
- [x] 3.2 `machine_view.js`: Panel block from the file (switches, buttons with keys, lamps, emergency stop), mouse and touch hold, disabled without `allow_changes` and offline.
- [x] 3.3 Keyboard: stage focus and its marker, own 200 ms repeat, release on key up, blur, page hidden, leaving the tab and failed poll.
- [x] 3.4 `machine_scene.js`: scanner, the two fields lit while occupied, the person figure, stack light red while the relay is not closed; the Person tool (place, drag with `sim_person` at most every 100 ms, remove).
- [x] 3.5 Page tests (no WebGL): Panel block from the example file, a held key repeats and releases on blur and on page hidden, keys ignored without focus, disabled buttons without `allow_changes`, person drag sends throttled requests, relay state shown.

## 4. Gantry example

- [x] 4.1 `panel.eds` (copy of the DIO-16 under its own name) and `panel.eds.notes.json` naming every bit; node 11 `panel` in `canworks.json` with TPDO1 (both input bytes, event-driven) and RPDO1 (lamps) with a 100 ms event timer on both I/O nodes' TPDOs; node 10's `safety_ok` and `scanner_warning` bits mapped.
- [x] 4.2 `machine.json`: panel, `estop`, scanner on the open sides (warning 1200 mm, protective 600 mm), relay (300 ms, joints x y z, conveyor infeed, feedback on node 10), `brake` on `z`.
- [x] 4.3 `main.st`: manual mode with ramped jog through `CO402_CyclicPosition`, soft limits after homing, slow before homing, gripper and conveyor toggles, home and reset; back to AUTO on `start` through step 95; safety stop and power again after reset; reduced speed in the warning field; lamps; `needEnable` option.
- [x] 4.4 `sim_tests`: manual jog, emergency stop and person in the existing `sim_gantry_demo` case (one homing for all; 24 s to about 52 s, its CTest cost updated); `emergency-stop` test scenario and `person-in-cell` in the example's simulation file.

## 5. Docs

- [x] 5.1 `docs/simulator.md`: panel, `sim_panel` and the lease, safety relay, scanner, person and `sim_person`, safe torque off in the drive model, and the plain statement that none of it is a safety function.
- [x] 5.2 `examples/gantry-cell/README.md`: the panel node and its bits, the keys, manual mode, emergency stop and scanner, and how the program reacts.
- [x] 5.3 `docs/tour.md` Simulated machine chapter: switch to MANUAL, jog, back to AUTO, press the emergency stop, walk the person in, reset (the chapter has no screenshots).
- [x] 5.4 README: the feature line for manual mode and the safety simulation.

## 6. By hand

- [ ] 6.1 Local simulator runtime on macOS or Windows: jog all three axes from the keyboard, check that the response feels immediate, and measure key to PDO with the bus trace.
- [ ] 6.2 Close the browser tab while holding a jog key: the axis stops within about half a second.
- [ ] 6.3 Emergency stop and person in the view: the stack light, fields and relay state match, and the reset brings the cell back.
