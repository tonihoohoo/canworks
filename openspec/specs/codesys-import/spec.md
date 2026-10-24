# codesys-import Specification

## Purpose
Reads the CANopen networks of a CODESYS project (its PLCopenXML export) into a canworks config, with each node's EDS, the settings only CODESYS has and a report of what is not carried, so a config moves back and forth between canworks and CODESYS without losing data.

## Requirements

### Requirement: Import source
canworks SHALL import CANopen networks from a CODESYS PLCopenXML export of a device or CANbus. It SHALL accept either such an `.xml` file, on any PC, or a CODESYS `.project`, which it SHALL first export to PLCopenXML by running CODESYS headless on this PC. A `.project` on a PC without CODESYS SHALL be refused with a message saying to export PLCopenXML in CODESYS and import that file.

#### Scenario: Hand-exported XML on a Mac
- **WHEN** the user imports `line2.xml` exported in CODESYS with Project > Export PLCopenXML on a Mac without CODESYS
- **THEN** the import reads it and offers the networks it holds

#### Scenario: Project file on a PC with CODESYS
- **WHEN** the user imports `C:\Projects\line2.project` on a PC with CODESYS
- **THEN** canworks exports it headless and imports the result, and the project file is not changed

#### Scenario: Project open in CODESYS
- **WHEN** the project is open in the CODESYS window
- **THEN** the import says to close it there or export PLCopenXML from CODESYS and import that file

### Requirement: Choosing the device
When the source holds more than one device with a CANopen Manager, the import SHALL list them with their networks and node counts and import the one the user picks; the device holding the project's active application SHALL be preselected when known.

#### Scenario: Display project with variants
- **WHEN** the project has 23 devices with a manager and `ExampleApp` holds the active application
- **THEN** the list shows 23 devices with `ExampleApp` selected

### Requirement: Imported networks
For each CANopen Manager network of the chosen device the import SHALL create a CANopen master network with the CODESYS network number in `codesys.net_id`, the interface `canN` for network number N, the bit rate, and the manager's node ID, SYNC (on, period, window), heartbeat producer, TIME producer and start options.

#### Scenario: Network number 1
- **WHEN** a CANbus has network number 1 at 250 kbit/s
- **THEN** the network has `codesys.net_id` 1, interface `can1` and bit rate 250000

### Requirement: Imported nodes
For each remote device the import SHALL create a node with node ID, a name (the CODESYS name made a valid identifier), optional or mandatory, no-initialization, restore before configuring, heartbeat producer and consumer, node guarding, TIME consumer, every enabled PDO with its communication settings and mapping, each entry's variable name as its `name` when it differs from the generated one (bit variables as its bits), and the startup SDOs the user added.

#### Scenario: Three networks
- **WHEN** the virtual-plant fixture export (networks on numbers 0, 1 and 2) is imported
- **THEN** the config has three master networks with the same nodes, PDOs, startup SDOs and entry names as the virtual-plant example config, apart from the settings listed as not carried

#### Scenario: Disabled PDO
- **WHEN** TPDO3 of a node has COB-ID bit 31 set
- **THEN** the imported node lists no TPDO3, which canworks switches off

### Requirement: Defaults left out
Imported values equal to the node's EDS default SHALL be left out of the config, except a PDO's transmission type, and a PDO COB-ID equal to the CiA default for the node SHALL be left out.

#### Scenario: Default event timer
- **WHEN** TPDO1 of `rtd` has the event timer its EDS gives
- **THEN** the imported TPDO1 has no `event_timer_ms`

### Requirement: Generated SDO rows skipped
SDO rows CODESYS generated SHALL NOT be imported as startup SDOs: the startup SDOs are the rows for objects from 0x2000 whose value differs from the EDS default.

#### Scenario: Generated SDO rows
- **WHEN** a node's SDO list has 12 generated rows for its PDOs and one row 0x2000:00 = 10 (EDS default 5)
- **THEN** the node's `sdo` list has only 0x2000:00 = 10

### Requirement: CODESYS-only settings carried
Settings that only CODESYS has SHALL be imported into `codesys` objects so a build gives them back, each only when it is set: the device's CODESYS name and identity-check ticks (other than the default vendor check) on the node, "processed by the manager" when off on a PDO, a fixed I/O address and a variable name that is no valid entry name on an entry, and abort-on-error and jump-to-line on a startup SDO.

#### Scenario: Fixed address
- **WHEN** a channel in the export has manual address `%IB40`
- **THEN** that entry gets `"codesys": {"address": "%IB40"}`

### Requirement: EDS for each node
Each imported node SHALL get an EDS: from the config's EDS library when one matches its vendor ID, product code and revision (an exact match first, else the same vendor and product with a warning naming both revisions); else the device description file from CODESYS's device repository when the import runs on the PC with that CODESYS, copied into the config folder; else the node SHALL be marked missing and the config SHALL NOT be written until the user adds an EDS for it.

#### Scenario: Missing EDS
- **WHEN** a node's identity matches nothing in the library and the import runs from an XML file on a Mac
- **THEN** the preview marks the node "EDS missing" with Add EDS…, and Create config stays disabled until it is added

### Requirement: Import report
The import SHALL list everything in the source it did not carry over (CODESYS as a CANopen slave, CANbuses without a CANopen Manager such as J1939, other device types on the bus or under the manager, manager and device settings canworks has no field for when they are not at their default, SDO flags on generated rows), with where it was. Nothing SHALL be dropped without a line.

#### Scenario: Slave on another CANbus
- **WHEN** the chosen device also has a CANbus holding a CANopen Device (CODESYS as slave)
- **THEN** the report lists it as not carried and the manager networks are imported

### Requirement: Network name from the bus object
Import from CODESYS SHALL take each network's name from its CAN bus object, and from its interface only when the object has the CODESYS default name.

#### Scenario: Round trip of one network
- **WHEN** a config with one network "field" is built into CODESYS and imported back
- **THEN** the imported network is named "field"

### Requirement: Clash reason in the import
When an imported network clashes with one in the open config, the import dialog SHALL say why (same name, or same CODESYS network number) and SHALL name both roles when a master would replace a slave network.

#### Scenario: Same network number
- **WHEN** imported master network host is CODESYS network 2 and the open config's slave network cell is network 2
- **THEN** the dialog says both are CODESYS network 2 and the replace button reads "Replace the slave network cell with the master host"
