## ADDED Requirements

### Requirement: EMCY COB-ID setting
Each slave entry MAY give `emcy_cob_id`: `"device"` (the default when left out), `"eds"`, or a number. With `"eds"` the master SHALL listen for the node's EMCY on the COB-ID its EDS gives as the default of 0x1014, or 0x80 + node ID without one, as before. With a number the master SHALL listen on that COB-ID from the start, written into the master DCF's EMCY consumer entry for the node, and SHALL NOT read the node's 0x1014. A startup SDO to 0x1014 sub-index 0 SHALL count as that number when `emcy_cob_id` gives none. A number with bit 31 or bit 29 set, a CiA 301 restricted CAN-ID, or a COB-ID another identifier of the network uses (another configured node's EMCY, a configured PDO, SDO or heartbeat COB-ID, NMT, SYNC, TIME or LSS) SHALL reject the configuration naming the node and `emcy_cob_id`. A predefined consumer entry of a node ID that is not configured and has the same COB-ID SHALL be left out.

#### Scenario: Fixed COB-ID
- **WHEN** node 5 has `"emcy_cob_id": 197` (0xC5)
- **THEN** the master DCF's EMCY consumer entry for node 5 is 0xC5, no other node ID has an entry on 0xC5, and node 5's EMCYs on 0xC5 are logged

#### Scenario: Unchanged config
- **WHEN** a config gives no `emcy_cob_id` and no startup SDO to 0x1014
- **THEN** the generated master DCF is byte-identical to the one before this change

#### Scenario: Clashing number
- **WHEN** node 5 has `"emcy_cob_id"` equal to node 6's TPDO 1 COB-ID
- **THEN** the configuration is rejected naming node 5, `emcy_cob_id` and node 6's TPDO 1

### Requirement: EMCY COB-ID read from the device
With `"emcy_cob_id": "device"`, after each successful boot of a node whose EDS has 0x1014, the master SHALL read 0x1014 sub-index 0 from the node once, before the node's SDO variables are read, in the node's turn on its SDO channel. When the value differs from the COB-ID the master listens on and passes the checks of the EMCY COB-ID setting, the master SHALL listen on it from then on and log once that node's EMCY COB-ID is the new value, read from the device. A value with bit 31 set (EMCY not valid), with bit 29 set, a restricted CAN-ID or a COB-ID another identifier of the network uses SHALL NOT be taken: the master SHALL keep the COB-ID in use and log one warning naming the node, the value and the reason, not repeated until the read gives another value. An abort or timeout of the read SHALL keep the COB-ID in use, SHALL be logged once as information, and SHALL NOT change the boot result, status bit, state byte or boot error byte. A master NMT reset SHALL restore the COB-IDs of the master DCF until the next boot reads them again.

#### Scenario: COB-ID moved on the device
- **WHEN** node 5's EDS default for 0x1014 is 0x85, the device's 0x1014 holds 0xC5, and node 5 boots
- **THEN** the log says node 5's EMCY COB-ID is 0xC5, read from the device, and an EMCY node 5 then sends on 0xC5 is logged, queued and in its history

#### Scenario: Default COB-ID
- **WHEN** node 5's 0x1014 holds 0x85, the COB-ID the master already listens on
- **THEN** nothing is logged about the COB-ID and nothing else changes

#### Scenario: EMCY disabled on the device
- **WHEN** node 5's 0x1014 reads 0x80000085
- **THEN** the master logs one warning that node 5's EMCY is switched off on the device (0x1014 bit 31), keeps listening on 0x85, and the status reports node 5's EMCY COB-ID as not valid

#### Scenario: Clashing value from the device
- **WHEN** node 5's 0x1014 reads 0x186, node 6's TPDO 1 COB-ID
- **THEN** the master logs one warning naming node 5, 0x186 and node 6's TPDO 1, and keeps listening on 0x85

#### Scenario: Device without 0x1014 answers abort
- **WHEN** the read of node 5's 0x1014 is aborted
- **THEN** node 5's boot result stays successful, the master keeps its COB-ID, and the log has one information line

#### Scenario: Turned off
- **WHEN** node 5 has `"emcy_cob_id": "eds"`
- **THEN** the master sends no SDO to node 5's 0x1014
