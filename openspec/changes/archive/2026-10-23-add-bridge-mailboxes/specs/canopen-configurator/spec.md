## ADDED Requirements

### Requirement: Function blocks section
The Modbus bridge page of a bridge config and of an OpenPLC config SHALL have a **Function blocks** section with a switch and, while on, the number of request mailboxes (0-4), the receive mailbox on or off, the number of cyclic jobs (0-16), network info on or off and the input and output areas with Suggest, writing `bridge.mailboxes`. Turning it on SHALL place both areas in free ranges. The section SHALL show the registers the blocks take and, for OpenPLC, the requests per poll of the whole map against the budget of 40, and SHALL say which blocks need which part (for example "CAN_RECEIVE, J1939_RECEIVE and CO_RECV_EMCY" for the receive mailbox). For OpenPLC a count change SHALL move both areas to free ranges at once, and the section SHALL say that the editor project needs **Update declarations** and a new Build. **New config…** for OpenPLC and a switch to OpenPLC SHALL start with the section on, one request mailbox, the receive mailbox, 4 cyclic jobs and network info.

#### Scenario: Turn on the receive mailbox
- **WHEN** the user turns on the receive mailbox of an OpenPLC config
- **THEN** the areas move to free ranges, the register and request counts grow, and the page says to run Update declarations and build again

#### Scenario: New OpenPLC config
- **WHEN** the user creates a new OpenPLC config
- **THEN** its Function blocks section is on with one request mailbox, the receive mailbox, 4 cyclic jobs and network info

### Requirement: ST calls for the blocks over the bridge
Every **Copy as ST call** of the configurator (an object dictionary entry, an NMT command, a CAN message, a J1939 PGN) SHALL write a call of the library's blocks over the bridge with `LINK := canworks.link`. An SDO call of an integer of up to 4 bytes SHALL use `CO_SDO_READ` or `CO_SDO_WRITE` with `DATA` converted to and from `UDINT` and the object's size; a wider integer, an OCTET_STRING or a DOMAIN SHALL use the `_BYTES` blocks, a REAL the `_REAL` blocks and a VISIBLE_STRING the `_STRING` blocks.

#### Scenario: Copy an SDO read
- **WHEN** the user copies the ST call of an INTEGER16 entry in the Online view's object dictionary
- **THEN** the copied text declares a `CO_SDO_READ`, calls it with `LINK := canworks.link` and converts the result with `UDINT_TO_INT`

## MODIFIED Requirements

### Requirement: Copy as ST call
The object dictionary tab SHALL offer "Copy as ST call" for a selected entry. It SHALL copy Structured Text that declares an instance of the matching block and calls it with the node ID, index and subindex filled in: `CO_SDO_READ_REAL`/`CO_SDO_WRITE_REAL` for REAL32 and REAL64, `CO_SDO_READ_STRING`/`CO_SDO_WRITE_STRING` for VISIBLE_STRING, `CO_SDO_READ_BYTES`/`CO_SDO_WRITE_BYTES` for OCTET_STRING, DOMAIN and integers wider than 4 bytes, and `CO_SDO_READ`/`CO_SDO_WRITE` for every other type, with the `UDINT_TO_<type>` conversion of a read's `DATA` in a comment and a write's `DATA` converted with `<type>_TO_UDINT` and its `SIZE` set to the type's size. Every call SHALL pass `LINK := canworks.link`. It SHALL offer the read call for readable entries and the write call for writable ones, and both when both apply. With several networks the call SHALL set `NETWORK` to the number of the network the online view talks to, with its name in a comment, and the instance name SHALL include the network's name. The entry row for any index and subindex SHALL offer the same, using `CO_SDO_READ`/`CO_SDO_WRITE` when no type is given.

#### Scenario: INTEGER16 entry
- **WHEN** the user picks "Copy as ST call", read, on node 5's 0x6401 subindex 1 (INTEGER16, `ro`)
- **THEN** the clipboard holds a declaration of a `CO_SDO_READ` instance, a call with `NODE := 5, INDEX := 16#6401, SUBINDEX := 1`, `LINK := canworks.link`, and a comment showing `UDINT_TO_INT(...DATA)`

#### Scenario: Device name
- **WHEN** the user picks "Copy as ST call" on 0x1008 subindex 0 (VISIBLE_STRING, `const`)
- **THEN** only the read is offered and it uses `CO_SDO_READ_STRING`

#### Scenario: Node on the second network
- **WHEN** the online view talks to `drives`, the second of two networks, and the user copies the read call for node 2's 0x1017 subindex 0
- **THEN** the clipboard declares `rd_drives_n2_1017_0 : CO_SDO_READ;` and calls it with `NETWORK := 1 (* drives *), NODE := 2, INDEX := 16#1017`
