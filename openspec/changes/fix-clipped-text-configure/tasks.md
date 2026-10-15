## 1. Dialogs

- [ ] 1.1 `style.css`: `dialog menu` wraps; dialog buttons wrap their label and are at most the dialog's width
- [ ] 1.2 `app.js` `addNetwork()`: CANopen, J1939 and Plain CAN as `.choice` buttons (name and one line) in the dialog's extra part, Cancel alone in the menu; focus on CANopen; Up and Down between choices; same return values as today

## 2. Network tree

- [ ] 2.1 `tree.js` and `style.css`: the network entry in two lines (name, arrow, badge, menu; protocol under the name)
- [ ] 2.2 `style.css`: names of networks and nodes wrap (`overflow-wrap: anywhere`), no ellipsis; badge and menu stay on the first line; tooltip and accessible name unchanged
- [ ] 2.3 Check the same tree in Commission with a config and in the narrow tree panel (1100 px and narrower)

## 3. Other views

- [ ] 3.1 Trace identifier table: Dir column wide enough for its heading and sort mark
- [ ] 3.2 Mark the data cells that are cut on purpose (with a tooltip of the whole value) with `data-cut-ok`

## 4. Tests

- [ ] 4.1 Cut-text page test: long-name config (16-character network name, 30-character node name, J1939 and plain CAN networks); every tree entry, node tab, tool tab, Add network and network menu at 1000, 1280 and 1600 px; fails on cut text or dialog content outside the dialog
- [ ] 4.2 Add network tests: three choices and Cancel visible, focus on CANopen, arrows, Escape adds nothing, each choice adds its protocol
- [ ] 4.3 Update existing tree and Add network tests for the two-line network entry and the choice list

## 5. Docs and release

- [ ] 5.1 `docs/configurator.md`: Add network… protocol list; network entry shows its protocol under the name. README.md only if it describes either
- [ ] 5.2 PC tools patch version bump
