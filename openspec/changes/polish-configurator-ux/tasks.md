## 1. Bugs

- [ ] 1.1 Move the per-node Export DCF out of `#node-list li` to the node page (next to Remove node) and the Export menu; render list items as buttons with name and error count only; verify with a page test that clicking the centre of every node item opens that node and runs no export.
- [ ] 1.2 Make the three export checks replace `S.check` and recompute counts in one `countProblems()`; verify that a failed export leaves the problem count unchanged and the Save tooltip agrees with the pane.
- [ ] 1.3 Remove the literal "null" in Variable declarations and the Online node overview (filter null children in `view.append`/`replaceChildren` calls through `put()`); verify with a page test that no text node equals "null" or "undefined" on any view, and guard `st.version`, `st.bus.interface`, `st.limit`, `r.note` and `SIM.settings.address`.
- [ ] 1.4 In commissioning mode hide the Project and Export menus, Save, the Problems pane and the config side bar entries; verify with a page test on "Commission a device".
- [ ] 1.5 Put the New project dialog's "Enable CANopen SDO blocks" checkbox inline with its label.

## 2. Dialogs and undo

- [ ] 2.1 Give `modal()` the safe-first convention, explicit focus on the safe button, a `danger` style and a single `cancel` listener; update Remove node, Close, Reload, Remove network, role switch, Restore, Store, New token and Trace Clear/Start; verify with a page test that Enter in the Remove node dialog keeps the node and that Escape closes it.
- [ ] 2.2 Add the draft snapshot stack with Ctrl+Z / Ctrl+Shift+Z and the "Removed … Undo" message for row removals; verify with page tests (remove a PDO entry and undo restores its location and timeout; typing then Ctrl+Z outside the field; the stack is empty after Reload from disk).
- [ ] 2.3 Confirm Pre-operational like Stop; make Trace Clear say the recording is lost unless saved and ask before leaving with an unsaved recording (`beforeunload` and Close); verify with page tests.

## 3. Keyboard and assistive technology

- [ ] 3.1 Node list and problem list as buttons with `aria-current`; `tabindex`, `role=button` and Enter/Space on online, scan and simulation rows; Home/End/PageUp/PageDown in the trace list; verify with a page test that tabs from Save through every node and problem and opens them with Enter.
- [ ] 3.2 Add the `tabs()` helper and use it for the Trace, Online node and Simulation tabs; verify with a page test (arrow keys move the selection, axe reports no `aria-allowed-attr`).
- [ ] 3.3 Live regions (`#problem-count`, job and scan progress, online connection line), `role=alert` on error messages, `<section aria-label>` for the Problems pane and the inspector box, heading levels, hidden "Actions" headers; verify with axe in the layout test.
- [ ] 3.4 Contrast and targets: `--ok` and the inspector tints at 4.5:1 in both themes, inputs and `.small` buttons at 24 px, `:focus-visible` in the accent colour, theme-aware trace series colours; verify with the contrast script from the review folded into the layout test and the axe `color-contrast` rule.

## 4. Header and node page

- [ ] 4.1 Project and Export menus (`<details class="menu">`, keyboard, one open at a time, This node's DCF enabled on a node page), header reduced to Reload, Close, Project, Export, Save; verify with page tests (every export still downloads; the header fits on one line at 1000 px) and update tests that clicked the old buttons.
- [ ] 4.2 Node page section index (sticky, follows scrolling), Startup SDO writes and SDO variables collapsed when empty with counts in the summary, "Add entry…" per PDO block replacing the separate "Map an object" fieldset (fixed-mapping PDOs keep "Map all"); verify with page tests (anchor click scrolls to the section; adding an entry through a PDO block) and the FIT check.
- [ ] 4.3 Side bar name follows the Name field as you type; focus moves to the new node's name after "Add node from EDS…"; "Pick EDS file…" on the Scan page navigates to the new node with a message that links back to the scan; verify with page tests.

## 5. Feedback and wording

- [ ] 5.1 Empty-config problem text, humanised trace and Frame lab decoding notes, one-sentence server error with the traceback in the terminal; verify with API and page tests that no message contains a filesystem path or `nodes[`.
- [ ] 5.2 `busy()` on Save, the exports, Move into project, New editor project and Add node; Save button states (Saved disabled when clean, Save when dirty, overlaps allowed, tooltip with the error count); verify with page tests including a double click during a slow save (one request).
- [ ] 5.3 Online: grey the node table and show "last data N s ago" when polling fails, name the deploy command in the different-configuration note; verify with the fake plugin stopping mid-session.
- [ ] 5.4 Labels: Trace "Save to traces folder" / "Download", distinct format select labels, visible lane labels, "Run both", a pass over Remove/Add labels and node/device/runtime/PLC wording in the four views; verify by grep in the page tests for the old labels.

## 6. Automated check, docs and release

- [ ] 6.1 Vendor `tests/data/axe.min.js` with its licence notice; run it after every `fits()` in `tests/test_configurator_layout.py`, fail on critical and serious, report the rest; add `tests/test_configurator_ux_page.py` for the probes above.
- [ ] 6.2 Update `docs/configurator.md` (menus, undo, keyboard, commissioning header) and README; bump the deploy tool minor version.

## 7. Hand check

- [ ] 7.1 With the local simulator runtime and the virtual example: open each view with the keyboard only, remove and undo a PDO entry, run every export from the menu, drop the runtime and watch the stale state, and check both themes with the OS in dark mode.
