## ADDED Requirements

### Requirement: truST trim offered only when it fits
The truST refusal for a map over 125 registers SHALL offer "Trim the mailboxes for truST" only when the trimmed map fits. Otherwise it SHALL say how many registers the map with a request mailbox needs and offer canworks blocks None or locating fewer values.

#### Scenario: Medium map
- **WHEN** a truST connection with canworks blocks SDO and send is exported for a map that needs 144 input registers with one request mailbox
- **THEN** the refusal says 144 is more than 125 and offers canworks blocks None, not the trim

### Requirement: Standard globals in the generic dialect
The generic PLCopen XML SHALL use the TC6 2.01 namespace and SHALL declare `canworks` as a VAR_EXTERNAL in every program that reads or writes it.

#### Scenario: Strict importer
- **WHEN** the generic export of a bridge config is checked
- **THEN** it validates against TC6 2.01 and each of `canworks_in`, `canworks_out` and `main` declares `canworks` in its external variables
