## MODIFIED Requirements

### Requirement: Deploy checks for J1939
The deploy tool SHALL run the J1939 config checks before upload and SHALL include J1939 signal, status, state and address locations in the address clash check across networks.

#### Scenario: Clash with a CANopen PDO
- **WHEN** a J1939 signal and a CANopen TPDO entry both map `%IW200`
- **THEN** deploy refuses the upload naming both paths

### Requirement: Trouble codes from the command line
`canworks-diag dm` SHALL offer:
- `list`: every ECU that sent DM1, with lamps and codes, from the bridge's status, or on a local adapter after listening 1.5 s
- `read --address N`: the previously active codes of ECU N (DM2)
- `clear --address N [--previous]`: DM11, or DM3 with `--previous`, refused without `--force`

Through the bridge it SHALL use the PLC's claimed address. On a local adapter it SHALL claim a J1939 address for itself (default 249, `--source-address` to change) with a NAME of its own, refuse to send if it cannot claim, and send nothing when only listing.

#### Scenario: List faults through the PLC
- **WHEN** the user runs `canworks-diag dm list --network machine` while ECU 0 reports one code
- **THEN** the output shows address 0, its lamps and the code with its FMI text

#### Scenario: Clear without force
- **WHEN** the user runs `canworks-diag dm clear --address 0`
- **THEN** nothing is sent and the tool says the clear needs `--force`
