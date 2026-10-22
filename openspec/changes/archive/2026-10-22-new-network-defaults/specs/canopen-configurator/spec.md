## ADDED Requirements

### Requirement: Defaults of a new network
Every network the configurator creates SHALL start with its protocol's default bit rate: 500 kbit/s for CANopen (master or slave), 250 kbit/s for J1939 and 500 kbit/s for plain CAN. A new CANopen master SHALL start with node ID 1 and no SYNC (no `sync_period_us` and no `sync_source`). This SHALL hold for New config…, Add network…, switching a network's protocol or switching a slave back to master. **Add network…** SHALL NOT copy another network's bit rate. Switching a network's protocol SHALL change its bit rate to the new protocol's default only when the rate is the old protocol's default, and SHALL keep any other rate. Existing configs SHALL keep their settings.

#### Scenario: New config
- **WHEN** the user creates a new OpenPLC config
- **THEN** the saved config's network has `"bitrate": 500000` and its master is `{"node_id": 1}` with no SYNC keys

#### Scenario: Add a J1939 network next to a CANopen one
- **WHEN** a config's first network runs at 500 kbit/s and the user adds a J1939 network
- **THEN** the new network's bit rate is 250 kbit/s

#### Scenario: Add a CANopen network
- **WHEN** the user adds a CANopen network
- **THEN** it runs at 500 kbit/s and its bus page shows SYNC source Off

#### Scenario: Switch a default network to J1939
- **WHEN** a CANopen network at 500 kbit/s with no nodes is switched to J1939
- **THEN** its bit rate is 250 kbit/s

#### Scenario: Switch keeps a chosen rate
- **WHEN** a CANopen network at 125 kbit/s is switched to J1939
- **THEN** its bit rate stays 125 kbit/s

### Requirement: SYNC Off on the bus page
A CANopen master's bus page SHALL offer **SYNC source** with three choices: **Off** (no SYNC), **Timer** and **PLC cycle**, where the target allows PLC cycle. The choice SHALL follow the config: PLC cycle when `sync_source` is `plc_cycle`, Timer when `sync_period_us` is above 0, else Off. Off SHALL show no period field and remove `sync_period_us`, `sync_source` and `sync_cycles`. Picking Timer SHALL set the SYNC period to 10 ms; emptying the period SHALL make the choice Off.

#### Scenario: Turn SYNC on
- **WHEN** on a new network the user picks SYNC source Timer
- **THEN** the SYNC period field shows 10 and the config has `"sync_period_us": 10000`

#### Scenario: Clear the period
- **WHEN** SYNC source is Timer and the user empties the SYNC period
- **THEN** SYNC source shows Off and the config has no `sync_period_us`

#### Scenario: Turn SYNC off from the PLC cycle
- **WHEN** SYNC source is PLC cycle with every 2 cycles and the user picks Off
- **THEN** the config's master has no `sync_source`, `sync_cycles` or `sync_period_us`

### Requirement: Default PDOs on a network without SYNC
When a node is added with **Map the EDS's default PDOs** on a network that produces no SYNC, each mapped PDO whose EDS transmission type needs SYNC (0-240 or 252) SHALL get transmission type 255, unless the EDS marks that type read-only, and the add message SHALL name those PDOs. On a network with SYNC, the PDOs SHALL keep their EDS transmission type.

#### Scenario: Synchronous EDS default without SYNC
- **WHEN** a network has no SYNC and the user adds a node whose EDS gives TPDO 1 transmission type 1, with the box ticked
- **THEN** the node's TPDO 1 has transmission 255, the message names TPDO 1, and Problems shows no "needs SYNC" error

#### Scenario: Same EDS with SYNC on
- **WHEN** the network's SYNC source is Timer and the user adds the same node
- **THEN** TPDO 1 has no `transmission` field and keeps the EDS type 1
