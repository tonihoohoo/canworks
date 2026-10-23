## MODIFIED Requirements

### Requirement: Library documentation
`docs/plc-library.md` SHALL be the library's page. It SHALL cover:
- the blocks over the bridge with their pins, error IDs and how they share the bridge's SDO slot and control block;
- the mailbox blocks with their pins and error IDs and how they share the request mailboxes;
- a section **With or without the mailboxes**:
  - what works without them: values, `CO_NMT`, `CO_NODE_LIVE`, `CO_SDO_READ`/`CO_SDO_WRITE` up to 4 bytes;
  - what each part costs, in registers and Modbus requests per poll, for the example config;
  - what can't be done without them: SDOs over 4 bytes, every EMCY, CAN ids not in the config, J1939 requests and DM2/DM3/DM11 from the program, bus load and error counters;
  - the config-only alternative to each mailbox block;
  - that the mailboxes are off by default and how they come on (the program's blocks for OpenPLC, a connection's canworks blocks choice, the Function blocks switch);
- the helper functions with their bit numbering, the word helpers, installing and enabling the library, and the PLCopen `EXECUTE` handshake.

`docs/raw-can.md` and `docs/j1939.md` SHALL link to it for the helpers instead of repeating them. `docs/modbus-bridge.md` and `docs/configurator.md` SHALL link to the With or without the mailboxes section. README SHALL link to the page as the place for the program's blocks, and SHALL say in one sentence that the values and the blocks over the bridge work as they are, while the other blocks need the mailboxes, which the configurator turns on when a program uses them. No doc SHALL describe a block that calls a runtime plugin.

#### Scenario: Reader looks for J1939 blocks
- **WHEN** a user opens `docs/plc-library.md`
- **THEN** it lists the J1939 helper functions and the J1939 message and trouble code blocks, which work through the bridge's mailboxes

#### Scenario: Reader looks for the SDO block
- **WHEN** a user opens `docs/plc-library.md`
- **THEN** it describes `CO_SDO_READ` with its pins, its 1-4 byte limit and error IDs 20 and 21, and points to `CO_SDO_READ_BYTES` and `CO_SDO_READ_STRING` for longer transfers

#### Scenario: Reader wants no mailboxes
- **WHEN** a user wants to know whether a program that receives one known CAN frame needs the mailboxes
- **THEN** the With or without the mailboxes section says to use an `rx` message in the config instead of `CAN_RECEIVE`, which needs no mailbox and no extra Modbus requests
