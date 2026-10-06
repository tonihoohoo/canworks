## MODIFIED Requirements

### Requirement: Master settings
The configurator SHALL edit the master's node ID, SYNC source, SYNC period, PLC cycles per SYNC, master heartbeat period, EDS lint setting and boot SDO timeout. The SYNC period field SHALL be optional: left empty it SHALL show "off" as its placeholder and SHALL save no `sync_period_us`, and its hint SHALL say that synchronous PDOs then need an event-driven transmission type. New configs SHALL still start with a SYNC period of 10 ms. The SYNC source SHALL offer "timer" (saved as no field) and "PLC cycle" (`"plc_cycle"`); with "PLC cycle" the SYNC period field SHALL be hidden and not saved, and an "every N PLC cycles" field SHALL show 1 as its placeholder, save nothing when empty and save `sync_cycles` otherwise. The boot SDO timeout field SHALL show 1000 as its placeholder and SHALL save nothing when left empty. The EDS lint setting SHALL offer "communication objects" (`"communication"`, the default, saved as no field), "every object" (`"all"`) and "off" (`"off"`). A loaded config with `strict_eds` SHALL be shown as the matching setting and saved as `eds_lint`, with the page saying so.

#### Scenario: Change the SYNC period
- **WHEN** the user sets the SYNC period to 10 ms and saves
- **THEN** `master.sync_period_us` is 10000 and every other value is unchanged

#### Scenario: SYNC period left empty
- **WHEN** the user clears the SYNC period field and saves
- **THEN** the saved `master` object has no `sync_period_us`

#### Scenario: Check without SYNC
- **WHEN** the SYNC period is empty, a node's TPDO 1 has no transmission type and its EDS default is 1, and the user presses Check
- **THEN** the check reports the same error the plugin would log, naming the node and TPDO 1

#### Scenario: Raise the boot SDO timeout
- **WHEN** the user enters 3000 in the boot SDO timeout field and saves
- **THEN** `master.sdo_timeout_ms` is 3000

#### Scenario: Boot SDO timeout left empty
- **WHEN** the user leaves the boot SDO timeout field empty and saves
- **THEN** the saved `master` object has no `sdo_timeout_ms`

#### Scenario: Old strict_eds false
- **WHEN** a loaded config has `"strict_eds": false` and the user saves
- **THEN** the saved `master` has `"eds_lint": "off"` and no `strict_eds`

#### Scenario: Lint rerun on check
- **WHEN** the user changes the EDS lint setting from "off" to "every object" for a config whose node EDS has findings in 0x6061, and presses Check
- **THEN** the check reports the same lint error the plugin would log for that node

#### Scenario: Switch to PLC-cycle SYNC
- **WHEN** a config has `"sync_period_us": 10000`, the user picks "PLC cycle", enters 2 in "every N PLC cycles" and saves
- **THEN** the saved `master` object has `"sync_source": "plc_cycle"` and `"sync_cycles": 2` and no `sync_period_us`, and the Check accepts a node TPDO with EDS default type 1

#### Scenario: Back to the timer
- **WHEN** the user switches a PLC-cycle config back to "timer", enters 10 ms and saves
- **THEN** the saved `master` object has `"sync_period_us": 10000` and neither `sync_source` nor `sync_cycles`
