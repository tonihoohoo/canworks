# modbus-connections Specification

## Purpose
List who talks to the Modbus bridge (OpenPLC, truST, another PLC, Node-RED, an HMI or script) as connections in the config: each gets its own Settings and Download, the bridge's writers follow them, and an OpenPLC connection sets the bridge up for OpenPLC's Modbus master.

## Requirements

### Requirement: Connections in the config
A bridge config MAY have `bridge.connections`, a list of objects, each with `kind` (`openplc`, `trust`, `plc`, `nodered` or `hmi`), a unique `name` (1-64 characters), `address` (an IP address), `writes` (boolean), the kind's own fields and `map_hash` (the map hash of the last download). The PC check SHALL refuse an unknown kind, a duplicate name, a bad address and more than one `openplc` entry, naming the entry's path.

#### Scenario: Two connections
- **WHEN** a bridge config has an `openplc` connection and an `hmi` connection named `Line HMI` at `192.168.10.20` with `writes` false
- **THEN** the check passes and the Modbus bridge page lists both

#### Scenario: Duplicate name
- **WHEN** two connections are both named `Line HMI`
- **THEN** the check fails naming `bridge.connections[1].name`

### Requirement: Connection kinds
Each kind SHALL have its own fields and download:
- `openplc`: `poll_ms` (5-1000, default 10), `remote_device` (default `canworks`), `iec_base`; address `127.0.0.1`, `writes` true; files kept in sync by Save;
- `trust` and `plc`: `format` (`plcopen`, or `st` for `plc`), `library`, `bridge_host`, `blocks`; the PLCopen or ST PLC link export;
- `nodered`: `period_ms`, `bridge_host`, `blocks`; the Node-RED flow;
- `hmi`: `format` (`csv`, `json` or `st`); the register map or ST variables.

`blocks` SHALL be `none` (default), `sdo_send`, `receive` or `all`; for `trust` only `none` and `sdo_send`.

#### Scenario: Node-RED download
- **WHEN** the user presses Download on a Node-RED connection with `bridge_host` 192.168.10.5
- **THEN** the browser gets the same file `canworks-deploy --export-nodered` writes for that host and period

#### Scenario: Other PLC as ST
- **WHEN** an Other PLC connection has `format` `st`
- **THEN** its Download gives the same file `--export-modbus-map OUT.st` writes for the config

#### Scenario: truST with receiving blocks
- **WHEN** a truST connection has `blocks` `receive`
- **THEN** the check fails naming `bridge.connections[0].blocks` and saying truST moves one request each way, so only None or SDO and send fit

### Requirement: Connections list on the Modbus bridge page
The Modbus bridge page SHALL show **Connections** first: one row per connection with its name, kind, address, whether it writes, its state and its actions, and **Add connection** listing the five kinds, each with one line on what it gets. With no connection the list SHALL say that programs, HMIs and Node-RED connect here. Each change SHALL be one undo step.

#### Scenario: Add an HMI
- **WHEN** the user picks Add connection → HMI, SCADA or script, names it `Line HMI` with address 192.168.10.20 and leaves Writes off
- **THEN** the list shows `Line HMI` as Not downloaded yet, and `bridge.writers` is unchanged

#### Scenario: Empty list
- **WHEN** a new Modbus bridge config's bridge page is open
- **THEN** Connections says programs, HMIs and Node-RED connect here and offers Add connection

### Requirement: Out-of-date connections
A Download SHALL store the current map hash in the connection's `map_hash`. A connection whose `map_hash` differs from the config's map hash SHALL show "Out of date" with **Download again**, and Problems SHALL list one warning per such connection that opens the bridge page. Without `map_hash` the row SHALL read "Not downloaded yet" with no warning. An OpenPLC connection SHALL show the result of "Out-of-date OpenPLC editor files" instead: In sync, or Out of date with Save.

#### Scenario: Value moved
- **WHEN** an HMI connection was downloaded and the user then moves a TPDO entry to another location
- **THEN** the row reads Out of date, Problems warns naming the connection, and Download again clears both

### Requirement: Writers follow the connections
When connections change, the configurator SHALL set `bridge.writers` to the sorted addresses of the connections with `writes` true, in the same undo step, and the page SHALL show them as "Who may write" instead of a Writers field. A config whose `writers` differ from its connections SHALL get a warning with **Use the connections' addresses**. A config without connections SHALL keep its `writers`.

#### Scenario: Node-RED writes
- **WHEN** a config without `plc_link` has an HMI connection at 192.168.10.20 with Writes on, and the user ticks Writes on a Node-RED connection at 192.168.10.30
- **THEN** `bridge.writers` is `["192.168.10.20", "192.168.10.30"]`, and one Undo restores the previous list

### Requirement: Only the PLC writes with a PLC link
With `plc_link` true the PLC owns the outputs and the mailboxes, whose owner words and tickets assume one client. A `nodered` or `hmi` connection with `writes` true SHALL then get a Problems warning naming it.

#### Scenario: Writer next to a PLC link
- **WHEN** a config has an OpenPLC connection and the user ticks Writes on a Node-RED connection
- **THEN** Problems warns that with the PLC link only the PLC writes outputs and mailboxes, naming the Node-RED connection

### Requirement: Connections reach the bridge
A connection whose address is not loopback while `listen` is a loopback address SHALL be an error naming the connection, with **Listen on all addresses**, which keeps the port and sets the address to `0.0.0.0`.

#### Scenario: HMI on the network
- **WHEN** a config listens on `127.0.0.1:1502` and the user adds an HMI connection at 192.168.10.20
- **THEN** Problems shows the error naming the HMI, and Listen on all addresses sets `listen` to `0.0.0.0:1502`

### Requirement: OpenPLC connection bridge settings
Adding an OpenPLC connection SHALL, in one undo step, set `plc_link` true, `word_order` `low_first`, `listen` `127.0.0.1:1502` when unset or when no other connection is on an address other than loopback, `watchdog_ms` 5 × `poll_ms` (at least 50) when unset, add a live list for every CANopen master network and repack. It SHALL NOT turn the mailboxes on: the program's mailbox blocks do that through Problems (canopen-configurator "Mailbox blocks the OpenPLC program declares"). With an OpenPLC connection the check SHALL refuse `plc_link` false and `word_order` `high_first`.

#### Scenario: Add OpenPLC to a new bridge config
- **WHEN** the user adds an OpenPLC connection to a new Modbus bridge config with one network
- **THEN** the config has `plc_link` true, `listen` `127.0.0.1:1502`, `writers` `["127.0.0.1"]`, `watchdog_ms` 50 and a live list, no `bridge.mailboxes`, and the values start after the PLC link header

#### Scenario: High word first
- **WHEN** a config with an OpenPLC connection has `word_order` `high_first`
- **THEN** the check fails saying OpenPLC's Modbus master reads 32- and 64-bit values lowest word first

### Requirement: OpenPLC connection and the editor project
On a standalone config, adding an OpenPLC connection SHALL offer **New editor project…** and **Move into project…**; either SHALL add the connection. New editor project and Move into project on a config without one SHALL add it too. A config inside an editor project without an OpenPLC connection SHALL get **Use with this OpenPLC project**. Removing the OpenPLC connection SHALL ask first and leave the editor files on disk.

#### Scenario: Remove OpenPLC
- **WHEN** the user removes the OpenPLC connection of a project and confirms
- **THEN** the connection is gone, the editor files stay on disk, and the next Save writes no editor files

#### Scenario: Hand-made project config
- **WHEN** a config inside an OpenPLC Editor project has a `bridge` and no OpenPLC connection
- **THEN** the Project page offers Use with this OpenPLC project, which adds the connection as Add connection does

### Requirement: PLC inputs while the bridge is lost
For the OpenPLC, truST and Other PLC connections, the generated `canworks_in` SHALL, while `canworks.ok` is FALSE, set every typed input of a status, state or timeout location (a `*_location` field other than an entry's or signal's `iec_location`: node status bits and state bytes, the master's state and bus state, PDO timeout bits, raw and J1939 message status) to 0. The other typed inputs SHALL follow the connection's `inputs_on_loss`: `"hold"` (default) keeps their last values, `"zero"` sets them to 0. The connection row SHALL offer the choice as "Inputs when the bridge is lost: keep last values / set to 0", and a change SHALL mark the connection's files out of date. The Node-RED package's canworks in node SHALL follow the same rule when its connection to the bridge is lost: it sends 0 or false for those values, for every live-list `.operational` value and for `bridge.bus_ok`, and keeps the other values. A download made before a change of `inputs_on_loss` SHALL show as out of date (`stale` in the connection) until the next download.

#### Scenario: Bridge killed under OpenPLC
- **WHEN** the bridge is killed while OpenPLC runs a program with node 23's status bit and an analogue input, with the default `inputs_on_loss`
- **THEN** within the stale time `canworks.ok` is FALSE, node 23's status bit is FALSE, and the analogue input keeps its last value

#### Scenario: Zero on loss
- **WHEN** the same happens with `"inputs_on_loss": "zero"`
- **THEN** the analogue input reads 0 as well

### Requirement: Bus state for the PLC
The `canworks` global variable list of a PLC-link connection SHALL have `bus_ok` (BOOL), which the generated `canworks_in` SHALL set TRUE while `canworks.ok` is TRUE and status block byte 7 bit 1 is clear (modbus-bridge "Status block").

#### Scenario: Cable fault
- **WHEN** the bridge's CAN interface goes down while the PLC runs
- **THEN** `canworks.ok` stays TRUE and `canworks.bus_ok` becomes FALSE, and both are TRUE again after the interface is back

### Requirement: Connections that cannot be downloaded
For each truST and Other PLC connection, the check SHALL warn about every reason its Download would be refused: no PLC link, or for truST a map larger than one request each way or a watchdog under 500 ms. Each warning SHALL carry the export's own text and the path of the field to change, and `canworks-deploy --check` SHALL print the same warnings. The connection row SHALL show "Cannot download" with the first reason.

#### Scenario: OpenPLC and truST
- **WHEN** a config has an OpenPLC connection (mailboxes on, `watchdog_ms` 50) and the user adds a truST connection
- **THEN** Problems shows a map-size warning and a watchdog warning before any Download, and the truST row reads "Cannot download"

### Requirement: Fixes for a truST connection
Problems SHALL offer **Set the watchdog to 500 ms** on the watchdog warning and **Trim the mailboxes for truST** on the map-size warning, each one undo step; the trim SHALL keep one request mailbox and nothing else and repack, and its title, like the map-size warning's text, SHALL name the blocks an OpenPLC connection of the same config loses.

#### Scenario: Fixed
- **WHEN** the user presses Trim the mailboxes for truST and Set the watchdog to 500 ms
- **THEN** both warnings go, the row reads "Not downloaded yet", and the truST Download gives the zip

### Requirement: Canworks blocks choice of a connection
Each `trust`, `plc` and `nodered` connection row SHALL offer "canworks blocks": None, SDO and send (one request mailbox), SDO, send and receive (also the receive mailbox) or All (also 4 cyclic jobs and network info), and SHALL show the choice with the parts it needs. truST SHALL offer only None and SDO and send. Node-RED SHALL offer the choice only without the PLC link: with it the flow is read-only, and the check SHALL refuse a Node-RED `blocks` other than `none`.

#### Scenario: Row text
- **WHEN** an Other PLC connection has SDO and send
- **THEN** its row reads "canworks blocks: SDO and send (1 request mailbox)"

### Requirement: Mailboxes follow the connections
When a connection's canworks blocks choice changes, the configurator SHALL add the missing parts to `bridge.mailboxes` in the same undo step and place the areas, keep parts that are already on, and mark the connection Out of date. A connection whose choice needs a part that is off (a config edited by hand) SHALL be an error in Problems with **Turn on what the program uses**.

#### Scenario: truST with SDO blocks
- **WHEN** a config without mailboxes has a truST connection and the user picks SDO and send
- **THEN** in one undo step `bridge.mailboxes` becomes one request mailbox with receive, network info and cyclic jobs off, the areas are placed, the row reads Out of date, and the PLCopen download is not refused

#### Scenario: Choice back to None
- **WHEN** the only connection that needed the mailboxes is set to None
- **THEN** the mailboxes stay as they are, and Problems shows the warning that nothing needs them, with Turn off the mailboxes

### Requirement: One program owns the mailboxes
The mailboxes' request words, tickets and receivers assume one client. At most one connection SHALL have a canworks blocks choice other than None, and none when the config has an OpenPLC connection, whose program owns them. Problems SHALL show an error naming both connections otherwise.

#### Scenario: Second mailbox user
- **WHEN** a truST connection has SDO and send, and the user picks SDO, send and receive on a Node-RED connection
- **THEN** Problems shows an error naming both connections, saying only one program can use the mailboxes
