## ADDED Requirements

### Requirement: Unpaired connections time out
The link service SHALL close an unpaired connection 30 s after it opened or after its first finished pairing attempt, SHALL count failed pairings per address as well as in total, and SHALL apply the pairing delay to `manage` logins.

#### Scenario: Idle connections
- **WHEN** a host opens 8 connections and never pairs
- **THEN** they are closed after 30 s and pairing works again
