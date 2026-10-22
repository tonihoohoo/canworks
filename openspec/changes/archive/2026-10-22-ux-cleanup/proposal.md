# Proposal

## Why

The usability hunt of 2026-10-21 (`research/ux-deep-hunt-2026-10-21`) found medium and low items that don't belong to the five larger changes (`save-anytime`, `compact-chrome`, `commission-master-detail`, `one-place-navigation`, `add-node-dialog`). Each is small, but together they make the page feel unfinished:

- **M1:** a simulated network's Bus page still shows the whole CAN adapter section with "Required" fields, and CODESYS shows dropdowns that have one choice (Protocol CANopen, Role Master).
- **M2:** an **empty yellow warning bar** (icon only) on Simulation while not connected (sim.js:374 creates the notice without `hidden`).
- **M3:** **Save to simulation file** is primary blue even when it says "Saved".
- **M7:** on Parameters, "Restore…" (from a backup) and "Restore defaults…" (factory, 0x1011) have nearly the same name, and the file inputs are the browser's unstyled "Choose File / No file chosen".
- **M8:** startup writes can add **0x1010 Save all parameters** and 0x1011 with a plain Add, which would store (and wear flash) or factory-reset on every boot. That goes against the project's rule never to save to the device's memory automatically.
- **M11:** a simulated value's slider spans the whole INTEGER16 range while its source moves 200…260. Set and Override aren't explained.
- **M12:** the Add device message lands beside the Host field in lowercase, and "Not reached" shows a raw `[Errno None] Unable to connect…`.
- **M14:** the folder dialog doesn't mark projects or configs before you enter them, and says "No EDS files in this folder" while you pick a project.
- **M15:** a network's ⋯ menu opens as a centred dialog with a row of buttons.
- **M17 (part):** PDO headings say "slave to PLC" and "PLC location" on a Modbus bridge config.
- **Small items:**
  - L3: the SDO table title shows twice, and a value is decimal next to a hex EDS default.
  - L4: Notes shows its buttons twice.
  - L6: Supervision has one Suggest per field.
  - L7: Declarations repeats "declared as <same name>" on every row.
  - L9: Graph series names are cut with no way to read them.
  - L10: in dark mode, the disabled "Saved" looks like the selected "Configure".
  - L11: the mode badge shows a whole path for config folders.

## What Changes

- **Bus page:** the adapter section folds on a simulated network; single-choice fields show as text.
- **No empty message bars:** M2 fixed, with a check that no notice is shown without text.
- **Save to simulation file:** disabled while saved.
- **Parameters:** "Restore from backup…" and "Factory defaults (0x1011)…" (in a section marked as changing the device), with styled file buttons.
- **Startup writes:** never 0x1010 or 0x1011, with a reason pointing to Store on device and Factory defaults.
- **Simulated value slider:** range from the source, else the EDS limits, else the type. Tooltips on Set and Override.
- **Devices:** messages under the field, one-sentence unreachable text with a checklist, the menu named Actions.
- **Folder dialog:** project and config tags, select then open, the EDS line only when picking EDS files.
- **Network menu:** anchored to its button.
- **PDO headings:** in the target's words.
- **Node tabs:** one SDO title, the same notation for a value and its default, Notes buttons once, Supervision "PLC signals" group with Suggest all.
- **Declarations:** check marks, an "Only missing" filter, the task interval under the block, no network picker.
- **Graph:** whole series names on hover and focus, the first PDO signal ticked on a first graph.
- **Dark theme:** disabled and selected look different.
- **Mode badge:** the folder name, with the path in its tooltip.
- PC tools minor version bump; docs/configurator.md where wording changes.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `canopen-configurator`: "Startup SDO picker shows settings" (no 0x1010/0x1011). New requirements: "Bus page of a simulated network", "No empty message bars", "Save to simulation file state", "Parameters names and file buttons", "Simulated value control range", "Device messages", "Folder dialog marks projects", "Network menu anchored", "PDO headings per target", "Small fixes on node tabs", "Declarations at a glance", "Graph series names", "Disabled and selected look different", "Mode badge names the folder".

## Impact

- `tools/deploy/canworks/configurator/static/`:
  - `app.js` (Bus page, startup writes, Parameters, declarations, badge);
  - `sim.js` (empty notice, Save state, slider);
  - `devices.js`;
  - folder dialog code in `app.js` / `shell.js`;
  - `tree.js` (menu);
  - `node.js` (headings, SDO title, notation, Supervision group);
  - `trace.js` (graph);
  - `style.css` (disabled vs selected).
- `server.py`: folder listing tags; Devices reach message.
- Tests: one page test per requirement; the empty-notice check in the layout sweep.
- No plugin, bridge or CODESYS export change. No hardware test.
