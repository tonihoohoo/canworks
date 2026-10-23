## MODIFIED Requirements

### Requirement: Slave network start-up
At PLC start the bridge SHALL load each slave network's EDS, lint and check it as for master networks, set the node ID from the config, open the network's adapter, and send its boot-up message. A config error SHALL open no interface of any network, as for master networks.

#### Scenario: Slave boots
- **WHEN** the PLC starts with a slave network on `can1`, node ID 10 and a valid EDS
- **THEN** the bridge sends the boot-up message 0x70A with data 0x00 on `can1` and the node is PRE-OPERATIONAL

#### Scenario: EDS fails the lint
- **WHEN** the slave EDS has a communication-area finding that `eds_lint` does not accept
- **THEN** the config is rejected, the log names the EDS and the finding, and no interface is opened

### Requirement: Behaviour comes from the EDS
The slave's object dictionary SHALL be the EDS's objects with their default values; the bridge SHALL NOT add objects or change EDS values except the node ID, values restored from a store, and the NMT startup object of the next requirement. PDO communication and mapping, heartbeat, guarding, SYNC and TIME consumer and error behaviour SHALL follow the dictionary.

#### Scenario: Heartbeat from the EDS
- **WHEN** the EDS has 0x1017 default 500
- **THEN** the slave sends a heartbeat every 500 ms after boot-up without any heartbeat setting in the config

#### Scenario: Object not in the EDS
- **WHEN** an `objects` entry names 0x2005:1 and the EDS has no such object
- **THEN** the config is rejected with an error naming the network, the object and the EDS

### Requirement: Wait for the master's start
After boot-up the slave SHALL stay PRE-OPERATIONAL until the master starts it. When the EDS has no NMT startup object 0x1F80, the bridge SHALL add it read-only with value 0x04 (do not start by itself); an EDS with 0x1F80 keeps its own value.

#### Scenario: Waits for the master's start
- **WHEN** the slave EDS has no object 0x1F80 and no master sends NMT start
- **THEN** the slave stays PRE-OPERATIONAL and sends no PDOs

### Requirement: Values from the PLC to the master
At the end of each scan the bridge SHALL write changed bound output values into the dictionary. Synchronous TPDOs SHALL carry the newest written values at the next SYNC; event-driven TPDOs that map a changed object SHALL be sent, honouring their inhibit time; an SDO upload SHALL return the newest written value. On entering OPERATIONAL every event-driven TPDO SHALL be sent once, so the master has all values without waiting for a change.

#### Scenario: Event-driven TPDO
- **WHEN** the program changes `%QW300`, bound to 0x2100:1, which TPDO 1 with transmission type 255 maps
- **THEN** TPDO 1 is sent with the new value, no earlier than its inhibit time after the previous one

#### Scenario: Synchronous TPDO
- **WHEN** TPDO 2 has transmission type 1 and maps 0x2100:2
- **THEN** each SYNC is answered with TPDO 2 holding the value the last finished scan wrote

### Requirement: LSS slave
With `node_id: null` the slave SHALL start without a node ID and wait for LSS. It SHALL answer LSS switch, identify and fastscan by its 0x1018 identity, take a node ID from the LSS master, and keep it on LSS store in the state file. An LSS bit timing change SHALL be answered as not supported.

`node_id: null` SHALL be rejected by the bridge and the deploy tool when the slave's EDS does not say `LSS_Supported=1` (left out or 0), with "slave: node_id null needs an EDS with LSS_Supported=1; its EDS has no LSS", since the slave could never get a node ID.

#### Scenario: Node ID assigned by LSS
- **WHEN** the slave has `node_id: null` and the LSS master assigns 12 and stores it
- **THEN** the slave boots as node 12, and after a PLC restart boots as node 12 again

#### Scenario: Bit rate change
- **WHEN** the LSS master asks to configure bit timing
- **THEN** the slave answers with error code 1 (not supported) and keeps the adapter's bit rate

#### Scenario: No LSS in the slave's EDS
- **WHEN** the slave has `node_id: null` and its EDS says `LSS_Supported=0`
- **THEN** the bridge and the deploy tool reject the configuration with that message

### Requirement: Node ID conflict
When a frame from another device with the slave's own node ID is seen (boot-up, heartbeat, EMCY or SDO answer), the bridge SHALL log the conflict once per PLC start naming the node ID.

#### Scenario: Two devices with node 10
- **WHEN** another device sends a heartbeat on 0x70A
- **THEN** the log has an error naming node 10 as used by another device
