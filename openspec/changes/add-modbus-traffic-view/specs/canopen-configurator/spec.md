## ADDED Requirements

### Requirement: Modbus requests in the Trace view
On a bridge project the Trace view's Capture… SHALL offer **Modbus requests** (on by default) with **Only changes** (on by default) and an optional client from the config's connections. With it on, recording SHALL fetch the bridge's Modbus records with the picked network's frames. The Chronological list SHALL show Modbus rows between the CAN rows by time, marked as Modbus, and the Filters SHALL have a source filter CAN / Modbus / both. A Modbus row SHALL open in the inspector with the request and answer, each value of its range by name, the skipped count and the hint. By identifier SHALL have a **By request** table for the Modbus records: one row per client, function and range, with the request count (skipped ones included), average cycle time, last values by name and the last exception. Recording through a USB adapter, or from a runtime that is not a bridge, SHALL grey the option out with the reason.

#### Scenario: Find a wrong address
- **WHEN** an HMI connection reads holding register 40001 and the user records with Modbus requests on
- **THEN** By request lists the HMI's read of holding register 40001 with its count and exception 0x02, and its inspector says holding registers start at 0 here

#### Scenario: Only Modbus
- **WHEN** the user sets the source filter to Modbus
- **THEN** only Modbus rows are listed, and the statistics say how many are shown

### Requirement: Modbus clients panel
While connected to a bridge, the Modbus bridge page SHALL show a **Clients** panel: one row per connection of the config with its name, address, connected or not, requests per second, exceptions, refused writes and its last write's range by name, and one row per other connected client, marked **Not in connections**. Recently closed connections SHALL be listed under a disclosure with their reason and how long ago they closed. A client with refused writes SHALL be marked with a link to its connection's Settings, or to **Add connection** when it is not in the connections.

#### Scenario: HMI that is not connected
- **WHEN** the config has connections OpenPLC and Line HMI, and only OpenPLC is connected
- **THEN** the panel shows OpenPLC with its request rate and Line HMI as not connected

#### Scenario: Unknown writer
- **WHEN** a client at 192.168.10.77 that is in no connection writes holding registers and gets refused
- **THEN** the panel lists 192.168.10.77 as Not in connections with its refused writes and an Add connection link
