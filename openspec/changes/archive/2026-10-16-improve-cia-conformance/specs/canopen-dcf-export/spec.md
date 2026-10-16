## MODIFIED Requirements

### Requirement: DCF body is the node's EDS
The DCF SHALL contain every section and key of the EDS copy the plugin uses (the prepared copy from the EDS lint step), in the same order and with the same values, so that removing the added lines gives back that copy, except that REAL32 and REAL64 DefaultValue, ParameterValue, LowLimit and HighLimit SHALL be written as decimal numbers that read back to exactly the same value. The export SHALL only add or change the lines this capability names: `ParameterValue` keys, the `[DeviceComissioning]` section, `[FileInfo]` keys, leading `;` comment lines and the decimal form of REAL values.

#### Scenario: Unwritten objects untouched
- **WHEN** a node's EDS defines 0x6000 and the config writes nothing there
- **THEN** the DCF's 0x6000 sections are identical to the EDS's, with no ParameterValue

#### Scenario: REAL limit
- **WHEN** a node's prepared EDS has `HighLimit=0x42C80000` on a REAL32 object
- **THEN** the DCF has `HighLimit=100.0` on that object

### Requirement: Validated against CiA 306
Before writing, the export SHALL check each finished DCF and SHALL write no file for any node when a check fails, reporting every failure with the node, the DCF section and the key. The checks SHALL be: Lely's CiA 306 lint (every finding fails, whatever `eds_lint` is set to, for the sections the export added or changed; findings already accepted on the EDS stay warnings) and Lely's device read with the node ID, both on Lely's form of the file; the PC tools' CiA 306 check on the sections and keys the export added or changed, on the file as written; every ParameterValue lies within its data type and the object's LowLimit/HighLimit; every ParameterValue is on a sub-object whose AccessType allows writing, or equals the EDS value; `NodeID` is 1 to 127 and equals the config's node ID; `NodeName` is printable ASCII of at most 246 characters; `Baudrate` is one of 10, 20, 50, 125, 250, 500, 800, 1000 and the EDS's `[DeviceInfo]` does not set `BaudRate_<rate>=0`.

#### Scenario: Value out of range
- **WHEN** a startup SDO writes 300 to an UNSIGNED8 object (only possible if the config checks were bypassed, as in a test)
- **THEN** the export fails with "ParameterValue overflow in [<section>]" for that node and writes nothing

#### Scenario: Read-only object
- **WHEN** a ParameterValue would land on a sub-object with AccessType `ro` and a different EDS value
- **THEN** the export fails naming the section and the AccessType

#### Scenario: Baud rate the device does not support
- **WHEN** the adapter runs at 1000 kbit/s and the node's EDS has `BaudRate_1000=0`
- **THEN** the export fails naming `[DeviceComissioning] Baudrate` and the EDS

#### Scenario: Node name with non-ASCII text
- **WHEN** node 23 is named `venttiili ä`
- **THEN** the export fails naming `[DeviceComissioning] NodeName` and writes nothing
