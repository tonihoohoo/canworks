## Context

After `ui-shell-and-connection` the page has two workspaces, a connection bar with Allow changes, one connect panel, a status bar with jobs and a bottom panel. After `network-tree-and-node-tabs` the side bar is a network tree and node pages are tabs. Commission still holds the old content:

- with a config, the online view (`app.js`): a node table and node pages with Overview, Object dictionary and Parameters, the Unconfigured devices panel, and no scan (the server answers `/api/online/scan` with 404 on a runtime since `rework-commission-and-trim-configurator`);
- without a config, the commissioning Nodes tab (`commission.js`): devices heard, scanned, set by LSS or added from an EDS, with Scan, LSS, PDO test, notes, Add to a config… and the commissioning log.

The server already matches a scan with the config (`_match_scan`: per device the config's name, EDS and expected identity, and the matching EDS files). The plugin already answers `scan` on its diagnostics channel and refuses it without `force` while a node is OPERATIONAL. The simulator runtime runs simulated devices that answer LSS and SDO like real ones, and its `sim_*` operations (faults, values) are what the Simulation tool uses.

This change makes Commission one coherent place. It changes no file format, protocol or CLI.

## Goals / Non-Goals

**Goals:**
- One home for Commission, the same with and without a config, whose empty state is the first step (connect).
- A scan that answers "is the bus what the config says?" and turns a found device into a node in one action.
- Everything about one node's live state on one tab, and a record of what happened to it.
- Node state visible on the tree without opening the table.
- No dead-end disabled controls.
- Commissioning can be practised on the local simulator runtime without switching tools.

**Non-Goals:**
- An adapter connection with a config, or a runtime connection in Commission a device. The rules from the last two changes stay.
- Writing a whole config to a node from the comparison (that stays Write configuration in Commission a device, and the PLC's boot with a config).
- New state colours and icons, denser tables (`visual-refresh`), the trace changes (`trace-workspace`).
- Removing a configured node from the comparison. Missing nodes may simply be powered off; removing a node is a Configure edit.

## Decisions

### 1. One Nodes table, two sources
`nodes.js` owns a session node list, keyed by network and node ID. Entries come from:
- the config's nodes (with a config);
- heartbeats and boot-ups seen in status;
- scan results;
- LSS Set node ID in this session;
- Add node from EDS… (Commission a device only).

Columns, in order:

| Column | With a config | Commission a device |
|---|---|---|
| Comparison | ✓ (after a scan, or from what was heard) | |
| Node ID, Name | config name, else EDS product name | EDS product name or user's name |
| State | NMT state as shape and text, greyed when stale | same |
| Last heard, Last EMCY | ✓ | ✓ |
| Boot result | from the master | |
| EDS | config EDS, or the match | the match or the picked EDS |
| Marks | simulated, absent, notes | notes |

The table is the Commission workspace's home: the Nodes tab with nothing selected in the tree, and the tree's network entry. Clicking a row (or Enter) opens the node in the tree and its Status tab. It replaces the online view's node table and the commissioning Nodes tab. The Unconfigured devices (LSS) panel stays under the table, collapsed until changes are allowed or a search runs.

*Alternative:* keep two tables, one per mode. Rejected: the research's main finding is that the two modes look like different tools for the same job.

### 2. Connect from the home
While not connected, the Nodes table's empty state is the connect panel's form, inline, plus up to three recent connections from `online.json` ("gs_usb:0 at 500 kbit/s", "line-3 runtime") with one-click Connect. A recent adapter connection still runs the bit rate check and still starts with Allow changes off. The shell's rule "entering Commission while not connected opens the panel once" is dropped, because the form is already on the page; the bar's **Connect…** still opens the dialog from any page.

### 3. Comparison states
The server extends `_match_scan` with `compare` per scanned device and a `missing` list of configured nodes of the scanned network that did not answer:

| State | Rule | Shown |
|---|---|---|
| Match | configured, answered, vendor and product match the node's EDS, and revision and serial match where the config sets them | neutral, check mark |
| Missing | configured, did not answer the scan and was not heard | fault colour, "Missing" |
| Not in config | answered, no configured node with that ID | warning colour, "Not in config" |
| Identity differs | configured, answered, identity differs from what the config expects | warning colour, differing fields listed in the row |
| Not scanned | before the first scan in this connection, from heartbeats only | neutral, "Heard" or "Not heard" |

A node that is not configured but heard counts as Not in config. Text names every state, so colour is never the only cue. A summary over the table reads "12 match · 1 missing · 2 not in config · 1 differs", each part a filter.

The research suggested red for "only on one side" in both directions. Missing is a fault (the machine will not run); Not in config is a finding (a device to add or ignore), so it gets the warning colour.

### 4. Actions on the comparison
- **Add to config** (Not in config): adds an unsaved node to the draft with that node ID, the matching EDS (a picker when several match, an EDS file picker when none does), the EDS product name as name, the serial number, and `lss.assign` when the ID was set by LSS in this session and the EDS supports LSS. Several rows can be ticked and added at once.
- **Use matching EDS** (Identity differs, when a library or project EDS matches the device): replaces the node's EDS in the draft. The config check then lists any mapped object the new EDS lacks, as for any EDS change.
- **Take serial number** (Identity differs only in serial): sets the node's `serial_number` to the device's.

All three are draft edits: the header's unsaved mark shows, Undo reverts them, and Save in the header saves. The user stays in Commission. Problems that follow show in the bottom panel's Problems tab, which opens.

### 5. Scan through a runtime
The 404 on `/api/online/scan` for a runtime is removed. The page offers Scan only in the Commission workspace. When the runtime refuses because a node is OPERATIONAL, the page asks: "Scanning sends SDO requests to every node ID while the PLC program runs nodes 3, 5 and 7. Scan anyway?" with Cancel as the default, and retries with `force`. Progress and Cancel are in the status bar (shell change). The scan is a read: it does not need Allow changes, as today on an adapter.

### 6. Commission node tabs
| Tab | With a config | Commission a device |
|---|---|---|
| Status | ✓ | ✓ |
| Object dictionary | ✓ | ✓ |
| Parameters | ✓ | ✓ |
| PDO test | | ✓ |
| Notes | ✓ (draft edit) | ✓ (read-only, as today) |
| Log | ✓ | ✓ |

**Status** has, top to bottom: NMT state, last heard, heartbeat and boot result with error text, NMT buttons (Start, Stop, Pre-operational, Reset node, Reset communication, with today's confirmations), PDO timeouts per monitored TPDO, the EMCY history and the error history (0x1003) with Refresh and Clear. The tabs follow the page's tab pattern. The selected tab is kept when another node is picked, so stepping through nodes on the Object dictionary tab stays there.

### 7. Session log
`log.js` keeps one list per page session:
- **events** derived from status polls and replies: NMT state change, boot result, EMCY, error history change, SDO abort, PDO timeout, connection ended;
- **changes** made through the page: SDO write, NMT, LSS set ID, set bit rate and store, write configuration, restore, restore defaults, store, error history clear, comparison actions.

Each entry has the UTC time, network, node, kind, text and result. A node's Log tab shows that node's entries; the bottom panel's **Log** tab shows all, with a filter (All, Changes, Events). The list keeps the last 5,000 events; changes are never dropped.

- **Commission a device:** Save log writes the commissioning record as today (`node<N>-commissioning-<time>.txt`, changes only), with a tick "Include bus events". Leaving with unsaved changes asks first, as today.
- **With a config:** the log exists in the Commission workspace only (Configure shows no Log tab), lives in this page only, and Save log downloads `<config>-commission-<time>.txt`. It is never written into the project. Toni's earlier point that the commissioning log must not show while editing a config holds: Configure has no log.

The bottom panel in Commission with a config gets Log next to Problems; Log is the default tab there.

### 8. Live state on the tree
While connected, `nodes.js` publishes state per node through the shell's event emitter, and the tree (from `network-tree-and-node-tabs`) draws, after the node's name:
- a state mark by shape with text for screen readers: circle Operational, triangle Pre-operational, square Stopped, cross Not answering or boot failed, hollow circle not heard;
- a flag when a new EMCY or error history entry arrived since the node's Status tab was last opened;
- in a comparison, a small "missing" or "differs" mark.

This change uses the existing state colours; `visual-refresh` replaces them. In Configure the tree shows live state only while connected to a runtime (the connection bar is visible then), using the same marks.

### 9. Unlock from a locked control
Every write control disabled by the lock gets the same affordance: its reason line reads "Locked. Changes are not allowed on this connection." with **Unlock…**. On an adapter, Unlock asks the same question as the bar's switch and, when confirmed, turns Allow changes on for the open connection, then the control is enabled where it is; focus stays on it. On a runtime, Unlock opens a short note: Allow changes is set in Configure → Bus and master → Online access and takes effect after an upload. Controls disabled for other reasons (no 0x1010, CiA 402 objects missing) keep their own reasons.

### 10. Simulated devices in Commission
Connected to the local simulator runtime (or any runtime with simulated nodes):
- the Nodes table and tree mark simulated nodes, and extra devices from the simulation file appear as Not in config after a scan or LSS find;
- a simulated node's Status tab gains a **Simulated device** panel: power state with Power off/on, the fault buttons the Simulation tool has (inject and clear), and the node's PDO objects with live values, each with Override and Release. It reuses the Simulation tool's controls from `sim.js` and addresses the device by node ID;
- Allow changes governs the panel as in the Simulation tool.

The Simulation tool stays for editing the simulation file and the scenarios.

### 11. Code layout
`nodes.js`, `status.js` and `log.js` are new ES modules beside the shell's. The online view code in `app.js` that draws the node table and the Overview tab moves into them; `commission.js` keeps LSS, Parameters, Write configuration, restore defaults, PDO test and Add to a config…. No build step.

## Risks / Trade-offs

- **[Scanning a running machine from the configurator]** → Scan is a read, needs a click, and asks before it uses `force`, naming the OPERATIONAL nodes. A relayed path or slow round trip asks first, as LSS does.
- **[Add to config from a scan picks the wrong EDS]** → Several matches open a picker; the node is unsaved and Undo removes it; the config check runs as for any added node.
- **[Session log grows]** → Events are capped at 5,000; changes are few.
- **[Overlap with `network-tree-and-node-tabs`]** → That change owns the tree and its simulated/absent marks; this change only adds the live state marks and the Commission tabs. Whichever is applied second rebases onto the other.
- **[Users look for Overview]** → The tab is renamed Status and keeps all of Overview's content; the docs say so.

## Migration Plan

UI only. `online.json` gains `recent` (up to three connections, no tokens); older files load unchanged. Rollback is the previous tools version.

## Open Questions

None. Defaults picked: Not in config uses the warning colour, not the fault colour; Log is the default bottom tab in Commission with a config; the connect panel no longer opens by itself on entering Commission.
