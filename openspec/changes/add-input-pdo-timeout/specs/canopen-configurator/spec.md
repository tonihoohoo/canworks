## MODIFIED Requirements

### Requirement: PDO communication parameters
For each PDO the configurator SHALL edit the PDO number, COB-ID, transmission type and event timer, leaving each unset to use the default unless the user sets it. For a TPDO it SHALL also edit the receive timeout: an empty field (no `timeout_ms`, shown as "off"), a number of milliseconds, or Auto, which SHALL show the resolved value next to it (two times the event timer from the config or the EDS) and SHALL be offered only when that event timer is not 0. When a timeout is set the configurator SHALL show the "on timeout" choice (hold, the default and saved as no field, or zero) and a timeout bit address field (`%IX`, optional, included in the address suggestion and clash checks). The Check SHALL give the same messages as the plugin for these fields, and SHALL warn when a numeric timeout is shorter than the PDO's effective event timer.

#### Scenario: Event-driven TPDO
- **WHEN** the user sets a TPDO's transmission type to 254 and event timer to 500 ms
- **THEN** the saved PDO has `transmission` 254 and `event_timer_ms` 500, and no `cob_id` unless one was set

#### Scenario: Auto timeout from the EDS
- **WHEN** a TPDO has no event timer set, its EDS gives 100 ms, and the user picks Auto
- **THEN** the field shows "auto (200 ms)" next to it and the saved PDO has `"timeout_ms": "auto"`

#### Scenario: Timeout off
- **WHEN** the user clears the timeout field and saves
- **THEN** the saved PDO has no `timeout_ms`, `on_timeout` or `timeout_location`

### Requirement: Online view
With online access set up, the configurator SHALL offer an online view that connects to the runtime, refreshes about twice a second, and shows the bus state and counters, the master state, and for each node its state, status bit, boot result with error text, retry and hold state, last EMCY with class, SDO variable values and status, and a mark on each monitored TPDO that is timed out with its timeout count, using the node names from the config. Opening a node SHALL show its EMCY history with times and CiA 301 error classes, and for each monitored TPDO its timeout, count and time since its last PDO. When the runtime's config fingerprint differs from the saved `canopen.json`, the view SHALL say that the runtime runs a different configuration. Connection failures SHALL be shown with the reason (host unreachable, port closed, wrong token, no CANopen session) and retried.

#### Scenario: Watch a node come back
- **WHEN** the online view is open and node 23's cable is plugged back in
- **THEN** within about a second node 23's state goes from 0 to 127 to 5 and its boot result shows success

#### Scenario: Different config on the runtime
- **WHEN** the user saved a change but has not uploaded it yet
- **THEN** the online view shows that the runtime runs a different configuration

#### Scenario: Timed-out PDO
- **WHEN** node 23 is OPERATIONAL and its monitored TPDO 1 has timed out
- **THEN** node 23's row stays green for its state and shows "TPDO 1 timed out" with the count
