## MODIFIED Requirements

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
