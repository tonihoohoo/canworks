## ADDED Requirements

### Requirement: Diagnostic messages in DBC import
A DBC message whose PGN is a diagnostic message this change handles (DM1 65226, DM2 65227, DM3 65228, DM11 65235, DM13 57088, DM22 49920) SHALL be listed by the import as a problem saying it is handled by `diagnostics`, and SHALL NOT be offered as an `rx` or `tx` entry. Its signals' `SPN` attributes SHALL still be read for naming codes in the trace and the Faults panel.

#### Scenario: Vendor DBC with DM1
- **WHEN** the user imports a DBC that defines PGN 65226 and PGN 65280
- **THEN** the picker offers PGN 65280 and lists 65226 as a problem pointing to diagnostics

### Requirement: Diagnostics in the configurator
The J1939 network page SHALL have a Diagnostics section with:
- the watched ECUs (`diagnostics.rx`): source or NAME filter, timeout, and each location, with free locations suggested at the right size (`dtcs` consecutive double words for codes)
- the network's own codes (`diagnostics.dtcs`): SPN, FMI (picked from the 32 failure modes with their texts), lamps, flash and a free `%QX` suggested
- `lamps_location`, `clear_location`, `accept_clear` and `dm13`

with the same validation and problem list as the rest of the page. A `j1939.rx` entry for PGN 65226 SHALL be flagged with a hint to use the Diagnostics section.

#### Scenario: Add an own code
- **WHEN** the user adds an own code with SPN 520192, FMI 3, lamp amber, and saves
- **THEN** the config has the entry with a free `%QX` location and no problems

### Requirement: Faults in the J1939 online view
With online access, a J1939 network's online view SHALL have a Faults panel: one row per ECU that sent DM1, with its lamps, its active codes (SPN, SPN name when known, FMI text, OC) and the time since its last DM1; the network's own active and previously active codes; and actions to read an ECU's previously active codes (DM2) and to clear its codes (DM3 or DM11). A clear SHALL ask for confirmation naming the ECU and what will be cleared.

#### Scenario: ECU raises a fault
- **WHEN** the simulator at address 0 starts reporting SPN 520192 FMI 3 while the Faults panel is open
- **THEN** the row for address 0 shows the amber lamp and the code within 2 s

### Requirement: Trouble codes from the command line
`canworks-diag dm` SHALL offer:
- `list`: every ECU that sent DM1, with lamps and codes, from the plugin's status, or on a local adapter after listening 1.5 s
- `read --address N`: the previously active codes of ECU N (DM2)
- `clear --address N [--previous]`: DM11, or DM3 with `--previous`, refused without `--force`

Through the plugin it SHALL use the PLC's claimed address. On a local adapter it SHALL claim a J1939 address for itself (default 249, `--source-address` to change) with a NAME of its own, refuse to send if it cannot claim, and send nothing when only listing.

#### Scenario: List faults through the PLC
- **WHEN** the user runs `canworks-diag dm list --network machine` while ECU 0 reports one code
- **THEN** the output shows address 0, its lamps and the code with its FMI text

#### Scenario: Clear without force
- **WHEN** the user runs `canworks-diag dm clear --address 0`
- **THEN** nothing is sent and the tool says the clear needs `--force`

### Requirement: Declarations for diagnostics
The located variable declarations SHALL include every diagnostics location: for a watched ECU `<network>_dm<source>_status`, `_lamps`, `_flash`, `_count` and `_dtc0`, `_dtc1`, ... (`UDINT`), and for each own code `<network>_dtc_<spn>_<fmi>` (`BOOL`), plus `<network>_dm_lamps` and `<network>_dm_clears`.

#### Scenario: Watched engine
- **WHEN** network `machine` watches source 0 with `count_location` `%IB222`
- **THEN** the declarations hold `machine_dm0_count AT %IB222 : USINT;`
