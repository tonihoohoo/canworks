## ADDED Requirements

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
A monitored PDO SHALL count as timed out when, while its node is up (master and node OPERATIONAL), the master's deadline expires, or no PDO has arrived within `timeout_ms` after the node came up. The next received PDO SHALL end the timeout. While its node is not up a PDO SHALL NOT count as timed out. A timeout SHALL NOT change the node's status bit, state byte, outputs or boot state.

#### Scenario: Event-driven PDO stops
- **WHEN** node 23's TPDO 1 has `"timeout_ms": 500`, the node keeps its heartbeat and stops sending TPDO 1
- **THEN** about 500 ms after its last TPDO 1 the PDO counts as timed out and node 23's status bit stays TRUE

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
