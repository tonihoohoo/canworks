## ADDED Requirements

### Requirement: Mailbox detection in programs
The scan for mailbox blocks SHALL count arrays of a block with any bounds and dimensions, namespaced block types, blocks inside user function blocks once per instance, and blocks in every POU file of the editor project. When a count cannot be worked out, Turn on what the program uses SHALL give the most for that part and Problems SHALL NOT offer to turn the mailboxes off.

#### Scenario: Arrays and function blocks
- **WHEN** main declares `rx : ARRAY[1..N] OF CAN_RECEIVE` with constant N 3, `cy : ARRAY[0..1, 0..1] OF CAN_SEND_CYCLIC` and `a : ARRAY[0..7] OF Axis` where Axis holds one `canworks.CAN_SEND_CYCLIC`
- **THEN** the scan finds the receive mailbox needed and 12 cyclic jobs

#### Scenario: Unknown size
- **WHEN** an array bound is an expression the scan cannot work out
- **THEN** Turn on what the program uses sets the maximum for that part and no Turn off fix is offered

### Requirement: New editor project needs openplc-cli
The Project page's **New editor project…** SHALL be disabled with the reason when openplc-cli is not found, as in the Add connection dialog.

#### Scenario: No openplc-cli
- **WHEN** the configurator runs without openplc-cli and the user opens the Project page of an OpenPLC config
- **THEN** New editor project is disabled and its title names openplc-cli

### Requirement: Restarted configurator
A tab whose requests are refused because the configurator was restarted with a new session SHALL stop polling and say that the configurator was restarted, with a link to open it again.

#### Scenario: Old tab
- **WHEN** canworks-config is stopped and started again while a tab is open
- **THEN** the old tab shows the restarted notice within 2 s and sends no more requests

### Requirement: Project name in the header
When the header is short of room, the project chip SHALL shorten the target part before the project name.

#### Scenario: Update chip shown
- **WHEN** the update chip is shown at 1280 px with project virtual-plant
- **THEN** the project chip still shows "virtual-plant"

## MODIFIED Requirements

### Requirement: Function blocks section
The Modbus bridge page of a bridge config SHALL have a **Function blocks** section with the switch "Mailboxes for the canworks mailbox blocks" and, while on, the number of request mailboxes (0-4), the receive mailbox on or off with its receive blocks (1 or 2), the number of cyclic jobs (0-16), network info on or off and the input and output areas with Suggest, writing `bridge.mailboxes`. Turning it on SHALL place both areas in free ranges.

Whether the switch is on or off, the section SHALL show:
- a **Works without mailboxes** list: the config's values, `CO_NMT`, `CO_NODE_LIVE`, and `CO_SDO_READ` and `CO_SDO_WRITE` up to 4 bytes;
- a **Needs mailboxes** table: each part, the blocks that need it (for example "CAN_RECEIVE, J1939_RECEIVE and CO_RECV_EMCY" for the receive mailbox) and the config-only alternative where one exists (an `rx` message for `CAN_RECEIVE`, a periodic `tx` message for `CAN_SEND_CYCLIC`, `emcy_code_location` for the latest EMCY per node, `bus_state_location` for the bus state);
- the cost as a difference against the map without mailboxes: the extra input and holding registers and, with an OpenPLC connection, the Modbus requests per poll with and without them against the budget of 40 (with the switch off: what the default parts would add);
- the expected receive rate with the receive mailbox on ("about N CAN frames/s at this poll": the CAN records per batch times the poll rate, halved);
- who needs which part: each connection's canworks blocks choice and the mailbox blocks the OpenPLC program declares.

With an OpenPLC connection, a count change SHALL move both areas to free ranges at once, and the section SHALL say that the editor project needs a Save (or `canworks-deploy --into-project`) and a new Build. A new config, adding a connection of any kind and a target change SHALL NOT turn the mailboxes on; only the switch, a connection's canworks blocks choice and **Turn on what the program uses** do.

#### Scenario: New OpenPLC config
- **WHEN** the user creates a new Modbus bridge config and adds an OpenPLC connection
- **THEN** the config has no `bridge.mailboxes`, the section is off and shows the Works without mailboxes list, the Needs mailboxes table and "+227 input / +79 holding registers, 7 instead of 5 Modbus requests per poll" for the defaults

#### Scenario: Turn on the receive mailbox
- **WHEN** the user turns on the receive mailbox of a config with an OpenPLC connection
- **THEN** the areas move to free ranges, the register and request counts grow, and the page says to save the editor project and build again

#### Scenario: Second receive block
- **WHEN** the user sets receive blocks to 2 in a config with an OpenPLC connection and a 10 ms poll
- **THEN** the areas move to free ranges, the register and request counts grow by 120 registers and one request, and the expected rate reads about 1050 CAN frames/s

#### Scenario: Who needs them
- **WHEN** the OpenPLC program declares a `CAN_RECEIVE` in `main`, or in a config without OpenPLC a truST connection "Line" has canworks blocks SDO and send
- **THEN** the section says "The OpenPLC program declares CAN_RECEIVE (main)", or "Line: canworks blocks SDO and send (1 request mailbox)"
