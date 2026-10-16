# j1939-plc-blocks Specification

## Purpose
The J1939 message blocks of the `canworks` library: sending, receiving and requesting any PGN from the PLC program through the network's claimed address, looking up ECUs, and the ST functions for signals and NAMEs.

## Requirements

### Requirement: J1939 message function blocks
The editor library `canworks` SHALL provide `J1939_SEND`, `J1939_RECEIVE`, `J1939_REQUEST`, `J1939_ECU_INFO` and `J1939_FIND_ECU`. Each SHALL have `NETWORK : USINT` (the network's place in `networks`) and the outputs `ERROR : BOOL` and `ERROR_ID : UINT`.
- `J1939_SEND`: in `EXECUTE : BOOL`, `PGN : UDINT`, `DESTINATION : USINT` (0..253, or 255 global; ignored for a PDU2 PGN), `PRIORITY : USINT` (0 meaning 6), `LENGTH : UINT` (0..1785), `TIMEOUT : TIME` (`T#0s` meaning 1 s up to 8 bytes and 10 s above); in-out `DATA : ARRAY[0..1784] OF BYTE`; out `BUSY`, `DONE : BOOL`.
- `J1939_RECEIVE`: in `ENABLE : BOOL`, `PGN : UDINT`, `ANY : BOOL` (every PGN), `SOURCE : USINT`, `FILTER_SOURCE : BOOL` (FALSE: any source; `SOURCE` 255 is any source too), `ALL_DESTINATIONS : BOOL`, `DEPTH : UINT` (0 meaning 4, at most 32); in-out `RX_DATA : ARRAY[0..1784] OF BYTE`; out `ACTIVE`, `NEW : BOOL`, `RX_PGN : UDINT`, `RX_SOURCE`, `RX_DESTINATION`, `RX_PRIORITY : USINT`, `RX_LENGTH : UINT`, `TIMESTAMP : ULINT` (UTC microseconds), `QUEUED : UINT`, `OVERFLOW : BOOL`, `DROPPED : UDINT`.
- `J1939_REQUEST`: in `EXECUTE : BOOL`, `PGN : UDINT`, `DESTINATION : USINT` (0..253, or 255 global), `TIMEOUT : TIME` (`T#0s` meaning 1 s); in-out `DATA : ARRAY[0..1784] OF BYTE` (the answer); out `BUSY`, `DONE : BOOL`, `SOURCE : USINT`, `LENGTH : UINT`, `ACK_CODE : USINT`.
- `J1939_ECU_INFO`: in `ENABLE : BOOL`; out `VALID : BOOL`, `STATE : USINT` (0 claiming, 1 claimed, 2 cannot claim, 3 no bus), `ADDRESS : USINT` (254 while none is held), `NAME : LWORD`, `ECU_COUNT : UINT`.
- `J1939_FIND_ECU`: in `ENABLE : BOOL`, `NAME : LWORD`, `MASK : LWORD`; out `VALID`, `FOUND : BOOL`, `ADDRESS : USINT`, `FOUND_NAME : LWORD`, `COUNT : UINT`.

`J1939_SEND` and `J1939_REQUEST` SHALL have the `EXECUTE` handshake of `CAN_SEND`: a rising edge starts one job with that call's inputs (and, for `J1939_SEND`, `DATA` as it is in that call), edges while `BUSY` are ignored, and outputs stay while `EXECUTE` stays TRUE and for one call after. `J1939_RECEIVE`, `J1939_ECU_INFO` and `J1939_FIND_ECU` SHALL work while `ENABLE` is TRUE and give their result in the same call.

#### Scenario: Send a long PGN to an address
- **WHEN** the network holds address 128 and the program sends PGN 65282 with `LENGTH` 40 to `DESTINATION` 0, and ECU 0 accepts the transfer
- **THEN** the message goes out from address 128 with RTS/CTS, ECU 0 receives the 40 bytes, and the block is `DONE`

#### Scenario: Send a short PGN globally
- **WHEN** the program sends PGN 65281 with `LENGTH` 8 and `DESTINATION` 255
- **THEN** one frame with source 128 goes out and the block is `DONE` once it is on the bus

#### Scenario: Receive a long PGN
- **WHEN** a receiver has `PGN` 65282 and ECU 0 sends it with 40 bytes by BAM
- **THEN** a later call returns `NEW` TRUE with `RX_LENGTH` 40, `RX_SOURCE` 0, `RX_DESTINATION` 255 and the 40 bytes in `RX_DATA`, and `ACTIVE` stays TRUE

#### Scenario: Request one ECU
- **WHEN** the program requests PGN 65259 from address 0 and ECU 0 answers
- **THEN** the block is `DONE` with `SOURCE` 0, the answer's length and bytes

#### Scenario: Find an ECU by NAME
- **WHEN** an ECU with NAME function 0 (engine) holds address 3 and the program calls `J1939_FIND_ECU` with that function's bits in `NAME` and `MASK`
- **THEN** `FOUND` is TRUE, `ADDRESS` 3 and `FOUND_NAME` that ECU's NAME

### Requirement: Sending from the claimed address
`J1939_SEND` SHALL send from the address the network holds at the time it sends, through the kernel's J1939 stack, which uses BAM for a global message and RTS/CTS for one to an address when `LENGTH` is above 8. It SHALL be `DONE` once the kernel has taken a single frame, and once the kernel reports the transport protocol session complete for a longer message (or, where the kernel gives no session reports, once it has taken the message). The network SHALL run one long send of the program at a time; the others wait in order. It SHALL refuse with `ERROR_ID` 4 the PGNs the network sends itself: Request, Address Claimed, Acknowledgement, TP.CM, TP.DT, DM1, DM2, DM3, DM11, DM13, DM22 and every `tx` PGN of the network's config. With `raw.program_override_protocol: true` on the network it SHALL send the DM and `tx` PGNs and log the first such send of a run; Request, Address Claimed, Acknowledgement and the transport protocol PGNs SHALL stay refused.

#### Scenario: No address held
- **WHEN** the network is still claiming or cannot claim and the program sends
- **THEN** the block reports `ERROR_ID` 11 and nothing is sent

#### Scenario: Address moved
- **WHEN** the network lost address 128 to a lower NAME and now holds 129
- **THEN** the next `J1939_SEND` goes out from 129

#### Scenario: PGN a config entry sends
- **WHEN** PGN 65281 is a `tx` entry and the program sends PGN 65281
- **THEN** the block reports `ERROR_ID` 4 and nothing is sent

#### Scenario: Transfer aborted
- **WHEN** the program sends 40 bytes to address 0 and ECU 0 answers the RTS with Connection Abort
- **THEN** the block reports `ERROR_ID` 14

### Requirement: J1939 receivers
While `ENABLE` is TRUE, `J1939_RECEIVE` SHALL queue, up to `DEPTH` messages, every received message whose PGN is `PGN` (any PGN with `ANY`), whose source is `SOURCE` (any with 255) and whose destination is the network's address or global (any with `ALL_DESTINATIONS`), reassembled when it came with the transport protocol. Each call SHALL take at most one message: `NEW` TRUE with its fields, or `NEW` FALSE with the last message's outputs kept. `QUEUED` SHALL say how many still wait. A message arriving at a full queue SHALL be dropped, set `OVERFLOW` until `ENABLE` falls and count in `DROPPED`. Messages the network sends itself SHALL NOT be queued. A network SHALL have at most 16 receivers. Receivers SHALL NOT change what config `rx` entries, diagnostics and requests receive. A receiver whose inputs change while `ENABLE` stays TRUE SHALL close and open again with the new inputs.

#### Scenario: PGN without a config entry
- **WHEN** no `rx` entry names PGN 65300 and a receiver for it is enabled
- **THEN** messages of PGN 65300 reach the receiver from then on

#### Scenario: Same PGN as a config entry
- **WHEN** PGN 65280 is an `rx` entry and a receiver for 65280 is enabled
- **THEN** the `rx` entry's locations still update and the receiver queues every message too

#### Scenario: Drain in one scan
- **WHEN** three messages wait and the program calls the block in `WHILE rx.NEW DO`
- **THEN** it handles all three in one scan and `QUEUED` is 0

#### Scenario: Queue full
- **WHEN** `DEPTH` is 4 and six messages arrive between two calls
- **THEN** four are queued, `OVERFLOW` is TRUE and `DROPPED` is 2

### Requirement: Requests from the program
`J1939_REQUEST` SHALL send a Request for `PGN` from the network's address. To an address it SHALL be `DONE` with the first message of that PGN from that address that arrives after the Request, SHALL be `DONE` with `LENGTH` 0 on a positive Acknowledgement for that PGN, and SHALL report `ERROR_ID` 12 with `ACK_CODE` (1 NACK, 2 Access Denied, 3 Cannot Respond) when that ECU answers with an Acknowledgement other than ACK for that PGN. To global (255) it SHALL be `DONE` once the Request is on the bus; the answers SHALL reach `J1939_RECEIVE` and config `rx` entries. An answer SHALL also update config `rx` entries for its PGN as any received message does.

#### Scenario: Refused
- **WHEN** the program requests PGN 65300 from address 0 and ECU 0 answers NACK
- **THEN** the block reports `ERROR_ID` 12 with `ACK_CODE` 1

#### Scenario: No answer
- **WHEN** address 7 does not answer within `TIMEOUT`
- **THEN** the block reports `ERROR_ID` 6

### Requirement: Error IDs of the J1939 message blocks
The J1939 message blocks SHALL report `ERROR_ID`:
- 1: the plugin is not loaded, does not offer version 2 of the J1939 block interface, or the network is not running
- 2: no such network
- 3: an input is invalid (`PGN` above 16#3FFFF, `LENGTH` above 1785, `DESTINATION` or `SOURCE` 254, `PRIORITY` above 7, `DEPTH` above 32)
- 4: the PGN is one the network sends itself (`J1939_SEND`)
- 6: not completed within `TIMEOUT`
- 7: the network is bus-off or its interface is down
- 8: cancelled by a PLC stop or a network restart
- 9: no free job slot (32 sends and requests across all networks, apart from the 64 of the trouble code blocks) or receiver (16 per network)
- 10: the network is not a J1939 network
- 11: the network holds no address (`J1939_SEND`, `J1939_REQUEST`)
- 12: the destination refused (`J1939_REQUEST`)
- 14: the transport protocol session was aborted (`J1939_SEND`)

#### Scenario: CANopen network
- **WHEN** `J1939_SEND` is called with the `NETWORK` of a CANopen network
- **THEN** it reports `ERROR_ID` 10 and sends nothing

#### Scenario: Too many receivers
- **WHEN** 16 receivers are open on a network and a 17th is enabled
- **THEN** the 17th reports `ERROR_ID` 9 and tries again while `ENABLE` stays TRUE

### Requirement: J1939 message blocks do not stall the scan
The J1939 message blocks SHALL never wait for CAN traffic, allocate memory or write the log on the PLC scan thread, and SHALL work from several PLC tasks at once with each instance getting its own result. They SHALL reach the plugin as the trouble code blocks do and call `canworks_j1939_api(2)`. The plugin SHALL return version 1 and version 2 tables, so the trouble code blocks keep asking for version 1. A program using a message block on a plugin without version 2 SHALL get `ERROR_ID` 1 from it, and the plugin SHALL log once that the program's library needs a newer plugin, naming both versions. A PLC stop SHALL end every pending job with `ERROR_ID` 8 and close every receiver.

#### Scenario: New library, older plugin
- **WHEN** a program using `J1939_SEND` and `J1939_DM_READ` runs with a plugin that offers only version 1
- **THEN** `J1939_SEND` reports `ERROR_ID` 1, `J1939_DM_READ` works, and the scan time does not change

### Requirement: J1939 ST functions
The library SHALL provide, needing no plugin:
- `J1939_GET_BITS(DATA, START_BIT : UINT, BIT_LENGTH : USINT, SIGNED : BOOL) : LINT` and `J1939_SET_BITS(DATA, START_BIT : UINT, BIT_LENGTH : USINT, VALUE : LINT) : BOOL` (FALSE, writing nothing, when a bit falls outside the array or `BIT_LENGTH` is not 1..64), with `DATA` an in-out `ARRAY[0..1784] OF BYTE`, little-endian as J1939 sends signals, `BIT_LENGTH` 1..64, bits beyond the array read as 0
- `J1939_NAME_MAKE(...) : LWORD` from the NAME fields (`IDENTITY_NUMBER`, `MANUFACTURER_CODE`, `ECU_INSTANCE`, `FUNCTION_INSTANCE`, `ECU_FUNCTION` (`FUNCTION` is an ST keyword), `VEHICLE_SYSTEM`, `VEHICLE_SYSTEM_INSTANCE`, `INDUSTRY_GROUP`, `ARBITRARY_ADDRESS_CAPABLE`) and the function block `J1939_NAME_SPLIT` the other way
Their results SHALL equal the plugin's and the PC tools' packing.

#### Scenario: Signal past byte 8
- **WHEN** a program reads 16 bits at bit 200 of a 40-byte message
- **THEN** it gets bytes 25 and 26 as a little-endian value

#### Scenario: NAME round trip
- **WHEN** a program makes a NAME from fields and splits it again
- **THEN** it gets the same fields back, and the NAME equals the one the config's `ecu.name` with those fields gives

### Requirement: Receivers opened at any time
A `J1939_RECEIVE` opened at any moment, also while the bus thread is updating the network's receivers, SHALL get its queue and receive matching messages within a few bus-thread ticks.

#### Scenario: Two tasks open receivers
- **WHEN** two PLC tasks each open a `J1939_RECEIVE` on the same network in the same millisecond
- **THEN** both receivers become active and each gets its matching messages

### Requirement: Long sends get their own result
A long `J1939_SEND` SHALL end with the result of its own transport session. A late result of a send that already ended (for example by its `TIMEOUT`) SHALL NOT be given to any other send. When the network changes its address and its sockets are reopened, sends in progress SHALL end with `ERROR_ID` 14 at once.

#### Scenario: Timed-out send followed by another
- **WHEN** a 200-byte send to 0x10 ends with `ERROR_ID` 6, and a 200-byte send to 0x20 starts before 0x10's session finishes
- **THEN** the second send ends with the result of its own session to 0x20
