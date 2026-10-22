# Proposal

## Why

The slave device page picks its EDS differently from every other place that picks one in Configure:

- **A bare dropdown.** "EDS" is a `<select>` of file names, starting at "(none yet)". It lists every EDS in the folder, nodes' device EDS files included, by file name only: no product name, no "used by", no grouping. The EDS library is not offered at all.
- **A raw file input next to it.** "Use an EDS file…" is a visible browser file input, with the browser's own "Choose File / No file chosen" text, on its own row of the grid.
- **Elsewhere it is one dialog.** Since `add-node-dialog`, **+ Add node…** picks the device description from one list: the project's EDS files (product name, file name, how many nodes use it), the EDS library's files, and **Browse…** for a new file. Someone who has added a node expects the same thing on the slave page and gets a different control with fewer choices.

## What Changes

- **One EDS list.** The device-description list of the Add node dialog becomes a shared piece of the page (list, groups, product names, use counts, EDS library, **Browse…** with the replace or keep-both question). The Add node dialog and the slave page both use it, so they look and behave the same.
- **Slave EDS field.** On the slave device page, the EDS field shows the slave's EDS as text: product name and file name (or "None yet: build one below, or choose an EDS file"), with **Choose EDS…** and **Export EDS** beside it. The dropdown and the "Use an EDS file…" file input go away.
- **Choose the slave's EDS dialog.** **Choose EDS…** opens a dialog titled "Choose the slave's EDS" with the shared list and **Use** / **Cancel**. Its groups:
  - **Built here**: EDS files generated for a slave in this config (they have a description), first;
  - **In this project**: the folder's other EDS files, with the nodes using them;
  - **EDS library**: the library's files, when a library is set.
  
  The current EDS is selected when the dialog opens. **Browse…** imports a file with the slave's EDS lint, as "Use an EDS file…" does today, and selects it. A library file is imported on **Use**, as Add node does. Cancel changes nothing, and focus goes back to **Choose EDS…**.
- **Keyboard in both dialogs.** Enter or a double-click on a list entry presses the dialog's main button (Add, Use). Both dialogs open with focus in the list, or on **Browse…** when the list is empty.
- No change to building the EDS, binding objects, or the export. PC tools minor version bump; docs/configurator.md (slave device) updated. README says nothing about the slave EDS control, so it stays.

## Non-goals

- The EDS pickers of Commission (Change EDS on a node's page, Add node from EDS…, an unmatched scanned device) and Trace stay system file pickers. They pick a file for one live device, partly before any config is open. Moving them to the shared list can follow as its own change if wanted.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `canopen-configurator`: "Slave device page" (the EDS is chosen in the Choose the slave's EDS dialog), "Add node dialog" (the list is the shared EDS list; Enter and double-click). New requirement: "One EDS list".

## Impact

- `tools/deploy/canworks/configurator/static/app.js`: the list part of `addNodeDialog` moves to a shared function (list, fill from project and library, Browse… import, resolve a library pick); `slaveFieldsets` gets the EDS text, **Choose EDS…** and the dialog; `useSlaveEdsFile` folds into the shared import; `projectEdsChoices` gets the slave-description group.
- `style.css`: the slave EDS field row (text plus buttons) if the existing classes don't cover it.
- Tests: `test_configurator_slave.py` (choose from the project, from Built here, from the library, Browse… with a name clash, Cancel keeps the EDS, empty state) and the Add node page tests (still pass on the shared list; Enter and double-click add).
- No server, plugin, bridge or CODESYS export change. No hardware test.
