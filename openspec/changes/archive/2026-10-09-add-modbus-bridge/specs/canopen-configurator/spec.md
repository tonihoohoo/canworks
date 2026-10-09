## ADDED Requirements

### Requirement: Modbus bridge target
A project SHALL have a target, "OpenPLC" (default) or "Modbus bridge". Switching the target SHALL offer to repack all locations for the new addressing (per-type for OpenPLC, Pack for Modbus for the bridge), and SHALL add or remove the `bridge` object. The settings that make no sense for the target (`sync_source: plc_cycle` for the bridge) SHALL be marked as problems.

#### Scenario: Switch to the bridge
- **WHEN** the user switches an OpenPLC project with two nodes to "Modbus bridge" and accepts repacking
- **THEN** the file gets a `bridge` object with `listen` `0.0.0.0:502`, every location is byte-addressed and packed, and Check reports no problems

### Requirement: Bridge settings panel
A bridge project SHALL have a "Modbus bridge" page with:
- listen address and port, unit ID, word order, maximum clients
- writer and reader allowlists
- watchdog time and client-loss action
- status block, control block, live lists and SDO bridge locations, each with a "Suggest" button that places it after the packed data

#### Scenario: Add a live list
- **WHEN** the user adds a live list for network `field` and clicks Suggest
- **THEN** a free 16-byte input range is chosen and shown in the register map

### Requirement: Register map preview and export
The bridge page SHALL show the register map as a table (Modbus table, address, size, type, name, source) with a filter, the suggested client channels, and buttons to export CSV, JSON and the ST variable list. "Pack for Modbus" SHALL be available on the page.

#### Scenario: Export the ST list
- **WHEN** the user clicks "Export ST variables"
- **THEN** the browser downloads the same file `canworks-deploy --export-modbus-map map.st` writes for this config
