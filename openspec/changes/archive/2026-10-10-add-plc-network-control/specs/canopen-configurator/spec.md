## ADDED Requirements

### Requirement: Copy NMT calls as ST
The online view SHALL offer "Copy as ST call" next to each node's NMT buttons (start, stop, pre-operational, reset node, reset communication). It SHALL copy Structured Text that declares a `CO_NMT` instance and calls it with the node ID and the CiA 301 command code of that button, with the command's name in a comment, and SHALL be available whether or not the runtime allows changes, since it sends nothing. With several networks the call SHALL set `NETWORK` to the number of the network the online view talks to, with its name in a comment, and the instance name SHALL include the network's name. The master's "Master goes operational" setting SHALL say that, when it is off, the master stays pre-operational until the PLC program starts it with `CO_NETWORK_START`, and SHALL offer "Copy as ST call" for a `CO_NETWORK_START` instance and call.

#### Scenario: Stop call for a node
- **WHEN** the user picks "Copy as ST call" next to node 5's Stop button
- **THEN** the clipboard holds a declaration of a `CO_NMT` instance and a call with `NODE := 5, COMMAND := 2 (* STOP *)`

#### Scenario: Changes not allowed
- **WHEN** the runtime's `allow_changes` is false
- **THEN** the NMT buttons are disabled and "Copy as ST call" still copies the call

#### Scenario: Network start call
- **WHEN** the user turns "Master goes operational" off
- **THEN** the hint says the program starts the master with `CO_NETWORK_START`, and "Copy as ST call" copies a `CO_NETWORK_START` declaration and call
