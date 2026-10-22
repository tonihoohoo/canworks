## ADDED Requirements

### Requirement: Link array for mailboxes
In an editor project for a config with `bridge.openplc`, `canworks.link` SHALL be declared `ARRAY[0..1023] OF WORD`. `canworks_in` SHALL copy the response blocks, receive mailbox, network info and cyclic table into their `LINK` places, set the mailbox flags from the config and then call `CW_LINK_SERVICE(LINK := canworks.link)` before any user code runs; `canworks_out` SHALL copy the request blocks, receive acknowledgement and keepalives from `LINK` to their holding registers before writing the PLC link header. Words of blocks the config does not have SHALL stay 0. Update declarations SHALL rewrite the declaration and both programs when `mailboxes` changes.

#### Scenario: Mailboxes added later
- **WHEN** the user turns on the Function blocks section of an existing OpenPLC project and runs Update declarations
- **THEN** the remote device file, `canworks_in`, `canworks_out` and the map hash constant are rewritten, the user's POUs are unchanged, and the project builds
