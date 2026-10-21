# Design

## Context

`targets.py ROWS` is the relevance table: key, targets that use it, reason per other target, targets that refuse it. The server sends it as `S.state.targets`. After each render, `target.js applyTarget(root)` walks every `[data-path]` input. A field the target does not use is hidden while empty and marked (`unusedMark`: tag and Remove) while set. A fieldset left with nothing visible is hidden. Choice options the target does not use are pruned. Tabs, tree entries and menus call `usedBy(key)`, usually as `usedBy(k) || <config still has a value>`. The check (`contract.py`) adds one warning per set unused value, so Problems, the field's `.field-msg` and the tab badges all repeat it.

## Survey (2026-10-21)

Method: the `modbus-bridge` example opened three times in the configurator in Chromium: as the bridge, as OpenPLC (`pack_openplc`), and as CODESYS (a `codesys` object, entry locations removed, other leftovers kept as **Switch, keep them** would). For every page and node tab, the visible `[data-path]` fields, table headers, legends, buttons, hints and unused marks were dumped and compared between targets.

What the table already handles: every empty unused field is hidden on all three targets, and choice options are pruned.

Gaps:

| # | Where | What shows | Targets |
|---|---|---|---|
| 1 | Node PDOs | PLC location column as soon as one entry has `iec_location` (`renderPdos`: `usedBy(...) \|\| pdos.some(...)`) | CODESYS |
| 2 | Node PDOs | TPDO receive timeout fields with values | CODESYS |
| 3 | Node Supervision | status, state, EMCY code locations and heartbeat timeout with values; tab badge "4 warnings" | CODESYS |
| 4 | Bus | adapter type, simulate, bus state and master state with values, plus their hints ("A virtual bus inside the plugin…") | CODESYS |
| 5 | Node tabs | Simulation tab while `simulate` is set (`nodeSimulated`); CiA 402 tab while `axis` is set | CODESYS |
| 6 | Bus | "Project addresses scanned …: N in use" (editor project scan) | bridge, CODESYS |
| 7 | Bus | role hint "The plugin is the network's master" | bridge, CODESYS |
| 8 | Bus | interface hint "The interface on the PLC (the Pi)…" | bridge |
| 9 | Bus | "Plugin sets up the link", restart hint "only when the plugin sets up the link" | bridge |
| 10 | Bus | EDS lint hint "The PLC stops only on lint findings…" | bridge |
| 11 | Bus | bus-off count hint "since the PLC started, also those shorter than a scan" | bridge |
| 12 | Node SDOs | "Hidden: N communication objects the plugin sets…" | bridge, CODESYS |
| 13 | Node Advanced | "dcfgen's node options" (tool name as jargon) | all |
| 14 | CAN messages | "Each signal gets a free PLC location", "The PLC reads … %I" | bridge |
| 15 | PDO links | "no longer passes through the PLC scan … while the PLC is stopped" | bridge |
| 16 | Variable declarations | "Paste this block into the VAR block of the program…" (OpenPLC program text) | bridge |
| 17 | Field messages, Problems | config file path in front of every check message on Windows (`readable()`: `^[^:]*canworks\.json: ` cannot get past `C:`) | all, Windows |

Rows 1 to 5 are the leftover-value rule. Rows 6 to 16 are wording or page parts the table does not cover. Row 17 is a bug that is not specific to any target.

## Decisions

### Leftovers are hidden and gathered, not shown in place

`applyTarget` treats a set unused field like an empty one: hidden. That also applies to table cells, columns, fieldsets, tabs and tree entries, so the `|| <has a value>` exceptions go. That means `renderPdos` (locations column), `nodeTabs` (Simulation, CiA 402), `node.js` SDO variables, `tree.js` (CAN messages, Online access, gateway) and `simTabWanted`. Each of those reads the value through one helper, `shownFor(key)`, which is `usedBy(key) || S.showAll`.

The values still have to be visible somewhere, or a user could not tell why the file differs from the page. Options considered:

- *Keep marking in place* (today): clutters exactly the case Toni hit; one value brings back a whole column.
- *A dialog when the config opens*: interrupts; a user who chose Keep would be asked every time.
- **A folded bar per page, plus one grouped problem** (chosen). The bar sits under the page heading (or the node tab's heading) and lists only that page's leftovers: "2 settings here are not used by CODESYS · Remove all · Show". Unfolded it lists each one as `<place>: <label> <value>` with its own Remove, using the existing `problemPlace()` and field labels from a small label map next to the table (the table row's key gives the label, for example `nodes.tx_pdos.entries.iec_location` gives "PLC location"). The bar is drawn from the check's unused items (paths from `targets.unused`), so it needs no extra server call.

**Remove all** in the bar removes that page's leftovers. **Remove all** in Problems removes every one. Both are one undo step (`changed(true)` after the batch, like the switch dialog). Network kinds (slave role, J1939, plain CAN on CODESYS) are not removable today and keep their current handling: the network's page says it stays with canworks.

### One grouped problem, badges without leftovers

The check keeps one warning per value: the CLI user and `--codesys-import` see them as today. On the page, `applyCheck` folds warnings whose `key` is a table row (the server adds `unused: true` to those items) into one Problems entry, "N settings are not used by CODESYS", with **Remove all** and a fold-out list. A list row click opens the page with the bar unfolded and highlights the row. Tree and tab badges skip `unused` items, and their `.field-msg` text is not written (the field is hidden anyway).

### Show every field

A Settings menu toggle (the configurator has no View menu), "Show fields the target does not use", stored in the configurator's per-PC UI settings (`ui.json`, `show_all_fields`, the same place as the theme). When on, `applyTarget` uses today's behaviour on every field, set or empty: shown, dimmed (`.unused-field` opacity) and tagged "not used by <target>", with Remove when set. Tabs and columns come back. The bar's **Show** turns the toggle on. The header badge shows "· all fields" while it is on, so a screenshot cannot be mistaken for the default view. It is per PC, not per config, because it is a viewing preference and should not touch the file.

### Wording per target from one place

`targetText(key)` in `target.js` returns the variant for the project's target from a `TARGET_TEXT` map (`{ openplc, bridge, codesys }`, a missing variant falls back to `openplc`). Call sites in `app.js`, `node.js` and `rawcan.js` use keys instead of literals for rows 7 to 15. Row 6 is gated by `usedBy("ui:editor_project")`. Row 16: `ui:declarations` becomes OpenPLC only. Bridge users get Export ST variables on the bridge page, which is the variable list for the PLC that talks Modbus to the bridge. Row 13 changes to "Node options canworks writes into the node's DCF" for every target.

New wording (final text in the implementation, these are the intent):

- role master: OpenPLC "The plugin is the network's master…", bridge "The bridge is the network's master…", CODESYS "The CODESYS CANopen manager is the network's master…";
- interface: bridge "The interface on the computer that runs the bridge";
- configure link: bridge "Bridge sets up the link (bit rate, up)";
- bus-off count: bridge "Bus-off events since the bridge started";
- EDS lint: bridge "The bridge does not start on lint findings…" (wording follows what the bridge does, checked in the implementation);
- SDO tab: CODESYS "communication objects CODESYS sets from the node's settings", bridge "…the bridge sets…";
- CAN messages: bridge "Each signal gets a free register location", "Messages the bridge reads from the bus. Their signals go to input registers.";
- PDO links: bridge "the data no longer passes through the bridge".

### Guard test

`test_configurator_target_view_page.py`: for each target, a config with every table row's setting set (the CODESYS one built by **Switch, keep them**). The test opens every tree entry and node tab and asserts:

- no visible `[data-path]` whose `pathRow()` excludes the target;
- no visible text matching the other targets' words. For CODESYS that is `plugin|the Pi|PLC location|%[IQ][XBWDL]|scan watchdog|OpenPLC`. For the bridge it is `the plugin|the Pi|PLC scan|PLC location|OpenPLC Editor`. For OpenPLC it is `Modbus|CODESYS`. Excluded: the Project target field's help and the switch dialog;
- the bar count equals the number of unused items for that page.

With the toggle on, every field of the full config is visible. This catches the next field or hint added without a table row or wording variant.

### Windows paths in messages

`readable()` strips any leading `<path ending in .json>: ` with a pattern that allows a drive letter (`^(?:[A-Za-z]:)?[^:]*\.json: `). `humanise()` gets the same pattern. A unit test runs both on POSIX and `C:\…` prefixes.

### Sections and blank tabs (folded in)

A section (fieldset, advanced block, PDO settings row) was hidden when all its `[data-path]` fields were hidden. The supervision Method choice and the Watch a node… picker have no path, so on CODESYS with Method "EDS default" the whole Supervision tab went blank. Now a section is hidden only when it had setting fields and no control at all (input, select, textarea, button) is left visible. If every child of a node tab's panel still ends up hidden, `applyTarget` adds one line: "<target> does not use the settings on this tab", with the reason for CODESYS. The guard test fails on a blank node tab for any target.

## Risks

- A user who switched with **Keep them** on purpose no longer sees those values in place. The bar and the grouped problem say they exist, and Show brings them back. The switch dialog's Keep button text becomes "Switch, keep them hidden" so the result is expected.
- Hiding a column whose value is set could hide a typo a user wants to fix. Only for a target that does not use the value, so fixing it has no effect anyway.
- Wording variants can drift. The guard test's word lists keep them honest.
