# canopen-pdo-io Specification

## Purpose
Connects CANopen process data to the PLC program: every PDO-mapped object is bound to an explicit IEC location and exchanged with the PLC I/O image once per scan cycle.

## Requirements

### Requirement: Explicit IEC location per PDO entry
Each PDO entry in the configuration SHALL name its object index, subindex, and data type, and SHALL give one explicit IEC location. Entries received from a slave (RPDO on the master) SHALL map to input locations (`%IX`, `%IB`, `%IW`, `%ID`, `%IL`). Entries sent to a slave (TPDO on the master) SHALL map to output locations (`%QX`, `%QB`, `%QW`, `%QD`, `%QL`). Addresses SHALL NOT be assigned automatically.

#### Scenario: Entry mapped to a matching location
- **WHEN** a slave-to-master UNSIGNED16 entry is configured with `iec_location` `%IW100`
- **THEN** the value received in that PDO appears in `%IW100`

#### Scenario: Direction or size mismatch
- **WHEN** an entry received from a slave is given an output location, or an entry's data type does not fit the size of its IEC location
- **THEN** the plugin rejects the configuration and names the node ID, the object, and the location

#### Scenario: Overlapping locations
- **WHEN** two PDO entries map to the same or overlapping IEC locations
- **THEN** the plugin rejects the configuration and names both entries

#### Scenario: Location outside the image
- **WHEN** an entry's IEC location lies outside the runtime's I/O image size
- **THEN** the plugin rejects the configuration and names the entry and the location

### Requirement: Exchange once per scan cycle
The plugin SHALL copy the latest received PDO values into their input locations once per PLC scan cycle, before the program runs. It SHALL copy the output locations into the PDOs sent to slaves once per scan cycle, after the program has run. Within one scan cycle, the program SHALL see a consistent set of input values that does not change while it runs.

#### Scenario: Ping-pong round trip
- **WHEN** the tutorial slave on `vcan0` sends a counter value in a PDO mapped to `%IW100`, and the PLC program writes `%IW100 + 1` to `%QW100`, which is mapped to the slave's receive PDO
- **THEN** the slave receives the incremented value, and the counter keeps increasing on every exchange

#### Scenario: Inputs stable during a scan
- **WHEN** a new PDO arrives while the PLC program is running
- **THEN** the program sees the new value no earlier than the next scan cycle

### Requirement: No blocking in the scan path
The plugin's per-scan I/O copy SHALL NOT allocate memory, perform file I/O, log, or wait on CAN traffic.

#### Scenario: Bus traffic does not stall the scan
- **WHEN** the CAN bus is saturated or a slave stops answering
- **THEN** the PLC scan cycle time stays within its configured period

### Requirement: EDS data-type and access-type check
At load the plugin SHALL check every PDO entry and every startup SDO against the node's EDS. The entry's `type` SHALL equal the object's `DataType` in the EDS. An entry in `rx_pdos` (written by the master) SHALL target an object the slave can receive in a PDO (`AccessType` `wo`, `rw`, `rww`). Every startup SDO SHALL target an object writable over SDO (`wo`, `rw`, `rwr`, `rww`). An entry in `tx_pdos` (sent by the slave) SHALL target an object whose `AccessType` allows reading (`ro`, `rw`, `rwr`, `const`). A failed check SHALL reject the configuration and leave the plugin inactive.

#### Scenario: Type mismatch
- **WHEN** an entry says `type: "UNSIGNED16"` for an object the EDS declares as `UNSIGNED32`
- **THEN** the config is rejected with an error naming the node ID, the index and subindex, and both types

#### Scenario: Master writes a read-only object
- **WHEN** an `rx_pdos` entry or a startup SDO targets an object with `AccessType=ro`
- **THEN** the config is rejected with an error naming the node ID, the index and subindex, and the access type

#### Scenario: Ping-pong config passes
- **WHEN** the plugin loads the ping-pong example against the tutorial slave's EDS
- **THEN** every check passes and the plugin starts

### Requirement: PDO communication settings
Each PDO in `tx_pdos` MAY give `inhibit_time_us`, `event_timer_ms` and `sync_start`; each PDO in `rx_pdos` MAY give `event_timer_ms`; any PDO MAY give `cob_id` as `"auto"`. The plugin SHALL configure the node's PDO communication object accordingly: inhibit time in sub-index 3 (100 µs units), event timer in sub-index 5 (on an RPDO the node's deadline monitor), SYNC start value in sub-index 6. A field left out SHALL write nothing, so the node keeps its EDS value. With `"auto"`, the COB-ID SHALL be the CiA 301 default for PDOs 1-4, and for higher PDOs a COB-ID outside every configured node's predefined set and unused in the config, logged at load. The plugin SHALL reject an `inhibit_time_us` that is not a multiple of 100, a `sync_start` outside 0-240 or on a PDO whose transmission type is not 1-240, and any of these fields on the wrong PDO kind, naming the node, the PDO and the field.

#### Scenario: Inhibit time on a node's TPDO
- **WHEN** node 5's first `tx_pdos` entry has transmission type 255 and `"inhibit_time_us": 10000`
- **THEN** node 5's 0x1800 sub 3 is 100 and the node sends that PDO at most every 10 ms

#### Scenario: Event timer on a node's RPDO
- **WHEN** node 23's first `rx_pdos` entry has `"event_timer_ms": 500`
- **THEN** the configuration loads, node 23's 0x1400 sub 5 is 500, and the plugin writes it itself after dcfgen's downloads

#### Scenario: Automatic COB-ID for PDO 5
- **WHEN** node 2 has a TPDO numbered 5 with `"cob_id": "auto"` and the config has nodes 2 and 3
- **THEN** the PDO gets a COB-ID that is not 0x180-0x57F + 2 or + 3 and not used by another PDO, and the log names it

#### Scenario: Field left out
- **WHEN** a TPDO gives no `inhibit_time_us`
- **THEN** nothing is written to its sub-index 3

#### Scenario: Wrong PDO kind
- **WHEN** an `rx_pdos` entry gives `inhibit_time_us` or `sync_start`
- **THEN** the configuration is rejected and the error names the node, the PDO and the field

### Requirement: EDS check of PDO communication settings
At load the plugin SHALL check every set PDO communication field (`cob_id`, `transmission`, `inhibit_time_us`, `event_timer_ms`, `sync_start`) against the node's EDS. The sub-index SHALL exist in the PDO's communication object (0x1400+n-1 or 0x1800+n-1), and it SHALL be writable unless the value equals the EDS default. Otherwise the configuration SHALL be rejected with the node, the PDO, the field and the EDS access type named.

#### Scenario: Read-only transmission type
- **WHEN** node 23's EDS marks 0x1400 sub 2 `ro` with default 255 and the config sets RPDO 1 `transmission` to 1
- **THEN** the configuration is rejected naming node 23, RPDO 1, `transmission` and `ro`, instead of the node failing boot with error status J

#### Scenario: Value equal to a read-only default
- **WHEN** the same RPDO sets `transmission` to 255
- **THEN** the configuration loads and nothing is written to 0x1400 sub 2

#### Scenario: Sub-index missing from the EDS
- **WHEN** a TPDO sets `inhibit_time_us` and the node's EDS has no 0x1800 sub 3
- **THEN** the configuration is rejected and the error says the EDS does not define it

### Requirement: PDO mapping written by the config or kept by the device
Each PDO in `tx_pdos` and `rx_pdos` MAY give `mapping` as `"config"` or `"device"`. With `"config"` the master SHALL write the PDO's mapping object from `entries` during node configuration. With `"device"` the master SHALL NOT write the mapping object, and the PDO SHALL carry the mapping that the node's EDS gives as default. When `mapping` is left out, it SHALL be `"device"` if the PDO's mapping object in the EDS is not writable (sub-index 0, or any sub-index from 1 to the default number of entries, has access type `ro` or `const`), and `"config"` otherwise. At load the plugin SHALL reject `"config"` on a PDO whose mapping object is not writable, and `"device"` on a PDO whose EDS has no `DefaultValue` on sub-index 0 or on a sub-index up to that number, naming the node, the PDO and the sub-index.

#### Scenario: Fixed mapping detected from the EDS
- **WHEN** node 4's EDS marks 0x1A00 sub-indices 0-2 `ro` with defaults 2, 0x60000108 and 0x60000208, and the config's TPDO 1 gives no `mapping`
- **THEN** the configuration loads, the log says TPDO 1 of node 4 uses the device mapping, no SDO to 0x1A00 is sent at boot, and node 4 becomes OPERATIONAL

#### Scenario: Config mapping on a fixed PDO
- **WHEN** the same TPDO gives `"mapping": "config"`
- **THEN** the configuration is rejected, naming node 4, TPDO 1, 0x1A00 and access type `ro`

#### Scenario: Device mapping on a writable PDO
- **WHEN** the ping-pong slave's TPDO 1 gives `"mapping": "device"` and one entry 0x4001 sub 0
- **THEN** no SDO to 0x1A00 is sent at boot and the counter value still reaches the entry's input location

#### Scenario: Existing config unchanged
- **WHEN** a configuration whose EDS mapping objects are all writable gives no `mapping`
- **THEN** the node's generated configuration is the same as before this change

#### Scenario: No default mapping in the EDS
- **WHEN** a PDO resolves to `"device"` and its EDS has no `DefaultValue` for 0x1A00 sub 1
- **THEN** the configuration is rejected, naming the node, the PDO and 0x1A00 sub 1

### Requirement: Entries of a device-mapped PDO
In a PDO whose mapping is `"device"`, each entry SHALL name an object that appears in the EDS default mapping of that PDO, with a `type` whose size equals the mapped length; the order of entries SHALL NOT matter, and entries MAY name a subset of the mapped objects. Otherwise the plugin SHALL reject the configuration, naming the entry and listing the default mapping. Mapped objects that no entry names (dummy entries included) SHALL travel in the PDO but SHALL NOT be exchanged with the PLC. For an RPDO (master to node), the plugin SHALL send those objects as zero and SHALL log one warning at load naming them.

#### Scenario: Subset of a fixed TPDO
- **WHEN** node 4's fixed TPDO 1 maps 0x6000 sub 1 and 0x6000 sub 2 (UNSIGNED8 each) and the config lists only 0x6000 sub 2 at `%IB40`
- **THEN** the configuration loads and `%IB40` shows the second byte of each TPDO 1 frame from node 4

#### Scenario: Entry not in the default mapping
- **WHEN** the same PDO lists 0x6000 sub 3
- **THEN** the configuration is rejected, naming node 4, TPDO 1 and 0x6000 sub 3, and listing 0x6000 sub 1 and 0x6000 sub 2 as the default mapping

#### Scenario: Unnamed objects in a fixed RPDO
- **WHEN** node 4's fixed RPDO 1 maps 0x6200 sub 1 and 0x6200 sub 2 and the config lists only 0x6200 sub 1
- **THEN** the configuration loads, a warning names 0x6200 sub 2 of node 4 RPDO 1 as sent as zero, and every RPDO 1 frame carries 0 in that byte

### Requirement: Read-only PDO communication sub-indices are not written
The master SHALL NOT write a PDO communication sub-index (0x1400-0x15FF, 0x1800-0x19FF) whose EDS access type is not writable, including the disable and re-enable of a configured PDO's COB-ID during node configuration. For a PDO with a read-only COB-ID, the COB-ID the plugin would use (given in the config, or the CiA 301 default when left out) SHALL equal the EDS value with the PDO enabled, or the configuration SHALL be rejected naming the node, the PDO and both values. A PDO that the configuration does not use and whose COB-ID is read-only SHALL be left as the node has it, and the plugin SHALL log this once at load instead of switching the PDO off.

#### Scenario: Fixed COB-ID equal to the default
- **WHEN** node 4's EDS marks 0x1800 sub 1 `ro` with value 0x184 and the config uses TPDO 1 without `cob_id`
- **THEN** no SDO to 0x1800 sub 1 is sent at boot and node 4 becomes OPERATIONAL

#### Scenario: Fixed COB-ID different from the config
- **WHEN** the same TPDO gives `"cob_id": 400`
- **THEN** the configuration is rejected, naming node 4, TPDO 1, 0x190 and 0x184

#### Scenario: Unused fixed PDO
- **WHEN** node 4's EDS has TPDO 2 enabled with a read-only COB-ID and the config does not use TPDO 2
- **THEN** the configuration loads, nothing is written to 0x1801, and the log says node 4 keeps TPDO 2 enabled

### Requirement: Synchronous PDOs need SYNC
When the master produces no SYNC, the plugin SHALL reject every configured PDO whose effective transmission type needs SYNC: 0-240 or 252. The effective type SHALL be the PDO's `transmission` when the JSON gives it, otherwise the default value of sub-index 2 of the PDO's communication object in the node's EDS. The plugin SHALL NOT change the transmission type on its own to avoid the error. The error SHALL name the node, the PDO, the type and where it came from (JSON or EDS), and say to set `master.sync_period_us`, `"master.sync_source": "plc_cycle"` or a `transmission` of 254 or 255. A PDO's `sync_start` SHALL likewise be rejected without SYNC. PDOs the config does not list are switched off and SHALL NOT be checked.

#### Scenario: Synchronous EDS default without SYNC
- **WHEN** the config has no `sync_period_us` and no `sync_source`, and node 5 has a `tx_pdos` entry 1 without `transmission` whose EDS default for 0x1800 sub 2 is 1
- **THEN** the configuration is rejected, naming node 5, TPDO 1, transmission type 1 from the EDS, and suggesting `sync_period_us`, `"sync_source": "plc_cycle"` or `"transmission": 254`

#### Scenario: Synchronous EDS default with PLC-cycle SYNC
- **WHEN** the config has `"sync_source": "plc_cycle"` and no `sync_period_us`, and node 5's TPDO 1 has EDS default type 1
- **THEN** the configuration loads and the node sends TPDO 1 after every SYNC

#### Scenario: Event-driven override
- **WHEN** the same PDO gives `"transmission": 255` and the EDS marks 0x1800 sub 2 writable
- **THEN** the configuration loads and the node sends TPDO 1 on change without SYNC

#### Scenario: Event-driven EDS default
- **WHEN** the config has no `sync_period_us` and node 23's RPDO 1 has no `transmission` and an EDS default of 255
- **THEN** the configuration loads

#### Scenario: Unlisted synchronous PDO
- **WHEN** the config has no `sync_period_us` and node 5's EDS has TPDO 2 with default type 1, but the config does not list TPDO 2
- **THEN** the configuration loads and TPDO 2 is switched off

### Requirement: Output exchange without SYNC
When the master produces no SYNC, the bus thread SHALL check for a new output snapshot from the scan at least every 1 ms and SHALL write changed output values to their PDOs, sending each event-driven PDO whose data changed, subject to its inhibit time. When the master produces SYNC, outputs SHALL be sent on SYNC as before. The scan side SHALL NOT change: it SHALL NOT wait on the bus thread.

#### Scenario: Valve output without SYNC
- **WHEN** the config has no `sync_period_us`, node 23's RPDO 1 is event-driven, and the program sets `%QX20.0` to TRUE
- **THEN** the master sends node 23's RPDO 1 with the new value within 1 ms plus one scan cycle, and no SYNC frame is sent

#### Scenario: Unchanged outputs
- **WHEN** the config has no `sync_period_us` and the program's outputs do not change
- **THEN** the master sends no RPDO for those outputs

### Requirement: PDO timing with PLC-cycle SYNC
With `"sync_source": "plc_cycle"`, the inputs a node samples at the SYNC sent in frame k SHALL reach the PLC at the `cycle_start()` of frame k+1 when they arrive on the bus before it, and the outputs the scan of frame k writes SHALL be sent in the master's synchronous PDOs right after the SYNC of frame k+1. The scan SHALL NOT wait for the bus in either direction. Event-driven master PDOs SHALL be sent when their data changed, at the SYNC that carries the change, as with the timer.

#### Scenario: Fixed output latency
- **WHEN** `"sync_source"` is `"plc_cycle"` with a 10 ms task, node 23's RPDO 1 has type 1, and the program sets `%QX20.0` to TRUE in one scan
- **THEN** the master's RPDO 1 for node 23 with the new value follows the next SYNC, and over 1000 such changes the time from the scan's `cycle_end()` to that RPDO never exceeds one frame plus the bus thread's wake-up time

#### Scenario: Inputs one frame old
- **WHEN** `"sync_source"` is `"plc_cycle"` with a 10 ms task and node 5's TPDO 1 (type 1) carries a counter the node increments at every SYNC
- **THEN** the PLC sees the counter increase by exactly one in every scan, with no repeated or missed value while no PDO is late

### Requirement: Receive timeout setting
Each PDO in `tx_pdos` MAY give `timeout_ms`: a number of milliseconds from 1 to 65535, or `"auto"`. The plugin SHALL write the resolved value as the deadline (sub-index 5) of the master's own RPDO for that PDO, the one whose COB-ID is the PDO's COB-ID, in the generated master DCF, so it also holds after a master NMT reset. Without `timeout_ms` the plugin SHALL monitor nothing and write nothing there, as before.

#### Scenario: Fixed timeout
- **WHEN** node 5's TPDO 1 has `"timeout_ms": 500`
- **THEN** the master DCF's RPDO for COB-ID 0x185 has sub-index 5 = 500

#### Scenario: Unchanged config
- **WHEN** a config gives no `timeout_ms` anywhere
- **THEN** the generated master DCF is byte-identical to the one before this change and no PDO is monitored

#### Scenario: Timeout on an output PDO
- **WHEN** an `rx_pdos` entry gives `timeout_ms`
- **THEN** the configuration is rejected naming the node, the PDO and the field

### Requirement: Automatic receive timeout from the event timer
`"timeout_ms": "auto"` SHALL resolve to two times the node's event timer for that TPDO: `event_timer_ms` from the config when given, else the `DefaultValue` of the node's 0x1800+n-1 sub-index 5 in its EDS. The plugin SHALL log the resolved value at load. It SHALL reject `"auto"` when that event timer is 0 or the EDS has no sub-index 5.

#### Scenario: Auto from the EDS event timer
- **WHEN** node 5's TPDO 2 has `"timeout_ms": "auto"`, no `event_timer_ms`, and its EDS gives 0x1801 sub 5 DefaultValue 100
- **THEN** the master's deadline for that PDO is 200 ms and the load log names it

#### Scenario: Auto from the config event timer
- **WHEN** node 5's TPDO 2 has `"event_timer_ms": 250` and `"timeout_ms": "auto"`
- **THEN** the master's deadline for that PDO is 500 ms

#### Scenario: Auto without an event timer
- **WHEN** node 5's TPDO 1 has `"timeout_ms": "auto"` and its effective event timer is 0
- **THEN** the configuration is rejected naming node 5, TPDO 1 and `timeout_ms`, saying there is no event timer to derive it from and a number is needed

### Requirement: Input PDO timeout detection
A monitored PDO SHALL count as timed out when, while its node is up (master and node OPERATIONAL), no PDO has arrived within `timeout_ms` after the last received one, or within `timeout_ms` after the node came up when none has arrived since. The plugin SHALL check this itself on every bus cycle, so detection SHALL NOT depend on the master's own deadline timer and SHALL work alike on a SocketCAN interface and on the simulated bus, for event-driven and synchronous PDOs. The next received PDO SHALL end the timeout. While its node is not up a PDO SHALL NOT count as timed out. A timeout SHALL NOT change the node's status bit, state byte, outputs or boot state.

#### Scenario: Event-driven PDO stops
- **WHEN** node 23's TPDO 1 has `"timeout_ms": 500`, the node keeps its heartbeat and stops sending TPDO 1
- **THEN** about 500 ms after its last TPDO 1 the PDO counts as timed out and node 23's status bit stays TRUE

#### Scenario: Synchronous PDO stops on the simulated bus
- **WHEN** simulated node 5's TPDO 1 (transmission type 1, `"timeout_ms": 200`) has been received for a while and the simulator's "TPDO stop 1" fault stops it
- **THEN** within about 300 ms TPDO 1 counts as timed out, its timeout bit reads TRUE, the log has one "no PDO" warning, and node 5 stays OPERATIONAL

#### Scenario: PDO never arrives
- **WHEN** node 23 goes OPERATIONAL but never sends its TPDO 1 with `"timeout_ms": 500`
- **THEN** TPDO 1 counts as timed out within about 600 ms of the node being up

#### Scenario: Node lost
- **WHEN** node 23 with a timed-out TPDO 1 loses its heartbeat
- **THEN** TPDO 1 no longer counts as timed out and nothing more is logged for it until the node is up again

### Requirement: Timeout reported to the PLC and the log
A monitored PDO MAY give `timeout_location`, an `%IX` input bit that SHALL be TRUE while the PDO is timed out and FALSE otherwise. On each timeout the plugin SHALL log one warning naming the node, the TPDO and the timeout, and count it; when the PDO arrives again it SHALL log once that it is back and how long it was missing.

#### Scenario: Timeout bit
- **WHEN** node 23's TPDO 1 has `"timeout_location": "%IX20.0"` and times out, then arrives again
- **THEN** `%IX20.0` reads TRUE, then FALSE by the next scan after the PDO, and the log has one warning and one "back" line

#### Scenario: Location clash
- **WHEN** `timeout_location` is `%IX10.0` and another binding uses `%IX10.0`
- **THEN** the configuration is rejected naming both uses

### Requirement: Inputs while a PDO is timed out
`on_timeout` SHALL choose what the PDO's inputs show while it is timed out: `"hold"` (default) keeps the last received values, `"zero"` sets every input of that PDO to 0 until the next PDO arrives. The plugin SHALL reject `on_timeout` or `timeout_location` on a PDO without `timeout_ms`, naming the node, the PDO and the field.

#### Scenario: Hold by default
- **WHEN** a monitored TPDO with an `%IW100` entry times out and gives no `on_timeout`
- **THEN** `%IW100` keeps its last value

#### Scenario: Zero on timeout
- **WHEN** a TPDO with `"on_timeout": "zero"` and an `%IW100` entry times out
- **THEN** `%IW100` reads 0 until the PDO arrives again

#### Scenario: Timeout fields without timeout_ms
- **WHEN** a TPDO gives `timeout_location` but no `timeout_ms`
- **THEN** the configuration is rejected naming the node, the PDO and the field

### Requirement: Short PDOs are logged
When Lely reports a received PDO that is shorter than its mapping, the plugin SHALL log one warning naming the node, the TPDO and the received and expected lengths, and SHALL NOT log it again for that PDO until a PDO of the right length has arrived. The inputs SHALL keep their values.

#### Scenario: Short PDO
- **WHEN** node 5 sends its TPDO 1 with 2 data bytes and the mapping needs 4
- **THEN** the log has one warning naming node 5, TPDO 1, 2 and 4 bytes, and the PDO's inputs are unchanged

### Requirement: Outputs sent again when a node comes up
When a node becomes up again (after a boot, a reboot it reported itself, or recovery from a loss), or when the outputs gate opens again, the master SHALL write the current values of that node's outputs to its PDOs before it enables them, and SHALL send each of the node's event-driven PDOs once, subject to inhibit time. With SYNC, the first synchronous PDO after the node is up SHALL carry the current values. Outputs that did not change SHALL otherwise not be sent again, as before.

#### Scenario: Device reboots while the program holds an output
- **WHEN** node 23's RPDO 1 is event-driven, the program holds `%QX20.0` TRUE, and node 23 resets and comes back
- **THEN** after node 23 is started again the master sends RPDO 1 with `%QX20.0` TRUE once, without the program changing it

#### Scenario: Node recovers on a SYNC network
- **WHEN** node 5 with a synchronous RPDO was lost while the program changed its outputs, and node 5 comes back
- **THEN** the first RPDO after node 5 is up carries the program's current values

### Requirement: Scan watchdog
The master SHALL support `master.scan_watchdog_ms` (10 to 60000, default 1000; 0 turns it off). While the PLC runs and its scan has not finished a cycle for that long, the outputs gate SHALL close: no RPDOs, raw or J1939 transmit messages. SYNC, inputs and node supervision SHALL keep running. The next finished scan SHALL open the gate and the outputs SHALL be sent again as when a node comes up. Closing and opening SHALL be logged.

#### Scenario: Program hangs
- **WHEN** the program's scan stops finishing cycles while the runtime keeps running and `scan_watchdog_ms` is 1000
- **THEN** about 1 s later the master stops sending RPDOs, SYNC keeps going, and the log names the scan watchdog
