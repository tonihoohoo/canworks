## Purpose

Lets an OpenPLC controller be one CANopen device (NMT slave) on a network run by another master, with its object dictionary from an EDS and chosen objects bound to the PLC program's inputs and outputs.

## ADDED Requirements

### Requirement: Slave network start-up
At PLC start the plugin SHALL load each slave network's EDS, lint and check it as for master networks, set the node ID from the config, open the network's adapter, and send its boot-up message. A config error SHALL open no interface of any network, as for master networks.

#### Scenario: Slave boots
- **WHEN** the PLC starts with a slave network on `can1`, node ID 10 and a valid EDS
- **THEN** the plugin sends the boot-up message 0x70A with data 0x00 on `can1` and the node is PRE-OPERATIONAL

#### Scenario: EDS fails the lint
- **WHEN** the slave EDS has a communication-area finding that `eds_lint` does not accept
- **THEN** the config is rejected, the log names the EDS and the finding, and no interface is opened

### Requirement: Behaviour comes from the EDS
The slave's object dictionary SHALL be the EDS's objects with their default values; the plugin SHALL NOT add objects or change EDS values except the node ID and values restored from a store. PDO communication and mapping, heartbeat, guarding, SYNC and TIME consumer and error behaviour SHALL follow the dictionary.

#### Scenario: Heartbeat from the EDS
- **WHEN** the EDS has 0x1017 default 500
- **THEN** the slave sends a heartbeat every 500 ms after boot-up without any heartbeat setting in the config

#### Scenario: Object not in the EDS
- **WHEN** an `objects` entry names 0x2005:1 and the EDS has no such object
- **THEN** the config is rejected with an error naming the network, the object and the EDS

### Requirement: NMT slave
The slave SHALL obey NMT commands addressed to its node ID or broadcast: start, stop, enter pre-operational, reset node and reset communication, as CiA 301 defines. PDOs SHALL be exchanged only in OPERATIONAL. Reset node SHALL reload the dictionary from the EDS and then apply stored values.

#### Scenario: Master starts the node
- **WHEN** the master sends NMT start to node 10
- **THEN** the slave enters OPERATIONAL and its TPDOs begin

#### Scenario: Reset node
- **WHEN** the master changed 0x1800:5 over SDO without storing and then sends reset node
- **THEN** the slave sends boot-up and 0x1800:5 has its EDS value again

### Requirement: SDO server
The slave SHALL answer SDO uploads and downloads on its default SDO server (expedited, segmented and block transfers) for every object the EDS allows, with the abort codes CiA 301 defines for unknown objects, wrong access and wrong length.

#### Scenario: Write a read-only object
- **WHEN** the master downloads to an object whose EDS access type is `ro`
- **THEN** the slave aborts with 0x06010002

### Requirement: PDO mapping set by the master
The slave SHALL accept PDO communication and mapping changes over SDO as CiA 301 allows, and SHALL exchange data with the mapping in force. A binding SHALL keep working whatever PDO carries its object, or none.

#### Scenario: Master remaps a TPDO
- **WHEN** the master maps a bound output object into TPDO 3 and starts the node
- **THEN** TPDO 3 carries the value of that object's `%Q` location

#### Scenario: Object only over SDO
- **WHEN** a bound input object is in no RPDO and the master downloads it over SDO
- **THEN** the PLC input shows the new value on the next scan

### Requirement: Object bindings and direction
Each `objects` entry SHALL bind one object to one PLC location. The direction SHALL come from the EDS access type: `rww` and `rw` objects are written by the master and SHALL bind to an `%I` location; `ro` and `rwr` objects are read by the master and SHALL bind to a `%Q` location. A `const` object, a location of the wrong area or a size that does not fit the data type SHALL be rejected with the reason.

#### Scenario: Output bound to a master-written object
- **WHEN** an `objects` entry binds 0x2000:1 (access `rww`) to `%QW300`
- **THEN** the config is rejected with an error saying the master writes 0x2000:1, so it needs an `%I` location

#### Scenario: Master never writes PLC outputs
- **WHEN** the master downloads a value to any object
- **THEN** no `%Q` location of the program changes

### Requirement: Values from the master to the PLC
A value the master writes to a bound input object, by RPDO or SDO, SHALL reach the PLC input at the next scan start. Inputs SHALL hold their last value while the node is not OPERATIONAL or communication is lost, unless `inputs_on_loss` is `"zero"`, which sets them to 0.

#### Scenario: RPDO to input
- **WHEN** an RPDO carrying 0x2000:1 arrives with 1234
- **THEN** `%IW300` reads 1234 in the next scan

#### Scenario: Master stops the node
- **WHEN** the master sends NMT stop and `inputs_on_loss` is not set
- **THEN** the bound inputs keep their last values

### Requirement: Values from the PLC to the master
At the end of each scan the plugin SHALL write changed bound output values into the dictionary. Synchronous TPDOs SHALL carry the newest written values at the next SYNC; event-driven TPDOs that map a changed object SHALL be sent, honouring their inhibit time; an SDO upload SHALL return the newest written value.

#### Scenario: Event-driven TPDO
- **WHEN** the program changes `%QW300`, bound to 0x2100:1, which TPDO 1 with transmission type 255 maps
- **THEN** TPDO 1 is sent with the new value, no earlier than its inhibit time after the previous one

#### Scenario: Synchronous TPDO
- **WHEN** TPDO 2 has transmission type 1 and maps 0x2100:2
- **THEN** each SYNC is answered with TPDO 2 holding the value the last finished scan wrote

### Requirement: Status locations
A slave MAY have `state_location`, `comm_ok_location` and `sync_count_location`; each one set SHALL be updated every scan: `state_location` (`%IB`, own NMT state: 0 not started, 4 stopped, 5 operational, 127 pre-operational), `comm_ok_location` (`%IX`, true while OPERATIONAL with no heartbeat consumer or life guarding error) and `sync_count_location` (`%IW`, SYNCs received, wrapping at 65535).

#### Scenario: Lost master heartbeat
- **WHEN** 0x1016 watches the master's heartbeat and it stops
- **THEN** `comm_ok_location` reads false, the log names the master's node ID, and the node follows 0x1029:1

### Requirement: Emergency messages from the program
A slave MAY have `emcy_code_location` (`%QW`) and `error_register_location` (`%QB`). A change to a non-zero code SHALL send one EMCY with that code and register and set 0x1001; a change to 0 SHALL send the error reset EMCY and clear 0x1001. EMCY inhibit time 0x1015 SHALL apply.

#### Scenario: Program raises an emergency
- **WHEN** the program sets `emcy_code_location` to 0x5000 and `error_register_location` to 1
- **THEN** the slave sends EMCY 0x08A with code 0x5000 and register 1, once

#### Scenario: Program clears it
- **WHEN** the program then sets the code back to 0
- **THEN** the slave sends an EMCY with code 0x0000 and 0x1001 reads 0

### Requirement: Stored parameters
A "save" written to 0x1010 by the master SHALL store the selected dictionary ranges in a state file outside the uploaded project, and a "load" to 0x1011 SHALL delete them. Stored values SHALL be applied after every PLC start and reset node, for as long as the slave's EDS is unchanged; with a changed EDS they SHALL be ignored with a warning.

#### Scenario: Survives an upload
- **WHEN** the master changed and saved 0x1800:5, and the user uploads a new PLC program with the same slave EDS
- **THEN** after the restart 0x1800:5 has the saved value

#### Scenario: Changed EDS
- **WHEN** the slave EDS changes after a save
- **THEN** the stored values are not applied and the log says why

### Requirement: Configuration date
When the EDS has 0x1020, the slave SHALL keep the values the master writes there with the stored parameters, so a master that compares them can skip its configuration download.

#### Scenario: Master skips configuration
- **WHEN** the master wrote 0x1020 and saved, and the PLC restarts
- **THEN** an SDO upload of 0x1020:1 and 0x1020:2 returns the saved values

### Requirement: LSS slave
With `node_id: null` the slave SHALL start without a node ID and wait for LSS. It SHALL answer LSS switch, identify and fastscan by its 0x1018 identity, take a node ID from the LSS master, and keep it on LSS store in the state file. An LSS bit timing change SHALL be answered as not supported.

#### Scenario: Node ID assigned by LSS
- **WHEN** the slave has `node_id: null` and the LSS master assigns 12 and stores it
- **THEN** the slave boots as node 12, and after a PLC restart boots as node 12 again

#### Scenario: Bit rate change
- **WHEN** the LSS master asks to configure bit timing
- **THEN** the slave answers with error code 1 (not supported) and keeps the adapter's bit rate

### Requirement: Node ID conflict
When a frame from another device with the slave's own node ID is seen (boot-up, heartbeat, EMCY or SDO answer), the plugin SHALL log the conflict once per PLC start naming the node ID.

#### Scenario: Two devices with node 10
- **WHEN** another device sends a heartbeat on 0x70A
- **THEN** the log has an error naming node 10 as used by another device

### Requirement: Slave on a simulated bus
A slave network with `adapter.simulate: true` SHALL run on the in-process simulated bus named by its `interface`, shared with a simulated master network of the same `interface` name and any simulated devices on it, with no CAN adapter, vcan or extra privileges, and with the same behaviour as on a real interface.

#### Scenario: Own master against own slave
- **WHEN** one config has a master network and a slave network, both simulated on `bench`, and the master's node list has the slave's node ID and EDS
- **THEN** the master boots the slave, PDOs move both ways between the two networks' PLC locations, and no interface is opened
