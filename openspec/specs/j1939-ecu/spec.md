# j1939-ecu Specification

## Purpose
How the bridge runs a J1939 ECU on a SocketCAN interface: address claim, receiving and sending PGNs to and from the bridge's byte image, requests, receive supervision, and recovery when the bus goes away.

## Requirements

### Requirement: Address claim
At start a J1939 network SHALL claim `ecu.address` with its NAME, answer Request for Address Claimed, and defend the address against a claim with a higher NAME. Against a lower NAME it SHALL move to the next free address in `address_range` when arbitrary-address-capable, and otherwise send Cannot Claim and stop sending. It SHALL send no other message before its claim has stood for 250 ms.

#### Scenario: Free address
- **WHEN** the network starts on a bus where no ECU uses address 128
- **THEN** it sends Address Claimed from 128, and after 250 ms starts sending its TX PGNs from 128

#### Scenario: Lost to a lower NAME with a range
- **WHEN** another ECU with a lower NAME claims 128 and `address_range` is [128, 135]
- **THEN** the network claims 129 (or the next free address), sets `address_location` to it, and continues sending from it

#### Scenario: Lost without a range
- **WHEN** another ECU with a lower NAME claims 128 and the NAME is not arbitrary-address-capable
- **THEN** the network sends Cannot Claim from 254, sends nothing else, and `state_location` shows "cannot claim"

### Requirement: Claim state to the PLC
`state_location` SHALL hold 0 (claiming), 1 (claimed), 2 (cannot claim) or 3 (no bus), and `address_location` the current source address, or 254 while none is held.

#### Scenario: Program reads its address
- **WHEN** the network has claimed 129 after a contention
- **THEN** the PLC program reads 1 at `state_location` and 129 at `address_location`

### Requirement: Receive PGNs into the PLC
For each `rx` entry, every matching message (multi-packet included) SHALL update its signals' `%I` locations by the next scan, as raw integers sign-extended when `signed`. A raw value of all ones (not available) or all ones minus one (error) for signals of 2 bits or more SHALL set `valid_location` FALSE and leave the value location unchanged.

#### Scenario: Pressure from an ECU
- **WHEN** ECU 0 sends PGN 65280 with bytes 0-1 = 0x04D2 and the config maps a 16-bit little-endian signal at start bit 0 to `%IW200`
- **THEN** the program reads 1234 at `%IW200` and TRUE at its `valid_location`

#### Scenario: Not available
- **WHEN** the same signal arrives as 0xFFFF
- **THEN** `valid_location` reads FALSE and `%IW200` keeps its previous value

#### Scenario: Multi-packet message
- **WHEN** a 40-byte PGN is sent with BAM and the config maps a signal in byte 30
- **THEN** the program reads the signal's value after the transfer completes

### Requirement: Send PGNs from the PLC
For each `tx` entry the network SHALL send the PGN with its signals taken from the `%Q` snapshot of the last finished scan, unused bits set to 1, every `period_ms`, and, when `period_ms` is 0, when a signal value changes (no faster than `min_gap_ms`). Messages longer than 8 bytes SHALL go out with the J1939 transport protocol.

#### Scenario: Periodic setpoint
- **WHEN** `%QW200` holds 500 and the `tx` entry for PGN 65281 has `period_ms` 100
- **THEN** the bus carries PGN 65281 from the claimed address about every 100 ms with bytes 0-1 = 0x01F4 and bytes 2-7 = 0xFF

#### Scenario: On change
- **WHEN** a `tx` entry has `period_ms` 0 and the program changes its signal once
- **THEN** the PGN is sent once after that scan and not again until a value changes or it is requested

### Requirement: Answer requests
The network SHALL answer a Request (PGN 59904) for any of its TX PGNs, sent to it or to global, with the current values, and SHALL answer requests for PGNs it does not send, when sent to its address, with a NACK.

#### Scenario: Requested on demand
- **WHEN** ECU 3 requests PGN 65281 from the network's address
- **THEN** the network sends PGN 65281 to ECU 3 (or global for PDU2) within 200 ms

#### Scenario: Unknown PGN
- **WHEN** ECU 3 requests PGN 65290, which the network does not send, from its address
- **THEN** the network answers with an acknowledgement (PGN 59392) NACK for 65290

### Requirement: Send periodic requests
For each `requests` entry the network SHALL send a Request for the PGN to the destination every `period_ms`, and the answer SHALL be handled like any received message.

#### Scenario: Component data on request
- **WHEN** a request entry asks ECU 0 for PGN 65282 every 1000 ms and an `rx` entry maps PGN 65282
- **THEN** the program's locations for PGN 65282 update about once per second

### Requirement: Receive supervision
An `rx` entry with `timeout_ms` above 0 SHALL set its `status_location` FALSE when no matching message has arrived for `timeout_ms`, and TRUE again on the next one; signal values SHALL hold their last value while timed out.

#### Scenario: ECU unplugged
- **WHEN** PGN 65280 with `timeout_ms` 300 stops arriving
- **THEN** about 300 ms later its `status_location` reads FALSE and `%IW200` holds its last value

### Requirement: Kernel J1939 required
A J1939 network SHALL use the Linux kernel J1939 protocol on its interface. When the kernel has no J1939 support, that network SHALL not start and SHALL log a line naming the `can-j1939` module; other networks SHALL run, and the network's `state_location` SHALL read 3.

#### Scenario: Module not loaded
- **WHEN** a config with a CANopen network on `can0` and a J1939 network on `can1` starts on a host without the `can-j1939` module loaded
- **THEN** the CANopen network runs, and the log says the J1939 network `machine` needs the can-j1939 kernel module

### Requirement: Bus loss and recovery
When its interface goes down, is unplugged or reaches bus-off, a J1939 network SHALL set `state_location` to 3, hold inputs, and on recovery claim its address again before sending.

#### Scenario: Adapter replugged
- **WHEN** the slcan adapter of a J1939 network is unplugged and plugged in again
- **THEN** the network re-creates the interface, claims its address again, and resumes sending

### Requirement: Request replies are rate-limited
The network SHALL answer Requests for the same PGN from the same requester at most once every 50 ms; Requests in between SHALL be ignored. Before sending Cannot Claim in answer to a Request for Address Claimed, the network SHALL wait a pseudo-random 0 to 153 ms.

#### Scenario: Request flood
- **WHEN** ECU 3 requests PGN 65281 every 5 ms
- **THEN** the network answers at most every 50 ms

### Requirement: Failed sends stay pending
An on-change send of a TX PGN that the interface refuses SHALL NOT count as sent: the PGN SHALL be sent with its current values once the interface takes frames again.

#### Scenario: Interface busy on a change
- **WHEN** the program changes a TX PGN's signal while the interface's transmit queue is full
- **THEN** the PGN with the new value goes out once the queue has room

### Requirement: Request replies and on-change messages
Answering a Request for a destination-specific message to the requester SHALL NOT count as sending it to the message's own destination: an on-change message whose value changed SHALL still be sent to its configured destination. Requests SHALL NOT be answered before the first PLC scan has written the outputs.

#### Scenario: Request before the change is sent
- **WHEN** an on-change message to 0x20 changes value and ECU 0x30 sends a Request for it before the next send
- **THEN** 0x30 gets the reply and 0x20 also gets the new value

#### Scenario: Request before the first scan
- **WHEN** a Request for a transmitted message arrives after the address is claimed but before the first PLC scan
- **THEN** no reply is sent

### Requirement: Signal valid bits on bus loss
When the bus is lost, every received signal's valid bit SHALL go FALSE along with the message status bits.

#### Scenario: Interface down
- **WHEN** a received PGN has signals with `valid_location` and the interface goes down
- **THEN** the valid bits are FALSE

### Requirement: Not-available values
Signed signals SHALL NOT be checked for not-available or error values. Unsigned 8, 16 and 32-bit signals SHALL use the J1939-71 ranges for error and not available; other lengths use all ones and all ones minus one. The bridge and the PC simulator SHALL follow the same rule.

#### Scenario: Signed -1
- **WHEN** a signed 16-bit signal reads 0xFFFF
- **THEN** the bridge and the simulator both treat it as -1, valid

#### Scenario: Unsigned error range
- **WHEN** an unsigned 16-bit signal reads 0xFE50
- **THEN** it is treated as an error value

### Requirement: Request answers
A Request to the global address for a PDU1 PGN SHALL be answered to the global address, and a destination-specific Request to the requester, in the bridge and the PC simulator. A `J1939_REQUEST` SHALL complete only on an answer addressed to the PLC's address or global.

#### Scenario: Global request
- **WHEN** another ECU sends a global Request for an on-change PDU1 PGN the PLC sends
- **THEN** the answer goes to the global address

### Requirement: Receive counter
An `rx` entry with `counter_location` SHALL increment it, wrapping from 65535 to 0, for every message the entry takes (after its source filter), and SHALL write it to the image together with that message's signal values. A message sent with the transport protocol SHALL count once, when it is complete. The counter SHALL start at 0 when the bridge starts and SHALL NOT be reset by a receive timeout, an address claim or the bus going down.

#### Scenario: Messages within one poll
- **WHEN** PGN 65280 from source 0 has `"counter_location": "%IW212"`, arrives every 10 ms and a Modbus client polls every 100 ms
- **THEN** the input register for `%IW212` grows by about 10 between polls

#### Scenario: Other source not counted
- **WHEN** the entry has `source` 0 and source 3 sends PGN 65280
- **THEN** `%IW212` does not change

#### Scenario: Multi-packet message
- **WHEN** a 20-byte message for the entry arrives over the transport protocol in 3 packets
- **THEN** `%IW212` grows by one, once the message is complete
