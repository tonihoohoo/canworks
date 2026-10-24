## MODIFIED Requirements

### Requirement: Modbus trace recorder
While at least one diagnostics client traces Modbus, the bridge SHALL record each answered request as one record: the UTC time of the answer in microseconds, the client, the MBAP transaction and unit identifiers, the function, the table, start and count, the values read or written (up to 250 bytes), and the result (ok or the exception code, and whether it was a refused write). It SHALL record nothing while no client traces. Recording SHALL happen after the answer is queued, so it never delays an answer. The bridge SHALL keep at least 4 MiB of records for clients to fetch.

With "changes only" (the default), a request whose client, function, start and count equal an earlier one's, and whose values and result equal that earlier one's, SHALL be counted and not recorded. The comparison SHALL leave out the words the mailboxes change on their own: the cyclic jobs' keepalive holding registers, and the clock words of the receive mailbox and the cyclic job table; a kept record SHALL still carry them. The next record of that kind from that client SHALL carry the number of requests skipped since its predecessor. Exceptions, refused writes and functions 8 and 43 SHALL always be recorded.

#### Scenario: OpenPLC polling with nothing changing
- **WHEN** a client reads input registers 0-49 every 10 ms for 10 s, the values never change, and a trace with changes only runs
- **THEN** one record of that read is kept, and no further one until a value changes; that next record says how many identical reads it skipped

#### Scenario: Nothing recorded without a trace
- **WHEN** no diagnostics client traces Modbus
- **THEN** the bridge records no Modbus records and answers requests as without the recorder

#### Scenario: Exception always recorded
- **WHEN** a client reads input register 30001 every 10 ms on a 40-byte image during a trace with changes only
- **THEN** every one of those requests is recorded with exception 0x02

#### Scenario: Keepalive alone does not make a record
- **WHEN** OpenPLC writes holding registers 3-94 every 20 ms, the only register that changes is a cyclic job's keepalive, and a trace with changes only runs
- **THEN** one record of that write is kept and the following ones are counted; when the valve output in that range changes, that write is recorded with its keepalive value and the number of writes skipped before it

#### Scenario: Mailbox clock alone does not make a record
- **WHEN** a client reads the receive mailbox every 50 ms, no CAN frame is received, and a trace with changes only runs
- **THEN** only the first read is kept, although the clock word differs in each answer

