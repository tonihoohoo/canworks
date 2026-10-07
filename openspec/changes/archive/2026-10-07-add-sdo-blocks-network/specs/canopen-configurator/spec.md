## MODIFIED Requirements

### Requirement: Copy as ST call
The object dictionary tab SHALL offer "Copy as ST call" for a selected entry. It SHALL copy Structured Text that declares an instance of the matching block and calls it with the node ID, index and subindex filled in: `CO_SDO_READ_REAL`/`CO_SDO_WRITE_REAL` for REAL32 and REAL64, `CO_SDO_READ_STRING`/`CO_SDO_WRITE_STRING` for VISIBLE_STRING, `CO_SDO_READ_BYTES`/`CO_SDO_WRITE_BYTES` for OCTET_STRING and DOMAIN, and `CO_SDO_READ`/`CO_SDO_WRITE` for every other type, with the `LWORD_TO_<type>` conversion for the entry's IEC type in a comment. It SHALL offer the read call for readable entries and the write call for writable ones, and both when both apply. With several networks the call SHALL set `NETWORK` to the number of the network the online view talks to, with its name in a comment, and the instance name SHALL include the network's name. The entry row for any index and subindex SHALL offer the same, using `CO_SDO_READ`/`CO_SDO_WRITE` when no type is given.

#### Scenario: INTEGER16 entry
- **WHEN** the user picks "Copy as ST call", read, on node 5's 0x6401 subindex 1 (INTEGER16, `ro`)
- **THEN** the clipboard holds a declaration of a `CO_SDO_READ` instance, a call with `NODE := 5, INDEX := 16#6401, SUBINDEX := 1`, and a comment showing `LWORD_TO_INT(...DATA)`

#### Scenario: Device name
- **WHEN** the user picks "Copy as ST call" on 0x1008 subindex 0 (VISIBLE_STRING, `const`)
- **THEN** only the read is offered and it uses `CO_SDO_READ_STRING`

#### Scenario: Node on the second network
- **WHEN** the online view talks to `drives`, the second of two networks, and the user copies the read call for node 2's 0x1017 subindex 0
- **THEN** the clipboard declares `rd_drives_n2_1017_0 : CO_SDO_READ;` and calls it with `NETWORK := 1 (* drives *), NODE := 2, INDEX := 16#1017`
