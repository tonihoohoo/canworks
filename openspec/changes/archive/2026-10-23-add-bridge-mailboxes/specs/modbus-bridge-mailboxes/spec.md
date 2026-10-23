## ADDED Requirements

### Requirement: Mailboxes section
A bridge config MAY have a `mailboxes` object inside `bridge` with `requests` (0-4, default 1), `receive` (default true), `cyclic_jobs` (0-16, default 4), `network_info` (default true), `input_location` and `output_location`. The bridge SHALL then serve, in one contiguous input area from `input_location`: one 72-register response block per request mailbox, the 120-register receive mailbox, one 18-register network info block for each of the first 8 networks, and, with cyclic jobs, the cyclic job table of a tick register and 4 registers per job; and in one contiguous output area from `output_location`: one 72-register request block per request mailbox, the 3-register receive acknowledgement and one keepalive register per cyclic job. Both locations SHALL be given and SHALL start at an even byte; a config without them SHALL be refused with a message that Pack for Modbus sets them. A config whose mailbox areas overlap another location SHALL be refused, naming both.

#### Scenario: Default mailboxes in an OpenPLC config
- **WHEN** an `openplc` bridge config with two networks has `"mailboxes": {}` and Pack for Modbus runs
- **THEN** the pack sets both locations after the bridge's other blocks, and the bridge serves one request mailbox, the receive mailbox, two network info blocks and four cyclic job slots there and logs their register ranges at start

#### Scenario: Overlap
- **WHEN** `output_location` is `%QB20` and an RPDO entry is mapped at `%QW40`
- **THEN** the config is refused, naming the RPDO entry and the request mailbox

### Requirement: Request mailbox handshake
Each request mailbox SHALL start one operation each time its request counter (request word 0) changes to a value other than its response counter echo, with the operation, network index, arguments and data written in the same request. The response SHALL echo the counter with state busy while the operation runs and state done or error with an ERROR_ID when it ends, and SHALL keep that until the next counter change. Rewriting the same request SHALL start nothing. A mailbox SHALL run one operation at a time; a counter change while busy SHALL be taken when the running operation ends. Operations of different mailboxes SHALL run in parallel. After the bridge starts, the first request words a mailbox gets SHALL only set its counter: a request in them SHALL NOT run and SHALL end with ERROR_ID 8 (cancelled), so a bridge restart never repeats the PLC's last request. An operation SHALL end with ERROR_ID 3 of its family when its arguments are invalid, and with the family's "no such network" ID when the network index does not exist.

#### Scenario: One request
- **WHEN** a client writes counter 7 with CAN_SEND on network 0, id 0x510, DLC 2, data 01 02
- **THEN** the frame 0x510 01 02 goes out once, the response shows counter 7 busy, then counter 7 done once the adapter confirmed the frame

#### Scenario: Bridge restart
- **WHEN** the bridge restarts while the PLC's last request (counter 7, CAN_SEND) is still in the holding registers
- **THEN** no frame goes out and the response shows counter 7 with error 8; the PLC's next request runs

#### Scenario: Same request rewritten every poll
- **WHEN** the client keeps writing the same request block every 10 ms
- **THEN** the frame is sent only once

### Requirement: Data in chunks
Each request mailbox SHALL have a staging buffer and a result buffer of 1785 bytes. STAGE SHALL copy the request's data bytes to the staging buffer at the given offset. SDO_WRITE and J1939_SEND SHALL take their data from the request itself when the length is at most 128 bytes, and from the staging buffer otherwise. An operation with a result longer than 128 bytes SHALL put its first 128 bytes into the response and keep the whole result, which FETCH SHALL return 128 bytes at a time from the given offset. The staging buffer SHALL be cleared by any operation other than STAGE that does not use it, and the result buffer by any operation other than FETCH.

#### Scenario: Long SDO read
- **WHEN** a client reads object 0x1008:0 of a node whose device name is 300 bytes long
- **THEN** the SDO_READ response is done with size 300 and the first 128 bytes, and two FETCHes at offsets 128 and 256 return the rest

#### Scenario: Long SDO write
- **WHEN** a client stages 600 bytes in five STAGE requests and then sends SDO_WRITE with size 600
- **THEN** one segmented or block SDO download of those 600 bytes goes to the node

### Requirement: Mailbox operations
The request mailboxes SHALL offer, on the network named in the request:
- SDO_READ and SDO_WRITE of any size up to 1785 bytes on a node of a CANopen master network, through the same queue, timeout, node availability rules and abort codes as the SDO bridge registers and `sdo_bridge_write`;
- CAN_SEND of one frame on any network, done when the adapter confirms it, with the protocol identifier guard and `raw.program_override_protocol` of the network;
- CYCLIC_SET and CYCLIC_STOP of a cyclic frame job;
- RX_OPEN and RX_CLOSE of a CAN, J1939 or EMCY receiver, and RX_FETCH of a receiver's held long message;
- J1939_SEND and J1939_REQUEST from the network's claimed address, with the transport protocol, PGN guard and acknowledgement handling of a J1939 network;
- DM_READ (the latest DM1 from a source without sending anything, or DM2 by request) and DM_CLEAR (DM3 or DM11);
- FIND_ECU by NAME and mask in the network's address table.
Each operation's ERROR_ID SHALL use the numbering of the matching block family of `bridge-plc-blocks`.

#### Scenario: Request a PGN
- **WHEN** a client sends J1939_REQUEST for PGN 65259 to address 0 on a J1939 network and ECU 0 answers with 30 bytes
- **THEN** the response is done with source 0, length 30 and the 30 bytes

#### Scenario: Guarded identifier
- **WHEN** node 5 has an RPDO on 0x205 and a client sends CAN_SEND with id 0x205 on that network
- **THEN** the response ends with error and ERROR_ID 4, and nothing is sent

### Requirement: Receive mailbox
With `receive` on, the bridge SHALL keep a FIFO per open receiver (CAN: `DEPTH` 1-256, default 32, matching id and mask as `CAN_RECEIVE` defines; J1939: `DEPTH` 1-32, default 4, matching PGN, source and destination as `J1939_RECEIVE` defines; EMCY: its own position in the network's EMCY history of 64 messages, from the oldest or, with skip old, from the next one) and SHALL show the records in batches in the receive mailbox: a batch sequence, the set of receivers that have records in it, the number of record words, the bridge's millisecond tick when the batch was built, the generation of every receiver number (0 while closed, changed each time the number is opened), and records in arrival order, each with its receiver, kind and flags, the records still queued for that receiver, its dropped count and its UTC receive time in microseconds. RX_OPEN SHALL answer the receiver number, its generation and the tick, so a block can tell its own receiver's records from those of an earlier receiver with the same number. The bridge SHALL show the next batch only after the receive acknowledgement names the current batch with no receiver still pending, and SHALL then fill it at once from the FIFOs. A record arriving at a full FIFO SHALL be dropped and counted for that receiver. Frames and messages the bridge sends itself SHALL NOT be queued. At most 32 receivers SHALL be open at once; RX_OPEN beyond that SHALL end with the family's "no free receiver" ID.

#### Scenario: Burst between two polls
- **WHEN** 20 matching frames arrive within 2 ms for one CAN receiver with `DEPTH` 32
- **THEN** the program receives all 20 in arrival order over the next batches and none is counted as dropped

#### Scenario: Two receivers in one batch
- **WHEN** a CAN receiver and an EMCY receiver both have records
- **THEN** one batch carries both, with both receivers marked present, and the next batch waits until the acknowledgement clears both

### Requirement: Stalled receivers
When a batch is not acknowledged with no receivers pending within 1 s of being shown (5 s while a pending receiver has an RX_FETCH in progress), the bridge SHALL close the receivers still pending in the last acknowledgement, log one line naming their numbers, and show the next batch. A closed receiver's next RX_FETCH or record SHALL report the family's "cancelled" ID.

#### Scenario: Block no longer called
- **WHEN** a program stops calling one of two `CAN_RECEIVE` instances while frames for both keep arriving
- **THEN** within about 1 s the bridge closes the stalled receiver and the other instance keeps receiving

### Requirement: Long J1939 messages in receivers
A J1939 message longer than 8 bytes SHALL be shown as one record with the long flag, its length and its first 8 bytes, and the whole message SHALL be held for its receiver until the batch that showed it is acknowledged. RX_FETCH SHALL make the held message from the given offset on the mailbox's result: its length as the first result and its first 128 bytes in the response, the rest by FETCH. A batch SHALL hold at most one long record per receiver.

#### Scenario: 40-byte message
- **WHEN** ECU 0 sends PGN 65282 with 40 bytes by BAM and a J1939 receiver for 65282 is open
- **THEN** the batch shows one long record with length 40, and RX_FETCH at offset 0 returns the 40 bytes

### Requirement: Network info
With `network_info` on, the bridge SHALL publish for each of the first 8 networks, at least every 100 ms: the CAN state (0 error active, 1 warning, 2 error passive, 3 bus-off, 4 interface down or missing), the bus load in percent over the last second, the TX and RX error counters, and 32-bit counts of bus-offs, received frames, sent frames and error frames; for a J1939 network also the address claim state (0 claiming, 1 claimed, 2 cannot claim, 3 no bus), the held address (254 while none), the network's NAME and the number of ECUs in its address table; for a network without a J1939 view 0xFF as the address claim state and the J1939 ERROR_ID as the address (1 not running, 10 not a J1939 network); and an update counter.

#### Scenario: Bus load
- **WHEN** network 0 carries about 40 % bus load
- **THEN** its network info shows a bus load near 40 and the update counter changes at least every 100 ms

### Requirement: Cyclic jobs
CYCLIC_SET with job 0xFFFF SHALL start a new job in a free slot of the cyclic job table and return its number; with a job number it SHALL change that job's data, DLC and period from its next send. The bridge SHALL send each active job's frame every period (1 ms to 60 s) from its own timer, whatever the poll and scan times, and SHALL show per job its state, ERROR_ID, generation (changed each time the slot gets a new job) and the frames sent since it started, after a tick register. While the network is bus-off or its interface is down a job SHALL stay and show the family's bus-off ID; it SHALL clear by itself when the bus is back. A job whose keepalive register has not changed for 1 s SHALL be stopped and its slot freed. CYCLIC_SET beyond the configured number of jobs SHALL end with the family's "no free job" ID.

#### Scenario: Faster than the poll
- **WHEN** a job runs with a 5 ms period on a bridge polled every 10 ms
- **THEN** the frame appears on the bus about every 5 ms and the job's count grows by about 2 per poll

#### Scenario: Forgotten job
- **WHEN** the program stops writing a job's keepalive
- **THEN** within about 1 s the frame stops and the slot is free

### Requirement: Program resources follow the link
When the PLC link header enters stopped or mismatch, or the output watchdog fires, the bridge SHALL end every busy mailbox operation with the family's "cancelled" ID, stop every cyclic job, close every receiver and clear the receive mailbox. A network restart SHALL do the same for that network's operations, jobs and receivers. The bridge SHALL log one line saying how many it ended.

#### Scenario: PLC stop
- **WHEN** a program has an open CAN receiver and a cyclic job, and the PLC is stopped
- **THEN** the cyclic frame stops within one period after the stop round arrives, the receiver is closed, and after the next start the blocks open them again
