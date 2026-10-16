## 1. Component

- [ ] 1.1 Add `notice(kind, content, {actions, close, timed, key})` and `noticeSlot(sectionEl)` to `app.js`; kinds info, done, warning, error with roles alert/status and no live role when drawn with the view
- [ ] 1.2 Style `.notice` and `.notice.info/.done/.warning/.error` in `style.css` (tint, 3 px accent, icon, actions row, close), light and dark; remove dead CSS (`#sim-banner` double padding, duplicate `#problems-box` marker rule)
- [ ] 1.3 Add the information icon to `icons.js` and the Colours and icons legend
- [ ] 1.4 Rebuild `banner()` on `notice()` with a kind argument; map every `banner(text, true)` call to error and every other call to info or done

## 2. Page level

- [ ] 2.1 Make `#sim-banner` a warning bar, sticky with the header above `#banner`
- [ ] 2.2 Give `#conn-bar` the warning tint for error passive and a round trip above 100 ms, the error tint for ended, lost, bus-off, another master and above 300 ms
- [ ] 2.3 Problems rows: use the bar tints and icons (check they already match)

## 3. Views and sections (move to the top slot)

- [ ] 3.1 `lockedNote()`: always in the top slot; move the Error history and NMT box notes up; sim read-only and Send blocked notes become warning bars
- [ ] 3.2 `.online-conn` and `.online-note` lines become bars; Commission Nodes connection line above the scan toolbar; node stale note in the node's slot
- [ ] 3.3 Job results (`followJob`/`startJob`): Parameters result moves from the bottom of the panel to its top slot; OD and LSS keep progress in their toolbar, results in the slot
- [ ] 3.4 Section warnings and errors built as `field-msg warning` / `field-msg` (axis profile, LSS, OD note, watch, J1939 DM, raw DBC missing and signal overlap, register map problem, notes import, EDS error, machine file errors, sim problems list with its real kinds) become bars in their slot; warnings beside one checkbox or field (Changes are allowed, Force is allowed, relay URLs, multiplexer problems in a picker row) stay field text
- [ ] 3.5 J1939 DM result moves to the top of the Faults box
- [ ] 3.6 Frame lab "Nothing here is sent" becomes an information bar; its input errors stay field errors with the alert role
- [ ] 3.7 Leftover-setting warnings from `eds-gated-node-settings` (with Remove) become section warning bars; EDS-limit hints stay grey hint text
- [ ] 3.8 Machine view: notice, no data and no WebGL as bars at the top of the stage

## 4. Dialogs

- [ ] 4.1 Add a top slot to `#modal` and `#conn-dialog`; the connect error moves there with the alert role; drop the "see the message at the top" text
- [ ] 4.2 Restore and write configuration previews: "no changes" becomes an information bar at the top
- [ ] 4.3 Folder chooser error becomes an error bar at the top of the dialog

## 5. Tests and docs

- [ ] 5.1 Playwright walk (virtual-plant and pingpong, Configure and Commission, Light and Dark): no retired classes, every `.notice` first after its heading or in a dialog's top slot, kind colours equal their tokens
- [ ] 5.2 Update existing page tests that look for the retired classes or positions
- [ ] 5.3 Screenshots before/after in the change folder for the PR
- [ ] 5.4 `docs/configurator.md`: message bars, where messages go, connection bar tints; README feature line; bump PC tools minor version
