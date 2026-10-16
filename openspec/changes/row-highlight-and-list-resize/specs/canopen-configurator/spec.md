## ADDED Requirements

### Requirement: Selected row in every list
Every list and table of the configurator whose rows are items (objects, nodes, messages, frames, writes, signals, routes, notes, devices) SHALL show a selected row the same way as the object dictionary view: a background tint across the whole row and an accent bar on its left edge, a lighter tint under the mouse pointer, and `aria-current` on the row. The network tree's selected entry SHALL use the same look. Key/value status tables and bit grids SHALL NOT be selectable.

#### Scenario: Startup SDO picker
- **WHEN** the user clicks the name of object 0x1010:2 in a node's Startup SDO writes picker
- **THEN** that row, from its object to its Add button, is highlighted with the tint and accent bar, and no other row of the picker is

#### Scenario: Trace row looks the same
- **WHEN** the user selects a frame in the Chronological trace list
- **THEN** its row shows the same tint and accent bar as a selected row in the object dictionary view, not a solid accent fill

### Requirement: Selecting a row in a list
Clicking anywhere on a row of a selectable list, its buttons included, or moving keyboard focus into it SHALL select that row, with at most one selected row per list. Escape in the list SHALL clear the selection, except in lists whose selection drives an inspector (Chronological, By identifier, Frame lab), which keep their own keys. The selection SHALL be kept while the page redraws, a live value refreshes or a filter hides and shows the row, until the page is reloaded, and SHALL NOT be saved.

#### Scenario: Button selects its row
- **WHEN** the user presses Add on object 0x2001:0 in the SDO variables picker
- **THEN** that row is highlighted and the variable is added as before

#### Scenario: Kept through a redraw
- **WHEN** a row of the Startup SDO writes list is selected and the user edits that write's value
- **THEN** the row is still highlighted after the page redraws

#### Scenario: Keyboard
- **WHEN** the user tabs to a Remove button in the gateway routes table and then presses Escape outside a text field
- **THEN** the route's row is highlighted when the focus arrives and the highlight goes away on Escape

### Requirement: Resizable list boxes
Each fixed-height list box on the page (the node page's pickers, the slave's objects, gateway routes, table scroll boxes, Frame lab lists, the bridge map, the problems list) SHALL have a resize bar under it. Dragging the bar, or Up and Down by 40 px while it has the focus, SHALL change the height between 120 px and 3000 px; double-click SHALL restore the default. Lists in dialogs SHALL keep fitting the window.

#### Scenario: Keyboard and reset
- **WHEN** the bar under the PDO picker has the focus and the user presses Up twice, then double-clicks the bar
- **THEN** the picker is 80 px shorter after the key presses and back to its default height after the double-click

### Requirement: List box heights kept
The height chosen for a resizable list box SHALL be kept per kind of box in the configurator's page settings on this PC, and SHALL apply to that box on every node and after a reload.

#### Scenario: Taller SDO picker
- **WHEN** the user drags the bar under node 5's Startup SDO writes picker down by 300 px
- **THEN** the picker shows more rows, and node 7's Startup SDO writes picker opens at the same height

#### Scenario: Kept after reload
- **WHEN** the user has made the SDO variables picker taller and reloads the page
- **THEN** the SDO variables picker opens at the chosen height

### Requirement: Device notes in the SDO variables picker
Each object row of the SDO variables picker SHALL show the object's device note line under its name, as the Startup SDO writes picker does, and each added SDO variable SHALL show its object's note line under its header.

#### Scenario: Picker row with a note
- **WHEN** object 0x2001:0 has a device note and the user opens the SDO variables picker
- **THEN** the note line appears under the object's name in the picker row

#### Scenario: Added variable
- **WHEN** the user adds 0x2001:0 as an SDO variable
- **THEN** the variable's block shows the object's note line under its header

## MODIFIED Requirements

### Requirement: Selected rows keep their controls readable
On a selected row of a list or table, every button and text of the row SHALL keep at least WCAG AA contrast against what is behind it, in both themes, and text that has its own colour on the row (an EMCY or error row, a Tx mark) SHALL keep that colour. A button SHALL keep its own colours rather than take the row's text colour.

#### Scenario: Remove on a selected CAN message
- **WHEN** the user selects a received message on the CAN messages page in the dark theme
- **THEN** its Remove button reads clearly (red on the button's own fill), and "(no name)" reads in the row's text colour

#### Scenario: Selected EMCY frame
- **WHEN** the user selects an EMCY frame in the Chronological trace list in the light theme
- **THEN** the frame's text keeps its EMCY colour and reads clearly on the selected row's tint
