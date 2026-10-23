## MODIFIED Requirements

### Requirement: Switch signals
A raw or J1939 signal MAY have `multiplexer: true`, which marks it as a switch. A switch SHALL be unsigned and at most 32 bits long. A switch MAY itself depend on another switch (a nested switch). A switch no signal depends on SHALL give a warning. The bridge and the PC tools SHALL make the checks of this capability with the same messages.

#### Scenario: Signed switch
- **WHEN** a signal has `multiplexer: true` and `signed: true`
- **THEN** the PC tools and the bridge both reject the file naming the signal

#### Scenario: Unused switch
- **WHEN** a message has switch `Page` and no signal has a `mux` on it
- **THEN** the file loads with a warning naming `Page`

### Requirement: Receiving multiplexed messages
For a frame matching a receive entry with switches, the bridge SHALL write the always-active signals, the switches and the active signals, and SHALL leave every other signal location at its last value. A frame shorter than the bytes its own page needs SHALL be counted as short and SHALL write nothing. The message-level locations (status, counter, identifier, DLC, data) SHALL behave as for any matching frame.

#### Scenario: Two pages
- **WHEN** `Status` has switch `Page` at `%IB10`, `Temp` (page 1) at `%IW12` and `Press` (page 2) at `%IW14`, and frames with page 1 (Temp 250) then page 2 (Press 400) arrive
- **THEN** after both, `%IB10` is 2, `%IW12` is 250 and `%IW14` is 400

#### Scenario: Extended multiplexing
- **WHEN** switch `Sub` is active for `Page` 3, signal `B` depends on `Sub` value 1, and a frame arrives with `Page` 3 and `Sub` 1
- **THEN** `B` is written; a later frame with `Page` 4 leaves `B` unchanged

### Requirement: Page list of a send entry
With `pages` `all` or `rotate`, switches SHALL NOT have an `iec_location`, and the page list SHALL be every combination of switch values the message's `mux.values` name, ranges expanded, in ascending order. More than 64 pages SHALL be rejected naming the message.

#### Scenario: Switch location in all mode
- **WHEN** an entry with `pages` `all` gives its switch an `iec_location`
- **THEN** the file is rejected saying the bridge sets the switch in this mode

#### Scenario: Too many pages
- **WHEN** an entry with `pages` `rotate` has a signal with `mux.values` [[0, 199]]
- **THEN** the file is rejected naming the message, the 200 pages and the 64-page limit, and suggesting `program`
