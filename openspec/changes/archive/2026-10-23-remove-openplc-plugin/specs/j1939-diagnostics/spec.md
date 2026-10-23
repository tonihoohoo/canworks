## MODIFIED Requirements

### Requirement: Previously active codes
A code that stops being active SHALL be kept, with its occurrence count, in the previously active list until cleared. The list SHALL be held in memory only and SHALL be empty after the bridge starts.

#### Scenario: Fault goes away
- **WHEN** an own code was active with OC 2 and its bit goes FALSE
- **THEN** the next DM1 no longer carries it and a DM2 request is answered with it and OC 2
