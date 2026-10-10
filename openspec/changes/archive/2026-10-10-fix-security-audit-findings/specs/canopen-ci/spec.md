## ADDED Requirements

### Requirement: Concurrency check of the frame blocks
The weekly browser workflow SHALL also build the frame block stress test with ThreadSanitizer and run it; the plain stress test SHALL run in the pull request suite.

#### Scenario: Data race added
- **WHEN** a change adds an unsynchronised write to a transmit slot
- **THEN** the weekly run fails with a ThreadSanitizer report
