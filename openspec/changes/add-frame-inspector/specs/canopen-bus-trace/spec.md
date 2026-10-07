## ADDED Requirements

### Requirement: Frame inspector on traces
Any frame of a recorded or opened trace SHALL be explainable with the `canopen-frame-explain` model, using the configuration the trace is decoded with, the trace's bit rate and the SDO context of the trace at that frame. Explaining a frame SHALL work on traces of any size by explaining one frame at a time on the PC.

#### Scenario: Explain a recorded PDO
- **WHEN** a trace holds node 5's TPDO1 and the user explains it
- **THEN** the explanation shows each mapped signal's bits with their PLC addresses and the wire layer at the network's bit rate

### Requirement: SDO conversations
The trace SHALL list SDO conversations: each transfer from its initiate request to its final answer or abort, per node and SDO channel, with object and name, direction, size, value or abort text, number of frames and the time of each step. Segmented and block transfers SHALL be one conversation. A conversation SHALL be shown as a sequence diagram between master and node, each arrow opening its frame's explanation.

#### Scenario: Segmented upload
- **WHEN** the trace holds an 18-byte segmented upload of 1008h:00 from node 5
- **THEN** one conversation lists the initiate request and answer and three segment requests and answers, with the toggle bits and the read string

#### Scenario: Aborted write
- **WHEN** a write to a read-only object is answered with abort 0x06010002
- **THEN** the conversation ends in the abort with the text "attempt to write a read only object"

### Requirement: SYNC cycle view
For a trace with SYNC, the trace SHALL show one SYNC cycle at a time as a timeline: the SYNC, then every frame up to the next SYNC with its time after the SYNC, grouped as synchronous PDOs, other PDOs, SDO and other frames; next to each PDO its configured transmission type and, for synchronous PDOs, whether it came inside the configured SYNC window. The user SHALL be able to step through cycles and jump to the slowest cycle.

#### Scenario: Late TPDO
- **WHEN** the SYNC window is 2 ms and node 5's synchronous TPDO1 comes 2.6 ms after a SYNC
- **THEN** that cycle's timeline marks the TPDO as outside the SYNC window

### Requirement: Boot story
For each boot of a node found in a trace (a boot-up message, or an NMT reset command to it), the trace SHALL show the steps until the node's first PDO after the NMT start: boot-up, each SDO the master reads and writes with its object name and value, the NMT start, the first heartbeat in Operational and the first PDOs, with their times. The master's writes SHALL be compared with the writes the configuration makes at boot (the same list as the network document's boot configuration), and missing, extra, different and refused writes SHALL be marked.

#### Scenario: Refused write in a boot
- **WHEN** the device refuses the write of 1400h:02 during a boot in the trace
- **THEN** the boot story marks that step as refused with the abort text and shows that the node did not get to Operational
