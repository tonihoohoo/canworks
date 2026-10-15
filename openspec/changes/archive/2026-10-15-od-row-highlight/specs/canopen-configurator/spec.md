## ADDED Requirements

### Requirement: Selected row in the object dictionary view
Clicking anywhere on a row of the object dictionary tab (VAR object, foldable object or sub-entry), its buttons and Watch box included, or moving keyboard focus into it SHALL select that row. At most one row SHALL be selected, and Escape inside the tree SHALL clear the selection. The selected row SHALL be shown across its whole width with a background tint and an accent bar on its left edge, and marked `aria-current`.

#### Scenario: Click a sub-entry
- **WHEN** the user unfolds object 0x1010 and clicks the name of sub-entry 2
- **THEN** that row, from its subindex to its Watch box, is highlighted and no other row is

#### Scenario: Button selects its row
- **WHEN** sub-entry 2 of 0x1010 is selected and the user clicks Read on sub-entry 3
- **THEN** sub-entry 3 is highlighted, sub-entry 2 is not, and the read runs as before

#### Scenario: Keyboard
- **WHEN** the user tabs to the Edit button of 0x1017
- **THEN** the 0x1017 row is highlighted, and pressing Escape removes the highlight

### Requirement: Selection kept in the object dictionary view
The selected row SHALL stay selected while values are read, the watch list refreshes, Read all runs, the search or filters change, objects are folded and unfolded, and the user moves to another tab or node and back, until the page is reloaded. A selected row hidden by a search, filter or fold SHALL be highlighted again when it is shown again. A row being edited in place SHALL be the selected row. The selection SHALL NOT be saved to the configurator's settings.

#### Scenario: Watch refresh
- **WHEN** 0x1001 is selected and on the watch list refreshed every second
- **THEN** its row stays highlighted through every refresh

#### Scenario: Search hides and shows the row
- **WHEN** 0x1017 is selected, the user types `6110` in the search box and then clears it
- **THEN** 0x1017 is highlighted again once it is shown

### Requirement: Row highlight visibility
With a mouse, the row under the pointer SHALL get a lighter tint than the selected row; a touch screen SHALL NOT keep a hover tint. The selected row's accent bar SHALL meet 3:1 contrast against the page and panel backgrounds in the Light and Dark themes, the tint SHALL keep the row's text and buttons at their normal contrast, and in forced-colours mode the selected row SHALL be outlined in the system highlight colour.

#### Scenario: Dark theme
- **WHEN** the page is in the Dark theme and 0x1018 sub-entry 1 is selected
- **THEN** the row is visibly highlighted, its Read and Edit buttons are readable, and the contrast check passes

#### Scenario: Forced colours
- **WHEN** the operating system's high contrast mode is on and a row is selected
- **THEN** the row is outlined in the system highlight colour
