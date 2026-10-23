## ADDED Requirements

### Requirement: Safe settings for new nodes and adapters
When the user adds a node, the configurator SHALL save it with `"config_check": true` when its EDS defines 0x1020 sub 1 and sub 2 as writable. When a node gets its first output entry (an RPDO entry with a location) and its EDS has a writable 0x1016, the configurator SHALL set `"heartbeat_consumer": true` in the same undo step, and when the master sends no heartbeat it SHALL also set `master.heartbeat_ms` to 100. When the user adds a `socketcan` adapter with `configure_link` on, the configurator SHALL save `"restart_ms": 100`. Each value SHALL show in its usual field and the user SHALL be able to turn it off; the configurator SHALL NOT set them again on a node or adapter where the user turned them off. Nodes and adapters loaded from a file SHALL NOT be changed. No value SHALL write a node's non-volatile memory (`store_configuration` stays off).

#### Scenario: New output node
- **WHEN** the user adds node 23 whose EDS has writable 0x1016 and 0x1020, and maps an RPDO entry to a location, on a master with `heartbeat_ms` 0
- **THEN** the saved node has `"config_check": true` and `"heartbeat_consumer": true`, the master has `"heartbeat_ms": 100`, and one undo removes the heartbeat settings and the mapping together

#### Scenario: New CAN interface
- **WHEN** the user adds a network with a SocketCAN adapter `can0`
- **THEN** the saved adapter has `"restart_ms": 100`

#### Scenario: User turns it off
- **WHEN** the user clears "Watches the master heartbeat" on node 23 and then maps another RPDO entry
- **THEN** `heartbeat_consumer` stays off

### Requirement: Problems for bridge stop and bus-off
Problems SHALL show, as warnings that do not block saving or the hand-off steps:
- every node that canopen-node-supervision "Nodes not protected against a bridge stop" names, with the message that it keeps its last outputs when the bridge crashes or loses power and a **Watch the master heartbeat** button, offered when the EDS has a writable 0x1016, that sets `heartbeat_consumer` true (and `master.heartbeat_ms` 100 when it is 0) in one undo step;
- every `socketcan` adapter with `configure_link` on and no `restart_ms`, with the message that a bus-off then lasts until the interface is restarted and a **Restart after bus-off (100 ms)** button.

#### Scenario: Fix from Problems
- **WHEN** a loaded config has node 23 with RPDO entries and no protection, and the user presses Watch the master heartbeat
- **THEN** node 23 has `"heartbeat_consumer": true`, the warning is gone, and one undo brings both back

#### Scenario: Bus-off restart fix
- **WHEN** a loaded config has adapter `can0` without `restart_ms` and the user presses Restart after bus-off (100 ms)
- **THEN** the adapter has `"restart_ms": 100` and the warning is gone
