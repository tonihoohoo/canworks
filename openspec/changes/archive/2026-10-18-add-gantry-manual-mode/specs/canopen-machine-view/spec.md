## ADDED Requirements

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
