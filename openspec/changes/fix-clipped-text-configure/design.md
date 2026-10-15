## Context

`modal()` in `app.js` is the one dialog of the configurator: a text, an optional extra element and a `<menu>` of buttons. `style.css` gives the dialog `max-width: 520px` and the menu `display: flex; justify-content: flex-end` without wrapping, and every `button` has `white-space: nowrap`. A row of buttons wider than the dialog therefore overflows, and because it is aligned to the end it overflows to the left, where the dialog's box cuts it and nothing can scroll it back. Measured with Chromium at 1280 px: the Add network row is 641 px in a 490 px menu; Cancel sits at x 236–304 and the dialog starts at 380.

The tree row (`tree.js`, `.tree-row`) is a one-line flex row: fold arrow, mark, name, protocol, badge, menu button. Name and protocol are both `flex: 0 1 auto; min-width: 0` with an ellipsis, so they share what the badge and the menu leave of 220 px and both shrink.

## Goals / Non-Goals

**Goals:**
- No text the user needs is cut in the Configure workspace, at any width the page supports.
- A guard in the tests, so the next long label does not bring it back.

**Non-Goals:**
- A new dialog component or a redesign of the tree.
- Data cells that are cut on purpose and carry their whole value in a tooltip.

## Decisions

### Dialog buttons wrap (all dialogs)
`dialog menu { flex-wrap: wrap; }` and `dialog menu button { white-space: normal; max-width: 100%; }`. Rows still end on the right, so a dialog whose buttons fit looks exactly as today. This fixes every dialog at once, including ones whose labels get longer with a long network name (the network menu reads "Make it a master network…" next to Rename… and Remove…).

Alternative considered: a wider dialog for long rows. Rejected: it only moves the limit, and on a narrow window there is no wider.

### Add network as a list of choices
Four buttons of 9 to 28 characters do not read well even when they wrap: the user has to read three labels in brackets to pick one. The start page already has `.choice` buttons (a title and a line of text, stacked). The dialog's extra part gets three such buttons, one per protocol, in a column; the menu keeps only Cancel. Picking a choice resolves the dialog with its protocol, the same values as today (`canopen`, `j1939`, `none`), so `addNetwork()` after the dialog does not change.

Focus goes to CANopen, the first choice. Adding a network is not destructive (Ctrl+Z removes it and nothing is written to disk), so "Confirmation dialogs default to the safe choice" does not apply; Escape still cancels. Up and Down move between the choices, as in a list.

Texts:
- CANopen: "A master and its nodes from EDS files, or the PLC as a slave device."
- J1939: "The PLC as an ECU that sends and receives parameter groups from a DBC file."
- Plain CAN: "CAN frames only, from a DBC file or entered by hand, with no protocol on top."

### Tree: protocol on its own line, names wrap
The network entry's row becomes a two-row grid: row 1 holds the fold arrow, name, badge and menu button; row 2 holds the protocol under the name. The name and node names get `white-space: normal; overflow-wrap: anywhere` and lose the ellipsis. Names allowed in a network are `[A-Za-z][A-Za-z0-9_]{0,15}`, so a long one is a single word; `anywhere` breaks it at the column edge instead of overflowing. The badge and menu button stay on the first line (`align-self: start`).

Alternatives considered:
- A wider column (260 px): the longest network name then fits on one line, but node names have no length limit and the protocol still competes for the same line. Rejected as the only fix; the width stays 220 px.
- Dropping the protocol from the entry: it tells a J1939 network from a CANopen one at a glance. Kept.

### Trace Dir heading
The identifier table's first column goes from `3ch` to `5ch`, enough for "Dir" and the sort mark at the table's font.

### Cut-text test
A page test (Playwright, like the other page tests) opens a config with a 16-character network name, a node name of 30 characters, a J1939 and a plain CAN network, and at 1000, 1280 and 1600 px opens every tree entry, every node tab, every tool tab, the Add network dialog and each network menu. For each visible element with text it fails when:
- `overflow-x` is `hidden` or `clip`, or `text-overflow` is `ellipsis`, and `scrollWidth > clientWidth`; except elements marked `data-cut-ok` (data cells with a tooltip of their whole value) and `.visually-hidden`;
- the element is inside an open `dialog` and its box is outside the dialog's box.

## Risks / Trade-offs

- [A wrapped tree is taller] → Only entries with long names grow; the common short name keeps one line plus the protocol line on networks. One extra small line per network is the cost of always seeing its protocol.
- [Data cells must be marked to pass the test] → Only the Trace and frame tables cut on purpose; marking them documents that the cut is deliberate.
