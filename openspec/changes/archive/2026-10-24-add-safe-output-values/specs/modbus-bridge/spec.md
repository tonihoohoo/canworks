## MODIFIED Requirements

### Requirement: Output watchdog
The bridge SHALL feed its watchdog with every accepted write request (functions 5, 6, 15, 16, 23) from a writer client. When no such write arrived for `watchdog_ms` (default 1000; 0 turns the watchdog off), the bridge SHALL enter outputs off with the action of `on_client_loss`:
- `"stop"` (default): outputs stop: no RPDOs, no raw or J1939 transmit messages. SYNC keeps running, so nodes that send their inputs on SYNC keep sending them and a node's RPDO event timer sees the outputs stop
- `"zero"`: every output location is set to 0, the outputs are sent once, then they stop
- `"hold"`: outputs keep being sent with their last values
- `"safe"`: every output location is set to its safe value (requirement "Safe values"), and the outputs keep being sent with those values

Inputs, SYNC, node supervision, the diagnostics channel and J1939 address claim SHALL keep running. The next accepted write SHALL end outputs off. Entering and leaving SHALL be logged with the reason.

#### Scenario: Client unplugged
- **WHEN** the client that writes outputs every 50 ms stops and `watchdog_ms` is 1000 with the default action
- **THEN** about 1 s later RPDOs stop, SYNC and input registers keep updating, the status block reads 2, and the log names the watchdog

#### Scenario: Reader does not feed the watchdog
- **WHEN** only a client that reads input registers is connected
- **THEN** the watchdog runs out and outputs stay off

#### Scenario: Client unplugged with safe values
- **WHEN** `on_client_loss` is `"safe"`, `safe_values` has `"%QW10": 500` for node 6's RPDO entry, and the writer stops for `watchdog_ms`
- **THEN** node 6's RPDO keeps being sent on every SYNC with 500 in that entry and 0 in its entries without a safe value, the status block reads 2, and the log names the watchdog and the safe values

## ADDED Requirements

### Requirement: Safe values
`bridge.safe_values` SHALL map output locations to values. A location SHALL be refused at load unless it is an output location covered by a data binding (an RPDO entry, a J1939 or raw transmit signal). Locations of the bridge's own blocks, the PLC link header, NMT command bytes, and the trigger and enable bits of SDO variables and raw messages SHALL be refused, naming the binding. A value SHALL be refused unless it fits the binding: an integer in the binding's range, a finite number for REAL32 and REAL64, `true`, `false`, 0 or 1 for a bit, and a decimal string for a 64-bit integer beyond 2^53. A bit location inside a bound byte or word SHALL set only that bit, after the whole values. Output locations without a safe value SHALL be 0 in the safe image. `safe_values` with an `on_client_loss` other than `"safe"` SHALL load with a warning that they are not used.

With `"safe"`, entering outputs off for any reason (the watchdog, the control block's idle command, the PLC link header stopped or mismatched) SHALL write the safe image over the output image and keep the outputs sent. Periodic J1939 and raw messages SHALL keep their period and on-change messages SHALL be sent once with the safe values. The write that ends outputs off SHALL start from the safe image. Mailbox operations, cyclic frame jobs and SDO variables SHALL end as in the other actions.

#### Scenario: Value out of range
- **WHEN** `safe_values` has `"%QB8": 300` and `%QB8` is an UNSIGNED8 RPDO entry
- **THEN** the config is refused with an error naming `%QB8`, the entry and the range 0-255

#### Scenario: Safe value on a command byte
- **WHEN** `safe_values` names the location of node 6's NMT command byte
- **THEN** the config is refused with an error saying safe values cannot be set on an NMT command byte

#### Scenario: Bit of a controlword
- **WHEN** `safe_values` has `"%QW20": 6` and `"%QX21.2": false` on a drive's controlword at `%QW20`, and outputs go off with `"safe"`
- **THEN** the controlword is sent as 6 with bit 2 of byte 21 cleared, which is 2

#### Scenario: PLC stops
- **WHEN** an OpenPLC connection's program stops (PLC link header running 0) and `on_client_loss` is `"safe"`
- **THEN** the outputs go to their safe values at once and keep being sent, and status byte 0 reads 5

#### Scenario: Reconnect after a loss
- **WHEN** outputs were off with `"safe"` and a writer then writes one coil
- **THEN** that coil's output is sent with its new value and every other output keeps its safe value

#### Scenario: Unused safe values
- **WHEN** `safe_values` is set and `on_client_loss` is `"stop"`
- **THEN** the bridge starts with a warning that the safe values are not used with `stop`

### Requirement: Safe values at start and clean stop
With `"safe"`, the bridge SHALL put the safe image in place at start, so the outputs are sent with their safe values from the moment each network runs until the first accepted write ends outputs off. On a clean stop the bridge SHALL write the safe image, wait one SYNC period of the CANopen master networks (the longest, at least 20 ms, at most 200 ms) while RPDOs, periodic J1939 and raw messages and on-change messages carry it, and then send `master.on_plc_stop` as before.

#### Scenario: Start before the PLC
- **WHEN** a bridge with `"safe"` and `"%QW10": 500` starts and no client has written yet
- **THEN** node 6's RPDO is sent with 500 from the first SYNC after the node is operational

#### Scenario: Clean stop
- **WHEN** a writer wrote `%QW10` = 900 and the bridge is stopped with `systemctl stop`
- **THEN** node 6 receives an RPDO with 500 before the NMT command of `master.on_plc_stop`
