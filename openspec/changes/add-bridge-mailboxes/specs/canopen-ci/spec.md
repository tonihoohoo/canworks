## ADDED Requirements

### Requirement: Mailbox block tests
CI SHALL build the mailbox blocks with STruC++ and run them against a scripted model of the request and receive mailboxes (one call is one poll round), covering the handshake, chunked reads and writes, ticket order with one mailbox and several instances, a skipped waiting instance, receive batches with several receivers, a stalled receiver, cyclic keepalive, ERROR_IDs 20 and 22, and timeouts. CI SHALL test the bridge's mailboxes in `test/bridge/` with a Modbus client on vcan0 (operations, chunks, FIFOs and drops, the 1 s stall rule, the link-stop cleanup, cyclic timing) and SHALL add to the OpenPLC through Modbus integration job one program that runs `CAN_SEND`, `CAN_RECEIVE`, `CO_SDO_READ_STRING` and `J1939_SEND`/`J1939_RECEIVE` against simulated devices. These SHALL run in the existing jobs under their path filters, and the PR SHALL report the CI time against the baseline.

#### Scenario: Integration with blocks
- **WHEN** the integration job runs the block program against a simulated CANopen node and a simulated J1939 ECU
- **THEN** a sent frame is received back by the receiver on the same vcan0, the node's device name is read, and a 40-byte J1939 message makes the round trip
