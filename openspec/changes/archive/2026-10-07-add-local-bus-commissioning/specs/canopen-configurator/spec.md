## ADDED Requirements

### Requirement: USB adapter as online target
The online access settings SHALL offer three targets: a runtime host, the local simulator runtime, and a USB adapter on this PC. For a USB adapter the page SHALL offer the adapter type, a port picked from the adapters found on this PC (with a refresh button) or typed, the bit rate (defaulting to the current network's `adapter.bitrate`), and an "Allow changes" checkbox that starts off for every connection and is not saved. The adapter type, port and bit rate SHALL be kept in the configurator's settings on this PC per project folder, never in the project. No token SHALL be needed for an adapter.

#### Scenario: Connect to a CANable
- **WHEN** the user picks "USB adapter", the found port `COM5` (slcan) and 250 kbit/s, and connects
- **THEN** the online view opens on that adapter, the banner says "USB adapter slcan:COM5, 250 kbit/s, read-only", and the project folder is unchanged

#### Scenario: Different bit rate than the config
- **WHEN** the network's `adapter.bitrate` is 500000 and the user types 250
- **THEN** the connection is made at 250 kbit/s and the banner shows both rates

### Requirement: Online pages on a USB adapter
On a USB adapter the Online view, scan page, object dictionary view with watch, Parameters actions and Trace view SHALL work as on a runtime, through the local backend. Fields the local backend does not report (boot result, retry, hold, SDO variable values, SYNC counters) SHALL be hidden, and the Simulation view and slave and gateway status SHALL be hidden. When another master is detected, the banner SHALL say so, and LSS buttons SHALL ask whether to go ahead anyway before sending with `force`. Write, NMT, LSS and restore controls SHALL be disabled with the reason while "Allow changes" is off.

#### Scenario: Scan from the PC
- **WHEN** the user runs a scan on a USB adapter target with a project open
- **THEN** found devices are listed and matched against EDS files and the config as on a runtime, and "Add as node" works

#### Scenario: PLC still running
- **WHEN** the user clicks LSS Find on a USB adapter while a PLC master runs on the bus
- **THEN** the page warns that another master is active and sends nothing unless the user confirms

### Requirement: Commission a device without a config
The configurator's start page SHALL offer "Commission a device", which opens the online pages on a USB adapter without any project or config: scan, object dictionary view (EDS from the scan match in the EDS library, or picked by the user), LSS, Parameters (backup, compare, restore, store) and Trace. "Add as node" SHALL be offered only when a config is open.

#### Scenario: New device on the desk
- **WHEN** the user opens "Commission a device", connects to a CANable at 250 kbit/s with "Allow changes" on, finds an unconfigured device with LSS and gives it node ID 12
- **THEN** a scan lists node 12, and nothing was stored on the device unless the user ticked "store"
