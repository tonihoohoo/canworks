## MODIFIED Requirements

### Requirement: Appendices
The document SHALL end with an object dictionary extract per node and the config file. The extract SHALL by default list every object the config, the PDO configuration or the bridge writes or maps, with name, data type, access, limits, EDS default and configured value; with the "all" option it SHALL list every object of the EDS, collapsed by default on screen. The config file SHALL be included verbatim except for the diagnostics token hash, collapsed by default on screen. With the embed option, each node's EDS file SHALL be downloadable from the document.

#### Scenario: Embedded EDS
- **WHEN** the export runs with the embed option
- **THEN** each node sheet has a link that saves its EDS file with its original name and identical content
