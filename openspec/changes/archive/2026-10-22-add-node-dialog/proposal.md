# Proposal

## Why

The usability hunt of 2026-10-21 (H5, M17, L2) added nodes the way a new user would:

- **"+ Add node…" is a bare OS file picker.** The project's EDS files (4 in the virtual plant) can't be picked from a list, so adding a second node of a known type means browsing to the same file again. There is no step for the node ID or the name: the node silently gets the lowest free ID and the file name ("2 dio16").
- **The new node maps no PDOs.** "0 of 2 PDOs defined in the EDS used". Every entry needs its own **Add entry…**, although the EDS's default mapping is what most users want first.
- **It opens on the wrong tab.** The spec says a new node opens on General with focus in its name ("Node tabs"). It opened on the tab last used on another node (Advanced).
- **A full-width banner says "dio16.eds is readable by dcfgen and Lely on the PLC."** That is jargon, and it is shown when nothing is wrong.
- **Two names for one variable in the PDO table.** The Variable field shows the placeholder `AI0_Input_PV`, and under the location sits "declared as io_rtd_AI0_Input_PV". An entry with no PLC location at all (dio's 0x6411:1 in the example) has no mark saying it is not mapped.

## What Changes

- **Add node dialog.** "+ Add node…" opens a dialog:
  - **Device description:** the project's EDS files as a list (product name, file name, and how many nodes use it), with **Browse…** for a new file (the system file picker, as today) and the EDS library when one is set.
  - **Node ID:** pre-filled with the lowest free ID, checked as typed (1 to 127, not taken, not the master's).
  - **Name:** pre-filled from the EDS product name, made a valid identifier, unique in the network.
  - **Map the EDS's default PDOs:** ticked. It maps the default mapping of every PDO the EDS enables by default (COB-ID valid), leaving out dummy entries, with suggested names and locations. For a target without locations, it maps names only.
  - **Add**, then the node opens on **PDOs**, or on General when nothing was mapped.

  The heartbeat default from `save-anytime` (when that change is in) applies on Add.
- **EDS check after adding.** A message is shown only when the EDS has a finding (not readable, lint warnings), in the message bar with the findings in words. Nothing is shown when the EDS is fine.
- **One name per PDO entry.** The Variable column shows the name the declarations will use (`io_rtd_AI0_Input_PV`) as its placeholder, and editing it sets `name` as today. The "declared as …" line is shown only when the editor project declares that location under a *different* name.
- **Entries without a location.** An entry with neither a location nor (for CODESYS) a name gets a "not mapped to the PLC" mark in warning text, with **Suggest** filling a free location.
- PC tools minor version bump; README (adding a node) and docs/configurator.md.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `canopen-configurator`: "Network tree" (Add node… opens the dialog), "Node tabs" (a new node opens on PDOs), "Variable names of PDO entries" (one name; declared-as only when different). New requirements: "Add node dialog", "Default PDOs of a new node", "EDS check after adding a node", "Entries without a location".

The change modifies "Network tree", and `one-place-navigation` modifies it too (the Project entry). Whichever change applies second brings its delta up to date first.

## Impact

- `tools/deploy/canworks/configurator/static/tree.js` (Add node action), `app.js` (dialog, EDS list from the project and library, default PDO mapping, EDS report message), `node.js` (PDO table names and not-mapped mark, open tab after adding), `server.py` (the list of the project's EDS files with product names; the add endpoint takes node ID, name and the mapping choice).
- Tests: page tests for the dialog (list pick, Browse, ID check, name, default PDOs on and off, CODESYS names only), the opened tab, no banner for a clean EDS, the variable column and the not-mapped mark.
- No plugin, bridge or CODESYS export change. No hardware test.
