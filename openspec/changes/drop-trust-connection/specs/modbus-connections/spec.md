## MODIFIED Requirements

### Requirement: Connections in the config
A bridge config MAY have `bridge.connections`, a list of objects, each with `kind` (`openplc`, `plc`, `nodered` or `hmi`), a unique `name` (1-64 characters), `address` (an IP address), `writes` (boolean), the kind's own fields and `map_hash` (the map hash of the last download). The PC check SHALL refuse an unknown kind (`trust` included: truST connects as an Other PLC), a duplicate name, a bad address and more than one `openplc` entry, naming the entry's path.

#### Scenario: Two connections
- **WHEN** a bridge config has an `openplc` connection and an `hmi` connection named `Line HMI` at `192.168.10.20` with `writes` false
- **THEN** the check passes and the Modbus bridge page lists both

#### Scenario: Duplicate name
- **WHEN** two connections are both named `Line HMI`
- **THEN** the check fails naming `bridge.connections[1].name`

### Requirement: Connection kinds
Each kind SHALL have its own fields and download:
- `openplc`: `poll_ms` (5-1000, default 10), `remote_device` (default `canworks`), `iec_base`; address `127.0.0.1`, `writes` true; files kept in sync by Save;
- `plc`: `format` (`plcopen` or `st`), `library`, `bridge_host`, `blocks`; the PLCopen or ST PLC link export;
- `nodered`: `period_ms`, `bridge_host`, `blocks`; the Node-RED flow;
- `hmi`: `format` (`csv`, `json` or `st`); the register map or ST variables.

`blocks` SHALL be `none` (default), `sdo_send`, `receive` or `all`.

#### Scenario: Node-RED download
- **WHEN** the user presses Download on a Node-RED connection with `bridge_host` 192.168.10.5
- **THEN** the browser gets the same file `canworks-deploy --export-nodered` writes for that host and period

#### Scenario: Other PLC as ST
- **WHEN** an Other PLC connection has `format` `st`
- **THEN** its Download gives the same file `--export-modbus-map OUT.st` writes for the config

#### Scenario: truST with receiving blocks
- **WHEN** a config has a connection with `kind` `trust` (any `blocks`, `receive` included)
- **THEN** the check fails naming `bridge.connections[0].kind` and listing `openplc`, `plc`, `nodered` and `hmi`

### Requirement: PLC inputs while the bridge is lost
For the OpenPLC and Other PLC connections, the generated `canworks_in` SHALL, while `canworks.ok` is FALSE, set every typed input of a status, state or timeout location (a `*_location` field other than an entry's or signal's `iec_location`: node status bits and state bytes, the master's state and bus state, PDO timeout bits, raw and J1939 message status) to 0. The other typed inputs SHALL follow the connection's `inputs_on_loss`: `"hold"` (default) keeps their last values, `"zero"` sets them to 0. The connection row SHALL offer the choice as "Inputs when the bridge is lost: keep last values / set to 0", and a change SHALL mark the connection's files out of date. The Node-RED package's canworks in node SHALL follow the same rule when its connection to the bridge is lost: it sends 0 or false for those values, for every live-list `.operational` value and for `bridge.bus_ok`, and keeps the other values. A download made before a change of `inputs_on_loss` SHALL show as out of date (`stale` in the connection) until the next download.

#### Scenario: Bridge killed under OpenPLC
- **WHEN** the bridge is killed while OpenPLC runs a program with node 23's status bit and an analogue input, with the default `inputs_on_loss`
- **THEN** within the stale time `canworks.ok` is FALSE, node 23's status bit is FALSE, and the analogue input keeps its last value

#### Scenario: Zero on loss
- **WHEN** the same happens with `"inputs_on_loss": "zero"`
- **THEN** the analogue input reads 0 as well

### Requirement: Connections that cannot be downloaded
For each Other PLC connection, the check SHALL warn about every reason its Download would be refused, such as no PLC link. Each warning SHALL carry the export's own text and the path of the field to change, and `canworks-deploy --check` SHALL print the same warnings. The connection row SHALL show "Cannot download" with the first reason.

#### Scenario: OpenPLC and truST
- **WHEN** a config has an OpenPLC connection (mailboxes on, `watchdog_ms` 50) and the user adds an Other PLC connection for a truST PLC
- **THEN** Problems has no map-size or watchdog warning for it: those were truST's own limits, and the row reads "Not downloaded yet"

#### Scenario: Other PLC without the PLC link
- **WHEN** a bridge config without `plc_link` has an Other PLC connection with format PLCopen XML
- **THEN** Problems shows a warning that the Download would be refused for the missing PLC link before any Download, and the row reads "Cannot download"

### Requirement: Canworks blocks choice of a connection
Each `plc` and `nodered` connection row SHALL offer "canworks blocks": None, SDO and send (one request mailbox), SDO, send and receive (also the receive mailbox) or All (also 4 cyclic jobs and network info), and SHALL show the choice with the parts it needs. Node-RED SHALL offer the choice only without the PLC link: with it the flow is read-only, and the check SHALL refuse a Node-RED `blocks` other than `none`.

#### Scenario: Row text
- **WHEN** an Other PLC connection has SDO and send
- **THEN** its row reads "canworks blocks: SDO and send (1 request mailbox)"

### Requirement: Mailboxes follow the connections
When a connection's canworks blocks choice changes, the configurator SHALL add the missing parts to `bridge.mailboxes` in the same undo step and place the areas, keep parts that are already on, and mark the connection Out of date. A connection whose choice needs a part that is off (a config edited by hand) SHALL be an error in Problems with **Turn on what the program uses**.

#### Scenario: truST with SDO blocks
- **WHEN** a config without mailboxes has an Other PLC connection for a truST PLC and the user picks SDO and send
- **THEN** in one undo step `bridge.mailboxes` becomes one request mailbox with receive, network info and cyclic jobs off, the areas are placed, and the row reads Out of date

#### Scenario: Choice back to None
- **WHEN** the only connection that needed the mailboxes is set to None
- **THEN** the mailboxes stay as they are, and Problems shows the warning that nothing needs them, with Turn off the mailboxes

### Requirement: One program owns the mailboxes
The mailboxes' request words, tickets and receivers assume one client. At most one connection SHALL have a canworks blocks choice other than None, and none when the config has an OpenPLC connection, whose program owns them. Problems SHALL show an error naming both connections otherwise.

#### Scenario: Second mailbox user
- **WHEN** an Other PLC connection has SDO and send, and the user picks SDO, send and receive on a Node-RED connection
- **THEN** Problems shows an error naming both connections, saying only one program can use the mailboxes

### Requirement: Any second writer next to a PLC link
With `plc_link` true, every connection other than the one with the PLC link that has `writes` true SHALL get the Problems warning naming it, whatever its kind. The Add connection dialog SHALL leave Writes off for a new connection while a PLC link exists.

#### Scenario: truST next to OpenPLC
- **WHEN** a config has an OpenPLC connection and the user adds an Other PLC connection for a truST PLC
- **THEN** the new row has Writes off, and ticking it gives the warning naming the Other PLC connection

### Requirement: Mailbox warning counts the connections
The warning that nothing uses the mailboxes, and its Turn off fix, SHALL appear only when neither the OpenPLC program nor any connection's canworks blocks choice needs them.

#### Scenario: truST blocks next to OpenPLC
- **WHEN** a config has an OpenPLC connection whose program declares no mailbox block and an Other PLC connection for a truST PLC with canworks blocks SDO and send
- **THEN** Problems has no Turn off the mailboxes warning

## REMOVED Requirements

### Requirement: Fixes for a truST connection
**Reason**: The truST connection kind is removed (Toni, 2026-10-24); its watchdog floor and one-request map limit, which these fixes answered, go with it.
**Migration**: None (not in real use).
