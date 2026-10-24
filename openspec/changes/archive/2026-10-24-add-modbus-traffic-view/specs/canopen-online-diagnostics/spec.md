## ADDED Requirements

### Requirement: Modbus trace operations
On a bridge the channel SHALL offer `modbus_trace_start`, `modbus_trace_fetch` and `modbus_trace_stop` to any authenticated client, without `allow_changes`. `modbus_trace_start` MAY give `changes_only` (default true) and a list of client addresses or prefixes, and SHALL return the sequence number to fetch after, the bridge's map hash and the buffer size. `modbus_trace_fetch` with a sequence number SHALL return the records recorded after it, in order, at most a requested maximum (default 2000, at most 4000) per answer, with the number the client lost because the buffer wrapped. A Modbus trace SHALL end on `modbus_trace_stop`, on disconnect, or after 10 s without a fetch, and SHALL NOT take a network. A runtime that is not a bridge SHALL answer these operations with "not a bridge".

#### Scenario: Read-only Modbus trace
- **WHEN** `allow_changes` is false and a client starts a Modbus trace
- **THEN** the trace runs, and the records show what the Modbus clients read and wrote

#### Scenario: Only one client's requests
- **WHEN** a client starts a Modbus trace with clients `["192.168.10.20"]` while OpenPLC on 127.0.0.1 and an HMI on 192.168.10.20 poll
- **THEN** the fetched records are the HMI's only

#### Scenario: Forgotten Modbus trace
- **WHEN** a client starts a Modbus trace and stops fetching without disconnecting
- **THEN** the bridge ends that trace after 10 s and stops recording if no other Modbus trace is active

### Requirement: Modbus clients in the status
The status answer of a bridge SHALL list each connected Modbus client with its counters (bridge capability `modbus-bridge`, "Client counters") and the recently closed connections with their close reasons. `canworks-diag status` SHALL print one line per client: address, connected time, requests per second, exceptions by code, refused writes and the last write's range, and one line per recently closed connection with its reason and how long ago it closed.

#### Scenario: Status of a bridge with two clients
- **WHEN** OpenPLC polls the bridge every 10 ms and an HMI reads it every 500 ms, and the user runs `canworks-diag --runtime HOST status`
- **THEN** the bridge part lists both clients with about 100 and 2 requests per second each, and OpenPLC's last write range

### Requirement: Modbus trace in the command-line client
`canworks-diag modbus-trace` SHALL print the bridge's Modbus records as they arrive, one line each: time, client, function, range, values and result; with `--config FILE` the values SHALL be named from that config's register map, and with `--all` every request SHALL be recorded, not only changes. `-o FILE.pcapng` SHALL write them to a pcapng file, `--duration` SHALL stop after that time, and Ctrl-C SHALL stop and still write the file.

#### Scenario: Watching an HMI's writes
- **WHEN** a user runs `canworks-diag --runtime plc.local modbus-trace --config canworks.json` and the HMI writes holding register 12 with 500
- **THEN** a line shows the HMI's address, function 6, holding register 12 named `dio.valve_cmd`, the value 500 and ok
