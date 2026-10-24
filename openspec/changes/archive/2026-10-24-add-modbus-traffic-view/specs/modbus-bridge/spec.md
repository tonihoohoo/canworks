## ADDED Requirements

### Requirement: Client counters
The bridge SHALL count, for every connected Modbus client and from the moment it connected: requests per function code, answers per exception code, writes refused because the client is not in `writers`, and the time, table and register or bit range of its last accepted write. It SHALL keep the number of requests answered in the last 5 s. The counters SHALL be kept whether or not anyone reads them and SHALL NOT delay any answer.

#### Scenario: Counting a polling client
- **WHEN** a writer client sends 100 reads of input registers 0-9 and 100 writes of holding registers 0-3
- **THEN** its counters show 100 requests of function 4, 100 of function 16, no exceptions, and its last write as holding registers 0-3 with its time

#### Scenario: Reader that tries to write
- **WHEN** a client not in `writers` writes holding register 5 three times
- **THEN** its counters show 3 refused writes and 3 answers with exception 0x01

### Requirement: Recently closed clients
When a connection closes, the bridge SHALL keep its address, its counters, how long it was connected and why it closed (closed by the client, idle for 60 s, an incomplete request for 5 s, replies not read, its slot taken by a writer, the per-address limit, not in `readers`, keepalive) for 10 minutes, at most the last 8 connections.

#### Scenario: Client cut for not reading
- **WHEN** a client sends reads without reading its socket until the bridge closes it
- **THEN** the closed list holds that client's address with the reason "replies not read" and its request counts, for 10 minutes

### Requirement: Modbus trace recorder
While at least one diagnostics client traces Modbus, the bridge SHALL record each answered request as one record: the UTC time of the answer in microseconds, the client, the MBAP transaction and unit identifiers, the function, the table, start and count, the values read or written (up to 250 bytes), and the result (ok or the exception code, and whether it was a refused write). It SHALL record nothing while no client traces. Recording SHALL happen after the answer is queued, so it never delays an answer. The bridge SHALL keep at least 4 MiB of records for clients to fetch.

With "changes only" (the default), a request whose client, function, start and count equal an earlier one's, and whose values and result equal that earlier one's, SHALL be counted and not recorded; the next record of that kind from that client SHALL carry the number of requests skipped since its predecessor. Exceptions, refused writes and functions 8 and 43 SHALL always be recorded.

#### Scenario: OpenPLC polling with nothing changing
- **WHEN** a client reads input registers 0-49 every 10 ms for 10 s, the values never change, and a trace with changes only runs
- **THEN** one record of that read is kept, and no further one until a value changes; that next record says how many identical reads it skipped

#### Scenario: Nothing recorded without a trace
- **WHEN** no diagnostics client traces Modbus
- **THEN** the bridge records no Modbus records and answers requests as without the recorder

#### Scenario: Exception always recorded
- **WHEN** a client reads input register 30001 every 10 ms on a 40-byte image during a trace with changes only
- **THEN** every one of those requests is recorded with exception 0x02
