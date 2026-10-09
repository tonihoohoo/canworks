# canopen-machine-view Specification

## Purpose
The configurator's Machine view: a 3D picture of a simulated machine built from its machine file and moved from the runtime's machine state, with quality levels, labels, cameras, a side panel with per-axis values and fault buttons, and an offline preview, all working without internet.

## Requirements

### Requirement: Machine view
The configurator SHALL have a Machine view for a network whose simulation file section names a machine file. Offline, it SHALL show the machine built from the machine file at its home positions. Online, against a runtime that runs the machine, it SHALL show the live machine from `sim_machine`. The view SHALL need no network access: its 3D library ships with the PC tools.

#### Scenario: Offline preview
- **WHEN** a user opens the Machine view for the gantry example with no runtime connected
- **THEN** the gantry, conveyor and pallet show at their home positions and the panel says the machine is offline

#### Scenario: No internet
- **WHEN** the PC has no internet connection and the configurator opens the Machine view
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
