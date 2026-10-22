# Proposal

## Why

The usability hunt of 2026-10-21 (H3, M10, L10) walked Commission against the real plugin on a simulated bus:

- **Picking a node shows nothing new on screen.** The node's page is drawn *under* the Nodes table, the bus and SYNC rows and the Unconfigured devices (LSS) card, about 765 px down at 1366×860. Clicking a node in the tree or a table row doesn't scroll, so the visible part of the page doesn't change. The spec already says a network entry opens the Nodes table and a node entry opens the node's live tabs ("Tree in Commission with a config"). The page shows both at once instead.
- **After Read all, the object dictionary still shows no values.** All three groups stay folded ("Groups and objects SHALL start folded"), and an empty Watch list card sits above them.
- **The Nodes table says things that are not true:**
  - "Last heard" is "-" for every node of a runtime connection, while heartbeats arrive every 100 ms. The plugin's status has no `last_heard` per node, and only the adapter path fills it.
  - A node whose device sent EMCY 0x0000 ("error reset or no error") gets the red flag "new error entry", although that entry clears the diagnosis.

## What Changes

- **Master and detail.** In Commission with a config, a network entry shows the Nodes table page: bus state, SYNC, the table and Unconfigured devices (LSS). A node entry shows **only** that node's page. The page starts with a one-line node header: ID, name, state shape and text, last heard, boot result, simulated mark, and "← Nodes" to go back. Clicking a table row opens the node like the tree does. Commission a device works the same way: Nodes is its home, a node is its own page. The selected tab still stays when stepping from node to node.
- **Scroll position.** Opening a page or switching a node tab starts at the top of the work area, with the tab row in view.
- **Read all shows what it read.** After Read all, the groups that got values unfold, with their objects folded. Objects whose value differs from the EDS default unfold too. A search or filter still unfolds what matches. The Watch list card shows only once an entry is watched; before that, a one-line hint "Tick Watch on an entry to read it again and again" sits under the filters.
- **Last heard from the plugin.** The plugin's status reports, per node, the time since anything was last received from it (heartbeat, boot-up, EMCY, a TPDO or an SDO answer). The Nodes table and node header show "0.1 s ago". "-" is kept only when the node was never heard.
- **EMCY 0x0000 clears, it doesn't flag.** An EMCY with error code 0x0000 counts as the clearing of the node's diagnosis: the flag turns grey (as "Diagnosis flag and simulated mark" says). The Last EMCY column shows "cleared (0x0000)" in neutral text.
- PC tools minor version bump; plugin patch version. docs/configurator.md (Commission).

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `canopen-configurator`: "Tree in Commission with a config" (node entry shows the node's page alone, with a node header), "Reading values in the object dictionary view" (Read all unfolds), "Object dictionary view" (folding rule), "Diagnosis flag and simulated mark" (EMCY 0x0000 clears). New requirements: "Watch list only when used", "Last heard in Commission".
- `canopen-online-diagnostics`: new requirement "Time since a node was last heard" in the node status.

## Impact

- `tools/deploy/canworks/configurator/static/nodes.js`, `app.js` (online view layout: network page vs node page, node header, row click), `tree.js`, `commission.js` (Commission a device the same way), object dictionary folding and watch card.
- Plugin: the diagnostics status adds `last_heard_ms` per node (`plugin/` network/diagnostics sources), and `diag.py` / `commissioning.py` read it.
- Tests: page tests for master/detail in both modes (row click, tree pick, back link, tab kept), Read all unfolding, watch card; a plugin unit or host test for `last_heard_ms`; an EMCY 0x0000 test for the flag.
- Hardware test on the Pi (plugin change): Last heard on node 23 with heartbeat on, and a power-off makes it grow.
