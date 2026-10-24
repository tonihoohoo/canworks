## ADDED Requirements

### Requirement: Modbus records in a trace
A trace recorded through a bridge's diagnostics channel with Modbus requests on SHALL hold the bridge's Modbus records next to the picked network's CAN frames, ordered by time on one timeline. Modbus records SHALL NOT count as frames in the frame rate, bus load or per-identifier statistics; the statistics SHALL say how many Modbus requests were recorded and how many were skipped as unchanged. A gap in either source (a lost range, an ended Modbus trace) SHALL be marked in the trace.

#### Scenario: Write then RPDO
- **WHEN** OpenPLC writes the holding register of node 6's output and the trace records Modbus requests and network `field`
- **THEN** the Chronological list shows the write and, after it, node 6's RPDO carrying the new value, with their times

#### Scenario: Modbus not in the frame rate
- **WHEN** a trace holds 2000 CAN frames and 300 Modbus records over 10 s
- **THEN** the frame rate reads about 200 frames/s and the statistics say 300 Modbus requests

### Requirement: Modbus decoding with the register map
Each Modbus record SHALL be decoded with the config's register map: the client by its connection's name when an entry of `bridge.connections` has its address, else its address; the range split into the map's values with their names and types (a 32- or 64-bit value over its registers in the config's word order, coils and discrete inputs by their bit names); and the result. An exception SHALL get a hint where the map explains it:
- exception 0x02 on a range past the image: the image's size in registers;
- a start of 30000 or more on input registers, or 40000 or more on holding registers: addresses here start at 0;
- a range that splits a 32- or 64-bit value: which value it cuts;
- exception 0x01 on a write: the client is not in `writers`.

When the bridge's map hash differs from the config's, the records SHALL be shown undecoded with a line saying the config is not the one the bridge runs.

#### Scenario: Named write
- **WHEN** a record is a write of holding registers 12-13 with 0x0000 0x01F4 and the map has `dio.valve_cmd` as a 32-bit value there, high word first
- **THEN** the row reads `HR 12-13 dio.valve_cmd = 500` with the client's connection name

#### Scenario: 40001-style address
- **WHEN** a client reads holding register 40001 and gets exception 0x02
- **THEN** the row shows the exception with the hint that holding registers start at 0 here and the image has N registers

### Requirement: Delay between Modbus and CAN
For a Modbus write, the trace SHALL find, for each value of the write that changed, the first CAN frame after the write on the traced network that carries the new value (an RPDO entry, a J1939 or raw transmit signal decoded with the config), and SHALL give the time from the write's answer to that frame. For a Modbus read, for each value that changed since that client's previous read of it, the trace SHALL find the last CAN frame before the read that carried the value read, and SHALL give the time from that frame to the read's answer. A value bound to another network SHALL say so. A value whose frame is not found within 1 s SHALL say "not seen on the bus". With **Only changes** these delays SHALL be exact, since the first record showing a new value is kept.

#### Scenario: Write to RPDO
- **WHEN** OpenPLC writes `dio.valve_cmd` = 500 at 10.000 s and node 6's RPDO carrying 500 is on the bus at 10.004 s
- **THEN** the write's delay for `dio.valve_cmd` is 4 ms

#### Scenario: TPDO to read
- **WHEN** node 5's TPDO carries a new `rtd.temp` at 20.000 s and the next read of it by OpenPLC is answered at 20.007 s
- **THEN** that read's delay for `rtd.temp` is 7 ms

#### Scenario: Value on another network
- **WHEN** the trace records network `field` and a write changes a value bound to network `drives`
- **THEN** that value's delay says it is on `drives`, not traced

### Requirement: Modbus records in saved traces
Saving a trace with Modbus records as pcapng SHALL write them as a second interface of IPv4 packets, one per request and one per answer, between the client's address and the bridge's port, so a Modbus/TCP dissector decodes them; skipped counts SHALL be kept in packet comments. Opening such a file SHALL bring the records back with their decoding. Saving in a format that has no place for them (ASC, BLF, TRC, candump, CSV) SHALL keep the CAN frames and say that the Modbus records are left out.

#### Scenario: Round trip through pcapng
- **WHEN** a trace with CAN frames and Modbus records is saved as pcapng and opened again
- **THEN** both come back with their times, and the Modbus rows are decoded as before

#### Scenario: Saving as ASC
- **WHEN** the same trace is saved as ASC
- **THEN** the file has the CAN frames, and the save says the Modbus requests are kept in pcapng only
