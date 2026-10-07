# canopen-gateway Specification

## Purpose
Lets one OpenPLC controller be a CANopen gateway: a slave on an upper network and the master of one or more field networks, passing process data, node status, emergencies and parameter access between them without PLC program code.

## Requirements

### Requirement: Gateway configuration
A version 2 file MAY have a top-level `gateway` object naming one slave network (`upper`) and holding `routes`, `status`, `emcy_forward`, `on_upper_loss` and `sdo_bridge`. Every network it names SHALL exist with the right role, and the gateway SHALL need at least one master network besides the slave.

#### Scenario: Upper network is a master
- **WHEN** `gateway.upper` names a master network
- **THEN** the file is rejected with an error saying the upper network must be a slave network

### Requirement: Process data routes
Each `routes` entry SHALL connect one slave object on the upper network with one PDO entry of a node on a field network. A route from a field node TPDO entry SHALL write the slave object (access `ro` or `rwr`); a route to a field node RPDO entry SHALL read a slave object the upper master writes (access `rww` or `rw`). Both ends SHALL have the same CANopen data type.

#### Scenario: Value up
- **WHEN** a route connects node 5 TPDO entry 0x6000:1 on network `field` with slave object 0x2100:1 and node 5 sends a new value
- **THEN** the slave object holds that value and an event-driven TPDO that maps it is sent, without waiting for a PLC scan

#### Scenario: Value down
- **WHEN** a route connects slave object 0x2000:1 with node 7 RPDO entry 0x6200:1 and the upper master writes 0x2000:1
- **THEN** node 7's RPDO carries the new value at the field network's next SYNC, or at once when the RPDO is event-driven

#### Scenario: Type mismatch
- **WHEN** a route connects an UNSIGNED16 field entry with an INTEGER32 slave object
- **THEN** the file is rejected with an error naming both ends and their types

#### Scenario: Wrong direction
- **WHEN** a route's slave end is a `ro` object and its field end is an RPDO entry
- **THEN** the file is rejected with an error saying the upper master cannot write that object

### Requirement: Routes run without the PLC program
Routed values SHALL be copied between the networks by the plugin within 2 ms of arrival, independent of the PLC scan. A routed field entry or slave object MAY also have a PLC location; the PLC then sees the same value, and an output location on a route's target SHALL be rejected so that only one writer exists.

#### Scenario: PLC also reads a routed value
- **WHEN** field entry 0x6000:1 of node 5 is routed up and also bound to `%IW100`
- **THEN** both the slave object and `%IW100` follow the node's value

#### Scenario: Two writers
- **WHEN** a field RPDO entry is the target of a route and also has a `%Q` location
- **THEN** the file is rejected with an error naming the entry, the route and the location

### Requirement: Field node status to the upper master
With `status` set, the gateway SHALL publish each field node's NMT state as an UNSIGNED8 sub-object of a status record in the slave's dictionary (0 while the node is not booted), updated on every change, plus a bit field of nodes that are OPERATIONAL, one record and bit field per master network by its position among the master networks (at most 4).

#### Scenario: Field node lost
- **WHEN** node 7 on a field network stops sending heartbeats
- **THEN** its status sub-object reads 0 and its bit in the operational bit field clears, and an event-driven TPDO that maps them is sent

#### Scenario: EDS made for fewer field networks
- **WHEN** a second master network is added and the slave EDS has the status objects of the first only
- **THEN** the config loads with a warning that the second network's status is not published, while missing objects of the first master network reject it

### Requirement: Emergency forwarding
With `emcy_forward: true`, an EMCY from a field node SHALL be sent on the upper network as an EMCY of the gateway slave with the same error code and error register, and manufacturer bytes holding the field network's position among the master networks (0 = the first) and the node ID. An error reset from the field node SHALL clear that entry, and the slave's 0x1001 SHALL be the OR of all active field registers and the program's own.

#### Scenario: Field EMCY forwarded
- **WHEN** node 5 on field network 1 sends EMCY code 0x5000, register 0x01
- **THEN** the gateway sends EMCY code 0x5000, register 0x01, manufacturer bytes 01 05 00 00 00 on the upper network

### Requirement: Behaviour when the upper master is lost
`on_upper_loss` SHALL set what routed values down do when the slave leaves OPERATIONAL or loses the upper master's heartbeat: `"hold"` (default) keeps the last values, `"zero"` sets routed field outputs to 0, `"stop_nodes"` stops the field nodes that receive routes with NMT stop and starts them again when the upper master starts the gateway.

#### Scenario: Zero on loss
- **WHEN** `on_upper_loss` is `"zero"` and the upper master's heartbeat stops
- **THEN** every field RPDO entry that a route targets is sent with 0, and the log names the reason

### Requirement: SDO bridge
With `sdo_bridge: true`, the slave's dictionary SHALL have an SDO bridge record through which the upper master reads or writes one object of up to 4 bytes on a field node: it writes network, node, index, subindex, value and length, then a command (1 read, 2 write), and reads the status (0 idle, 1 busy, 2 done, 3 aborted) and abort code. Writes to field nodes SHALL also need `sdo_bridge_write: true`.

#### Scenario: Read a field object
- **WHEN** the upper master writes network 1, node 5, 0x1018:1 and command 1 to the bridge record
- **THEN** the status goes busy then done and the value sub-object holds node 5's vendor ID

#### Scenario: Write not allowed
- **WHEN** `sdo_bridge_write` is not set and the upper master issues command 2
- **THEN** the status reads aborted with abort code 0x08000020 and nothing is sent to the field node

### Requirement: Gateway objects in the generated EDS
The slave EDS generator SHALL take the gateway configuration and add one object per route end on the slave side with the route's type and direction, the status record, and the SDO bridge record when enabled, with default PDOs carrying the routed values and the status.

#### Scenario: Routes into the EDS
- **WHEN** the user generates the slave EDS for a gateway with three routes up and two down
- **THEN** the EDS has three `ro` and two `rww` objects with the routes' types, mapped in its default TPDOs and RPDOs
