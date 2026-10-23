# bridge-plc-blocks Specification

## Purpose
The canworks library's ST blocks that reach the bridge through its mailboxes: the link array and its service block, how instances share the request mailboxes, the long SDO, EMCY, CAN frame and J1939 blocks with their pins and error IDs, and building them for any Modbus PLC.

## Requirements

### Requirement: Link array and link service
The blocks of this capability and the blocks over the bridge of `plc-library` SHALL take the in-out `LINK : ARRAY[0..1279] OF WORD`, the generated `canworks.link`. Words 0-88 SHALL keep the meaning `add-openplc-modbus-target` gave them; the mailbox flags, scan counter, ticket words, mailbox owners, receive acknowledgement, cyclic keepalives, request mailboxes, receive mailbox, network info and cyclic job table SHALL follow at fixed places. The library SHALL provide `CW_LINK_SERVICE` (in-out `LINK`), which the generated input code SHALL call once at the start of every scan after copying the input words: it SHALL increment the scan counter, move the lowest waiting ticket of the last scan into place, free a request mailbox whose owner has not been called for 100 scans, and set the receivers pending from a new batch.

#### Scenario: Change 1 blocks unchanged
- **WHEN** a program from change 1 that calls `CO_SDO_READ` and `CO_NMT` is rebuilt with this library and Update declarations
- **THEN** it builds and behaves as before

### Requirement: Sharing the request mailboxes
Blocks that need a request mailbox SHALL take a ticket when they start and SHALL get a free mailbox in ticket order: the waiting instance with the lowest ticket seen in the previous scan takes the first free mailbox. An instance SHALL keep its mailbox for its whole transfer, including STAGE and FETCH requests, and SHALL free it when it ends. An instance that is not called SHALL NOT hold up the others: it drops out of the order while waiting, and loses its mailbox after 100 scans without a call. Time spent waiting for a mailbox SHALL NOT count against `TIMEOUT`.

#### Scenario: Three senders, one mailbox
- **WHEN** three `CAN_SEND` instances start in the same scan on a config with one request mailbox
- **THEN** their frames go out one after another in the order the instances were called, and all three end with `DONE`

#### Scenario: Waiting instance skipped
- **WHEN** an instance waits for a mailbox and the program stops calling it
- **THEN** the instances that started after it get the mailbox within one scan of it becoming free

### Requirement: Long SDO blocks over the bridge
The library SHALL provide `CO_SDO_READ_BYTES`, `CO_SDO_WRITE_BYTES` (in-out `BUFFER : ARRAY[0..1023] OF BYTE`, `SIZE : UINT`), `CO_SDO_READ_STRING`, `CO_SDO_WRITE_STRING` (`VALUE : STRING`), `CO_SDO_READ_REAL` and `CO_SDO_WRITE_REAL` (`VALUE : LREAL`, `SIZE : USINT` for the write) with the pins, data rules, handshake and ERROR_IDs the plugin's SDO blocks had, plus the in-out `LINK`. They SHALL transfer through a request mailbox, in chunks of 128 bytes. `CO_SDO_READ_REAL` SHALL accept 4- and 8-byte replies.

#### Scenario: Read the device name
- **WHEN** a program reads 0x1008:0 with `CO_SDO_READ_STRING` from a node whose name is "Valve block 24 V"
- **THEN** the block ends with `DONE` and `VALUE` holds that text

#### Scenario: Write 600 bytes
- **WHEN** a program writes 600 bytes from `BUFFER` with `CO_SDO_WRITE_BYTES`
- **THEN** the node receives the 600 bytes in one SDO download and the block ends with `DONE`

### Requirement: EMCY block over the bridge
The library SHALL provide `CO_RECV_EMCY` with the plugin block's pins plus the in-out `LINK`. On the rising edge of `ENABLE` it SHALL open an EMCY receiver for `NETWORK` and `NODE` (0 every node), from the oldest kept message or, with `SKIP_OLD`, from the next one. Each call SHALL deliver at most one message (`NEW`), oldest first, from the receive mailbox. `QUEUED`, `OVERFLOW` and `LOST` SHALL report what the bridge reports for that receiver. A new CANopen session SHALL show `ERROR_ID` 8 for one call, after which the block continues with the new session's messages. Several instances SHALL each receive every matching message.

#### Scenario: Two instances
- **WHEN** two `CO_RECV_EMCY` instances on network 0 are enabled and node 3 sends one EMCY
- **THEN** both deliver it once

### Requirement: Frame blocks over the bridge
The library SHALL provide `CAN_SEND`, `CAN_SEND_CYCLIC`, `CAN_RECEIVE` and `CAN_BUS_INFO` with the plugin blocks' pins plus the in-out `LINK`, and with their handshake, receiver, cyclic and error behaviour, except that:
- `CAN_SEND` SHALL send through a request mailbox and end with `DONE` when the bridge reports the frame confirmed;
- `CAN_SEND_CYCLIC` SHALL start its job on the rising edge of `ENABLE`, send changed `DATA`, `DLC` or `PERIOD` to the bridge only when they change, write its keepalive on every call, read `COUNT` and errors from the cyclic job table, and stop the job when `ENABLE` falls;
- `CAN_RECEIVE` SHALL open its receiver on the rising edge of `ENABLE` (`DEPTH` 0 meaning 32, at most 256), deliver at most one frame per call from the receive mailbox, clear its pending mark when it has delivered all its records of the current batch, and close the receiver when `ENABLE` falls;
- `CAN_BUS_INFO` SHALL read the network info block without a request, for the first 8 networks.

#### Scenario: Drain in one scan
- **WHEN** five matching frames are in the current batch for one receiver and the program calls `WHILE rx.NEW DO ... rx(); END_WHILE` after a first `rx()` call
- **THEN** the program sees the five frames in arrival order in that scan

#### Scenario: Update cyclic data
- **WHEN** a `CAN_SEND_CYCLIC` with `PERIOD := T#20ms` runs and the program changes `DATA[0]` from 1 to 2
- **THEN** within about two polls the frames on the bus carry 2, and no request is written while `DATA` does not change

### Requirement: J1939 blocks over the bridge
The library SHALL provide `J1939_SEND`, `J1939_RECEIVE`, `J1939_REQUEST`, `J1939_ECU_INFO`, `J1939_FIND_ECU`, `J1939_DM_READ` and `J1939_DM_CLEAR` with the plugin blocks' pins plus the in-out `LINK`, and with their handshake, address, receiver and trouble code behaviour, except that:
- `J1939_SEND` and `J1939_REQUEST` SHALL transfer through a request mailbox, in chunks of 128 bytes for data longer than that;
- `J1939_RECEIVE` SHALL open its receiver on the rising edge of `ENABLE` and again when its filter inputs change, and SHALL report `NEW` for a message longer than 8 bytes only after reading it whole with RX_FETCH;
- `J1939_ECU_INFO` SHALL read the network info block without a request;
- `J1939_FIND_ECU` SHALL repeat FIND_ECU through a request mailbox while `ENABLE` is TRUE, taking a new ticket for each, and SHALL set `VALID` after the first answer;
- `J1939_DM_READ` with `PREVIOUS` FALSE SHALL return the bridge's latest DM1 from `SOURCE` without bus traffic.

#### Scenario: Long message received
- **WHEN** a `J1939_RECEIVE` for PGN 65282 is enabled and ECU 0 sends 40 bytes by BAM
- **THEN** a later call returns `NEW` TRUE with `RX_LENGTH` 40 and the 40 bytes in `RX_DATA`

#### Scenario: Active trouble codes
- **WHEN** ECU 0 sends a DM1 with two codes and the program runs `J1939_DM_READ` with `SOURCE := 0`, `PREVIOUS := FALSE`
- **THEN** the block ends with `DONE`, `COUNT` 2, both codes in `DTCS` and the lamps of that DM1

### Requirement: Error IDs over the bridge
Each block SHALL keep the ERROR_IDs of its family as the plugin's blocks defined them, with these changes: the ID that meant "the plugin is not loaded" SHALL mean "the network is not running"; 20 SHALL mean the bridge is not reachable or does not serve this program's map (`canworks.ok` FALSE at start or during the transfer); 22 SHALL mean the config has no bridge block this block needs (no request mailbox, no receive mailbox, no network info or a network past the first 8, no cyclic job table); the "cancelled" ID SHALL also cover a receiver or job the bridge closed because the link stopped or the receiver stalled; and the "no free receiver or job" ID SHALL also cover the 32 receivers and the configured cyclic jobs of the link. A block refused with 20 or 22 SHALL end in the call that started it without writing a request.

#### Scenario: No mailboxes configured
- **WHEN** a program calls `CAN_SEND` on a bridge config without `mailboxes`
- **THEN** the block ends with `ERROR` and `ERROR_ID` 22 in the same call

#### Scenario: Bridge gone during a transfer
- **WHEN** the bridge stops while `CO_SDO_READ_BYTES` waits for FETCH answers
- **THEN** the block ends with `ERROR_ID` 20 within 3 × `watchdog_ms` plus one poll

### Requirement: Blocks for any Modbus PLC
The blocks, `CW_LINK_SERVICE` and their helpers SHALL be plain IEC 61131-3 ST that uses only standard functions, `TON` and the `LINK` array, so that they build for OpenPLC and for other IEC 61131-3 runtimes. Their behaviour SHALL depend only on the `LINK` words, never on the runtime.

#### Scenario: Built by STruC++ without OpenPLC
- **WHEN** the block sources are built by STruC++ with the scripted mailbox model in CI
- **THEN** they build and pass without any OpenPLC runtime header
