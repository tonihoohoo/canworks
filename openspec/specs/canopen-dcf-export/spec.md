# canopen-dcf-export Specification

## Purpose
Export each configured CANopen node as a CiA 306 Device Configuration File (DCF) that holds exactly the values the plugin configures on that node at boot, checked against CiA 306 before it is written, so the configuration can be inspected, compared and used in other CANopen tools.

## Requirements

### Requirement: One DCF per configured node
The export SHALL produce one DCF file per node in the config, named `node_<id>.dcf`. It SHALL be built on the engineering PC from the config and the node's EDS alone, with no PLC, runtime or CAN bus. Only a config that passes the deploy tool's existing checks (schema, EDS checks, EDS lint under the config's `eds_lint` setting) SHALL be exported; otherwise the export SHALL stop with those checks' messages and write nothing.

#### Scenario: Two nodes
- **WHEN** a valid config has nodes 2 and 23 and the user exports all
- **THEN** `node_2.dcf` and `node_23.dcf` are written, each from its own node's EDS

#### Scenario: Config with an error
- **WHEN** an `rx_pdos` entry targets a read-only object in the EDS
- **THEN** the export stops with the same message the deploy tool's checks give, and no DCF is written

### Requirement: DCF body is the node's EDS
The DCF SHALL contain every section and key of the EDS copy the plugin uses (the prepared copy from the EDS lint step), in the same order and with the same values, so that removing the added lines gives back that copy. The export SHALL only add or change the lines this capability names: `ParameterValue` keys, the `[DeviceComissioning]` section, `[FileInfo]` keys and leading `;` comment lines.

#### Scenario: Unwritten objects untouched
- **WHEN** a node's EDS defines 0x6000 and the config writes nothing there
- **THEN** the DCF's 0x6000 sections are identical to the EDS's, with no ParameterValue

### Requirement: ParameterValue for every boot write
For every sub-object the plugin writes to the node during its boot-time configuration, the DCF SHALL carry `ParameterValue=` with the value the sub-object holds after the whole configuration download, i.e. the last value written. This covers the writes from PDO communication and mapping settings, heartbeat producer and consumer, node guarding, TIME COB-ID, RPDO deadlines, the configuration-check stamp and startup SDOs. Writes the plugin drops (read-only PDO communication sub-indices whose EDS value already matches, the 0x1016 clear when `heartbeat_consumer` is unset) SHALL get no ParameterValue. `$NODEID` expressions SHALL be resolved: ParameterValue holds the absolute value. A sub-object defined through `CompactSubObj` SHALL get its value in the object's `[<index>Value]` section.

#### Scenario: PDO COB-ID disable and enable
- **WHEN** a TPDO is configured and the plugin writes its COB-ID first with the invalid bit set and later without it
- **THEN** the DCF's `[1800sub1]` ParameterValue is the final, valid COB-ID

#### Scenario: Startup SDO
- **WHEN** node 23 has a startup SDO writing 0x2020 sub 0 = 1
- **THEN** `[2040]` in `node_23.dcf` has `ParameterValue=1` (in the data type's CiA 306 form)

#### Scenario: Dropped read-only write
- **WHEN** a node's EDS has 0x1800 sub 2 read-only with the configured value
- **THEN** `[1800sub2]` has no ParameterValue

### Requirement: Boot commands are not parameter values
Writes that are commands rather than settings (0x1010 store and 0x1011 restore) and the firmware download (`software_file`) SHALL NOT be written as ParameterValue. The DCF SHALL list each such step the plugin performs for the node in a leading `;` comment, in boot order.

#### Scenario: Store after configuration check
- **WHEN** a node has the configuration check with store enabled
- **THEN** the DCF has a ParameterValue on 0x1020 sub 1 and sub 2, none on 0x1010, and a comment line saying the plugin writes "save" to 0x1010 sub 1 after the configuration

### Requirement: Commissioning and file information
The DCF SHALL have a `[DeviceComissioning]` section with `NodeID` (the node ID, decimal), `NodeName` (the node's name in the config, else `node_<id>`), `Baudrate` (the adapter bit rate in kbit/s), `NetNumber=1`, `NetworkName=OpenPLC CANopen`, `CANopenManager=0`, and `LSS_SerialNumber` when the config gives the node a `serial_number`. In `[FileInfo]` it SHALL set `FileName` to the DCF's name, `LastEDS` to the EDS file name, `ModifiedBy` to the tool and its version, and `ModificationDate`/`ModificationTime` to the export time in CiA 306 form, keeping the other FileInfo keys.

#### Scenario: Commissioning section
- **WHEN** node 23 named `valve` runs on a 500 kbit/s adapter
- **THEN** `[DeviceComissioning]` has `NodeID=23`, `NodeName=valve` and `Baudrate=500`

### Requirement: Validated against CiA 306
Before writing, the export SHALL check each finished DCF and SHALL write no file for any node when a check fails, reporting every failure with the node, the DCF section and the key. The checks SHALL be: Lely's CiA 306 lint (every finding fails, whatever `eds_lint` is set to, for the sections the export added or changed; findings already accepted on the EDS stay warnings) and Lely's device read with the node ID; every ParameterValue lies within its data type and the object's LowLimit/HighLimit; every ParameterValue is on a sub-object whose AccessType allows writing, or equals the EDS value; `NodeID` is 1 to 127 and equals the config's node ID; `Baudrate` is one of 10, 20, 50, 125, 250, 500, 800, 1000 and the EDS's `[DeviceInfo]` does not set `BaudRate_<rate>=0`.

#### Scenario: Value out of range
- **WHEN** a startup SDO writes 300 to an UNSIGNED8 object (only possible if the config checks were bypassed, as in a test)
- **THEN** the export fails with "ParameterValue overflow in [<section>]" for that node and writes nothing

#### Scenario: Read-only object
- **WHEN** a ParameterValue would land on a sub-object with AccessType `ro` and a different EDS value
- **THEN** the export fails naming the section and the AccessType

#### Scenario: Baud rate the device does not support
- **WHEN** the adapter runs at 1000 kbit/s and the node's EDS has `BaudRate_1000=0`
- **THEN** the export fails naming `[DeviceComissioning] Baudrate` and the EDS

### Requirement: Values match the plugin's downloads
For every node, the set of sub-objects carrying ParameterValue and their values SHALL equal the final per-sub-object result of the configuration download the plugin performs for the same config (`canopen_check --dump-writes`), excluding the boot commands named above.

#### Scenario: Fixture parity
- **WHEN** CI exports every fixture config and runs `canopen_check --dump-writes` on it
- **THEN** for each node the two lists match
