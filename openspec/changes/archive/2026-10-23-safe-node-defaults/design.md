## Context

Node-side protection against a lost master already exists in the config, but nothing in the tools steers toward it:
- `heartbeat_consumer` makes the node watch the master's heartbeat (0x1016);
- `heartbeat_watch` makes it watch other nodes;
- an RPDO's `event_timer_ms` is its deadline;
- `error_behavior` sets 0x1029.

The rule "unset means the EDS's value" (canopen-master-bringup "Slave configuration and start-up") is Toni's and stays. The bridge's behaviour for unset fields does not change.

## Decisions

**Explicit values from the configurator, not new bridge defaults.** Changing what an unset field means would break the EDS rule and surprise anyone editing JSON by hand. Instead:
- the configurator writes the safer value when it creates the item (a node, an adapter);
- configs that lack it get a warning from the bridge, from the deploy check and in Problems.

Alternative considered: bridge-side defaults (`heartbeat_consumer` true when unset). Rejected for the rule above.

**When a node counts as protected.** A node is protected when any of these hold:
- `heartbeat_consumer` is true;
- the EDS default of 0x1016 already has an entry with the master's node ID and a non-zero time, and the config does not clear it;
- one of its RPDOs has `event_timer_ms` above 0, given or from the EDS.

Only nodes with output entries are checked, meaning RPDO entries with an `iec_location`. Nodes that only send are not, since there is nothing of theirs to stop. A PDO-link consumer counts as a node with outputs. `heartbeat_watch` of other nodes does not count, because it does not see the master.

**What "react" means is the device's.** 0x1029 sub 1 decides what a node does when it loses the master's heartbeat (pre-operational, no change, stopped). The configurator does not set it. The docs say to check it, and `error_behavior` is where to set it.

**`config_check` on new nodes.** It writes 0x1020 in RAM. `store_configuration` stays off, so nothing is saved to NVM. Its cost is one extra download after a tools update that changes the stamp. Its gain is that a bridge restart does not reset running nodes.

**`restart_ms` 100 on new socketcan adapters.** It is the value the docs already suggest. It does nothing on virtual interfaces and is not offered on slcan.

**Bus flag.** Byte 7 bit 1 is the OR over the bridge's CAN networks of "interface down or controller bus-off", read from the same rtnetlink state the bus diagnostics use. It is updated by the 1 ms loop from a per-network atomic set by the bus thread. Error-passive is not counted: frames still flow.

**PLC inputs while the bridge is lost.** The generator knows which typed inputs come from:
- node status (`status_location`);
- node state (`state_location`);
- the master's state and bus state;
- the live lists.

While `canworks.ok` is FALSE these are written 0, because "no node is known to run" is the only true statement then. The other inputs default to hold, because a zeroed measurement (a temperature of 0) can mislead as much as a frozen one. The connection's `inputs_on_loss: "zero"` makes them 0 too. `canworks.bus_ok` is `canworks.ok AND NOT bit 1`.

## Risks / Trade-offs

- **Watching the master's heartbeat makes a node react to a planned bridge restart too.** An update restart is under 3 s, and the master heartbeat timeout is `heartbeat_ms` × `heartbeat_multiplier` (300 ms by default). The node goes pre-operational and the master starts it again; with `config_check` there is no re-download. This is the intended trade: a planned stop already sends pre-operational today.
- **A warning on every existing config with outputs** is noise until fixed. The one-click fix and the examples being clean keep it short-lived, and nothing is in real use.
