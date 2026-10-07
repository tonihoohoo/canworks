# Spec Delta

## ADDED Requirements

### Requirement: One channel for all networks
The plugin SHALL serve all networks over one diagnostics channel, with one port, one token, one `allow_changes` setting and one client limit. The hello answer SHALL list the networks in config order, each with its name (empty for a version 1 config), interface, bit rate and master node ID, and SHALL keep `master_node_id` as the first network's.

#### Scenario: Hello with two networks
- **WHEN** a client says hello to a plugin running networks `io` on `can0` and `drives` on `can1`
- **THEN** the answer has protocol 1 and a `networks` list with both, in that order, each with its interface, bit rate and master node ID

### Requirement: Network selector on requests
Every request other than `hello` SHALL accept a `network` field naming a network. With one network it MAY be left out. With several, a request without it SHALL be refused with `network required` and the network names, and an unknown name with `unknown network` and the names. The request SHALL act on the named network only.

#### Scenario: SDO read on the second network
- **WHEN** a client sends `sdo_read` with `network: "drives"`, node 2, 0x1018:1
- **THEN** the read goes to node 2 on `can1`, not to node 2 on `can0`

#### Scenario: Old client and one network
- **WHEN** a client that never sends `network` talks to a plugin with a version 1 config
- **THEN** every request works as before this change

#### Scenario: Missing selector with two networks
- **WHEN** a client sends `status` without `network` to a plugin with two networks
- **THEN** the answer is an error naming `io` and `drives`

### Requirement: Network state is kept per network
Scans, LSS requests, traces, holds, EMCY history and the `no bus` answer SHALL be per network: a scan or LSS request on one network SHALL NOT make the same request on another network answer busy, and a network with no CANopen session SHALL answer `no bus` while the others answer normally. The status answer SHALL carry the network's name.

#### Scenario: Scan on both networks
- **WHEN** a client starts a scan on `io` and then on `drives`
- **THEN** both scans run, and `scan_status` for each network reports its own progress and nodes

#### Scenario: One network without a bus
- **WHEN** network `drives` has no interface and a client asks `status` for `io`
- **THEN** the answer shows `io` with its session, while `status` for `drives` shows `"session": false`

### Requirement: Network option in the command-line client
`openplc-canopen-diag` SHALL take `--network NAME` for every command that talks to the plugin. Without it, a command against several networks SHALL fail listing the names, except `status`, which SHALL print every network one after another.

#### Scenario: Status of all networks
- **WHEN** the user runs `openplc-canopen-diag --runtime plc.local status` against two networks
- **THEN** it prints the status of `io` and then of `drives`, each headed by its name and interface

#### Scenario: SDO read needs a network
- **WHEN** the user runs `sdo-read 2 0x1018 1` without `--network` against two networks
- **THEN** it exits with status 1 saying `--network` is needed and naming `io` and `drives`
