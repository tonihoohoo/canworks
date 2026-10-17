## ADDED Requirements

### Requirement: No TIME settings for period 0
The CODESYS export SHALL emit no TIME producer settings when `time_period_ms` is 0.

#### Scenario: TIME off
- **WHEN** `time_period_ms` is 0
- **THEN** the export has no TIME settings and no TIME note
