## ADDED Requirements

### Requirement: Skeleton keeps existing notes
`notes skeleton -o FILE` SHALL refuse an existing FILE unless `--force` is given.

#### Scenario: Filled-in notes
- **WHEN** the notes file already exists
- **THEN** the command refuses and leaves it unchanged
