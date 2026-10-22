## MODIFIED Requirements

### Requirement: Tree in Commission with a config
In Commission with a config, the tree SHALL show the config's networks and their nodes, without the configuration-only entries (Bus and master, Add node…, PDO links, CAN messages, Online access, Gateway, Modbus bridge, Add network…) and without the network menu. A network entry SHALL open that network's page: bus state, SYNC, the Nodes table and Unconfigured devices. A node entry SHALL open only that node's page: a one-line node header (node ID, name, state shape and text, last heard, boot result, simulated mark, and a link back to the Nodes table) above the node's live tabs. The node's page SHALL NOT be drawn under the Nodes table, and opening a page or a tab SHALL show its top with the tab row in view. Picking an entry on another network SHALL move the connection bar's network picker to that network, and changing the picker SHALL select that network's entry. Each workspace SHALL keep its own selected entry. Commission a device SHALL lay out its Nodes table and node pages the same way.

#### Scenario: Open a live node
- **WHEN** the page is connected to a runtime running `io` and `drives` and the user opens node 2 under `drives` in Commission
- **THEN** node 2's page opens with its header and live tabs at the top of the work area, no Nodes table is shown above it, and the connection bar's picker shows `drives`

#### Scenario: Back to where the user was
- **WHEN** the user was on node 5's PDOs tab in Configure, opened node 2 in Commission, and switches back to Configure
- **THEN** node 5's PDOs tab is shown

#### Scenario: Back to the table
- **WHEN** the user is on node 7's Object dictionary tab and presses the node header's link back to Nodes
- **THEN** the network's page with the Nodes table is shown and node 7's row is selected

### Requirement: Object dictionary view
In the online view every node SHALL have an object dictionary tab: from its EDS for each configured node and each node with a matched or picked EDS, else from the standard object dictionary (see "Standard object dictionary without an EDS"). The tab SHALL show a tree of every object, grouped as communication (0x1000-0x1FFF), manufacturer (0x2000-0x5FFF) and profile (0x6000-0x9FFF), with index, subindex, name, data type, access, EDS default and device value. Each object SHALL be one row: a VAR object with its value in that row, an ARRAY or RECORD object as a foldable row with its sub-entries below it, each sub-entry named by its own name without the object's name in front. Groups and objects SHALL start folded, except that a search or filter unfolds the groups and objects that hold a match, and Read all unfolds as "Reading values in the object dictionary view" says. The tab SHALL use the full width of the online view, and long names SHALL wrap so that the row's buttons and watch box always stay inside the view without sideways scrolling. A search box SHALL filter by name or index.

#### Scenario: Browse node 3
- **WHEN** the user opens the object dictionary tab of node 3
- **THEN** the tree shows the objects from node 3's EDS in three folded groups, values empty until read

#### Scenario: Node without an EDS
- **WHEN** the user opens the object dictionary tab of a heard node that has no EDS
- **THEN** the tree shows the standard objects instead of saying the node has no EDS

#### Scenario: Object with sub-entries
- **WHEN** the user unfolds object 0x6110 "AI Sensor Type" of node 3
- **THEN** one row for the object and one row per sub-entry are shown, the sub-entries named "Number Of Entries", "AI0_Sensor_Type" and so on

#### Scenario: Long names
- **WHEN** a node's EDS has names such as `Store_Parameters_Field_Highest_subindex_supported` and the window is 1280 px wide
- **THEN** the names wrap and every row's Read and Edit buttons and Watch box are fully visible

#### Scenario: Search by index
- **WHEN** the user types `6110` in the search box
- **THEN** only object 0x6110 and its subindices are shown, unfolded

### Requirement: Reading values in the object dictionary view
The object dictionary tab SHALL offer "Read all" (the parameter read-all, with progress and cancel), "Read" on an object (all its readable sub-entries, in subindex order) and on a single entry, and a watch list of up to 32 entries refreshed at a period the user picks (500 ms or longer). Values SHALL be decoded as in the SDO panel. An entry whose value differs from its EDS default SHALL be marked, and an entry the configuration writes at boot or an SDO variable owns SHALL be marked as such. When Read all ends, every group that got a value SHALL unfold, and every object holding an entry that differs from its EDS default SHALL unfold; the other objects SHALL stay folded.

#### Scenario: Read all and see changed values
- **WHEN** the user presses Read all on node 3 and 0x6110 subindex 1 differs from the EDS default
- **THEN** progress is shown while reading, and afterwards the groups are unfolded, object 0x6110 is unfolded with subindex 1 marked as different from the default, and its object row says that one of its entries differs

#### Scenario: Read one object
- **WHEN** the user presses Read on object 0x6110 of node 3, which has subindices 0 to 8
- **THEN** 9 SDO reads are sent and all 9 values are shown

#### Scenario: Watch limit
- **WHEN** 32 entries are watched and the user adds another
- **THEN** the page refuses it and says at most 32 entries can be watched

### Requirement: Diagnosis flag and simulated mark
A pending diagnosis (an EMCY or error problem not yet cleared) SHALL add a flag in the error colour after a node's state icon; once cleared the flag SHALL turn grey and stay until the history is cleared. An EMCY with error code 0x0000 SHALL count as clearing the node's diagnosis and SHALL NOT raise the error-colour flag; the Last EMCY column SHALL show it as "cleared (0x0000)" in neutral text. A simulated node SHALL add a dashed outline to its state icon.

#### Scenario: Cleared diagnosis
- **WHEN** node 5 sent an EMCY that is later cleared
- **THEN** its flag turns from the error colour to grey

#### Scenario: Simulated node
- **WHEN** node 9 is simulated and OPERATIONAL
- **THEN** its icon is the filled circle with a dashed outline

#### Scenario: Error reset EMCY
- **WHEN** node 5 sends EMCY 0x5000 and then EMCY 0x0000
- **THEN** node 5's flag is grey and its Last EMCY reads "cleared (0x0000)"

## ADDED Requirements

### Requirement: Watch list only when used
The Watch list card SHALL be shown only while at least one entry of the node is watched. Before that, a one-line hint under the filters SHALL say how to watch an entry.

#### Scenario: Nothing watched
- **WHEN** the user opens node 6's Object dictionary tab with no watched entries and presses Read all
- **THEN** no Watch list card is shown above the groups, and the hint line is

### Requirement: Last heard in Commission
The Nodes table and the node header SHALL show the time since the node was last heard, from the plugin's status for a runtime connection and from the adapter for a direct one. "-" SHALL be shown only for a node never heard in the session.

#### Scenario: Heartbeat every 100 ms
- **WHEN** node 6 sends a heartbeat every 100 ms and the page is connected to the runtime
- **THEN** node 6's Last heard reads about "0.1 s ago"
