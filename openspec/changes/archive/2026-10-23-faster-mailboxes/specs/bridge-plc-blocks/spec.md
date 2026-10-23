## MODIFIED Requirements

### Requirement: Frame blocks over the bridge
The library SHALL provide `CAN_SEND`, `CAN_SEND_CYCLIC`, `CAN_RECEIVE` and `CAN_BUS_INFO` with the removed plugin blocks' pins plus the in-out `LINK` (the pin `NEW` named `RECEIVED`, and `CAN_RECEIVE`'s `ANY` named `ALL_IDS`, because `NEW` and `ANY` are reserved words in IEC 61131-3), and with their handshake, receiver, cyclic and error behaviour, except that:
- `CAN_SEND` SHALL send through a request mailbox and end with `DONE` when the bridge reports the frame confirmed;
- `CAN_SEND_CYCLIC` SHALL start its job on the rising edge of `ENABLE`, send changed `DATA`, `DLC` or `PERIOD` to the bridge only when they change, write its keepalive on every call, read `COUNT` and errors from the cyclic job table, and stop the job when `ENABLE` falls;
- `CAN_RECEIVE` SHALL open its receiver on the rising edge of `ENABLE` (`DEPTH` 0 meaning 32, at most 256), deliver at most one frame per call from the receive mailbox, clear its pending mark when it has delivered all its records of the current batch, and close the receiver when `ENABLE` falls;
- `CAN_RECEIVE`'s `TIMESTAMP` SHALL be the batch time of the batch the frame came in (the receive time of that batch's first record), not the frame's own receive time;
- `CAN_BUS_INFO` SHALL read the network info block without a request, for the first 8 networks.

#### Scenario: Drain in one scan
- **WHEN** five matching frames are in the current batch for one receiver and the program calls `WHILE rx.RECEIVED DO ... rx(); END_WHILE` after a first `rx()` call
- **THEN** the program sees the five frames in arrival order in that scan

#### Scenario: Update cyclic data
- **WHEN** a `CAN_SEND_CYCLIC` with `PERIOD := T#20ms` runs and the program changes `DATA[0]` from 1 to 2
- **THEN** within about two polls the frames on the bus carry 2, and no request is written while `DATA` does not change

#### Scenario: Timestamp of a batch
- **WHEN** three frames arrive 2 ms apart and come in one batch
- **THEN** `CAN_RECEIVE` reports the same `TIMESTAMP` for all three: the first frame's receive time

### Requirement: J1939 blocks over the bridge
The library SHALL provide `J1939_SEND`, `J1939_RECEIVE`, `J1939_REQUEST`, `J1939_ECU_INFO`, `J1939_FIND_ECU`, `J1939_DM_READ` and `J1939_DM_CLEAR` with the removed plugin blocks' pins plus the in-out `LINK` (the pin `NEW` named `RECEIVED`, and `J1939_RECEIVE`'s `ANY` named `ALL_PGNS`), and with their handshake, address, receiver and trouble code behaviour, except that:
- `J1939_SEND` and `J1939_REQUEST` SHALL transfer through a request mailbox, in chunks of 128 bytes for data longer than that;
- `J1939_RECEIVE` SHALL open its receiver on the rising edge of `ENABLE` and again when its filter inputs change, and SHALL report `RECEIVED` for a message longer than 8 bytes only after reading it whole with RX_FETCH;
- `J1939_RECEIVE`'s `TIMESTAMP` SHALL be the batch time of the batch the message came in;
- `J1939_ECU_INFO` SHALL read the network info block without a request;
- `J1939_FIND_ECU` SHALL repeat FIND_ECU through a request mailbox while `ENABLE` is TRUE, taking a new ticket for each, and SHALL set `VALID` after the first answer;
- `J1939_DM_READ` with `PREVIOUS` FALSE SHALL return the bridge's latest DM1 from `SOURCE` without bus traffic.

#### Scenario: Long message received
- **WHEN** a `J1939_RECEIVE` for PGN 65282 is enabled and ECU 0 sends 40 bytes by BAM
- **THEN** a later call returns `RECEIVED` TRUE with `RX_LENGTH` 40 and the 40 bytes in `RX_DATA`

#### Scenario: Active trouble codes
- **WHEN** ECU 0 sends a DM1 with two codes and the program runs `J1939_DM_READ` with `SOURCE := 0`, `PREVIOUS := FALSE`
- **THEN** the block ends with `DONE`, `COUNT` 2, both codes in `DTCS` and the lamps of that DM1
