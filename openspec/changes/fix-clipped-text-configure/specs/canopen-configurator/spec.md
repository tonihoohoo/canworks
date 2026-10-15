## ADDED Requirements

### Requirement: Dialog buttons stay inside the dialog
In every dialog of the configurator, every button SHALL be shown whole and inside the dialog's box, at any window width the page supports. Buttons that do not fit on one row SHALL wrap onto further rows, and a button label wider than the dialog SHALL wrap inside its button. The order of the buttons and which button gets the focus SHALL NOT change.

#### Scenario: Network menu with a long name
- **WHEN** the user opens the menu of a network named `conveyor_line_01` in a 1000 px window
- **THEN** Cancel, Rename…, Make it a slave network… and Remove… are all shown whole inside the dialog

#### Scenario: Focused button is visible
- **WHEN** any dialog opens
- **THEN** the button that has the focus is inside the dialog's box and on screen

### Requirement: Add network protocol choice
**Add network…** SHALL ask for the new network's protocol with one choice per row (CANopen, J1939, Plain CAN), each showing the protocol's name and one line on what it is for, followed by Cancel. CANopen SHALL be first and have the focus. Escape and Cancel SHALL add nothing.

#### Scenario: Pick with the keyboard
- **WHEN** the dialog opens and the user presses Down twice and Enter
- **THEN** focus moved from CANopen to J1939 to Plain CAN, and a plain CAN network is added

#### Scenario: Add a plain CAN network
- **WHEN** the user picks **Add network…** and then **Plain CAN**
- **THEN** a plain CAN network is added and its Bus page opens, as today

#### Scenario: Cancel is visible and works
- **WHEN** the user opens **Add network…** in a 1280 px window and presses Escape
- **THEN** every choice and Cancel were shown whole inside the dialog, and no network is added

### Requirement: Whole names in the network tree
The network tree SHALL show the whole name of every network and node: a name wider than the tree column SHALL wrap onto the next line, breaking inside the name when it has no space, and SHALL NOT be cut. A network entry SHALL show its name, fold arrow, problem badge and menu button on its first line and its protocol on a second line under the name. Each entry SHALL keep its tooltip with the whole text.

#### Scenario: New network with a problem
- **WHEN** a config has one CANopen master network `can0` with no nodes, so its entry carries an error badge
- **THEN** the entry reads `can0` on its first line and `CANopen master` on the second, neither cut

#### Scenario: Longest network name
- **WHEN** a network is named `conveyor_line_01` and the window is 1280 px wide
- **THEN** all 16 characters of the name are shown in the tree, on one or more lines

#### Scenario: Long node name
- **WHEN** node 5 is named `temperature_inputs_left`
- **THEN** its entry shows `5 temperature_inputs_left` whole, wrapped if needed

### Requirement: No cut text in Configure
In the Configure workspace no label, heading, button, tree entry or hint SHALL be cut by its box (an ellipsis, or text hidden by its box's overflow) at 1000 px wide and wider. Only cells of data tables that carry their whole value in a tooltip MAY be cut. The column headings of the Trace identifier table SHALL be shown whole with their sort mark.

#### Scenario: Trace Dir heading
- **WHEN** the user opens Trace and sorts the identifier table by Dir
- **THEN** the heading reads `Dir` whole, with its sort mark

### Requirement: Selected rows keep their controls readable
On a selected row of a list or table (filled with the accent colour), every button and text of the row SHALL keep at least WCAG AA contrast against what is behind it, in both themes. A button SHALL keep its own colours rather than take the row's text colour.

#### Scenario: Remove on a selected CAN message
- **WHEN** the user selects a received message on the CAN messages page in the dark theme
- **THEN** its Remove button reads clearly (red on the button's own fill), and "(no name)" reads in the row's text colour

## MODIFIED Requirements

### Requirement: Network tree keyboard
The tree SHALL follow the WAI-ARIA tree view pattern: one tab stop, Down and Up to the next and previous visible entry, Right to expand a network or move to its first child, Left to collapse a network or move to its parent, Home and End to the first and last entry, Enter or Space to open an entry, and type-ahead on the entry text. Shift+F10 on a network entry SHALL open its menu. The open entry SHALL be marked as selected. Focus SHALL stay on the same entry when the tree is redrawn. A name too long for the column SHALL wrap as "Whole names in the network tree" says, and SHALL be given whole in a tooltip and in the accessible name.

#### Scenario: Find a node by typing
- **WHEN** focus is in the tree and the user types `2`
- **THEN** focus moves to the first entry whose text starts with `2`, such as node 23, and Enter opens it

#### Scenario: Collapse with Left
- **WHEN** focus is on node 5 under `io` and the user presses Left twice
- **THEN** focus moves to `io` and then `io` collapses
