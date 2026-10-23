## MODIFIED Requirements

### Requirement: Function blocks section
The Modbus bridge page of a bridge config SHALL have a **Function blocks** section with the switch "Mailboxes for the canworks mailbox blocks" and, while on, the number of request mailboxes (0-4), the receive mailbox on or off with its receive blocks (1 or 2), the number of cyclic jobs (0-16), network info on or off and the input and output areas with Suggest, writing `bridge.mailboxes`. Turning it on SHALL place both areas in free ranges.

Whether the switch is on or off, the section SHALL show:
- a **Works without mailboxes** list: the config's values, `CO_NMT`, `CO_NODE_LIVE`, and `CO_SDO_READ` and `CO_SDO_WRITE` up to 4 bytes;
- a **Needs mailboxes** table: each part, the blocks that need it (for example "CAN_RECEIVE, J1939_RECEIVE and CO_RECV_EMCY" for the receive mailbox) and the config-only alternative where one exists (an `rx` message for `CAN_RECEIVE`, a periodic `tx` message for `CAN_SEND_CYCLIC`, `emcy_code_location` for the latest EMCY per node, `bus_state_location` for the bus state);
- the cost as a difference against the map without mailboxes: the extra input and holding registers and, with an OpenPLC connection, the Modbus requests per poll with and without them against the budget of 40 (with the switch off: what the default parts would add);
- the expected receive rate with the receive mailbox on ("about N CAN frames/s at this poll": the CAN records per batch times the poll rate, halved);
- who needs which part: each connection's canworks blocks choice and the mailbox blocks the OpenPLC program declares.

With an OpenPLC connection, a count change SHALL move both areas to free ranges at once, and the section SHALL say that the editor project needs **Update declarations** and a new Build. A new config, adding a connection of any kind and a target change SHALL NOT turn the mailboxes on; only the switch, a connection's canworks blocks choice and **Turn on what the program uses** do.

#### Scenario: New OpenPLC config
- **WHEN** the user creates a new Modbus bridge config and adds an OpenPLC connection
- **THEN** the config has no `bridge.mailboxes`, the section is off and shows the Works without mailboxes list, the Needs mailboxes table and "+227 input / +79 holding registers, 7 instead of 5 Modbus requests per poll" for the defaults

#### Scenario: Turn on the receive mailbox
- **WHEN** the user turns on the receive mailbox of a config with an OpenPLC connection
- **THEN** the areas move to free ranges, the register and request counts grow, and the page says to run Update declarations and build again

#### Scenario: Second receive block
- **WHEN** the user sets receive blocks to 2 in a config with an OpenPLC connection and a 10 ms poll
- **THEN** the areas move to free ranges, the register and request counts grow by 120 registers and one request, and the expected rate reads about 1050 CAN frames/s

#### Scenario: Who needs them
- **WHEN** the OpenPLC program declares a `CAN_RECEIVE` in `main` and a truST connection has canworks blocks "SDO and send"
- **THEN** the section lists "OpenPLC program: request and receive mailbox (CAN_RECEIVE in main)" and the truST connection with "1 request mailbox"

### Requirement: New editor project in standalone mode
In standalone mode the page SHALL offer "New editor project" next to "move into project". It SHALL ask for a parent folder (prefilled with the home folder, as "move into project" does), a project name, the task interval (default `T#20ms`) and whether to install the canworks library in the project ("Install the canworks library in the project", unchecked by default, with a hint that the mailbox blocks also need the bridge's mailboxes, which Problems offers once the program declares them). It SHALL create the project as `canopen-editor-project` describes, and then switch to project mode on the new project. It SHALL require the config to be saved first and SHALL show the reason when creation is refused. The standalone folder SHALL be left unchanged.

#### Scenario: Create and switch
- **WHEN** the user has saved a standalone config in `~/canworks/rtd`, chooses "New editor project", picks `~/workspace` and the name `rtd-monitor`
- **THEN** `~/workspace/rtd-monitor` is created with the config in its `canworks/` folder and `main` declaring its I/O, and the page shows mode "project rtd-monitor" with every CANopen entry marked as declared

#### Scenario: Function blocks enabled
- **WHEN** the user ticks "Install the canworks library in the project" in the dialog
- **THEN** the project is created as with `--blocks`, the config still has no mailboxes, and the page shows how to install the library when the creation output says it is missing

#### Scenario: Unsaved changes
- **WHEN** the config has unsaved changes
- **THEN** the page asks the user to save first and creates nothing

#### Scenario: Name taken
- **WHEN** `~/workspace/rtd-monitor` already exists
- **THEN** the dialog says the folder exists and stays open, nothing is written and the page stays in standalone mode

## ADDED Requirements

### Requirement: Mailbox blocks the OpenPLC program declares
For a config with an OpenPLC connection, Check and Save SHALL scan the editor project's Structured Text POUs and global variable lists for instances of mailbox blocks, ignoring comments and strings and leaving out the generated `canworks_in` and `canworks_out`. For each mailbox part that a declared block needs and the config lacks, Problems SHALL show an error naming the POU, the block and the part, with **Turn on what the program uses**.

#### Scenario: Program receives frames
- **WHEN** `main` declares `rx : CAN_RECEIVE;` and the config has no mailboxes
- **THEN** Problems shows an error "main declares CAN_RECEIVE, which needs the request and receive mailboxes" with Turn on what the program uses

#### Scenario: Commented out
- **WHEN** `main` has `(* rx : CAN_RECEIVE; *)` and no other mailbox block
- **THEN** no mailbox error is shown

### Requirement: Turn on what the program uses
**Turn on what the program uses** SHALL, in one undo step, turn on exactly the parts the declared blocks need and place both areas in free ranges. The parts are: one request mailbox; the receive mailbox for a receiving block; one cyclic job per declared `CAN_SEND_CYCLIC` instance (at least 4, at most 16); and network info for an info block.

#### Scenario: Only what is needed
- **WHEN** the program declares one `CAN_RECEIVE` and one `CO_SDO_READ_STRING`, and the user presses Turn on what the program uses
- **THEN** the config gets one request mailbox and the receive mailbox, without cyclic jobs or network info, and one Undo removes them again

### Requirement: Mailboxes nobody needs
When the config has mailboxes and neither the OpenPLC program nor any connection's canworks blocks choice needs them, Problems SHALL show an info with the Modbus requests per poll the mailboxes take, and **Turn off the mailboxes**, which removes `bridge.mailboxes` in one undo step.

#### Scenario: Mailboxes nobody uses
- **WHEN** the config has the default mailboxes, the program declares no mailbox block and no connection has a canworks blocks choice other than None
- **THEN** Problems shows an info saying the mailboxes take 2 of the 7 Modbus requests per poll, and Turn off the mailboxes removes `bridge.mailboxes` in one undo step
