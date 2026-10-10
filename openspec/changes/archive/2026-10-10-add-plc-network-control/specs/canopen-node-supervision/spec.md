## MODIFIED Requirements

### Requirement: Per-node NMT command byte
Each slave entry MAY give an `nmt_command_location` (an `%QB` output byte) through which the PLC program commands the node with CiA 301 NMT command codes:
- 0 or 1: the master runs the node as it does without the field (boots, configures, starts and recovers it). A change from 2 or 128 to 0 or 1 SHALL send START to a node that is booted.
- 2: the master SHALL send STOP to the node and keep it STOPPED: after any later boot of the node it SHALL configure it and then send STOP again.
- 128: the same with ENTER PRE-OPERATIONAL, keeping the node PRE-OPERATIONAL.
- 129 or 130: when the byte changes to this value, the master SHALL send RESET NODE or RESET COMMUNICATION once, then treat the node as with 0 (boot and configure it again after its boot-up message). Holding the value SHALL NOT repeat the command.
- Any other value SHALL be ignored, with one warning per change naming the node and the value.

The master SHALL act on a change within 100 ms or by the next SYNC, whichever comes first, and SHALL NOT act on the byte before the PLC program has completed its first scan cycle since start. For a node with `boot` false the master SHALL never boot or configure it, and a change to 1 SHALL send START. Each command sent SHALL be logged with the node and the command. A node held in STOPPED or PRE-OPERATIONAL SHALL have its status bit FALSE and SHALL exchange no PDOs. The location SHALL be an `%QB` location that does not overlap another location of the configuration, else the configuration SHALL be rejected naming the node and the field.

The byte SHALL act on the same hold as the program's `CO_NMT` block and the NMT commands of the diagnostics channel and the Modbus control block (`canopen-plc-nmt`): whichever acted last decides, and the byte acts only on a change of its value. A hold or reset sent through the byte to a mandatory node SHALL NOT count as a loss of that node.

#### Scenario: Stop and restart a node
- **WHEN** node 5 is OPERATIONAL with `nmt_command_location` `%QB30` and `state_location` `%IB20`, and the program writes 2 to `%QB30` and later 0
- **THEN** after the first write `%IB20` reads 4, the status bit reads FALSE and node 5's input locations hold their last values; after the second, `%IB20` reads 5 and PDO data flows again

#### Scenario: Held node resets itself
- **WHEN** `%QB30` holds 128 and node 5 power-cycles
- **THEN** the master configures node 5 after its boot-up message and then puts it into PRE-OPERATIONAL, and `%IB20` ends at 127

#### Scenario: Reset a node from the program
- **WHEN** the program changes `%QB30` from 0 to 129 and leaves it there
- **THEN** the master sends one RESET NODE to node 5, configures and starts node 5 after its boot-up message, and sends no further reset

#### Scenario: Unknown command
- **WHEN** the program writes 7 to `%QB30`
- **THEN** the plugin logs one warning naming node 5 and the value 7, and node 5 keeps running

#### Scenario: Wrong location type
- **WHEN** `nmt_command_location` is not an `%QB` location or overlaps another location
- **THEN** the plugin rejects the configuration and names the node and the field

#### Scenario: Block releases a byte hold
- **WHEN** `%QB30` holds 2 and the program runs `CO_NMT` with `NODE := 5, COMMAND := 1`
- **THEN** node 5 is started and stays OPERATIONAL until `%QB30` changes again

#### Scenario: Mandatory node held by the byte
- **WHEN** node 5 is mandatory, `master.reset_all_nodes` is `true`, and the program writes 2 to `%QB30`
- **THEN** node 5 is STOPPED, no other node is reset, and the master stays OPERATIONAL
