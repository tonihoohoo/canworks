# Proposal

## Why

Toni: "all eds pickers should be the same". Today the configurator picks an EDS in at least ten ways:

| Where | Today |
|---|---|
| Configure, **+ Add node…** | dialog with a grouped list: project EDS files (product name, file, nodes using it), EDS library, **Browse…** (`add-node-dialog`) |
| Configure, node **General** tab | plain dropdown of file names |
| Configure, slave device page | plain dropdown of all file names, "(none yet)", plus a visible browser file input "Use an EDS file…"; no library |
| Commission, **Add node from EDS…** | browser file picker first, then a node ID box |
| Commission, a node without an EDS (Nodes table, node page, Parameters tab) | "Use <match>" buttons or a match dropdown with Use, plus "Pick EDS file…" (browser file input) |
| Commission, **Change EDS…** | button dialog: one button per other match, Pick EDS file…, Clear EDS / Remove node |
| Commission, **Add to config** for found devices | a dropdown in a dialog when several match, a browser file input in a dialog when none does |
| Commission, **Add to a config…** | browser file input inside the dialog when the node has no EDS |
| Commission, LSS result | dropdown of matches |
| Trace, Decoding panel and frame inspector | "Pick EDS…" / "Change EDS…" browser file input |
| Simulation, extra devices | dropdown of file names plus a browser file input |

Each one offers different sources (project, library, matches, a file), shows files differently (file name only, product name, "exact revision"), and looks different. Someone who learned one has to learn the next.

## What Changes

- **One EDS dialog.** Every place that picks an EDS opens the same dialog, built from the Add node dialog's list. The list groups, in this order, each shown only when it has files:
  - **Matches this device**: the scan or identity matches, best first, with "exact revision" where it applies (Commission, LSS, found devices);
  - **Built here**: EDS files generated for a slave of this config (slave page only);
  - **In this project**: the config's EDS files (and DCF files where the place takes them), with the nodes using each;
  - **EDS library**: the library's files, when a library is set.

  Each entry shows the product name and the file name. **Browse…** opens the system file picker (EDS, plus DCF where the place takes it), imports the file (asking to replace or keep both on a name clash) and selects it. The current EDS, else the best match, is selected when the dialog opens. A library file is imported when the main button is pressed. Enter or a double-click on an entry presses the main button. Focus starts in the list, or on **Browse…** when it is empty, and goes back to the opener on close.
- **One EDS field.** Where a page shows a chosen EDS (node General tab, slave device page, Commission Nodes table and node pages, LSS result, Add to a config…, Trace, Simulation extra devices), it shows the product name and file name as text, with **Choose EDS…** when there is none and **Change EDS…** when there is one. No page shows a dropdown of EDS file names or a browser file input any more.
- **Dialogs that pick more than the EDS** carry the list inside them, with their own fields:
  - **+ Add node…** (Configure): as today, now on the shared list;
  - **Add node from EDS…** (Commission): the list plus the node ID, with **Add node**; no file picker first;
  - **Add to config** for found devices: one dialog per device that has several or no matches, with **Add node** and **Skip**;
  - **Change EDS…** (Commission): the list plus **Clear EDS**, or **Remove node** for a node only added on the page.
- **Labels.** "Pick EDS file…", "Pick EDS…", "Use an EDS file…" and "Use <file>" become **Choose EDS…**; "Change EDS…" stays.
- What each place does with the picked EDS does not change (draft edit, Commission-only node, trace decoding, simulation file).
- PC tools minor version bump; README (adding a node, Commission) and docs/configurator.md, docs/slave.md where they name the old controls.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `canopen-configurator`: new requirements "One EDS dialog", "Keyboard in the EDS dialog", "One EDS field". Modified: "Slave device page", "Add node dialog", "Nodes in commissioning", "Add found devices to the config", "Parameters of a node without an EDS", "Change or clear a node's EDS", "Decoding panel in the Trace view", "PDO layout in the frame inspector", "Fields and buttons fit their content" (scan page scenario label).

## Impact

- `tools/deploy/canworks/configurator/static/app.js`: shared `chooseEds(...)` dialog and `edsField(...)` from the Add node dialog's list; Add node dialog, node General tab, slave page, LSS result use them.
- `commission.js` (Add node from EDS…, `edsPick`, Add to a config…), `identity.js` (`edsChoices`, `changeEds`), `nodes.js` (`addFound`), `trace.js` (`layoutActions`), `sim.js` (extra devices).
- `server.py`: Commission may need to take a project EDS by name (today it takes library matches by path and picked files as bytes); the list of the config's EDS files with product names exists since `add-node-dialog`.
- Tests: page tests for each place (list sources, Browse… with a clash, Cancel changes nothing, Enter and double-click, focus return), the existing tests updated to the new labels, and the layout check over the dialog.
- No plugin, bridge or CODESYS export change. No hardware test needed; a Commission walk with a real device is listed as optional.
