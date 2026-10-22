## MODIFIED Requirements

### Requirement: Network tree
In both workspaces of a config, the left column of the workspace tab SHALL be a network tree, and it SHALL be the only navigation there. The tree SHALL show every network of the config at once, each as an entry with its name and protocol (CANopen master, CANopen slave, J1939 or Plain CAN). Under a network it SHALL show the entries that network has:
- Bus and master (Bus and ECU on J1939, Bus on Plain CAN and on a slave network);
- its nodes, sorted by node ID, each named by node ID and name;
- the slave device on a slave network;
- **Add node…** on a CANopen master network in Configure, which opens the Add node dialog for that network (see "Add node dialog");
- PDO links and CAN messages, when the network has them today.

After the networks the tree SHALL show Online access (Configure), Gateway and Modbus bridge when the config has them, and **Add network…** (Configure). Each network entry SHALL have a menu with **Rename…**, **Role** (CANopen networks) and **Remove…**, keeping today's confirmations. Which networks are folded SHALL be kept on this PC and SHALL come back after a page reload; a folded network SHALL show the sum of its entries' problem counts, and SHALL unfold by itself when a problem link opens an entry in it. The unused EDS files note and the address scan line SHALL be shown under the tree. Renaming a node SHALL update its entry as the user types.

#### Scenario: Two networks at once
- **WHEN** a config has networks `io` with nodes 5 and 7 and `drives` with node 2
- **THEN** the tree shows `io` and `drives` with their nodes, and opening node 2 needs no network switch

#### Scenario: Add a node to the second network
- **WHEN** the user picks **Add node…** under `drives`, picks an EDS from the dialog's list and presses Add
- **THEN** the node is added to `drives`, its entry is selected, and its PDOs tab opens

#### Scenario: Remove a network from its menu
- **WHEN** the user opens the menu of network `drives`, which has 3 nodes, and picks **Remove…**
- **THEN** the page asks for confirmation naming `drives` and its 3 nodes, with Cancel as the default

### Requirement: Node tabs
A node page in Configure SHALL show its heading, Export DCF and Remove node above a tab list, and SHALL show one tab at a time:
- **General**: node ID, name, EDS and Simulated, and the EDS error when the EDS cannot be read;
- **PDOs** (see "PDOs tab");
- **SDOs** (see "SDOs tab");
- **Supervision**: heartbeat or guarding, status bit, state byte, NMT command, boot error byte, EMCY code, error register and EMCY COB-ID;
- **CiA 402**: the axis settings, shown only when the node's EDS has 0x6040 and 0x6041 or the node already has an axis;
- **Simulation**, shown only for a simulated node (see "Simulation tab of a node");
- **Notes** (see "Notes tab");
- **Advanced**.

The tabs SHALL follow the page's tab pattern. Opening another node SHALL keep the open tab when that node has it, and open General otherwise. The open tab SHALL come back after a page reload. A node just added SHALL open on PDOs when its default PDOs were mapped, else on General, whatever tab another node had open. Objects SHALL be mapped from within the PDO they go into ("Add entry…" per PDO, listing that direction's mappable objects), with "Map all" kept for device-mapped PDOs.

#### Scenario: Compare heartbeats across nodes
- **WHEN** the user is on node 5's Supervision tab and opens node 7 in the tree
- **THEN** node 7's Supervision tab is shown

#### Scenario: No CiA 402 tab for an I/O module
- **WHEN** the user opens a node whose EDS has neither 0x6040 nor 0x6041 and that has no axis
- **THEN** the node has no CiA 402 tab

#### Scenario: Reload keeps the tab
- **WHEN** the user is on node 5's PDOs tab and reloads the page
- **THEN** node 5's PDOs tab is shown

#### Scenario: Add an entry from the PDO
- **WHEN** the user clicks "Add entry…" on TPDO 1 and picks 0x6150:1
- **THEN** 0x6150:1 is added to TPDO 1 with a suggested location, and the picker lists only input-direction objects

### Requirement: Variable names of PDO entries
The PDO table SHALL have a Variable column for every target, editing the entry's `name`, with the full name the declarations and exports will use as placeholder (for OpenPLC the declared name, such as `io_rtd_AI0_Input_PV`). The entry SHALL show a "declared as" line only when the editor project declares its location under a different name. The Location column SHALL be shown only for targets that use locations, also when an entry of a target without locations still has one.

#### Scenario: Rename a channel
- **WHEN** the user types `door_open` as the variable of an entry in a CODESYS project
- **THEN** the entry gets `name` `door_open` and the CODESYS export names that channel `<node>_door_open`

#### Scenario: No Location column for CODESYS
- **WHEN** a CODESYS project has an entry with `iec_location` left over
- **THEN** the PDO table's columns are Object, Name, Type, Variable, PDO and the remove button

#### Scenario: One name shown
- **WHEN** node 5's entry 0x7130:1 has no `name`, its location `%IW100`, and the project declares `io_rtd_AI0_Input_PV AT %IW100`
- **THEN** the Variable field's placeholder reads `io_rtd_AI0_Input_PV` and no "declared as" line is shown

## ADDED Requirements

### Requirement: Add node dialog
**Add node…** SHALL open a dialog with:
- the device description: the config's EDS files (product name, file name, nodes using it), the EDS library's files, and **Browse…**;
- the node ID: the lowest free ID, checked as typed;
- the name: from the EDS product name, unique in the network;
- **Map the EDS's default PDOs**, ticked.

**Add** SHALL add the node to that network. Cancel SHALL add nothing.

#### Scenario: Second node of a known type
- **WHEN** the virtual plant's `io` network has node 6 with `dio16.eds` and the user opens Add node…, picks dio16.eds from the list, and presses Add
- **THEN** a node with the lowest free ID and a unique name is added with `dio16.eds`, and no file picker was opened

#### Scenario: Taken node ID
- **WHEN** the user types 6 as the node ID in the dialog on `io`
- **THEN** the field says node 6 is already used and Add is disabled with that reason

### Requirement: Default PDOs of a new node
With **Map the EDS's default PDOs** ticked, adding a node SHALL map, for each PDO the EDS enables by default (COB-ID without the invalid bit), the objects of its default mapping, leaving out dummy entries, with suggested names and, for targets that use locations, suggested free locations. Unticked, the node SHALL start with no PDO entries.

#### Scenario: I/O module defaults
- **WHEN** the user adds a node from an EDS whose TPDO 1 default maps 0x6000:1 and 0x6000:2 and whose RPDO 1 default maps 0x6200:1, with the box ticked
- **THEN** the node's TPDO 1 has the two inputs and RPDO 1 the output, each with a suggested location, and the PDOs tab is open

### Requirement: EDS check after adding a node
After a node is added, the EDS check SHALL show a message only when it has findings (the EDS cannot be read by the tools on the PLC, or lint warnings), in the message bar, with the findings in words. A clean EDS SHALL show no message.

#### Scenario: Clean EDS
- **WHEN** the user adds a node from an EDS without findings
- **THEN** no banner or message about the EDS is shown

### Requirement: Entries without a location
For a target that uses locations, a PDO entry without a location SHALL show "not mapped to the PLC" in warning text, with **Suggest** filling a free location.

#### Scenario: Unmapped output
- **WHEN** dio's RPDO 1 entry 0x6411:1 has no location
- **THEN** the row shows "not mapped to the PLC" and Suggest, and pressing Suggest gives it a free `%QW` location
