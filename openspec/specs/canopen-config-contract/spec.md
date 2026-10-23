# canopen-config-contract Specification

## Purpose
Defines the CANopen JSON configuration as a stable, versioned contract shared by the bridge, the deploy tool, the configurator and the other PC tools.

## Requirements

### Requirement: Versioned configuration format
The configuration file SHALL carry an integer `schema_version`. A file without `schema_version` SHALL be read as version 1. The bridge and the deploy tool SHALL read versions 1 and 2. They SHALL reject a file whose `schema_version` is higher than the highest version they support, naming both versions.

#### Scenario: Version omitted
- **WHEN** a config has no `schema_version` field and is otherwise valid
- **THEN** it is read as version 1 and loads

#### Scenario: Version 2 loads
- **WHEN** a config has `schema_version: 2` and a valid `networks` list
- **THEN** the bridge and the deploy tool load it

#### Scenario: Version from the future
- **WHEN** a config has `schema_version: 3` and the bridge supports versions up to 2
- **THEN** the bridge logs an error naming version 3 and supported version 2, and stays inactive

### Requirement: Compatibility rules within a version
Within one `schema_version`, a later release of the bridge SHALL accept every file an earlier release accepted, with the same meaning. New optional fields MAY be added within a version. Removing a field, making an optional field required, or changing a field's meaning SHALL require a new `schema_version`. Unknown fields SHALL be ignored with a warning naming the field, so that a file written for a newer minor release still loads.

#### Scenario: Unknown field
- **WHEN** a version 1 config contains a field the bridge does not know
- **THEN** the bridge logs a warning naming the field and its JSON path, and loads the rest of the config

### Requirement: Pre-contract keys
The bridge and the deploy tool SHALL accept the top-level `interface` and `bitrate` keys used before this contract, reading them as an `adapter` of type `socketcan` with `configure_link` false (as before the contract, the bridge leaves the link alone), and SHALL log a deprecation warning. A config that has both `adapter` and either top-level key SHALL be rejected.

#### Scenario: Old-style config
- **WHEN** a config has top-level `interface: "vcan0"` and `bitrate: 125000` and no `adapter`
- **THEN** it loads as a SocketCAN adapter on `vcan0` at 125 kbit/s and a deprecation warning is logged

#### Scenario: Both styles at once
- **WHEN** a config has an `adapter` object and a top-level `interface`
- **THEN** the config is rejected with an error naming both keys

### Requirement: Simulation switches in the config
`canworks.json` version 1 SHALL accept an optional boolean `adapter.simulate` (the network is simulated), default false, and an optional boolean `simulate` on each node (the device is simulated), whose default is true on a simulated network and false on a real one. A config without them SHALL behave as before. The schema SHALL describe both, and the bridge and the deploy tool SHALL accept a config with simulated parts whose adapter would otherwise be valid.

#### Scenario: Old config
- **WHEN** a config written before this change is loaded
- **THEN** it loads unchanged, runs on its real adapter and simulates nothing

#### Scenario: Simulated network validates
- **WHEN** the example ping-pong config with `adapter.simulate: true` is checked against the schema
- **THEN** it validates

#### Scenario: One simulated node validates
- **WHEN** a config on `can0` with `"simulate": true` on one node is checked against the schema
- **THEN** it validates

### Requirement: Simulation file contract
The simulation file (`simulation.json`, next to `canworks.json`) SHALL carry its own integer `schema_version`, read as 1 when omitted, and the repository SHALL publish a JSON Schema (draft 2020-12) for it. The bridge, the standalone simulator and the PC tools SHALL reject a file whose version is higher than they support, naming both versions, and SHALL reject unknown keys. Checks the schema cannot express (objects that exist in the EDS, value sources on master-written objects, expression syntax and references) SHALL be documented next to it and run by the deploy tool's check as well as at load. Behaviour given for a node that is not simulated SHALL be kept and SHALL NOT be an error, so a node can be switched between real and simulated without editing the file.

#### Scenario: Unknown key
- **WHEN** a simulation file has `"nodes": {"5": {"sources": {...}, "sourcse": {...}}}`
- **THEN** it is rejected with a message naming `sourcse`

#### Scenario: Check without a runtime
- **WHEN** a user runs the deploy tool's check on a project whose simulation file has an expression with an unknown function
- **THEN** the check fails naming the node, the object and the function

#### Scenario: Behaviour for a real node
- **WHEN** the simulation file has sources for node 23 and node 23 is a real device in this config
- **THEN** the config loads, node 23 is not simulated, and the sources apply again when node 23 is switched to simulated

### Requirement: Version 2 layout
A version 2 file SHALL have `schema_version: 2`, a `networks` list, and MAY have a top-level `diagnostics` object with the fields version 1 has under `master.diagnostics`. It SHALL NOT have top-level `adapter`, `master`, `nodes`, `interface` or `bitrate`, nor `diagnostics` inside a network's `master`; each is rejected with a message naming where it belongs in version 2.

#### Scenario: Version 1 keys in a version 2 file
- **WHEN** a file has `schema_version: 2` and a top-level `nodes` list
- **THEN** it is rejected with an error saying nodes belong in `networks[].nodes` in version 2

#### Scenario: Diagnostics inside a network
- **WHEN** a version 2 file has `networks[0].master.diagnostics`
- **THEN** it is rejected with an error saying `diagnostics` is a top-level object in version 2

#### Scenario: Empty node lists with diagnostics
- **WHEN** a version 2 file has a top-level `diagnostics` and a network with `"nodes": []`
- **THEN** it loads, that network running as a scan-only network

### Requirement: Version 2 schema shares version 1 definitions
The repository SHALL publish `schema/canworks.v2.schema.json`. Its adapter, master and node definitions SHALL be the version 1 definitions, referenced rather than copied, so an optional field added to version 1 is accepted in version 2 too. Every example config SHALL validate against the schema of its own version.

#### Scenario: Field added to version 1
- **WHEN** a new optional `master` field is added to the version 1 schema
- **THEN** a version 2 file with that field in a network's `master` validates without changing the version 2 schema file

### Requirement: Writers use the lowest version that holds the config
The configurator and every tool that writes a config SHALL write version 1 when the config has one network without a `name` of its own (none, or one equal to the interface name), and version 2 otherwise. Reading a file and saving it unchanged SHALL keep its meaning.

#### Scenario: One network saved
- **WHEN** the configurator saves a config with one network on `can0` and no custom name
- **THEN** the file is version 1 with top-level `adapter`, `master` (holding `diagnostics` if set) and `nodes`

#### Scenario: Second network added
- **WHEN** the user adds a second network and saves
- **THEN** the file is version 2 with both networks and a top-level `diagnostics` if online access is on

#### Scenario: Back to one network
- **WHEN** the user removes the second network of a version 2 config whose remaining network has no custom name, and saves
- **THEN** the file is written as version 1

### Requirement: Slave network role
A version 2 network MAY have `role`, `"master"` (default) or `"slave"`. A slave network SHALL have `adapter` and `slave`, and SHALL NOT have `master` or `nodes`; a master network SHALL NOT have `slave`. Each misplaced key SHALL be rejected with a message naming the role it belongs to. Version 1 files SHALL NOT have `role` or `slave`.

#### Scenario: Slave network with nodes
- **WHEN** a network has `"role": "slave"` and a `nodes` list
- **THEN** the file is rejected with an error saying nodes belong to a master network

#### Scenario: Slave in a version 1 file
- **WHEN** a version 1 file has a top-level `slave`
- **THEN** it is rejected with an error saying slave networks need `schema_version: 2`

### Requirement: Slave object
The `slave` object SHALL have `node_id` (1-127, or null for LSS) and `eds`, and MAY have `objects`, `inputs_on_loss` (`"hold"` default or `"zero"`), `state_location`, `comm_ok_location`, `sync_count_location`, `emcy_code_location` and `error_register_location`. Each `objects` entry SHALL have `index`, `subindex` and `iec_location`, and MAY have `name`. The JSON Schema SHALL describe all of these.

#### Scenario: Example validates
- **WHEN** `config/slave/canopen_config.json` is checked against `schema/canworks.v2.schema.json`
- **THEN** it validates

### Requirement: One role per interface
Two networks on the same real adapter interface SHALL be rejected whatever their roles, so a master and a slave never share one real bus in the bridge. Simulated networks (`adapter.simulate: true`) with the same `interface` name SHALL share one simulated bus, allowed for at most one master network and one slave network. On such a bus, the master network's node with the slave network's node ID SHALL have `simulate: false`, so no simulated device answers in place of the bridge's slave.

#### Scenario: Master and slave on can0
- **WHEN** a master network and a slave network both use `can0`
- **THEN** the file is rejected with an error naming the interface and both networks

#### Scenario: Master and slave on one simulated bus
- **WHEN** a master network and a slave network both have `adapter.simulate: true` and `interface: "bench"`
- **THEN** the file loads and both networks run on one in-process simulated bus named `bench`

#### Scenario: Two masters on one simulated bus
- **WHEN** two master networks are simulated with the same `interface`
- **THEN** the file is rejected with an error naming the interface and both networks

#### Scenario: The slave's node simulated on the master
- **WHEN** a master network and a slave network with node ID 10 share simulated bus `bench`, and the master's node 10 is simulated (its default on a simulated network)
- **THEN** the file is rejected with an error naming node 10, both networks and `"simulate": false`

### Requirement: Configs with a slave network are version 2
Tools that write a config SHALL write version 2 whenever any network is a slave network, even when it is the only network.

#### Scenario: Only a slave
- **WHEN** the configurator saves a config whose one network is a slave
- **THEN** the file has `schema_version: 2` and that network has `"role": "slave"`

### Requirement: Gateway section in the schema
`schema/canworks.v2.schema.json` SHALL describe the top-level `gateway` object (`upper`, `routes`, `status`, `emcy_forward`, `on_upper_loss`, `sdo_bridge`, `sdo_bridge_write`), and a version 1 file SHALL NOT have `gateway`.

#### Scenario: Gateway example validates
- **WHEN** `config/gateway/canopen_config.json` is checked against the version 2 schema
- **THEN** it validates

### Requirement: Simulation file version 2
The repository SHALL publish a JSON Schema (draft 2020-12) for simulation file version 2: `schema_version` 2, an optional top-level `tick_ms`, and `networks`, an object whose keys are network names and whose values each allow `nodes`, `extra_devices` and `scenarios` exactly as in version 1. The bridge and the PC tools SHALL accept versions 1 and 2. A version 2 file SHALL be refused, naming the section, when a section names a network that is not in the config; a section for a network that simulates nothing SHALL be kept without error, as behaviour for a real node is. The checks the schema cannot express SHALL run per section against that network's nodes and EDS files, and their messages SHALL name the network.

#### Scenario: Unknown network
- **WHEN** a version 2 simulation file has a section `drivez` and the config's networks are `io` and `drives`
- **THEN** the check fails naming `drivez` and the config's network names

#### Scenario: Check names the network
- **WHEN** the `motion` section has a source on an object node 4's EDS does not have
- **THEN** the check fails naming network `motion`, node 4 and the object

#### Scenario: Version 1 still valid
- **WHEN** the single-network `config/rtd-sensor` example with its version 1 `simulation.json` is checked
- **THEN** it passes as before

#### Scenario: Machine file missing
- **WHEN** a version 2 section has `"machine": "machine.json"`
- **THEN** the check fails naming the section and the unknown key `machine`

#### Scenario: Gateway example validates
- **WHEN** `config/gateway/canopen_config.json` is checked against the version 2 schema
- **THEN** it validates

### Requirement: Raw messages in the schema
The version 2 JSON Schema SHALL describe protocol `none`, `adapter.listen_only` and the `raw` object with its `rx`, `tx` and signal entries, so an editor with JSON Schema support completes and checks them. Checks the schema cannot express (unique `tx` identifiers, signals inside the DLC, protocol ownership, location sizes and clashes) SHALL be made by the bridge and by the PC tools with the same messages, from shared test fixtures.

#### Scenario: Schema check of a raw message
- **WHEN** a config's `raw.rx` entry has `id` 0x800 without `extended`
- **THEN** the PC tools and the bridge both reject it naming the path and the 11-bit range

### Requirement: Configs with raw messages are version 2
A version 1 config SHALL NOT have `raw` or `listen_only`. Writers SHALL save version 2 whenever any network has `raw` or protocol `none`.

#### Scenario: Adding a raw message to a version 1 project
- **WHEN** the configurator adds a raw message to a project whose file is version 1
- **THEN** it saves the file as version 2 with one network holding the old content and the raw message

### Requirement: Bridge section in the schema
The version 2 schema SHALL define an optional top-level `bridge` object with:
- `listen` (required)
- `unit_id`, `word_order` (`high_first` or `low_first`), `max_clients`
- `writers` and `readers` (lists of addresses or prefixes)
- `watchdog_ms`, `on_client_loss` (`stop`, `zero` or `hold`)
- `status_location`, `control_location`, `live_lists`
- `sdo_bridge_location` (`request`, `response`) and `sdo_bridge_write`

The schema SHALL also define the `diagnostics.allow_config_upload` flag. A writer SHALL save a config with `bridge` as version 2.

#### Scenario: Bridge config validates
- **WHEN** `examples/modbus-bridge/canworks.json` is validated against the published version 2 schema
- **THEN** it is valid

### Requirement: Bridge configs are byte-addressed
A config with a `bridge` object SHALL be a bridge config. Its locations SHALL be byte-addressed (`%IW2` is input bytes 2 and 3) and checked as the modbus-bridge capability describes. Since every config the bridge runs is a bridge config, there is no other addressing.

#### Scenario: Bridge config uploaded to OpenPLC
- **WHEN** `canworks-deploy --config bridge.json --runtime HOST` is run with a bridge config
- **THEN** it fails as for any unknown option, since the deploy tool no longer uploads to an OpenPLC runtime

#### Scenario: Overlapping words
- **WHEN** a bridge config maps one entry at `%IW10` and another at `%IW11`
- **THEN** the bridge and the PC tools refuse it, naming both, since the two words share byte 11

### Requirement: Multiplexing in the schema
The version 2 config and simulation file schemas SHALL describe `multiplexer`, `mux`, raw `valid_location` and `pages`. Checks the schema cannot express (switch names, cycles, value ranges, per-page overlap and length, the page limit, switch locations per mode) SHALL be made by the bridge and the PC tools with the same messages, from shared test fixtures. Configs without these fields SHALL behave as before.

#### Scenario: Unknown switch name
- **WHEN** a raw signal has `mux.on` `Pgae` and the message has a switch `Page`
- **THEN** the PC tools and the bridge both reject the file naming the signal's path and the unknown switch

### Requirement: Remote link settings in the config
The schema and the config checks (bridge, bridge and PC tools) SHALL accept an optional `remote_link` object in the diagnostics settings (`diagnostics.remote_link` in version 2, `master.diagnostics.remote_link` in version 1) with `internet` (boolean, default false), `relays` (list of `https://` URLs, at most 8) and `pairing` (`"lan"`, `"anywhere"` or `"off"`, default `"lan"`). Other keys or values SHALL be rejected with the path of the bad field. The bridge and the bridge SHALL not otherwise act on it.

#### Scenario: Bad relay URL
- **WHEN** `remote_link.relays` contains `http://relay.example.com`
- **THEN** the config check fails naming `diagnostics.remote_link.relays[0]` and saying relay URLs must use https

### Requirement: EMCY COB-ID in the schema
The JSON Schema SHALL describe the optional node field `emcy_cob_id` as `"device"`, `"eds"`, or an integer from 0x001 to 0x7FF, in the node definition shared by `schema_version` 1 and 2. `contract.py` SHALL apply the same checks as the bridge (restricted CAN-IDs and clashes with the network's other identifiers), and the shared config fixtures SHALL cover a valid number, each rejected kind and the default.

#### Scenario: Valid config without the field
- **WHEN** a version 1 config written before this change is checked by the schema, the bridge and the deploy tool
- **THEN** all three accept it

#### Scenario: Restricted COB-ID
- **WHEN** a node has `"emcy_cob_id": 1537` (0x601)
- **THEN** the bridge and the deploy tool reject it with the same message naming the node and `emcy_cob_id`

### Requirement: Number strings are decimal or hex
A number written as a JSON string SHALL be read as decimal, or as hex with a `0x` or `0X` prefix, by the schema, the PC tools and the bridge alike. A string with a leading zero other than `"0"` itself SHALL be refused by all of them with the same message, which names the field and suggests the decimal and hex spellings. No tool SHALL read a number string as octal.

#### Scenario: Leading zero
- **WHEN** a config has `"node_id": "012"`
- **THEN** the configurator, `canworks-deploy` and the bridge all refuse it with "leading zero: write 12 or 0x0C", and nothing is deployed

#### Scenario: Hex and decimal
- **WHEN** a config has `"cob_id": "0x200"` and `"node_id": "12"`
- **THEN** every tool and the bridge read COB-ID 0x200 and node 12

### Requirement: No repeated keys
A config object that has the same key twice SHALL be refused by the PC tools and by the bridge, naming the key and the object's path.

#### Scenario: Node ID twice
- **WHEN** a node object has `"node_id": 5` and later `"node_id": 6`
- **THEN** the configurator check and the bridge both refuse the config naming `node_id`

### Requirement: PDO identifiers stay off service identifiers
The PC tools and the bridge SHALL refuse a PDO COB-ID, or the master's TIME COB-ID, that is a CiA 301 restricted CAN-ID, the network's SYNC or TIME COB-ID, or a configured node's EMCY identifier, with a message naming the clashing service. Both SHALL give the same verdict.

#### Scenario: RPDO on a node's SDO channel
- **WHEN** an RPDO of node 2 has COB-ID 0x602
- **THEN** the configurator and the bridge refuse it with "COB-ID 0x602 is node 2's SDO request"

#### Scenario: TPDO on SYNC
- **WHEN** a TPDO has COB-ID 0x80 and SYNC uses its default
- **THEN** both refuse it naming SYNC

#### Scenario: TPDO on a node's EMCY
- **WHEN** node 2's EMCY is not moved and a TPDO uses 0x82
- **THEN** both refuse it naming node 2's EMCY

### Requirement: Store and restore are never startup writes
A startup SDO to 0x1010 or 0x1011 SHALL be refused by the PC tools and the bridge with a pointer to `store_configuration` and `restore_configuration`. A write SDO variable on 0x1010 or 0x1011 SHALL be accepted only with a `trigger_location`.

#### Scenario: Save in the startup list
- **WHEN** a node's `sdo` list writes 0x65766173 to 0x1010 sub 1
- **THEN** both refuse the config and name `store_configuration`

#### Scenario: Triggered write variable
- **WHEN** a write SDO variable on 0x1010 sub 1 has a `trigger_location`
- **THEN** the config is accepted and the write happens only on the trigger

### Requirement: 64-bit values as JSON numbers
A JSON integer whose magnitude is above 2^53 SHALL be refused in every config field by the PC tools and the bridge, with a message to write it as a string.

#### Scenario: Large UNSIGNED64 startup value
- **WHEN** a startup SDO value is the JSON number 9007199254740993
- **THEN** both refuse it and ask for a string

### Requirement: Same number syntax on both sides
The PC tools SHALL refuse every number or location string the bridge refuses, including strings with leading or trailing whitespace or a newline, `"-0"` on unsigned types, and the JSON constants NaN and Infinity. String values in maps such as `error_behavior` SHALL be range-checked like JSON numbers.

#### Scenario: Trailing newline
- **WHEN** `node_id` is `"3\n"`
- **THEN** the configurator refuses it as the bridge does

#### Scenario: error_behavior as a string
- **WHEN** `error_behavior` is `{"1": "0x100"}`
- **THEN** both refuse it as out of range

### Requirement: Automatic COB-IDs are checked where they land
A PDO with `cob_id: "auto"` SHALL be checked for clashes at its resolved COB-ID, not at a default one.

#### Scenario: Auto TPDO 6 next to an explicit 0x682
- **WHEN** node 2 TPDO 6 is `auto` and node 3 TPDO 1 uses 0x682
- **THEN** both accept the config and the auto PDO gets a free COB-ID

### Requirement: Heartbeat consumer time is the configured timeout
The master's heartbeat consumer entry for a node SHALL equal the node's `heartbeat_timeout_ms`, never less, in the bridge and the DCF export.

#### Scenario: Timeout 10 ms on a 3 ms heartbeat
- **WHEN** `heartbeat_ms` is 3 and `heartbeat_timeout_ms` is 10
- **THEN** the master's 0x1016 entry for the node is 10 ms

### Requirement: Config target
A config SHALL target one system: the Modbus bridge when it has a top-level `bridge` object, CODESYS when it has a top-level `codesys` object. A config with both SHALL be an error. A config with neither SHALL be refused by the bridge, the deploy tool and the check with one message: it is for the removed OpenPLC plugin, and the configurator's **Use with canworks-bridge** converts it. A CODESYS config SHALL be version 2.

#### Scenario: Both markers
- **WHEN** a config has both `bridge` and `codesys`
- **THEN** the check fails saying a config targets one system

#### Scenario: OpenPLC through Modbus
- **WHEN** a config has a `bridge` object with `plc_link` true and an `openplc` entry in `connections`
- **THEN** its target is the Modbus bridge and `canworks-bridge` runs it

#### Scenario: Old plugin config
- **WHEN** `canworks-bridge --check-only` or `canworks-deploy --check` runs on a config with neither `bridge` nor `codesys`
- **THEN** it exits non-zero with the message naming **Use with canworks-bridge**, and nothing is started or uploaded

### Requirement: CODESYS section in the schema
The version 2 schema SHALL define an optional top-level `codesys` object with `project`, `device`, `create` (`TYPE:ID:VERSION`) and `variables` (boolean), and an optional network `codesys` object with `net_id` (0-255) and `interface` (a name), all optional. In a CODESYS config PDO entries SHALL NOT need `iec_location` and `adapter.interface` SHALL be optional.

#### Scenario: CODESYS config validates
- **WHEN** a version 2 config with `"codesys": {}`, network `field` with `"codesys": {"net_id": 1}` and PDO entries without locations is validated
- **THEN** it is valid

### Requirement: Variable name of a PDO entry
A PDO entry MAY have `name`, an IEC 61131-3 identifier. It SHALL replace the EDS part of the names the declarations, the Modbus register map and the CODESYS channels give that entry, after the same network and node prefixes. Two entries whose names come out equal SHALL be an error naming both paths.

#### Scenario: Named entry
- **WHEN** node `dio` on a one-network config maps 0x6000 sub 1 with `name` `door_open`
- **THEN** its declaration and CODESYS channel are named `dio_door_open`

### Requirement: Settings the target does not use
One relevance table SHALL list, per setting, the targets that use it and why the others do not. The check SHALL warn, with the setting's path and that reason, for every set value its target does not use. Values the target refuses SHALL stay errors. Fields of removed features (`master.sync_source`, `sync_cycles`, `scan_watchdog_ms`, a node's `axis`) SHALL NOT be in the table: they are unknown fields, warned about as ignored, and `"sync_source": "plc_cycle"` is an error.

#### Scenario: Scan watchdog in a CODESYS config
- **WHEN** a CODESYS config has `master.scan_watchdog_ms` 500
- **THEN** the check warns that `scan_watchdog_ms` is an unknown field and is ignored, naming its path

#### Scenario: Scan watchdog in a bridge config
- **WHEN** a bridge config has `master.scan_watchdog_ms` 500
- **THEN** the check warns that `scan_watchdog_ms` is an unknown field and is ignored, naming its path, and the bridge logs the same warning and starts

#### Scenario: Bridge status locations in a CODESYS config
- **WHEN** a CODESYS config has `master.bus_state_location` `%IB10`
- **THEN** the check warns that CODESYS does not use it, naming its path and the reason

### Requirement: CODESYS configs are for CODESYS
canworks-bridge and `canworks-bridge` SHALL refuse a config with a `codesys` object at load with an error saying it is for CODESYS, and the deploy tool SHALL refuse to upload one to a runtime or a bridge.

#### Scenario: CODESYS config uploaded to OpenPLC
- **WHEN** `canworks-deploy --config codesys.json --runtime HOST` is run with a CODESYS config
- **THEN** it stops before uploading with a message pointing to `--codesys-import`

### Requirement: Published JSON Schema of the bridge config
The repository SHALL publish a JSON Schema (draft 2020-12) for each supported config version. The schema SHALL describe every field the bridge reads, its type, and whether it is required. Any file the bridge accepts SHALL validate against the schema, and the checks the schema cannot express (EDS contents, overlapping locations, node ID uniqueness) SHALL be documented next to it.

#### Scenario: Example configs validate
- **WHEN** the schema is applied to every example config in the repository
- **THEN** each example validates without errors

#### Scenario: Bridge and schema agree
- **WHEN** a test config breaks a rule the schema expresses (wrong type, missing required field, value out of range)
- **THEN** both the schema validation and the bridge reject it

### Requirement: Links and heartbeat watch in the config schema
The JSON Schemas for version 1 and version 2 SHALL describe `links` (on a version 1 file's top level and on a version 2 CANopen master network) and the node field `heartbeat_watch`, through one shared definition each. Both fields SHALL be optional, so every file an earlier release accepted SHALL still validate and mean the same. The checks the schema cannot express (layout against both EDS files, COB-ID rules, nodes of the same network, heartbeat watch capacity) SHALL be listed with the other such checks in docs/config.md, and the shared config fixtures SHALL hold cases for them that the schema, the bridge and the deploy tool judge alike.

#### Scenario: Example with a link validates
- **WHEN** the schema is applied to an example config with a link and a heartbeat watch
- **THEN** it validates without errors in both versions

#### Scenario: Consumer entry with a location
- **WHEN** a link consumer entry gives `iec_location`
- **THEN** the schema, the bridge and the deploy tool reject it, naming `links[0].to[0].entries[0].iec_location`

#### Scenario: Older bridge
- **WHEN** a bridge from before this change loads a version 1 file with `links`
- **THEN** it logs that `links` is an unknown field and loads the rest of the config

### Requirement: Mailboxes in the schema
The version 2 schema SHALL define an optional `mailboxes` object inside `bridge` with `requests` (integer 0-4), `receive` (boolean), `cyclic_jobs` (integer 0-16), `network_info` (boolean), `input_location` (a `%IB` byte location) and `output_location` (a `%QB` byte location), and no other members. A bridge config without `mailboxes` SHALL behave as before this change.

#### Scenario: Mailboxes validate
- **WHEN** the shipped OpenPLC Modbus example with `"mailboxes": {"requests": 2, "cyclic_jobs": 8}` is validated against the published schema
- **THEN** it is valid

#### Scenario: Too many mailboxes
- **WHEN** a config has `"mailboxes": {"requests": 5}`
- **THEN** schema validation and the bridge's check both refuse it, naming `requests` and its range
