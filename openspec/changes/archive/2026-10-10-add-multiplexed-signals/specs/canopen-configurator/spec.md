## MODIFIED Requirements

### Requirement: CAN messages page
Every network SHALL have a CAN messages page with a receive table and a send table. A row SHALL edit one message (name, identifier in hex, extended, remote, mask for receive, DLC, timing for send, timeout and status locations for receive, and `pages` for a send message with switches) and SHALL open its signal rows (name, start bit, length, byte order, signed, scale, offset, unit, Switch, Page, PLC location, and valid location for receive). Signal rows SHALL be sorted with always-active signals first, then by page. The page SHALL draw the selected message's 8 bytes as a bit grid with each signal's bits marked, as the frame inspector does; for a message with switches the grid SHALL show one page at a time with a page picker. "Suggest addresses" SHALL fill free PLC locations of the right size, and SHALL leave switches of send messages with `pages` `all` or `rotate` without a location. A send message on an identifier the network's protocol uses SHALL be marked with the use and an "Override protocol" switch.

#### Scenario: Overlapping signals
- **WHEN** the user gives two signals of one message overlapping bits
- **THEN** both rows are marked with a problem naming the other signal, and the bit grid shows the overlap

#### Scenario: Send on a PDO identifier
- **WHEN** the user adds a send message 0x205 on a network where 0x205 is RPDO1 of node 5
- **THEN** the row says "RPDO1 of node 5" and Check reports a problem until "Override protocol" is on

#### Scenario: Pages in the bit grid
- **WHEN** the user marks `Page` as Switch, gives `Temp` Page `1` and `Press` Page `2` on the same bits, and picks page 2 in the grid
- **THEN** the grid shows `Page` and `Press`, no overlap problem is reported, and picking page 1 shows `Page` and `Temp`

### Requirement: Import a DBC into CAN messages
The CAN messages page SHALL have "Import DBC…", which reads a DBC file, lists its messages with identifier, DLC, sender and signal count, and adds the chosen messages as receive or send messages (send preselected for messages whose sender is a node the user marks as "this PLC"). Imported messages SHALL keep the DBC's names, layouts, scale, offset, unit, limits and multiplexing (simple and extended); a cycle time from the DBC SHALL become `period_ms` for send and three times the cycle as `timeout_ms` for receive. A message with several switches but no `SG_MUL_VAL_` SHALL be listed with a note that its multiplexing cannot be read. The file name SHALL be stored in `raw.dbc`.

#### Scenario: Import two messages
- **WHEN** the user imports a DBC with messages `Joystick` (cycle 100 ms) and `Lamps`, choosing receive for `Joystick` and send for `Lamps`, then clicks Suggest addresses and saves
- **THEN** the file has `Joystick` in `raw.rx` with `timeout_ms` 300 and `Lamps` in `raw.tx`, every signal has a location, and Check reports no problems

#### Scenario: Import a multiplexed message
- **WHEN** the user imports `Status` with switch `Page` and signals on pages 1 and 2 as receive
- **THEN** the file has `Page` with `multiplexer: true` and each page's signals with their `mux.values`, and Check reports no problems
