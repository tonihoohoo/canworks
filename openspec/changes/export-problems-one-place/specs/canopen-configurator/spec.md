## MODIFIED Requirements

### Requirement: Exports report progress and keep Problems clean
While an export runs, the page SHALL show that it is running. The findings of a failed export SHALL replace those of the previous export, not add to them, and an export that does not apply to the open network (DCF or DBC of a slave or J1939 network) SHALL not be offered there.

A failed export (DCF, Documentation, Download for CODESYS, DBC, register map, Node-RED flow) SHALL report in the Problems panel only: its findings as Problems rows, and an error bar at the top of the panel naming the export and saying that nothing was downloaded. It SHALL NOT also show the page message bar. The panel SHALL open if it was closed and scroll into view, and the summary SHALL be announced as an alert. The summary SHALL go when the next check after an edit replaces the export's findings or when an export runs again. If the Problems panel is not shown on the current page, the failure SHALL be reported in the message bar instead.

A successful export SHALL report in the message bar; when it has warnings, the message SHALL give their number and Problems SHALL open with them.

#### Scenario: Repeated failing export
- **WHEN** the user runs a failing DBC export three times
- **THEN** Problems lists its findings once

#### Scenario: CODESYS export with no nodes
- **WHEN** the config's only network has no nodes and the user presses Download for CODESYS
- **THEN** no message bar is shown at the top, Problems lists the two findings under a bar "CODESYS export stopped. Nothing was downloaded. Fix the problems below and export again.", and nothing is downloaded

#### Scenario: Problems was closed
- **WHEN** the user has closed Problems and a DCF export fails
- **THEN** Problems opens and scrolls into view with the summary bar on top and focus stays on the export control

#### Scenario: Summary clears after an edit
- **WHEN** a failed export's summary is shown and the user adds a node
- **THEN** the next check replaces the list and the summary bar is gone

#### Scenario: Register map export findings
- **WHEN** the register map export stops with two findings
- **THEN** each finding is its own Problems row under the "Register map export stopped" summary, and the message bar stays hidden

#### Scenario: Export with warnings
- **WHEN** a DBC export succeeds with two warnings
- **THEN** the message bar says "Exported <file> with 2 warnings." and Problems is open with the two warnings
