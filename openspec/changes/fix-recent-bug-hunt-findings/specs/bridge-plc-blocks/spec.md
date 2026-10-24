## MODIFIED Requirements

### Requirement: Link array and link service
The blocks of this capability and the blocks over the bridge of `plc-library` SHALL take the in-out `LINK : ARRAY[0..1279] OF WORD`, the generated `canworks.link`. Words 0-88 SHALL keep the meaning `add-openplc-modbus-target` gave them; the mailbox flags, scan counter, ticket words, mailbox owners, receive acknowledgement, cyclic keepalives, request mailboxes, receive mailbox, network info and cyclic job table SHALL follow at fixed places. The library SHALL provide `CW_LINK_SERVICE` (in-out `LINK`), which the generated input code SHALL call once at the start of every scan after copying the input words: it SHALL increment the scan counter, move the lowest waiting ticket of the last scan into place, free a request mailbox whose owner has not been called for 100 scans, and set the receivers pending from a new batch.

#### Scenario: Change 1 blocks unchanged
- **WHEN** a program from change 1 that calls `CO_SDO_READ` and `CO_NMT` is rebuilt with this library after a Save of the editor project
- **THEN** it builds and behaves as before
