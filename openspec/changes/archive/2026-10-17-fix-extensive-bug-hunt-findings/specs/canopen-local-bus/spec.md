## ADDED Requirements

### Requirement: Another master on the bus needs force
On a USB adapter, SDO writes, NMT commands other than start, restores and configure writes SHALL need `--force` when another master is seen on the bus or a node reported OPERATIONAL, and the refusal SHALL say which was seen.

#### Scenario: SYNC from a PLC
- **WHEN** a PLC sends SYNC and the user runs `sdo-write` without `--force`
- **THEN** the write is refused naming the other master

### Requirement: Adapter numbers match
Listing and opening gs_usb adapters SHALL use the same set and order, and the listing SHALL show each adapter's USB bus and address.

#### Scenario: Two adapters
- **WHEN** two gs_usb adapters of different USB IDs are plugged in
- **THEN** `gs_usb:1` opens the adapter listed as 1

### Requirement: Adapter lock for several users
The adapter lock SHALL work for each user on a shared PC, and a lock failure SHALL be reported as an unreachable adapter, not a traceback.

#### Scenario: Second user
- **WHEN** a second Linux user opens an adapter after the first
- **THEN** the adapter opens or a clear message is shown
