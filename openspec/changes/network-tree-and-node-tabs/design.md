## Context

After `ui-shell-and-connection` the page has a header with the **Configure | Commission** switch and tool tabs, a connection bar, a status bar with jobs, and a bottom panel with Problems or Log. Inside the workspace tab ("Network" in Configure, "Nodes" in Commission) the left column is still the old side bar:

- a network bar with one tab per network (`renderNetBar`), showing one network at a time;
- **Bus and master**, the network's node list, **Add node from EDS…**;
- loose entries for Gateway, Modbus bridge, PDO links, CAN messages;
- the unused EDS note and the address scan line.

A Configure node page (`renderNode` in `app.js`) is one scroll with a sticky section index: Node, Supervision, Emergency, Axis, Advanced, Inputs, Outputs, Startup SDO writes, SDO variables. In Commission with a config, the online view has its own node list, and a node opens the tabs Overview, Object dictionary and Parameters.

This change replaces that left column with a network tree, turns the Configure node page into tabs, and moves problem counts and live state onto the tree. It changes no file format, protocol or CLI.

## Goals / Non-Goals

**Goals:**
- One navigation for everything on the bus, the same in Configure and in Commission with a config, with every network visible at once.
- A node is edited one subject at a time, with no page-long scroll.
- The user sees where a problem is before opening anything: which network, which node, which tab.
- In Commission the tree shows which nodes are running, waiting, stopped or in error.

**Non-Goals:**
- Commission a device's device list, the Nodes table home, scan comparison and node Status and Log tabs (`commission-workspace`).
- New state colours, icon set and density (`visual-refresh`).
- Splitting the Bus and master page into tabs. With Online access moved out it is short enough.
- A link matrix for PDO links (research 4.3). The Links page stays as it is.

## Decisions

### 1. The tree replaces the side bar, the network bar and the node list
`tree.js` renders the left column of the workspace tab from `S.model.networks` and the top-level config. Its entries:

```
▾ io · CANopen master            2✕
    Bus and master
    ● 5  rtd                    2✕
    ○ 7  valve (simulated)
    + Add node…
    PDO links
    CAN messages
▸ drives · CANopen master        1⚠
▸ trucks · J1939
  Online access
  Gateway
  Modbus bridge
+ Add network…
```

- A network entry shows its name and protocol (CANopen master, CANopen slave, J1939, Plain CAN). Its children are what the side bar shows for that network today, in the same order, with nodes sorted by node ID. A slave network shows Bus and its slave device entry ("12 slave (this PLC)").
- **Add node…** is the last child of a CANopen master network and opens the EDS file chooser for that network, as today's **Add node from EDS…** does.
- Online access, Gateway and Modbus bridge are config-wide, so they sit after the networks. Gateway and Modbus bridge show when the config has them, as today.
- **Add network…** is the last entry and opens today's add-network dialog.
- The unused EDS note and the address scan line move under the tree as a muted footer.
- Each network entry has a "⋯" menu button with **Rename…**, **Role** (master or slave, CANopen networks) and **Remove…**, with today's confirmations. With one network the tree still shows the network entry, so the network's name and menu are always reachable; it starts expanded.
- Which networks are expanded is kept per folder in `ui.json`. A network holding the selected entry or a new error expands by itself.

*Alternative:* keep network tabs and only make the node list a tree. Rejected: a config with two networks then still hides one network's problems and state.

### 2. Tree behaviour and keyboard
The tree follows the WAI-ARIA tree view pattern: `role="tree"` with `treeitem` entries, `aria-expanded` on networks, `aria-selected` on the open entry, and one tab stop (roving `tabindex`).

| Key | Action |
|---|---|
| Down / Up | next / previous visible entry |
| Right | expand a network, or move to its first child |
| Left | collapse a network, or move to the parent |
| Home / End | first / last entry |
| Enter / Space | open the entry |
| a letter or digits | type-ahead on the entry text, so `5` finds node 5 |
| Shift+F10, or the ⋯ button | the network menu |

Long names are cut with an ellipsis and shown whole in a tooltip and in the accessible name. Renaming a node updates its entry as the user types (today's rule for the node list). The tree keeps focus on the same entry across re-renders, as the node list does today.

### 3. Node tabs in Configure
`node.js` takes over `renderNode` and splits it into tabs, using the page's existing `tabs()` helper:

| Tab | Content (from today's sections) |
|---|---|
| General | Node: node ID, name, EDS, Simulated; the EDS error when the EDS cannot be read |
| PDOs | Inputs and Outputs |
| SDOs | Startup SDO writes, SDO variables |
| Supervision | Supervision (heartbeat or guarding, status bit, state byte, NMT command, boot error byte) and Emergency (EMCY code, error register, EMCY COB-ID) |
| CiA 402 | Axis |
| Simulation | new, see decision 6 |
| Notes | new, see decision 7 |
| Advanced | Advanced |

- **CiA 402** shows when the node's EDS has 0x6040 and 0x6041, or when the node already has an `axis`, so an axis set on a wrong EDS stays visible with its problem.
- **Simulation** shows when the node is simulated.
- The toolbar above the tabs keeps the heading "Node 5 rtd", Export DCF and Remove node. Export merged notes moves to the Notes tab.
- The open tab kind is kept when the user opens another node, when that node has it (General otherwise), so comparing one setting across nodes is a click per node. It is part of the URL hash next to the workspace (`#configure/io/node/5/pdos`) and of `ui.json`, so a reload returns to it.
- A new node from an EDS opens on General with focus in its name, as today.
- The section index and its `IntersectionObserver` are removed.

*Alternative:* keep one page and fold sections. Rejected: the research's main finding for node pages was the 4,000 to 5,000 px scroll, and every tool compared uses tabs.

### 4. PDOs tab
- Inputs (TPDOs) and Outputs (RPDOs) are two columns when the page is at least 1400 px wide, and stacked, Inputs first, below that. The page is wider than today because the Problems column is gone since `ui-shell-and-connection`.
- Each PDO is a card: its title ("TPDO 1"), its mapping table and "Add entry…" as today, and one summary line of its communication settings, for example "COB-ID 0x185 · on change · event 100 ms · timeout 500 ms". **Settings** on that line opens the fields under it (COB-ID, transmission type, inhibit time, event timer, SYNC start, timeout).
- The settings start closed, and open by themselves when one of them has a problem. The user's own open or close is kept for the open node, as `collapsible()` does today.
- "Map all" stays for device-mapped PDOs.

### 5. SDOs tab
Startup SDO writes and SDO variables stay two tables on the tab, each with its heading, count and add action. Their columns differ (a value written once at boot against a PLC variable read or written while running), and one merged table would need a kind column and empty cells on every row. Both show expanded on this tab; the collapse of empty sections goes away, because the tab holds nothing else.

### 6. Simulation tab and simulated marks
For a simulated node (the node's `simulate`, or a simulated network), the Simulation tab edits that node's part of `simulation.json`: value sources, faults at start, `default_behaviour`. It uses the Simulation tool's editors and the same draft, so a change shows in both places and is saved with **Save to simulation file**. Live values and fault injection stay in the Simulation tool and, from `commission-workspace`, in the node's Status tab.

On the tree, a simulated node's mark is hollow with "(simulated)" in its accessible name, and a node switched off on a simulated network is drawn dashed and named "absent". The simulation banner stays: it warns not to upload the config as it is, which a mark on the tree does not.

### 7. Notes tab
The Notes tab lists the objects of the node's EDS that have a note (built-in or the user's own), with the note text, unit and meaning of values, and a **Note** button that opens the existing Note editor. A search box filters by index or name. **Export merged notes** moves here from the toolbar. Without an EDS, or with notes that cannot be edited (as `notesEditable` decides today), the tab is read-only and says why.

### 8. Problem badges
Problems already carry the config path of their field (`nodes[2].tx_pdos[1].entries[0].location`). A small map turns a path into a tree entry and a tab:

| Path | Entry | Tab |
|---|---|---|
| `nodes[i].tx_pdos…`, `rx_pdos…` | node | PDOs |
| `nodes[i].sdo…`, `sdo_variables…` | node | SDOs |
| `nodes[i].heartbeat…`, `…status_location`, `…emcy…` and the other supervision keys | node | Supervision |
| `nodes[i].axis…` | node | CiA 402 |
| `nodes[i].node_id`, `name`, `eds`, `simulate` | node | General |
| other `nodes[i].…` | node | Advanced |
| `adapter…`, `master…` | Bus and master | |
| `links…`, `raw…`, `slave…` | PDO links, CAN messages, slave device | |
| `diagnostics…`, `cia309…`, `gateway…`, `bridge…` | Online access, Gateway, Modbus bridge | |
| no path | the network | |

- Each tree entry and node tab shows its error count with a cross and its warning count with a triangle, for example "2✕ 1⚠"; the accessible name says "2 errors, 1 warning".
- A collapsed network shows the sum of its entries; an expanded one shows only its own (network-level) problems.
- Clicking a problem in the bottom panel selects its entry, expands its network, opens its tab, opens a closed PDO settings part when needed, and focuses the field, as clicking a problem does today.

### 9. State on the tree
`tree.js` subscribes to the connection service of `ui-shell-and-connection` (`connected`, `changed`, `ended`). While a runtime is connected, in Commission and in Configure, each node entry of the connected network shows its NMT state from the online status:

| State | Mark | Name |
|---|---|---|
| OPERATIONAL (5) | filled circle | operational |
| PRE-OPERATIONAL (127) | triangle | pre-operational |
| STOPPED (4) | square | stopped |
| no contact (0) or a boot error | cross | no contact / boot error with its letter code |
| unknown, not connected | none | |

A node whose last EMCY has a non-zero error code gets a "!" mark after its state; it turns grey once the device sends its error reset, and goes away when the user opens the node. Colours are today's state colours; shape and the accessible name carry the meaning without colour. When the connection ends, the marks turn grey with the bar ("last data N s ago" is in the bar), so stale state is never shown as live. The network entry shows the bus state of that network when it is not error active.

Marks use the same online status the Commission node table reads, so no new polling.

### 10. Commission with a config
The Commission workspace tab uses the same tree, built from the config:
- a network entry opens that network's node table (today's online view of the network);
- a node entry opens the node's live tabs (Overview, Object dictionary, Parameters, as today);
- Bus and master opens the bus and master part of the online view;
- configuration-only entries (Add node…, PDO links, CAN messages, Online access, Gateway, Modbus bridge, Add network…) are not shown, and the network menu is not shown.

The connection bar's network picker and the tree stay in step: picking a node on another network moves the picker, and changing the picker selects that network's entry. With the tree, the picker's start rule ("the network whose tab is open in Configure") becomes "the network of the entry selected in Configure".

Selected entries are kept per workspace, so switching workspace returns to where the user was in each.

### 11. Online access entry
Online access (`master.diagnostics`, with the CiA 309-3 gateway part) is one setting for the whole config (requirement "Online access for all networks"), so it becomes its own tree entry after the networks instead of a section of the first network's Bus and master page. The connection bar's read-only lock text and the connect panel's "Online access is off" link point there.

### 12. Narrow window
Below 1000 px the tree folds into a "Network ▾" button at the top of the workspace tab that opens the tree as a panel over the page; picking an entry closes it. The button shows the selected entry's name and the config's total error count, so problems stay in view with the bottom panel's count.

### 13. Code layout
- `tree.js`: tree rendering, keyboard, network menu, badges, state marks.
- `node.js`: node toolbar and tabs; each tab's content keeps today's render functions (`renderPdos`, `renderSdos`, `renderSdoVars`, `axisFields`, `nodeAdvanced`, `supervisionFields`), moved with it.
- `problems.js` (or in `panel.js` from the last change): the path-to-entry-and-tab map, shared by the badges and problem navigation.

There is still no build step.

## Risks / Trade-offs

- **[Many page tests click the side bar, the network bar or a node page section]** → Test helpers `openEntry(network, item)` and `openNodeTab(node, tab)` first; the existing tests move to them, all green before new tests are added. The same tests then check the new layout.
- **[A field moves to a tab the user does not expect]** → Problem navigation always opens the right tab, the tab badges show where the problems are, and docs/configurator.md has a table of where each former section went.
- **[A problem path that the map does not know]** → It falls back to the node's General tab, or the network entry, and a test walks every check message in the parity corpus (`test/fixtures/config/bad`) to assert each lands on an entry.
- **[PDOs side by side are cramped at exactly 1400 px]** → The layout fit check runs at 1280, 1440 and 1600 px, and the breakpoint moves up if a mapping table does not fit.
- **[State marks on a slow or relayed path lag]** → They read the same status as the bar, so they are as fresh as it is, and grey with it.

## Migration Plan

UI only:
- `ui.json` gains `tree_expanded` and `node_tab` per folder; older files lack them and the page starts with every network expanded and General.
- Rollback is the previous tools version.

## Open Questions

None. Defaults picked here, easy to change in review:
- PDO columns side by side from 1400 px;
- SDO writes and SDO variables as two tables on one tab;
- the open tab kept across nodes;
- Online access as a tree entry rather than a Bus and master section;
- Commission a device left to `commission-workspace`.
