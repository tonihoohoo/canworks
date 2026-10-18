## ADDED Requirements

### Requirement: Operator panel
A machine file SHALL be able to have an operator panel of buttons and lamps. Each button SHALL have a name, a label, a key, an input binding and a kind: `momentary` (on while pressed), `switch` (keeps the position it was last set to) or `latching` (an emergency stop: a press latches it and a second press releases it). Each lamp SHALL have a name, a label and an output binding. The simulator SHALL set a button's input bit while the button is on, and SHALL report a lamp as lit while its output bit is on. The I/O module SHALL send the change in its TPDO as any input change.

#### Scenario: Jog button reaches the PLC
- **WHEN** button `jog_x_plus` is bound to node 11 0x6000:1 bit 1 and a client presses it
- **THEN** node 11 sends its TPDO with bit 1 of 0x6000:1 on, and the PLC's input for that bit turns on

#### Scenario: Lamp lit by the PLC
- **WHEN** the PLC sets node 11 0x6200:1 bit 0, the `manual_lamp` lamp's output
- **THEN** `sim_machine` reports the `manual_lamp` lamp as lit

### Requirement: Pressing panel buttons
The simulator SHALL answer a `sim_panel` request with `network`, `button` and `pressed`, which needs `allow_changes`. A momentary button pressed with `sim_panel` SHALL stay pressed for 500 ms and SHALL then release by itself unless another press arrives first; a release SHALL end it at once. A switch and a latching button SHALL keep the state the last request gave them. An unknown button SHALL be refused naming it.

#### Scenario: Browser lost while jogging
- **WHEN** a client presses `jog_x_plus` and then sends nothing more
- **THEN** the button's input bit turns off 500 ms after the press

#### Scenario: Held key
- **WHEN** a client repeats the press of `jog_x_plus` every 200 ms for 3 s and then releases it
- **THEN** the input bit stays on for the whole 3 s and turns off with the release

#### Scenario: Read-only runtime
- **WHEN** the diagnostics channel has `allow_changes` off and a client sends `sim_panel`
- **THEN** the request is refused saying that changes are not allowed

### Requirement: Virtual safety relay
A machine file SHALL be able to have a safety relay with emergency stop buttons and scanner protective fields as inputs, a reset button, a stop delay (default 300 ms), the joints it switches off, the conveyors it cuts and a feedback input binding. The relay SHALL open when any emergency stop is latched or any protective field is occupied. On opening, it SHALL turn its feedback input off at once and, after the stop delay, SHALL set the safe torque off input of each listed joint's drive and stop each listed conveyor. It SHALL close again only on a rising edge of its reset button while no emergency stop is latched and no protective field is occupied; it SHALL then clear safe torque off and turn the feedback on. The documentation SHALL say that the relay is a simulation for trying a PLC program and is no safety function.

#### Scenario: Emergency stop during a move
- **WHEN** the X axis moves at 600 mm/s and a client latches `estop`
- **THEN** the relay's feedback bit turns off at once, and 300 ms later node 4's drive is in safe torque off and the conveyor stops

#### Scenario: Reset while still pressed
- **WHEN** `estop` is latched and the reset button is pressed
- **THEN** the relay stays open and the feedback bit stays off

#### Scenario: Reset after release
- **WHEN** `estop` is released and the reset button is then pressed
- **THEN** the relay closes, the feedback bit turns on and the drives leave safe torque off, still switched on disabled

### Requirement: Joint brake
A joint SHALL be able to have a brake. While its drive is in safe torque off, a braked joint SHALL hold its position, and an unbraked joint SHALL coast to a stop as the drive model's actual velocity falls.

#### Scenario: Z holds on emergency stop
- **WHEN** joint `z` has a brake and holds a part at 200 mm when the relay switches its drive off
- **THEN** joint `z` stays at 200 mm and the part stays held

### Requirement: Safety scanner and person
A machine file SHALL be able to have safety scanners, each with a warning field and a protective field as boxes on the floor and a warning output binding. The machine SHALL have at most one person, a point on the floor with a 300 mm radius, placed and removed with a `sim_person` request (`network`, `at`: `[x, y]` or `null`, needing `allow_changes`) or a scenario step. A field SHALL be occupied while the person's circle overlaps it. The warning field SHALL set its input bit while occupied, and the protective field SHALL be an input of the safety relay.

#### Scenario: Walking into the cell
- **WHEN** a person is placed outside both fields and then moved into the warning field and on into the protective field
- **THEN** the warning bit turns on first, and the relay opens when the person reaches the protective field

#### Scenario: Leaving does not restart
- **WHEN** the person leaves the protective field after the relay opened
- **THEN** the relay stays open until the reset button is pressed

### Requirement: Panel and safety in scenarios
Scenario steps SHALL be able to set panel buttons (`"panel": {"jog_x_plus": true}`) and place or remove the person (`"person": [x, y]` or `"person": null`). A button a scenario presses SHALL stay pressed until the scenario releases it, with no 500 ms release. Scenario `wait` and `expect` conditions SHALL accept the relay state, panel button and lamp states and field occupancy.

#### Scenario: Jog in a test
- **WHEN** a test scenario sets `manual` and `jog_x_plus` on, waits 2 s and sets `jog_x_plus` off
- **THEN** joint `x` has moved in the positive direction and stopped, and the scenario can expect the `manual_lamp` lamp lit

## MODIFIED Requirements

### Requirement: Machine state contents
A `sim_machine` answer SHALL hold:
- the simulator's time stamp in microseconds and a sequence number;
- per joint its position, velocity, demand position, drive state and fault, and whether its drive is in safe torque off;
- the tool's opening and whether it holds a part;
- every part with its id, kind, position, yaw and state (on a belt, held, falling, placed, on the table);
- every sensor's state, every fixture's state and pallet offset, and the counters;
- with a panel, every button's state and every lamp's state;
- with a safety section, the relay's state (closed, stopping, open), each scanner's field occupancy and the person's position or none.

#### Scenario: Part held
- **WHEN** the gripper holds a part and a client sends `sim_machine`
- **THEN** the answer shows that part as held at the tool's position and the tool as closed with a part

#### Scenario: Relay open
- **WHEN** `estop` is latched and a client sends `sim_machine`
- **THEN** the answer shows `estop` on, the relay open and each listed joint's drive in safe torque off
