## MODIFIED Requirements

### Requirement: Mailboxes section
A bridge config MAY have a `mailboxes` object inside `bridge` with `requests` (0-4, default 1), `receive` (default true), `receive_blocks` (1 or 2, default 1), `cyclic_jobs` (0-16, default 4), `network_info` (default true), `input_location` and `output_location`. The bridge SHALL then serve, in one contiguous input area from `input_location`: one 72-register response block per request mailbox, the receive mailbox of 120 registers per receive block, one 18-register network info block for each of the first 8 networks, and, with cyclic jobs, the cyclic job table of a tick register and 4 registers per job; and in one contiguous output area from `output_location`: one 72-register request block per request mailbox, the 3-register receive acknowledgement and one keepalive register per cyclic job. Each receive block SHALL be its own block of the map, so a client reads it with one request. Both locations SHALL be given and SHALL start at an even byte; a config without them SHALL be refused with a message that Pack for Modbus sets them. A config whose mailbox areas overlap another location SHALL be refused, naming both. `receive_blocks` other than 1 or 2 SHALL be refused.

#### Scenario: Default mailboxes in an OpenPLC config
- **WHEN** an `openplc` bridge config with two networks has `"mailboxes": {}` and Pack for Modbus runs
- **THEN** the pack sets both locations after the bridge's other blocks, and the bridge serves one request mailbox, the receive mailbox of one block, two network info blocks and four cyclic job slots there and logs their register ranges at start

#### Scenario: Overlap
- **WHEN** `output_location` is `%QB20` and an RPDO entry is mapped at `%QW40`
- **THEN** the config is refused, naming the RPDO entry and the request mailbox

#### Scenario: Two receive blocks
- **WHEN** a config has `"receive_blocks": 2`
- **THEN** the receive mailbox takes 240 input registers as two map blocks of 120, the OpenPLC remote device reads them in two groups, and the network info blocks follow them

### Requirement: Receive mailbox
With `receive` on, the bridge SHALL keep a FIFO per open receiver (CAN: `DEPTH` 1-256, default 32, matching id and mask as `CAN_RECEIVE` defines; J1939: `DEPTH` 1-32, default 4, matching PGN, source and destination as `J1939_RECEIVE` defines; EMCY: its own position in the network's EMCY history of 64 messages, from the oldest or, with skip old, from the next one) and SHALL show the records in batches in the receive mailbox: a 25-word header with the batch sequence, the set of receivers that have records in it, the number of record words, the bridge's millisecond tick when the batch was built, the generation of every receiver number (0 while closed, changed each time the number is opened) and the batch time (the UTC receive time in microseconds of the batch's first record), then records in arrival order across all receive blocks. Every record SHALL carry its receiver, kind and flags, the records still queued for that receiver and its dropped count; a CAN record (10 words) SHALL add the identifier, format, DLC and 8 data bytes, a J1939 record (12 words) the PGN, addresses, priority, length and the first 8 data bytes, and an EMCY record (12 words) its own UTC receive time in microseconds, node, error register, error code and 5 bytes. A batch SHALL hold as many records as fit in the receive blocks' record words (95 words with one block, 215 with two). RX_OPEN SHALL answer the receiver number, its generation and the tick, so a block can tell its own receiver's records from those of an earlier receiver with the same number. The bridge SHALL show the next batch only after the receive acknowledgement names the current batch with no receiver still pending, and SHALL then fill it at once from the FIFOs. A record arriving at a full FIFO SHALL be dropped and counted for that receiver. Frames and messages the bridge sends itself SHALL NOT be queued. At most 32 receivers SHALL be open at once; RX_OPEN beyond that SHALL end with the family's "no free receiver" ID.

#### Scenario: Burst between two polls
- **WHEN** 20 matching frames arrive within 2 ms for one CAN receiver with `DEPTH` 32
- **THEN** the program receives all 20 in arrival order over the next batches and none is counted as dropped

#### Scenario: Two receivers in one batch
- **WHEN** a CAN receiver and an EMCY receiver both have records
- **THEN** one batch carries both, with both receivers marked present, and the next batch waits until the acknowledgement clears both

#### Scenario: Full batches
- **WHEN** one CAN receiver has 30 frames queued
- **THEN** a batch with one receive block carries 9 of them and a batch with two receive blocks 21, and the batch time is the first frame's receive time
