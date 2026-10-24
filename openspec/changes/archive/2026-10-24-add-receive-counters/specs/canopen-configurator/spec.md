## ADDED Requirements

### Requirement: Frame counter fields
For a TPDO the PDO settings SHALL offer a "Frame counter" address field (`%IW`, optional) next to the timeout bit, shown whether or not a timeout is set, and the J1939 page SHALL offer the same field for each received message next to its status bit. Both SHALL be included in the address suggestion and the clash check, give the same check messages as the bridge, and save as `counter_location`; an empty field SHALL save no field. A hint SHALL say that the counter grows by one per received frame and shows frames that came within one poll. The fields SHALL NOT be offered on a CODESYS project.

#### Scenario: Set a counter
- **WHEN** the user enters `%IW40` as node 5 TPDO 1's frame counter and saves
- **THEN** the saved PDO has `"counter_location": "%IW40"` and the variable list declares `rtd_tpdo1_count` as `UINT` at `%IW40`

#### Scenario: Clash
- **WHEN** the frame counter is `%IW100` and an entry of the same node uses `%IW100`
- **THEN** Problems names both uses, as for other locations

#### Scenario: Clear
- **WHEN** the user empties the frame counter field and saves
- **THEN** the saved PDO has no `counter_location`
