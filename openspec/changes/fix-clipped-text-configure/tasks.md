## 1. Dialogs

- [x] 1.1 `style.css`: `dialog menu` wraps; dialog buttons wrap their label and are at most the dialog's width
- [x] 1.2 `app.js` `addNetwork()`: CANopen, J1939 and Plain CAN as `.choice` buttons (name and one line) in the dialog's extra part, Cancel alone in the menu; focus on CANopen; Up and Down between choices; same return values as today

## 2. Network tree

- [x] 2.1 `tree.js` and `style.css`: the network entry in two lines (name, arrow, badge, menu; protocol under the name)
- [x] 2.2 `style.css`: names of networks and nodes wrap (`overflow-wrap: anywhere`), no ellipsis; badge and menu stay on the first line; tooltip and accessible name unchanged
- [x] 2.3 Check the same tree in Commission with a config and in the narrow tree panel (1100 px and narrower)

## 3. Other views

- [x] 3.1 Trace identifier table: Dir column wide enough for its heading and sort mark
- [x] 3.2 Data cells that are cut on purpose (grid and table cells, trace rows, series list, PDO link cells) are the only exemption of the cut-text check
- [x] 3.3 Selected CAN message row: Remove keeps its button colours, muted text takes the row colour (`rawcan.css`); other selected rows checked (no buttons)

## 4. Tests

- [x] 4.1 Cut-text checks in `FIT_CHECK` (every layout check of every view): cut text and dialog content outside the dialog; tree test with a 16-character network name and a long node name, every network menu and Add network at 1000, 1280 and 1600 px
- [x] 4.2 Add network tests: three choices and Cancel visible, focus on CANopen, arrows, Escape adds nothing, each choice adds its protocol
- [x] 4.3 Update existing tree and Add network tests for the two-line network entry and the choice list
- [x] 4.4 Contrast test of a selected CAN message row, light and dark

## 5. Docs and release

- [x] 5.1 `docs/configurator.md`: Add network… protocol list; network entry shows its protocol under the name. README.md only if it describes either
- [x] 5.2 PC tools patch version bump
