## ADDED Requirements

### Requirement: Switch signals
A raw or J1939 signal MAY have `multiplexer: true`, which marks it as a switch. A switch SHALL be unsigned and at most 32 bits long. A switch MAY itself depend on another switch (a nested switch). A switch no signal depends on SHALL give a warning. The plugin and the PC tools SHALL make the checks of this capability with the same messages.

#### Scenario: Signed switch
- **WHEN** a signal has `multiplexer: true` and `signed: true`
- **THEN** the PC tools and the plugin both reject the file naming the signal

#### Scenario: Unused switch
- **WHEN** a message has switch `Page` and no signal has a `mux` on it
- **THEN** the file loads with a warning naming `Page`

### Requirement: Dependent signal fields
A raw or J1939 signal MAY have `mux` with `values` and optional `on`. `mux.values` SHALL be a non-empty list of integers or `[low, high]` ranges (low ≤ high), all within the switch's range. `mux.on` SHALL name a switch of the same message and MAY be left out only when the message has exactly one switch. Switches SHALL NOT depend on each other in a cycle. A `mux` in a message with no switch SHALL be rejected.

#### Scenario: Simple multiplexing
- **WHEN** message `Status` has switch `Page` (bits 0-7) and signals `Temp` with `mux.values` [1] and `Press` with `mux.values` [2], both at bits 8-23
- **THEN** the file loads with no overlap warning or error

#### Scenario: Two switches, no `on`
- **WHEN** a message has switches `Page` and `Sub` and a signal whose `mux` has no `on`
- **THEN** the file is rejected naming the signal and saying which switch must be given

#### Scenario: Cycle
- **WHEN** switch `A` has `mux.on` `B` and switch `B` has `mux.on` `A`
- **THEN** the file is rejected naming both signals

#### Scenario: Value outside the switch
- **WHEN** a 2-bit switch has a dependent signal with `mux.values` [4]
- **THEN** the file is rejected naming the signal, the value and the switch's range

### Requirement: Active signals of a frame
A signal SHALL be active in a frame when it has no `mux`, or when its switch is active in that frame and the frame's value of the switch is in the signal's `mux.values`. Overlap checks SHALL apply only to signals that can be active in the same frame. The bytes a frame needs SHALL be those of its always-active signals, its switches and its active signals.

#### Scenario: Pages share bits
- **WHEN** `Temp` (page 1) and `Press` (page 2) both use bits 8-23 of a J1939 message
- **THEN** the file loads, although J1939 signals of one message must not overlap

#### Scenario: Overlap within one page
- **WHEN** `Temp` and `Volt` both have `mux.values` [1] and overlapping bits
- **THEN** a raw message gives the overlap warning and a J1939 message is rejected, both naming the two signals

### Requirement: Receiving multiplexed messages
For a frame matching a receive entry with switches, the plugin SHALL write the always-active signals, the switches and the active signals, and SHALL leave every other signal location at its last value. A frame shorter than the bytes its own page needs SHALL be counted as short and SHALL write nothing. The message-level locations (status, counter, identifier, DLC, data) SHALL behave as for any matching frame.

#### Scenario: Two pages
- **WHEN** `Status` has switch `Page` at `%IB10`, `Temp` (page 1) at `%IW12` and `Press` (page 2) at `%IW14`, and frames with page 1 (Temp 250) then page 2 (Press 400) arrive
- **THEN** after both, `%IB10` is 2, `%IW12` is 250 and `%IW14` is 400

#### Scenario: Extended multiplexing
- **WHEN** switch `Sub` is active for `Page` 3, signal `B` depends on `Sub` value 1, and a frame arrives with `Page` 3 and `Sub` 1
- **THEN** `B` is written; a later frame with `Page` 4 leaves `B` unchanged

### Requirement: Unknown pages on receive
A received frame whose switch value selects none of that switch's dependent signals SHALL count as an unknown page in the entry's diagnostics status, and SHALL write only the always-active signals and the switches.

#### Scenario: Unknown page
- **WHEN** a frame of `Status` arrives with `Page` 7 and no signal has value 7
- **THEN** `%IB10` is 7, `%IW12` and `%IW14` keep their values, and the diagnostics status of `Status` counts one unknown page

### Requirement: Page validity bits
A received raw or J1939 signal MAY have `valid_location` (`%IX`). It SHALL be FALSE until a frame made the signal active, TRUE after such a frame, and FALSE again when the entry's `timeout_ms` (when not 0) passes with no frame that made the signal active. For J1939 signals, a not-available or error value SHALL also make it FALSE, as before.

#### Scenario: Page stops
- **WHEN** an entry has `timeout_ms` 300, `Press` (page 2) has a `valid_location`, and the sender keeps sending page 1 but stops page 2
- **THEN** about 300 ms after the last page 2 frame the `Press` valid bit goes FALSE while the entry's status bit stays TRUE

### Requirement: Sending multiplexed messages
A send entry (`raw.tx` or `j1939.tx`) with switches MAY have `pages`: `program` (default), `all` or `rotate`. With `program`, each send SHALL pack the page that the switches' output locations select. With `all`, each periodic send SHALL send every page back to back; with `rotate`, each periodic send SHALL send the next page. Only the page's active signals SHALL be packed; other bits SHALL come from `data_location` and `fill` (raw) or be set to 1 (J1939).

#### Scenario: Program picks the page
- **WHEN** send entry `Display` has `pages` `program`, switch `Line` at `%QB20`, `period_ms` 100, and the program sets `Line` to 2
- **THEN** every 100 ms the bus carries `Display` with `Line` 2 and line 2's signals

#### Scenario: All pages
- **WHEN** `Display` has `pages` `all`, `period_ms` 100 and signals on `Line` values 1, 2 and 3
- **THEN** every 100 ms three frames go out, with `Line` 1, 2 and 3

#### Scenario: Rotate
- **WHEN** the same entry has `pages` `rotate`
- **THEN** one frame goes out every 100 ms and `Line` cycles 1, 2, 3, 1

### Requirement: Page list of a send entry
With `pages` `all` or `rotate`, switches SHALL NOT have an `iec_location`, and the page list SHALL be every combination of switch values the message's `mux.values` name, ranges expanded, in ascending order. More than 64 pages SHALL be rejected naming the message.

#### Scenario: Switch location in all mode
- **WHEN** an entry with `pages` `all` gives its switch an `iec_location`
- **THEN** the file is rejected saying the plugin sets the switch in this mode

#### Scenario: Too many pages
- **WHEN** an entry with `pages` `rotate` has a signal with `mux.values` [[0, 199]]
- **THEN** the file is rejected naming the message, the 200 pages and the 64-page limit, and suggesting `program`

### Requirement: Changes, triggers and requests by page
On change, `program` SHALL send when any output location changed, `all` SHALL send the pages with a changed active signal (an always-active signal counts for every page), and `rotate` SHALL send the next page with a pending change, all no sooner than `min_gap_ms`. A trigger edge (raw) and a J1939 request SHALL send the selected page (`program`), every page (`all`) or the next page (`rotate`).

#### Scenario: One page changed
- **WHEN** `Display` has `pages` `all`, `on_change` and no period, and the program changes only a line 2 signal
- **THEN** one frame goes out, with `Line` 2

#### Scenario: Request for a multiplexed PGN
- **WHEN** ECU 3 requests a PGN whose `tx` entry has `pages` `all` and three pages
- **THEN** the network sends the three pages

### Requirement: Unknown pages on send
In `program` mode, switch outputs that select no page SHALL send the frame with the switches and always-active signals only, and the entry's diagnostics status SHALL show `unknown_page`.

#### Scenario: Program sets an unused page
- **WHEN** the program sets `Line` to 9 and no signal is on line 9
- **THEN** the frame goes out with `Line` 9 and the always-active signals, and the online view shows `unknown_page` for `Display`
