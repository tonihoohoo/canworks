# canopen-plc-nmt Specification

## Purpose
NMT from the PLC program at run time: the `canworks` editor library's function blocks command any node or every node, start and stop the network, and read the NMT state the master sees, through the running CANopen plugin, without stalling the scan.

## Requirements

### Requirement: NMT function blocks
The editor library `canworks` SHALL provide the function blocks `CO_NMT`, `CO_NETWORK_START`, `CO_NETWORK_STOP` and `CO_GET_STATE`. Every block SHALL have the inputs `EXECUTE : BOOL` and `NETWORK : USINT`, and the outputs `BUSY : BOOL`, `DONE : BOOL`, `ERROR : BOOL` and `ERROR_ID : UINT`. The other pins SHALL be:
- `CO_NMT`: in `NODE : USINT`, `COMMAND : USINT`.
- `CO_NETWORK_START`: in `TIMEOUT : TIME`.
- `CO_NETWORK_STOP`: in `NODE_COMMAND : USINT`.
- `CO_GET_STATE`: in `NODE : USINT`; out `STATE : USINT`, `MASTER_STATE : USINT`, `HELD : USINT`, `BOOT_ERROR : USINT`, `CONFIGURED : BOOL`, `STARTED : BOOL`.
`NETWORK` SHALL pick the network as it does for the SDO blocks, and a `NETWORK` that is not a CANopen master network of the running configuration SHALL end the block with `ERROR_ID` 6 in the call that started it, with nothing sent.

#### Scenario: Network that is not a master
- **WHEN** the config's network 0 is a CANopen master and network 1 is J1939, and the program calls `CO_NMT` with `NETWORK := 1`
- **THEN** the block ends with `ERROR`, `ERROR_ID` 6 in the same call and no frame is sent on either network

#### Scenario: Old plugin
- **WHEN** the installed plugin does not offer the NMT entry point and the program calls `CO_NMT`
- **THEN** the block ends with `ERROR_ID` 4, and the program's SDO blocks keep working

### Requirement: NMT block handshake
The NMT blocks SHALL follow the SDO blocks' handshake: a rising edge of `EXECUTE` SHALL start the request with the inputs of that call; `BUSY` SHALL be TRUE until it ends, and input changes and further edges while `BUSY` SHALL be ignored; when it ends exactly one of `DONE` and `ERROR` SHALL be TRUE, held while `EXECUTE` stays TRUE and shown for one call when `EXECUTE` was already FALSE; a new rising edge SHALL clear the outputs and start the next request. `CO_GET_STATE` SHALL end in the call with the rising edge and SHALL never be `BUSY`.

#### Scenario: State read in one call
- **WHEN** the program calls `gs(EXECUTE := TRUE, NODE := 5)` with `gs : CO_GET_STATE` and node 5 is OPERATIONAL
- **THEN** in that call `gs.DONE` is TRUE, `gs.BUSY` is FALSE and `gs.STATE` is 5

#### Scenario: Command held while busy
- **WHEN** the program changes `COMMAND` while a `CO_NMT` instance is `BUSY`
- **THEN** the running request keeps the command from its start

### Requirement: NMT commands from a block
`CO_NMT` SHALL send the CiA 301 command given by `COMMAND` (1 START, 2 STOP, 128 ENTER PRE-OPERATIONAL, 129 RESET NODE, 130 RESET COMMUNICATION) to `NODE`, and SHALL end with `DONE` once the command is sent. `NODE` SHALL accept 1 to 127, whether the configuration lists the node or not, and 0 for every node. For a node the configuration lists:
- STOP and ENTER PRE-OPERATIONAL SHALL hold the node in that state as the node's NMT command byte does with 2 and 128: the master SHALL send the command again after every later boot of the node, SHALL NOT reboot it when it leaves OPERATIONAL, and SHALL send the hold again to a node that starts by itself. A node that has not booted SHALL get the hold when its boot ends.
- START SHALL release the node's hold and send START to a booted node, or let the master start it when its boot ends.
- RESET NODE and RESET COMMUNICATION SHALL clear the hold, and the master SHALL boot and configure the node again after its boot-up message.
For a node the configuration does not list the command SHALL be sent and nothing SHALL be kept. With `NODE := 0` the master SHALL send one NMT command to node ID 0, SHALL apply the bookkeeping above to every configured node, and SHALL NOT change its own NMT state. The master SHALL send the command within 100 ms of the block's start, and SHALL log each command with the node and "from the program".

#### Scenario: Stop and restart a configured node
- **WHEN** node 5 is OPERATIONAL with `state_location` `%IB20` and the program runs `CO_NMT` with `NODE := 5, COMMAND := 2`, later with `COMMAND := 1`
- **THEN** after the first `%IB20` reads 4 and node 5's status bit is FALSE; after the second `%IB20` reads 5 and PDO data flows again

#### Scenario: Held node power-cycles
- **WHEN** the program has held node 5 with `COMMAND := 128` and node 5 power-cycles
- **THEN** the master configures node 5 after its boot-up message, then sends ENTER PRE-OPERATIONAL, and node 5's state byte ends at 127

#### Scenario: Node not in the configuration
- **WHEN** the program runs `CO_NMT` with `NODE := 40, COMMAND := 129` and the config does not list node 40
- **THEN** one RESET NODE frame for node 40 goes out, the block ends with `DONE`, and the master does not boot node 40

#### Scenario: All nodes
- **WHEN** nodes 5 and 23 are configured and OPERATIONAL, and the program runs `CO_NMT` with `NODE := 0, COMMAND := 128`
- **THEN** one ENTER PRE-OPERATIONAL frame with node ID 0 goes out, both nodes stay held PRE-OPERATIONAL after a later boot, and the master's state byte keeps reading 5

#### Scenario: Invalid inputs
- **WHEN** `CO_NMT` starts with `NODE := 128`, with `COMMAND := 7`, or with `NODE` equal to the master's node ID
- **THEN** the block ends with `ERROR_ID` 6 in the same call and nothing is sent

### Requirement: One hold per node
The node's NMT command byte, `CO_NMT`, NMT commands from the diagnostics channel and from the Modbus control block SHALL act on the same hold of a configured node, and the command that acted last SHALL decide. The command byte SHALL act only when its value changes. A START from `CO_NMT` to a node held by the gateway's upper-loss reaction SHALL end with `ERROR_ID` 9 and send nothing.

#### Scenario: Block after the byte
- **WHEN** node 5's NMT command byte stays at 0 and the program holds node 5 with `CO_NMT`, `COMMAND := 2`
- **THEN** node 5 stays STOPPED, also after a reboot, until the byte changes or a START releases it

#### Scenario: Byte after the block
- **WHEN** the program has held node 5 with `CO_NMT`, `COMMAND := 2`, and then changes node 5's command byte from 0 to 128
- **THEN** node 5 is held PRE-OPERATIONAL

### Requirement: Commands to mandatory nodes
A hold or a reset of a mandatory node from the program SHALL NOT count as a loss of that node: the master SHALL stay OPERATIONAL while the node is held or reboots after the reset, and SHALL NOT react with `reset_all_nodes` or `stop_all_nodes`. A mandatory node that is lost while held SHALL be handled as any lost mandatory node.

#### Scenario: Reset a mandatory node
- **WHEN** node 3 is mandatory, `master.stop_all_nodes` is `true`, and the program resets node 3 with `CO_NMT`
- **THEN** only node 3 reboots, the master's state byte keeps reading 5, and the other nodes stay OPERATIONAL

### Requirement: Start the network from the program
`CO_NETWORK_START` SHALL make the master go OPERATIONAL as `master.start` true does: at once when every mandatory node has booted, else as soon as the last one has. It SHALL be `BUSY` until the master is OPERATIONAL and then end with `DONE`. With a `TIMEOUT` other than `T#0s` it SHALL end with `ERROR_ID` 2 when the master is not OPERATIONAL by then, and the start SHALL stay requested. The start SHALL last for the rest of the PLC run, including after the master resets itself with `reset_all_nodes`. Nodes held only by `CO_NETWORK_STOP` SHALL be started again, unless `start_nodes` is false. A master that is STOPPED after a mandatory node's loss with `stop_all_nodes` SHALL NOT be started: the block SHALL end with `ERROR_ID` 9 and the log SHALL say that the plugin must restart.

#### Scenario: Autostart off
- **WHEN** `master.start` is `false`, nodes 2 and 5 have booted and the program runs `CO_NETWORK_START` once the machine is ready
- **THEN** the master's state byte goes from 127 to 5, the nodes' status bits become TRUE, PDO data flows, and the block ends with `DONE`

#### Scenario: Mandatory node still missing
- **WHEN** `master.start` is `false`, mandatory node 3 is missing, and the program runs `CO_NETWORK_START` with `TIMEOUT := T#2s`
- **THEN** the block ends with `ERROR_ID` 2 after about 2 s, and the master goes OPERATIONAL when node 3 boots later

#### Scenario: After a PLC restart
- **WHEN** the program started a `master.start: false` network and the PLC is stopped and started again
- **THEN** the master stays PRE-OPERATIONAL until the program runs `CO_NETWORK_START` again

### Requirement: Stop the network from the program
`CO_NETWORK_STOP` SHALL stop the PDO exchange: no output PDO SHALL be sent after the request, received PDOs SHALL no longer change the inputs, the master SHALL be PRE-OPERATIONAL as its state byte and `CO_GET_STATE` report it, without a communication reset of any node, and every configured node that is up SHALL get `NODE_COMMAND`'s command: 0 what `master.on_plc_stop` says, 2 STOP, 128 ENTER PRE-OPERATIONAL, 255 none. Any other `NODE_COMMAND` SHALL end with `ERROR_ID` 6. The block SHALL end with `DONE` once the master is PRE-OPERATIONAL and the commands are sent. Until `CO_NETWORK_START`, the master SHALL NOT go OPERATIONAL by itself, SHALL keep supervising and booting nodes, and SHALL send a node that boots meanwhile the same command after configuring it. SDO transfers SHALL keep working to nodes that are not STOPPED.

#### Scenario: Stop with the default node command
- **WHEN** `master.on_plc_stop` is `"preop"`, nodes 5 and 23 are OPERATIONAL, and the program runs `CO_NETWORK_STOP` with `NODE_COMMAND := 0`
- **THEN** the master's state byte reads 127, both nodes get ENTER PRE-OPERATIONAL, no RPDO goes out after the request, and an SDO read from node 5 still ends with `DONE`

#### Scenario: Nodes keep running
- **WHEN** nodes 5 and 23 are OPERATIONAL and the program runs `CO_NETWORK_STOP` with `NODE_COMMAND := 255`
- **THEN** the master's state byte reads 127, the nodes' status bits are FALSE, no node is reset and both nodes stay OPERATIONAL

#### Scenario: Node boots while the network is stopped
- **WHEN** the program has stopped the network with `NODE_COMMAND := 2` and node 23 power-cycles
- **THEN** the master configures node 23 and sends it STOP, and the master stays PRE-OPERATIONAL

### Requirement: Read NMT state from the program
`CO_GET_STATE` SHALL report what the master last saw, from a snapshot the bus thread keeps: `STATE` the node's NMT state with the state byte's codes (5, 127, 4, 0 no contact), `MASTER_STATE` the master's own state with the master state byte's codes, `HELD` 0 or the command (2 or 128) the master keeps applying to the node, `BOOT_ERROR` the boot error byte's code, `CONFIGURED` whether the configuration lists the node, and `STARTED` whether the master may run (`master.start` true or `CO_NETWORK_START` this run, and no `CO_NETWORK_STOP` since). For a node the configuration does not list, `STATE`, `HELD` and `BOOT_ERROR` SHALL be 0. `NODE := 0` SHALL fill only `MASTER_STATE` and `STARTED`, the others 0; `NODE` above 127 SHALL end with `ERROR_ID` 6. The values SHALL not need a `state_location` in the configuration.

#### Scenario: Node without a state byte
- **WHEN** node 5 has no `state_location` and reports PRE-OPERATIONAL in its heartbeat
- **THEN** `CO_GET_STATE` for node 5 gives `STATE` 127 and `CONFIGURED` TRUE

#### Scenario: Master held by autostart off
- **WHEN** `master.start` is `false` and the program has not started the network
- **THEN** `CO_GET_STATE` with `NODE := 0` gives `MASTER_STATE` 127 and `STARTED` FALSE

### Requirement: NMT block error IDs
An NMT block that ends with `ERROR` SHALL set `ERROR_ID` to: 2 `CO_NETWORK_START` timed out; 4 CANopen is not running (no plugin, its configuration rejected, the PLC stopping, or no matching NMT API version); 5 more than 16 NMT requests in progress or waiting; 6 an input is invalid; 8 the request was cancelled by a PLC stop or a CANopen restart; 9 the request is refused by a state the program does not own (a node held by the gateway's upper-loss reaction, a master STOPPED by `stop_all_nodes`). The library documentation SHALL list these IDs.

#### Scenario: Too many at once
- **WHEN** 17 `CO_NMT` instances start in the same scan
- **THEN** 16 are `BUSY` or `DONE` and one ends with `ERROR_ID` 5

### Requirement: NMT blocks do not stall the scan
An NMT block call SHALL return without waiting on CAN traffic, SHALL NOT allocate memory and SHALL NOT write to the log; it SHALL at most take a lock held only for copying a request or a result, and `CO_GET_STATE` SHALL take none. NMT requests SHALL use their own request slots, so SDO transfers in progress SHALL NOT delay them.

#### Scenario: Stop while SDO slots are full
- **WHEN** 64 SDO transfers are in progress and the program runs `CO_NMT` with `COMMAND := 2` for node 5
- **THEN** node 5 gets STOP within 100 ms

### Requirement: NMT blocks and PLC stop
When the PLC stops, NMT requests waiting or in progress SHALL be dropped, and their blocks SHALL end with `ERROR_ID` 8 on their next call. `master.on_plc_stop` SHALL apply to every configured node that is up, whatever the program held. Holds, a program start and a program stop SHALL NOT outlast the PLC run: after the next PLC start the master SHALL start by itself only with `master.start` true, and every node SHALL be booted and started as the configuration says.

#### Scenario: Held node after a restart
- **WHEN** the program held node 5 STOPPED with `CO_NMT`, and the PLC is stopped and started again with a program that does not command node 5
- **THEN** node 5 is booted and started as usual

### Requirement: Finding the NMT entry point
The NMT blocks SHALL reach the plugin as the SDO blocks do, and SHALL call it only through one exported C entry point of their own, `canopen_plc_nmt_api`, that takes the NMT API version the library was built for and returns a table of functions, or nothing when the plugin does not offer that version. The SDO entry point and its table SHALL NOT change. A block that finds no plugin, no NMT entry point or no matching version SHALL end with `ERROR_ID` 4 and SHALL look again on its next rising edge; the plugin SHALL log once which NMT API version was asked for and which it offers.

#### Scenario: Library newer than the plugin
- **WHEN** the library asks for an NMT API version the installed plugin does not offer
- **THEN** every NMT block ends with `ERROR_ID` 4, and the log says once that the program's library needs a newer plugin, naming both versions

### Requirement: NMT blocks in the library
The NMT blocks SHALL be built into `canworks.stlib` with the library's other blocks and delivered with it, and SHALL appear in the editor's library tree of every project that enables the library.

#### Scenario: Blocks in the editor
- **WHEN** the user installs the `canworks.stlib` of this release in OpenPLC Editor 4.3.2 and enables it in a project
- **THEN** the library tree lists `CO_NMT`, `CO_NETWORK_START`, `CO_NETWORK_STOP` and `CO_GET_STATE`, and a project that calls them builds for OpenPLC Runtime v4
