## MODIFIED Requirements

### Requirement: No jobs for the removed OpenPLC plugin
CI SHALL NOT build or test an OpenPLC runtime plugin, an editor hook or a modified runtime image: no job builds against runtime sources, the only job that checks out the runtime's sources is the `engine` job, for the OpenPLC integration test's Modbus master, and releases publish no local runtime image. The PR that removes them SHALL state the wall and summed job time against the median of the last five green `main` runs, and neither SHALL be higher.

#### Scenario: Release
- **WHEN** a `deploy-v` release runs
- **THEN** it publishes the wheel, the library, the scripts and the bridge image, and no `canworks-local-runtime` image

### Requirement: Mailbox block tests
CI SHALL build the mailbox blocks with STruC++ and run them against a scripted model of the request and receive mailboxes (one call is one poll round), covering the handshake, chunked reads and writes, ticket order with one mailbox and several instances, a skipped waiting instance, receive batches with several receivers, a stalled receiver, cyclic keepalive, ERROR_IDs 20 and 22, and timeouts. CI SHALL test the bridge's mailboxes in `test/bridge/` against a scripted engine (operations, chunks, FIFOs and drops, long J1939 messages fetched in parts, the 1 s stall rule, the link-stop cleanup, cyclic jobs and keepalive) and SHALL add to the OpenPLC integration job, which runs the pinned runtime's own Modbus master against the bridge, an SDO read through a request mailbox and a CAN receiver's frames through the receive mailbox from the simulated nodes, written and read as the blocks do. The ST tests SHALL also build the PLC link file `--export-modbus-map OUT.st` writes for another PLC together with the library. These SHALL run in the existing jobs under their path filters, and the PR SHALL report the CI time against the baseline.

#### Scenario: Integration with blocks
- **WHEN** the integration job runs against the example's simulated CANopen nodes
- **THEN** an SDO read through the request mailbox returns the node's object, a CAN receiver for a node's TPDO gets its frames in the receive mailbox, and the next batch comes after the acknowledgement
