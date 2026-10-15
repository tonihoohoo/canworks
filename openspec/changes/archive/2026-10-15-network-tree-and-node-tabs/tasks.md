## 1. Groundwork

- [x] 1.1 Page test helpers (`tree_entry`, `tree_node`, `node_tab`, `show_path`, `net_action` in `tests/helpers.py`); move the existing page tests from side bar, network bar and section index clicks to them, all green before anything new is added
- [x] 1.2 Problem place map (`entryOfPath` and `nodeTabOfPath` in `tree.js`): config path to tree entry and node tab, with the fallbacks
- [x] 1.3 `ui.json`: `tree_folded` and `node_tab`; older files load unchanged

## 2. Network tree

- [x] 2.1 `tree.js`: networks with protocol, Bus and master, nodes by node ID, slave device, Add node…, PDO links, CAN messages; Online access, Gateway, Modbus bridge, Add network…; unused EDS and scan line as footer; remove `#side`'s node list and the network bar
- [x] 2.2 Network menu: Rename…, Role, Remove… with today's confirmations; Add network… opens today's dialog
- [x] 2.3 Keyboard: ARIA tree, roving tab stop, arrows, Home, End, type-ahead, Shift+F10; focus kept across redraws; ellipsis with full name in tooltip and accessible name
- [x] 2.4 Folded networks kept on this PC; a problem link unfolds its network; node rename updates its entry as the user types
- [x] 2.5 Online access as its own entry: move the Online access section (with the CiA 309-3 gateway part) out of Bus and master; point the connection bar's lock link and the connect panel's link at it

## 3. Node tabs

- [x] 3.1 `node.js`: toolbar (heading, Export DCF, Remove node) and tabs General, PDOs, SDOs, Supervision, CiA 402, Simulation, Notes, Advanced, moving today's render functions; remove the section index and its observer
- [x] 3.2 Tab rules: CiA 402 only with 0x6040 and 0x6041 or an existing axis; Simulation only when simulated; tab kept across nodes and in `ui.json`; new node opens General with focus in the name
- [x] 3.3 PDOs tab: columns from 1400 px, stacked below; per-PDO summary line and Settings part, open on a problem, user choice kept for the open node
- [x] 3.4 SDOs tab: startup writes and SDO variables as two tables, always shown, with counts and add actions
- [x] 3.5 Simulation tab: the node's sources, faults at start and default behaviour from the Simulation tool's editors and draft, per network section
- [x] 3.6 Notes tab: objects with notes, search, Note editor, Export merged notes (moved from the toolbar), read-only with the reason

## 4. Badges and marks

- [x] 4.1 Problem badges on entries and node tabs (errors and warnings, shape and text, accessible names); sum on a collapsed network
- [x] 4.2 Problem navigation: select entry, expand network, open tab and closed part, focus the field
- [x] 4.3 Simulated (hollow) and absent (dashed) marks in both workspaces

## 5. Commission with a config

- [x] 5.1 The tree in Commission: networks and nodes only; network opens its node table, node its live tabs; remove the online view's own node list
- [x] 5.2 Tree and the connection bar's network picker in step; selected entry kept per workspace; picker starts on Configure's selected network

## 6. Layout

- [x] 6.1 Narrow layout: tree button with the selected entry and error count at 1100 px and narrower, tree over the page, closes on pick
- [x] 6.2 Layout fit at 1000, 1280, 1440 and 1600 px for the tree, every node tab and the PDOs columns

## 7. Tests

- [x] 7.1 Page tests: two networks in the tree, Add node… under the second network, network menu rename/role/remove, expanded state after reload
- [x] 7.2 Page tests: node tabs (tab kept across nodes, reload, CiA 402 shown and hidden, new node focus), PDO summary and Settings opening on a problem, SDOs tab empty, Notes search, Simulation tab saving to `simulation.json`
- [x] 7.3 Page tests: badges per entry, tab and collapsed network; problem click to the field on another node's tab; badges clear after a fix
- [x] 7.4 Page tests on the fake plugin runtime: Commission tree with two networks, no configuration-only entries, the picker in step, selection kept per workspace
- [x] 7.5 axe-core on the tree and the node tabs in both themes; keyboard-only run: open a node by typing its ID, change a tab, follow a problem, rename a network from its menu

## 8. Docs and release

- [x] 8.1 `docs/configurator.md` (tree, node tabs, badges, simulated marks, Online access entry, table of where each former section went), `docs/tour.md`, `docs/simulator.md` (marks and the node's Simulation tab), `README.md`
- [x] 8.2 PC tools minor version bump and changelog line
