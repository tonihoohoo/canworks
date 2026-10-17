## ADDED Requirements

### Requirement: CiA 306 check on written lines only
The DCF export SHALL check only the lines it writes against CiA 306, not the vendor EDS text it copies.

#### Scenario: Vendor text
- **WHEN** a vendor EDS has a non-conforming comment line
- **THEN** the export does not report it
