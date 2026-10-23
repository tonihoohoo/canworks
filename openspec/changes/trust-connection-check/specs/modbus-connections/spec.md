## ADDED Requirements

### Requirement: Connections that cannot be downloaded
For each truST and Other PLC connection, the check SHALL warn about every reason its Download would be refused: no PLC link, or for truST a map larger than one request each way or a watchdog under 500 ms. Each warning SHALL carry the export's own text and the path of the field to change, and `canworks-deploy --check` SHALL print the same warnings. The connection row SHALL show "Cannot download" with the first reason.

#### Scenario: OpenPLC and truST
- **WHEN** a config has an OpenPLC connection (mailboxes on, `watchdog_ms` 50) and the user adds a truST connection
- **THEN** Problems shows a map-size warning and a watchdog warning before any Download, and the truST row reads "Cannot download"

### Requirement: Fixes for a truST connection
Problems SHALL offer **Set the watchdog to 500 ms** on the watchdog warning and **Trim the mailboxes for truST** on the map-size warning, each one undo step; the trim SHALL keep one request mailbox and nothing else and repack, and its title SHALL name the blocks an OpenPLC connection of the same config loses.

#### Scenario: Fixed
- **WHEN** the user presses Trim the mailboxes for truST and Set the watchdog to 500 ms
- **THEN** both warnings go, the row reads "Not downloaded yet", and the truST Download gives the zip
