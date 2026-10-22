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

Fewer places pick an EDS, and those that remain use one dialog.

**After the change there are two entry points, both opening the same EDS dialog:**

1. **Add node…**, in Configure and in Commission (today "Add node from EDS…"): the EDS list plus node ID (and, in Configure, the name and default PDOs).
2. **The EDS field** of one node, slave or extra device: product name and file name as text, **Choose EDS…** when there is none and **Change EDS…** when there is one. It is on the node General tab, the slave page, the Commission node (Nodes table EDS column and node header, the same field), and a simulation extra device.

**Places that stop picking on their own:**

| Today | After |
|---|---|
| Commission node page and Parameters tab: "Use <match>" buttons + Pick EDS file… | link to the node's EDS field (same dialog, matches first) |
| Trace Decoding panel and frame inspector: Pick EDS… / Change EDS… file input | link to the node's EDS field |
| LSS result: dropdown of matches | the best match as text; after Set node ID the node is in the Nodes table with that EDS, changed there if needed |
| Add to config for found devices: dropdown or file input dialog per device | uses the node's EDS on the page; a device with none or several matches opens the EDS dialog for that node first |
| Add to a config…: file input in the dialog | uses the node's EDS on the page; opens the EDS dialog first when it has none |
| Commission "Change EDS…" button dialog | the EDS dialog with **Clear EDS** / **Remove node** |
| Node General tab, slave page, extra devices: dropdowns + file inputs | the EDS field |

**The EDS dialog.** One list, grouped in this order, each group shown only when it has files: **Matches this device** (scan or identity matches, best first, "exact revision"), **Built here** (EDS generated for a slave of this config, slave page only), **In this project** (the config's EDS files, DCF too for extra devices, with the nodes using each), **EDS library**. Each entry shows product name and file name. The current EDS, else the best match, is selected. Enter or a double-click presses the main button; focus starts in the list and returns to the opener.

**Browse… uses the page's file browser**, the same folder dialog as Choose folder… for the EDS library and Open, listing `.eds` files (and `.dcf` where taken); in a dialog without other fields the picked file is used at once, in Add node it is selected. It starts in the folder last browsed, else the EDS library. Because the page then knows the file's folder, notes next to it can come along (below).

**Notes come with the EDS automatically.** When an EDS is taken from a folder (Browse…, the EDS library, the commissioning folder), its notes file next to it (`<eds>.notes.json`) is imported with it when the config has no notes for that EDS yet. When the config already has notes for it, they are kept and the message says the other notes file can be brought in with **Import notes…** (as "Add to a config…" does today). A `<eds>.datasheet.notes.json` next to the EDS is not imported by itself; the message points to Import notes…, where its preview shows the changes. No separate "import notes" step is needed in the dialog.

What each place does with the picked EDS does not change (draft edit, Commission-only node, trace decoding, simulation file).

PC tools minor version bump; README (adding a node, Commission) and docs/configurator.md, docs/slave.md where they name the old controls.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `canopen-device-notes`: new requirement "Notes come with a picked EDS".

- `canopen-configurator`: new requirements "One EDS dialog", "Keyboard in the EDS dialog", "One EDS field", "EDS chosen in one place per node". Modified: "Unconfigured devices in the online view", "Slave device page", "Add node dialog", "Nodes in commissioning", "Add found devices to the config", "Parameters of a node without an EDS", "Change or clear a node's EDS", "Decoding panel in the Trace view", "PDO layout in the frame inspector", "Fields and buttons fit their content" (scan page scenario label).

## Impact

- `tools/deploy/canworks/configurator/static/app.js`: shared `chooseEds(...)` dialog and `edsField(...)` from the Add node dialog's list; Add node dialog, node General tab, slave page, LSS result use them.
- `commission.js` (Add node from EDS…, `edsPick`, Add to a config…), `identity.js` (`edsChoices`, `changeEds`), `nodes.js` (`addFound`), `trace.js` (`layoutActions`), `sim.js` (extra devices).
- `server.py`: take an EDS by path from the file browser (as `use_eds` does for the library, now any folder the user browsed to), copy `<eds>.notes.json` with it under the rule above, list `.eds`/`.dcf` files in `/api/folders`; Commission takes a project EDS by name.
- Tests: page tests for each place (list sources, Browse… with a clash, Cancel changes nothing, Enter and double-click, focus return), the existing tests updated to the new labels, and the layout check over the dialog.
- No plugin, bridge or CODESYS export change. No hardware test needed; a Commission walk with a real device is listed as optional.
