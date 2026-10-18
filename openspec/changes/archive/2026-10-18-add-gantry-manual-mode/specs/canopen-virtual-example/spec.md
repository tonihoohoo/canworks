## ADDED Requirements

### Requirement: Gantry example manual mode and safety
The gantry example SHALL have an operator panel on node 11 `panel` of its `motion` network, an ordinary 16-in / 16-out CiA 401 module shipped as `panel.eds` with a notes file naming each bit, and its input bytes SHALL reach the program through PDOs, which the program decodes into named BOOLs. Its machine file SHALL bind the panel's buttons and lamps, an emergency stop, a safety scanner covering the fence's open sides and a safety relay, with joint `z` braked. Its program SHALL:
- in MANUAL, stop the sequence with a ramp, jog each axis while its button is held (20 mm/s, 150 mm/s with `fast`, ramped), keep the travel as soft limits once homed and jog slowly without soft limits before homing, toggle the gripper and conveyor on their buttons, home on `home` and reset drives on `reset`;
- back in AUTO, wait for `start`, then recover and carry on;
- on the relay feedback dropping, in any mode, stop every axis inside the relay's stop delay, power the drives again after the relay's reset and wait for `start` (AUTO) or the operator (MANUAL);
- in AUTO, run at reduced speed while the scanner's warning field is occupied;
- light the `manual_lamp`, `homed_lamp`, `fault_lamp` and `auto_lamp` lamps.

The example's README, the tour's Simulated machine chapter and `docs/simulator.md` SHALL describe manual mode, the emergency stop, the scanner and the relay, and SHALL say that the relay is a simulation and no safety function.

#### Scenario: Manual jog in CI
- **WHEN** `sim_tests` runs the example and switches to MANUAL during an XY move, jogs X to beyond its travel and goes back to AUTO with `start`
- **THEN** the axes ramp down without a drive fault, X stops at 900 mm, and the program recovers and places the next part

#### Scenario: Emergency stop in CI
- **WHEN** `sim_tests` latches `estop` during an XY move faster than 500 mm/s, waits, releases it, presses `reset` and `start`
- **THEN** the axes are at standstill before their drives go to safe torque off, Z keeps its position, no drive faults, and the program places the next part

#### Scenario: Person in CI
- **WHEN** `sim_tests` places the person in the warning field and then the protective field
- **THEN** the program's moves slow down first, and the relay opens and the axes stop second
