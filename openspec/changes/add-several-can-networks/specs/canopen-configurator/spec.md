# Spec Delta

## ADDED Requirements

### Requirement: Network bar
The configurator SHALL show a network bar above the Bus and master section, with one tab per network and buttons to add, rename and remove a network. Each tab SHALL hold that network's Bus and master settings and its node list. With one network the bar SHALL show only the add button, so a single-network page looks as before.

#### Scenario: Add a second network
- **WHEN** the user opens a config with one network on `can0` and presses Add network
- **THEN** a second tab appears with an empty node list and an adapter interface the user must fill in, and the first tab is named `can0`

#### Scenario: Remove a network with nodes
- **WHEN** the user removes a network that has nodes
- **THEN** the page asks for confirmation naming the network and its number of nodes before removing it

### Requirement: Checks across networks in the configurator
Address suggestions SHALL skip locations used by any network, and Validate before save SHALL report the cross-network checks (duplicate names, shared interfaces or serial devices, IEC location clashes) with the network names in each message.

#### Scenario: Suggested address on the second network
- **WHEN** network `io` uses `%IW100` and the user asks for a suggested address for a 16-bit input on network `drives`
- **THEN** the suggestion is not `%IW100`

### Requirement: Online access for all networks
The Online access settings SHALL be shown once for the whole config, not per network.

#### Scenario: Online access with two networks
- **WHEN** a config has two networks and the user turns Online access on
- **THEN** the saved version 2 file has one top-level `diagnostics` object

### Requirement: Network picker in online, scan and trace views
The online view, the scan page and the trace view SHALL each have a network picker when the runtime reports more than one network, and SHALL show and act on the picked network only. The picker SHALL start on the network whose tab is open.

#### Scenario: Online view of the second network
- **WHEN** the runtime runs `io` and `drives` and the user picks `drives` in the online view
- **THEN** the view shows `drives`' bus state and nodes, and SDO, NMT, parameter and object dictionary actions go to `drives`

#### Scenario: Scan adds to the picked network
- **WHEN** the user scans `drives` and adds a found device as a node
- **THEN** the node is added to the `drives` tab

### Requirement: Exports per network in the configurator
The configurator's DBC export SHALL export the network of the open tab. Its DCF export SHALL export the open tab's nodes, or every network into per-network folders when the user chooses all.

#### Scenario: DBC of the open tab
- **WHEN** the `drives` tab is open and the user exports a DBC file
- **THEN** the file describes only `drives`' nodes and is named after the network
