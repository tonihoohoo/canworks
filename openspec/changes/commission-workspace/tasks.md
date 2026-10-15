## 1. Groundwork

- [ ] 1.1 Rebase onto `ui-shell-and-connection` and `network-tree-and-node-tabs` once applied; move the page tests of the online node table, the Overview tab and the commissioning Nodes tab to the Nodes table and Status tab helpers, all green before anything new is added
- [ ] 1.2 New ES modules `nodes.js`, `status.js`, `log.js`; move the online table and Overview code out of `app.js` and the log out of `commission.js`, no behaviour change yet

## 2. Server

- [x] 2.1 Allow `/api/online/scan` and `scan_stop` on a runtime connection; force on retry only when the page sends it
- [x] 2.2 `_match_scan`: `compare` per device (match, not_in_config, identity_differs with the differing fields) and `missing` (configured nodes of the scanned network that did not answer); unit tests for each state, several networks and a v1 config
- [x] 2.3 `online.json` `recent`: up to three connections (adapter target and bit rate, or runtime name and address), no tokens; older files load unchanged

## 3. Nodes table

- [ ] 3.1 Session node list (config, heard, scanned, LSS, Add node from EDS) and the table with its columns per mode; greyed stale values; row opens the node in the tree and its Status tab
- [ ] 3.2 Not-connected state: inline connect form and recent connections; drop the shell's "open the panel once"
- [ ] 3.3 Comparison: states, summary with filters, Heard / Not heard before a scan
- [ ] 3.4 Actions: Add to config (single and ticked rows, EDS picker, LSS assign rule), Use matching EDS, Take serial number; all as draft edits with Undo; Problems opens on a new problem
- [ ] 3.5 Scan through a runtime: force dialog naming OPERATIONAL nodes, relayed or slow path confirmation, progress in the status bar
- [ ] 3.6 Unconfigured devices panel under the table, collapsed until changes are allowed or a search runs; Set node ID with a config ends in Not in config with Add to config

## 4. Node tabs

- [ ] 4.1 Commission node tabs (Status, Object dictionary, Parameters, PDO test in Commission a device only, Notes, Log); selected tab kept across nodes; tab pattern
- [ ] 4.2 Status tab: state, heartbeat, boot result, NMT buttons, PDO timeouts, EMCY history, error history; Add to a config… in Commission a device
- [ ] 4.3 Session log: events from status and replies, changes, comparison actions; node Log tab; bottom panel Log tab with filter; caps; Save log per mode with "Include bus events"
- [ ] 4.4 Bottom panel in Commission with a config: Log (default) and Problems

## 5. Tree, lock and simulation

- [ ] 5.1 Live state on the tree: shape marks with text, new-entry flag cleared by opening Status, Missing and Identity differs marks; in Configure only while connected to a runtime
- [ ] 5.2 Unlock… on every control disabled by the lock: confirmation on an adapter with focus kept; explanation on a runtime; other disabled reasons unchanged
- [ ] 5.3 Simulated devices: marks in the table, Simulated device panel on the Status tab (power, faults, live values with Override and Release) reusing `sim.js` controls, following Allow changes

## 6. Tests

- [ ] 6.1 Page tests on the fake plugin runtime: comparison states and summary, Add to config with Undo, Use matching EDS, scan refused without force then confirmed, Log in Commission and none in Configure
- [ ] 6.2 Page tests on the virtual adapter: Nodes table without a config, inline connect and recent connection, Status tab, Save log with and without bus events, Unlock in place without "another master"
- [ ] 6.3 Page tests: tree state marks and announcement when a node stops answering; selected tab kept across nodes
- [ ] 6.4 Local simulator runtime test (in the existing simulator CI job): scan finds an extra device as Not in config, fault injected from the Status tab shows in the table, tree and Log
- [ ] 6.5 axe-core on the Nodes table, comparison, Status and Log tabs in both themes; layout fit at 1000, 1280 and 1440 px; one keyboard-only run: connect, scan, add a found device, open its Status tab, unlock, disconnect

## 7. Docs and release

- [ ] 7.1 `docs/configurator.md` (Commission workspace: Nodes table, comparison, node tabs, log, tree state, Unlock, simulated devices; Overview is now Status), `docs/pc-adapter.md`, `docs/tour.md`, `README.md`
- [ ] 7.2 PC tools minor version bump and changelog line

## 8. Hardware check

- [ ] 8.1 On the bench through a runtime with a config: scan compares the real node with the config (Match), a changed expected revision reads Identity differs, and a powered-off node reads Missing
