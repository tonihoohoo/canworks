# canopen-dbc-export Specification

## Purpose
Export the configured CANopen network as a DBC file, so that generic CAN bus tools can decode the PDOs and the fixed CANopen frames the plugin uses, without access to the EDS files or the PLC.

## Requirements

### Requirement: One DBC file for the configured network
The export SHALL produce one DBC file describing the whole config. It SHALL be built on the engineering PC from the config and the nodes' EDS files alone, with no PLC, runtime or CAN bus. Only a config that passes the deploy tool's existing checks (schema, EDS checks, EDS lint under the config's `eds_lint` setting) SHALL be exported; otherwise the export SHALL stop with those checks' messages and write nothing. The file SHALL be ASCII text with CRLF line endings and SHALL load in cantools with strict checking (no overlapping signals, every signal inside its message).

#### Scenario: Example config
- **WHEN** `config/rtd-sensor/canopen_config.json` is exported
- **THEN** the DBC has messages `rtd_TPDO1` (COB-ID 0x185, 8 bytes) and `rtd_TPDO2` (0x285, 4 bytes) plus node 5's heartbeat and EMCY, NMT and SYNC, and cantools loads it with `strict=True`

#### Scenario: Config with an error
- **WHEN** a TPDO number does not exist in the node's EDS
- **THEN** the export stops with the same message the deploy tool's checks give, and no DBC is written

### Requirement: Network nodes
The DBC SHALL declare a network node `Master` for the PLC and one network node per configured CANopen node, named after the node's `name` in the config, else `node<id>`. Names SHALL be turned into DBC identifiers (letters, digits and `_`, not starting with a digit); when two nodes end up with the same identifier, each SHALL get `_<node id>` appended.

#### Scenario: Node without a name
- **WHEN** node 23 has no `name`
- **THEN** its network node is `node23`

### Requirement: A message per configured PDO
Every PDO in the config's `tx_pdos` and `rx_pdos` SHALL become one message with the PDO's COB-ID as the plugin resolves it (explicit `cob_id`, `"auto"`, or the CiA 301 default for PDOs 1-4), named `<node>_TPDO<n>` or `<node>_RPDO<n>`. A TPDO SHALL be sent by its node and received by `Master`; an RPDO SHALL be sent by `Master` and received by its node. The message length SHALL be the mapped bits rounded up to whole bytes.

#### Scenario: Auto COB-ID
- **WHEN** node 2 has TPDO 5 with `"cob_id": "auto"` and the plugin resolves it to 0x57F
- **THEN** the DBC message `<node>_TPDO5` has COB-ID 0x57F

#### Scenario: RPDO direction
- **WHEN** node 2 has RPDO 1
- **THEN** message `<node>_RPDO1` at 0x202 has sender `Master` and its signals have node 2 as receiver

### Requirement: Signal layout follows the PDO mapping
Each mapped object SHALL become one signal at its bit offset in the frame, in Intel (little-endian) byte order, with the object's bit length. The mapping SHALL be the config's `entries` in order for a PDO whose mapping the master writes, and the EDS default mapping for a PDO that keeps the device's mapping (`"mapping": "device"`, or left out on a read-only mapping). Objects of a device mapping that the config's entries do not name SHALL still get a signal. Dummy mapping entries (index 0x0001-0x0007) SHALL take their bits but get no signal.

#### Scenario: Four INTEGER16 inputs
- **WHEN** TPDO 1 maps 0x7130 sub 1-4, each INTEGER16
- **THEN** the signals start at bits 0, 16, 32 and 48, each 16 bits, signed, little-endian

#### Scenario: Device mapping with an unused object
- **WHEN** a TPDO keeps a device mapping of 0x6041 (16 bit) then 0x6061 (8 bit), and the config's entries name only 0x6041
- **THEN** the message has a 16-bit signal at bit 0 and an 8-bit signal at bit 16, and the second signal's comment says the PLC does not use it

#### Scenario: Dummy entry
- **WHEN** a device mapping holds 0x0005 (8 bit dummy) then 0x6000 sub 1 (8 bit)
- **THEN** the message has one signal, at bit 8

### Requirement: Signal types and ranges
Signals of INTEGER types SHALL be signed and of UNSIGNED and BOOLEAN types unsigned, with minimum and maximum the full range of the type's bit length. REAL32 and REAL64 signals SHALL be declared as IEEE single and double floats. Factor SHALL be 1, offset 0 and unit empty. The type SHALL be the config entry's `type` where the config names the object, else the EDS data type.

#### Scenario: REAL32 input
- **WHEN** a TPDO maps a REAL32 object
- **THEN** its signal is 32 bits and declared as an IEEE single float

### Requirement: Signal names
A signal SHALL be named after the object in the node's object dictionary (EDS), turned into a DBC identifier. For a plain object (ObjectType VAR) the name SHALL be its `ParameterName`. For a sub-object of a record or array the name SHALL be the parent object's `ParameterName`, `_`, then the sub-object's own `ParameterName`, except that the parent part SHALL be left out when the sub-object's name already starts with it (compared as identifiers, ignoring case), as with `CompactSubObj` sub-objects. When the export runs on a config that belongs to an editor project and the signal's PLC location has exactly one named located variable in the project, the signal SHALL be named after that variable instead. Within a message, a name that is already taken SHALL get `_<index hex>_<subindex>` appended. An object without a usable name SHALL be named `obj_<index hex>_<subindex>`.

#### Scenario: EDS name
- **WHEN** a standalone config maps 0x6041 named "Statusword" in the EDS
- **THEN** the signal is `Statusword`

#### Scenario: Sub-object name with its parent
- **WHEN** a TPDO maps 0x6110 sub 1, the EDS names 0x6110 "AI Sensor Type" and 0x6110 sub 1 "Output 1"
- **THEN** the signal is `AI_Sensor_Type_Output_1`

#### Scenario: Sub-object name already holds the parent
- **WHEN** the EDS names 0x6200 "Write Output 8 Bit" and its sub 1 "Write Output 8 Bit 1"
- **THEN** the signal is `Write_Output_8_Bit_1`

#### Scenario: PLC variable name
- **WHEN** the config belongs to an editor project whose program declares `valve1 AT %QX20.0 : BOOL` and an RPDO entry targets `%QX20.0`
- **THEN** that signal is `valve1`

### Requirement: Comments and timing
Each signal SHALL have a comment naming the object as `0x<index>:<subindex>`, its CANopen type, and its PLC location, or saying that the PLC does not use it. Each PDO message SHALL have a comment naming the node ID, the PDO and its transmission type (or that the EDS value applies). A PDO with a synchronous transmission type 1-240 SHALL get a `GenMsgCycleTime` attribute of the SYNC period times the transmission type, in milliseconds. With `"sync_source": "plc_cycle"` such a PDO SHALL get no `GenMsgCycleTime`, and its comment SHALL say it is sent every N SYNCs, one SYNC every `sync_cycles` PLC cycles.

#### Scenario: Synchronous TPDO
- **WHEN** the SYNC period is 100000 µs and TPDO 1 has transmission type 1
- **THEN** the message has `GenMsgCycleTime` 100 and its signals' comments read like `0x7130:1 INTEGER16 -> %IW100`

#### Scenario: Synchronous TPDO with PLC-cycle SYNC
- **WHEN** the config has `"sync_source": "plc_cycle"` and `"sync_cycles": 2`, and TPDO 1 has transmission type 1
- **THEN** the message has no `GenMsgCycleTime` and its comment says it is sent at every SYNC, one SYNC every 2 PLC cycles

### Requirement: Fixed CANopen frames
The DBC SHALL describe, for every configured node, its heartbeat message (0x700 + node ID, 1 byte, a 7-bit `NMT_State` signal with values Boot-up 0, Stopped 4, Operational 5, Pre-operational 127) and its EMCY message (0x80 + node ID, 8 bytes: `Error_Code` 16 bits, `Error_Register` 8 bits, `Manufacturer_Data` 40 bits). It SHALL also describe the NMT command message (0x000, 2 bytes, sent by `Master`: `Command` with values Start 1, Stop 2, Enter pre-operational 128, Reset node 129, Reset communication 130, and `Node_ID`) and, when the master produces SYNC (a SYNC period greater than 0, or `"sync_source": "plc_cycle"`), the SYNC message (0x080, sent by `Master`, 0 bytes).

#### Scenario: Heartbeat decode
- **WHEN** node 5 sends 0x705 with data `05`
- **THEN** a tool using the DBC shows `NMT_State` = Operational

#### Scenario: No SYNC message without a SYNC period
- **WHEN** the config has no `sync_period_us` and no `sync_source`
- **THEN** the DBC has no message with ID 0x080

#### Scenario: SYNC message with PLC-cycle SYNC
- **WHEN** the config has `"sync_source": "plc_cycle"` and no `sync_period_us`
- **THEN** the DBC has the SYNC message with ID 0x080

### Requirement: Optional SDO frames
The export SHALL take an SDO option with the values `none` (the default), `config` and `all`. With `none` the DBC SHALL have no SDO messages. With `config` or `all`, the DBC SHALL describe, for every configured node, an SDO request message (0x600 + node ID, sent by `Master`, named `<node>_SDO_Rx`) and an SDO response message (0x580 + node ID, sent by the node, named `<node>_SDO_Tx`), each 8 bytes with:
- a `Command` signal (bits 0-7) with a value table for the expedited command specifiers (download 1, 2, 3 and 4 bytes, download response, upload request, upload 1, 2, 3 and 4 bytes, abort);
- an `Object` multiplexor signal (bits 8-31, unsigned) whose value is `index + subindex * 65536`, as the index and subindex bytes read little-endian, with a value table naming each object `0x<index>:<subindex> <signal name>`;
- one data signal per object at bits 32 up to the object's bit length, multiplexed on that object's `Object` value, with the type, sign, range and naming rules of PDO signals.

The objects SHALL be, with `config`, the node's `sdo_variables` and startup `sdo` entries; with `all`, every sub-object in the node's EDS with a numeric type of 32 bits or less (BOOLEAN, INTEGER8-32, UNSIGNED8-32, REAL32). An SDO variable's `name` SHALL take precedence over the EDS name. A signal's comment SHALL name the object, its type, and what the config does with it (SDO variable with direction and PLC location, startup SDO with its value). Objects larger than 32 bits, strings and domains SHALL be left out, since only expedited transfers carry the value in one frame. The SDO option SHALL NOT change any other message.

#### Scenario: Default without SDO
- **WHEN** the export runs without choosing an SDO option
- **THEN** the DBC has no message at 0x580 + node ID or 0x600 + node ID

#### Scenario: Startup SDO decodes
- **WHEN** node 5 has a startup SDO writing 0x6110 sub 1 = 30 (UNSIGNED16), the export runs with `config`, and the master sends 0x605 with data `2B 10 61 01 1E 00 00 00`
- **THEN** a tool using the DBC shows `Command` "Download 2 bytes", `Object` 0x6110:1 and the object's signal = 30

#### Scenario: All EDS objects
- **WHEN** the export runs with `all` on a node whose EDS has 0x1008 (VISIBLE_STRING) and 0x1017 (UNSIGNED16)
- **THEN** the SDO messages have a signal for 0x1017 and none for 0x1008

#### Scenario: Abort
- **WHEN** a node answers with an SDO abort
- **THEN** `Command` shows "Abort" and `Object` names the object; the abort code is the raw value of bytes 4-7, which the comment on `Command` explains

### Requirement: Warnings that affect the file
When the deploy tool's checks warn that a startup SDO overrides PDO settings the plugin writes, the export SHALL still write the DBC from the PDO settings in the config and SHALL report the warning with it, stating that the DBC may not match the bus for that PDO.

#### Scenario: Startup SDO rewrites a COB-ID
- **WHEN** a startup SDO writes 0x1800 sub 1 of a configured TPDO
- **THEN** the DBC is written and the export reports that warning naming the PDO
