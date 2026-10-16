## Why

Clicking a row in most of the configurator's lists and tables shows nothing, so on a wide row it is hard to follow the name across to its Add, Remove or Read button. Where a row does highlight, it looks different from place to place: the Object dictionary tab uses a light wash with an accent bar on the left, the trace lists, the By identifier view, Frame lab and the CAN messages page fill the row with the solid accent colour, the network tree uses the hover colour and bold text, and the notes tables highlight only while a control in the row has the focus. The user cannot learn one cue.

The pickers on a node's page (PDO objects, Startup SDO writes, SDO variables) and similar lists are boxes with a fixed height of 340 px. With a large EDS the user sees eight or nine rows at a time and has to scroll inside a small box, even on a tall screen.

The SDO variables picker also leaves out the device-note line under each object name that the Startup SDO writes picker shows, and an added SDO variable does not show its object's note either, so a variable has to be chosen without the text that says what the object does. Where a picker does show notes, it shows only a note's text: a note that gives only a unit, a scale, named values or bit meanings shows nothing on the PDO and Startup SDO writes pickers, although the Notes tab lists it, and the picker filters do not search note text.

## What Changes

- **One selected-row look everywhere.** Every list and table whose rows are items (objects, nodes, messages, frames, writes, signals, routes, notes, devices) on the Configure and Commission pages, the Trace and Frame lab views, the CAN messages and J1939 pages and the simulator gets the Object dictionary tab's highlight: a light wash across the whole row and a 3 px accent bar on its left edge, with a lighter hover tint under a mouse. The rows that today fill with the solid accent colour (Chronological trace, By identifier, Frame lab tables, CAN messages) and the network tree's selected entry change to this look.
- **Same behaviour everywhere.** Clicking anywhere on a row, its buttons included, or moving keyboard focus into it selects it. One row is selected per list. The selected row is marked `aria-current`. Escape in the list clears it, except where the selection drives an inspector (trace lists, By identifier, Frame lab), which keep their own keys. The selection survives the page redrawing (a field edit, a live refresh, a filter that hides and shows the row) until the page is reloaded; it is not saved.
- **Resizable list boxes.** The node page's pickers (PDO objects, Startup SDO writes, SDO variables), the slave's bound objects and builder, gateway routes, the scroll boxes of the Object dictionary, simulator values and J1939 signals tables, the Frame lab lists, the Modbus bridge map and the problems list get the resize bar the trace lists already have under them: drag it, or Up and Down by 40 px when it has the focus, double-click for the default height. Heights range from 120 px to 3000 px. Each kind of box keeps its height on this PC (`ui.json`), so every node's Startup SDO picker opens at the height last chosen. Dialog lists stay sized to the window.
- **Notes in the SDO variables picker.** Each object row in the SDO variables picker shows the device note line under its name, the same as the Startup SDO writes picker, and each added SDO variable shows its object's note line under its header.
- **Whole notes on the pickers.** The note under an object's name on the PDO, Startup SDO writes and SDO variables pickers, and on the Startup SDO writes list, PDO entries and SDO variables, shows every note that has something to say: its text, then a second line with the unit and scale and the named values or bit meanings, the same summary the Notes tab shows. A note with no text but a unit or named values gets that line alone. The picker filters also match note text.
- README.md and docs/configurator.md describe the selected row and the resize bars. PC tools minor version bump.

Non-goals: no multi-select; no change to what any button does; no new actions on the selected row; key/value status tables (bus status, node status) and the bit grids are not selectable.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `canopen-configurator`: one selected-row look and behaviour for every item list and table; resize bars on the in-page list boxes; device notes in the SDO variables picker and on added SDO variables; whole notes (text, unit, named values, bits) under object names on the pickers and lists, and picker filters matching note text. The requirement on readable controls in a selected row no longer assumes an accent fill.

## Impact

- `tools/deploy/canworks/configurator/static/`: a shared row-selection helper and a shared size-bar helper (moved out of the Object dictionary tab and `trace.js`), used by `app.js`, `commission.js`, `node.js`, `nodes.js`, `sim.js`, `trace.js`, `trace_ids.js`, `explain.js`, `rawcan.js`, `j1939.js`, `bridge.js`, `links.js`, `tree.js`; `style.css` and `rawcan.css` (one set of selected-row rules, the solid accent row rules removed).
- `configurator/server.py`: `ui.json` gains the list box heights.
- Page tests: selection in a sample of lists per page, the resize bar, the SDO variables note line; layout and contrast checks in Light, Dark and forced colours.
- README.md, docs/configurator.md, PC tools version.
- CI: runs under the existing configurator `ui` path filter; no new job or shard.
