## ADDED Requirements

### Requirement: No start for a held node
The master SHALL NOT send NMT START to a configured node while the node is held STOPPED or PRE-OPERATIONAL, whoever set the hold (the command byte, `CO_NMT`, a diagnostics client, the gateway's upper-loss reaction or `CO_NETWORK_STOP`): not when the node's boot ends, and not when the master starts all nodes. The plugin SHALL NOT write or store anything on the node for this.

#### Scenario: Node boots while the network is stopped
- **WHEN** the program has stopped the network with `NODE_COMMAND := 2` and node 23 power-cycles or the CAN link goes down and up
- **THEN** the master configures node 23 and sends it STOP, and no NMT START to node 23 or to all nodes goes out until the program runs `CO_NETWORK_START`

#### Scenario: Held node and start all nodes
- **WHEN** `master.start_all_nodes` is true, the program holds node 5 PRE-OPERATIONAL with `CO_NMT`, and the master starts all nodes
- **THEN** the other nodes get START and node 5 gets none

### Requirement: Held node state after its boot
After configuring a held node the master SHALL send only the hold's command, and the node's state byte and `CO_GET_STATE` SHALL never report it OPERATIONAL in between. When the hold ends the master SHALL start the node as it would without the hold.

#### Scenario: State byte of a held node
- **WHEN** node 23 boots while held STOPPED
- **THEN** its state byte goes from 0 to 4 and never reads 5

#### Scenario: Release after a boot
- **WHEN** node 5 booted while held STOPPED and the program then sends START with `CO_NMT`
- **THEN** node 5 gets START and goes OPERATIONAL
