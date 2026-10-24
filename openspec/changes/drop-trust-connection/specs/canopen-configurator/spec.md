## MODIFIED Requirements

### Requirement: Target of a new config
New config… SHALL ask "What runs the CAN networks?" with two cards: **Modbus bridge** (canworks-bridge runs the networks and serves Modbus TCP registers; the card lists OpenPLC, other PLCs, Node-RED and HMI, SCADA or scripts as what it works with) and **CODESYS** (a CODESYS PLC runs the CANopen master). Modbus bridge SHALL be preselected. Then it SHALL ask for the name and location, and Create SHALL write the empty config before the page opens it.

#### Scenario: New Modbus bridge config
- **WHEN** the user creates a new Modbus bridge config and reloads the page
- **THEN** the folder holds a config with a `bridge` object and no connections, and the page shows it with the Modbus bridge target and "Saved"

#### Scenario: New CODESYS config
- **WHEN** the user creates a new config with target CODESYS
- **THEN** the config is version 2 with a `codesys` object, it is on disk, and the page shows the CODESYS target

#### Scenario: New OpenPLC config with an editor project
- **WHEN** `openplc-cli` is found, the user creates a new Modbus bridge config and adds an OpenPLC connection with New editor project… in `~/plc/new-machine`
- **THEN** the dialog shows "Creating the editor project…" until `~/plc/new-machine` is an OpenPLC Editor project with the config in its `canworks/` folder holding an `openplc` connection and `devices/remote/canworks.json`, and the page shows the mode "project new-machine"

#### Scenario: No editor command-line tool
- **WHEN** `openplc-cli` is not found and the user adds an OpenPLC connection to a standalone config
- **THEN** New editor project… is disabled with the reason, and the connection is added to the config in its folder

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
- **WHEN** the OpenPLC program declares a `CAN_RECEIVE` in `main`, or in a config without OpenPLC an Other PLC connection "Line" has canworks blocks SDO and send
- **THEN** the section says "The OpenPLC program declares CAN_RECEIVE (main)", or "Line: canworks blocks SDO and send (1 request mailbox)"

### Requirement: Export for another PLC
The Other PLC connection with `format` `plcopen` SHALL download the `--export-plcopen --for generic` folder as a zip. Add connection SHALL NOT offer a truST kind: truST is an Other PLC. Its settings SHALL hold the bridge address the PLC uses (default: `listen` when it is neither a wildcard nor a loopback address) and whether to include the library (on).

#### Scenario: Other PLC connection
- **WHEN** the user downloads an Other PLC connection with format PLCopen XML and bridge address 192.168.10.5 on a config with `plc_link`
- **THEN** the zip equals `canworks-deploy --export-plcopen --for generic --bridge-host 192.168.10.5` for the config

#### Scenario: truST connection
- **WHEN** the user opens Add connection… on the Modbus bridge page
- **THEN** it lists OpenPLC, Other PLC, Node-RED and HMI, SCADA or script, and no truST

#### Scenario: Only on Modbus bridge configs
- **WHEN** a CODESYS config is open
- **THEN** there is no Connections list and nothing offers a PLCopen download

### Requirement: Reachability warnings for other PLCs
A PLCopen or ST connection whose bridge address is empty SHALL show a warning on its row and in Problems. Connection addresses that cannot reach `listen` SHALL be the error of `modbus-connections` "Connections reach the bridge".

#### Scenario: No bridge address
- **WHEN** an Other PLC connection has no bridge address and `listen` is `0.0.0.0:502`
- **THEN** its row and Problems warn that the PLC needs the bridge's address

#### Scenario: Loopback listen
- **WHEN** a config with `plc_link` listens on `127.0.0.1:1502` and has an Other PLC connection at 192.168.10.7
- **THEN** Problems shows the error naming the Other PLC connection with Listen on all addresses
