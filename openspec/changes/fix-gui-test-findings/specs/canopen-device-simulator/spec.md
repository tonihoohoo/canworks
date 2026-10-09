## ADDED Requirements

### Requirement: Simulation file checked like the plugin checks it
The PC tools' check of the simulation file (the configurator's Simulation view, its save, and the deploy tool) SHALL refuse everything the plugin refuses when it loads the file, with a message naming the network, node and object: a value source or override on an object the master writes (an entry of a configured RPDO mapping), an override or `set` value that does not fit the object's data type, and a scenario step or fault on a node that is not simulated on that network. The plugin's control protocol SHALL refuse an override that does not fit the object's data type instead of storing it.

#### Scenario: Source on an RPDO entry
- **WHEN** the user adds a value source on node 6's 0x6200:1, which node 6's RPDO 1 maps, and saves
- **THEN** Problems lists "node 6: 0x6200:1 is written by the master (RPDO 1); a value source cannot drive it" and Save is disabled

#### Scenario: Override that does not fit
- **WHEN** an override of "abc" is sent for an INTEGER16 object, from the page or over the control protocol
- **THEN** it is refused with a message naming the data type, and the object keeps its value

### Requirement: Power cycle keeps the network running
Powering a simulated device off and on again, by the user, a fault or a scenario, SHALL leave the network's bus running: the master SHALL see the device boot again, the diagnostics channel SHALL keep answering, and stopping the PLC SHALL end the bus thread. A network whose simulation the plugin refuses at start SHALL run its master without simulated devices and SHALL NOT keep a thread busy.

#### Scenario: Power off and on
- **WHEN** simulated node 5 is powered off for 2 s and powered on again, five times in a row
- **THEN** node 5 is OPERATIONAL again after each cycle, the status request answers within 1 s throughout, and the plugin stops within 2 s when the PLC stops
