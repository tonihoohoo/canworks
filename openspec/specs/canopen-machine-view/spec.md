# canopen-machine-view Specification

## Purpose
The configurator's Machine view: a 3D picture of a simulated machine built from its machine file and moved from the runtime's machine state, with quality levels, labels, cameras, a side panel with per-axis values and fault buttons, and an offline preview, all working without internet.

## Requirements

### Requirement: Machine view
The configurator SHALL show the machine as a **Machine** tab of the **Simulation** view, after **Live values**, **Simulation file** and **Scenarios**, for a network whose simulation file section names a machine file; for other networks the tab SHALL not show. The configurator SHALL have no separate Machine item in the sidebar. While the Machine tab is open, the scene and its panel SHALL use the whole content area. Offline, it SHALL show the machine built from the machine file at its home positions. Online, against a runtime that runs the machine, it SHALL show the live machine from `sim_machine`. The view SHALL need no network access: its 3D library ships with the PC tools.

#### Scenario: Tab of Simulation
- **WHEN** a user opens **Simulation** for the `motion` network of the gantry example
- **THEN** the tabs read Live values, Simulation file, Scenarios and Machine, and the sidebar has no Machine item

#### Scenario: No machine file
- **WHEN** a user opens **Simulation** for a network whose section names no machine file
- **THEN** there is no Machine tab

#### Scenario: Offline preview
- **WHEN** a user opens the Machine tab for the gantry example with no runtime connected
- **THEN** the gantry, conveyor and pallet show at their home positions and the panel says the machine is offline

#### Scenario: No internet
- **WHEN** the PC has no internet connection and the configurator opens the Machine tab
- **THEN** the view loads completely

### Requirement: Built-in gantry drawing
The view SHALL build the machine from the file's kind and dimensions. A built-in gantry SHALL be drawn with:
- T-slot profiles, linear rails and carriages;
- a servo motor per joint and energy chains that follow the moving axes;
- the gripper with moving fingers;
- belt conveyors with a moving belt, sensors with a visible beam, and fixtures with slots;
- a stack light, a guard fence and the floor.

#### Scenario: Moving parts drawn
- **WHEN** the gantry example runs and the X axis moves while the conveyor runs
- **THEN** the X energy chain bends with the carriage and the belt surface moves

### Requirement: Rendering presets
The view SHALL render with physically based materials, image-based lighting, soft shadows, screen-space ambient occlusion, bloom limited to light sources and status lamps, and anti-aliasing (High). It SHALL offer a Low preset without ambient occlusion and bloom and with smaller shadows.

#### Scenario: Preset remembered
- **WHEN** a user picks Low and opens the Machine view again later
- **THEN** the view starts on Low

### Requirement: Rendering fallback
The view SHALL switch to Low by itself, and say so, when the frame rate stays under 28 frames per second for 3 seconds. Without WebGL the view SHALL show the panel with live values and a message that the 3D view needs WebGL. The chosen preset SHALL be remembered on this PC.

#### Scenario: Slow graphics
- **WHEN** the view runs on High at 20 frames per second for 3 seconds
- **THEN** it switches to Low and shows that it did

#### Scenario: WebGL off
- **WHEN** the browser has WebGL turned off
- **THEN** the axes, I/O and counters still update and the 3D area shows the message

### Requirement: Labels, tool path and faults in the view
The view SHALL be able to show labels pinned to each drive (node, position, mode or EMCY code) and to sensors and fixtures, which can be turned on and off. It SHALL be able to show the tool point's path of the last seconds and the target of the current move. A drive in FAULT SHALL be marked on its axis in the scene and in its label. The stack light and drive status lamps SHALL follow the drives' states.

#### Scenario: Jam shown
- **WHEN** joint `z` jams and node 6 goes to FAULT
- **THEN** the Z axis and its label turn red with EMCY 0x8611 and the stack light shows red

### Requirement: Smooth motion from snapshots
The view SHALL draw the machine between two `sim_machine` snapshots by their simulator time stamps, a fixed delay behind the newest one, so motion stays smooth at the display's frame rate when answers arrive late or unevenly. It SHALL hold the last pose and say "no data" after 1 s without an answer.

#### Scenario: Uneven answers
- **WHEN** answers arrive alternately 20 ms and 50 ms apart
- **THEN** the drawn tool position changes smoothly every frame with no jump back

### Requirement: Camera and panel
The view SHALL have overview, top and follow-tool camera presets, and orbit, pan and zoom with mouse and touch. Beside the scene, a panel SHALL show per axis its state, mode, statusword, position in units and counts, following error against the window, and actual torque. It SHALL also show the I/O bits the machine uses, the counters and the last EMCY messages. Clicking a drive in the scene or the panel SHALL open that node in the online view.

#### Scenario: Open a node from the scene
- **WHEN** a user clicks the X axis motor in the scene
- **THEN** the online view opens on node 4 of `motion`

### Requirement: Machine faults from the view
With changes allowed on the diagnostics channel, the view SHALL offer the machine faults for injection and clearing. Without changes allowed it SHALL show them disabled, with the reason.

#### Scenario: Read-only runtime
- **WHEN** the runtime's diagnostics has `allow_changes` off
- **THEN** the fault buttons are disabled and say that changes are not allowed

### Requirement: Machine view messages
The view's messages (switched to Low for a slow frame rate, no data for more than 1 s, no WebGL, machine file problems) SHALL be the configurator's message bars at the top of the stage: no data as an error, Low and no WebGL as information, file problems as warnings or errors. None SHALL sit at the bottom of the stage.

#### Scenario: No data
- **WHEN** the simulator stops answering for 2 s
- **THEN** an error bar "No data" is shown at the top of the stage, the pose is held, and the bar goes when data comes back

#### Scenario: Switched to Low
- **WHEN** the view switches itself to Low
- **THEN** an information bar at the top of the stage says so

### Requirement: Operator panel in the view
For a machine file with a panel, the Machine view's side panel SHALL show a Panel block built from the file: the switches, the buttons with their labels and keys, the lamps, and an emergency stop shown as a larger red button with its state. Online, the buttons and lamps SHALL follow `sim_machine`. A button SHALL be pressed by its key, by a mouse press or by touch, held while held, and sent with `sim_panel`. Without `allow_changes` the buttons SHALL be disabled with the reason; offline they SHALL be shown disabled with the machine offline.

#### Scenario: Click and hold
- **WHEN** a user holds the mouse on **Jog X+** for 2 s
- **THEN** the button shows pressed for 2 s, the X axis jogs as the PLC program drives it, and the button is released on mouse up

#### Scenario: No changes allowed
- **WHEN** the runtime's diagnostics has `allow_changes` off
- **THEN** the panel's buttons are disabled and say that changes are not allowed, and the lamps still follow the PLC

### Requirement: Keyboard on the stage
The panel's keys SHALL act only while the 3D stage has keyboard focus. A click on the stage SHALL give it focus, and the stage SHALL show that the keyboard is on; Escape or a click outside the stage SHALL take it away. The view SHALL ignore the browser's key repeat and SHALL repeat a held key's press itself every 200 ms. It SHALL release every pressed momentary button on key up, when the stage loses focus, when the page is hidden, when the user leaves the Machine tab, and when a `sim_machine` poll fails.

#### Scenario: Leaving the tab while jogging
- **WHEN** a user holds the right arrow key and switches to another browser tab
- **THEN** the view sends the release of `jog_x_plus`, and the X axis stops as the program ramps it down

#### Scenario: Keys without focus
- **WHEN** the stage does not have focus and the user presses G
- **THEN** no panel request is sent

### Requirement: Safety in the view
For a machine file with a safety section, the view SHALL draw each scanner at its mounting point and its warning and protective fields on the floor as translucent areas, brighter while occupied. It SHALL show the relay's state (closed, stopping, open, waiting for reset) in the panel, and the stack light SHALL show red while the relay is not closed. A Person tool SHALL place a person figure where the floor is clicked, drag the person while the pointer is held (sending `sim_person` at most every 100 ms), and remove the person on a second click of the tool.

#### Scenario: Person trips the relay
- **WHEN** a user drags the person from outside the fence into the protective field
- **THEN** the warning field and then the protective field light up, the relay shows open, the stack light turns red, and the axes stop

#### Scenario: Waiting for reset
- **WHEN** the person is removed and the emergency stop is released after a trip
- **THEN** the relay shows waiting for reset until **Reset** is pressed
