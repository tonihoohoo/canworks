## ADDED Requirements

### Requirement: Slave networks in the bundle and checks
The deploy tool SHALL bundle each slave network's EDS with the config, and `--check` and every upload SHALL run the same EDS lint, object and binding checks the plugin runs, including the direction and location checks.

#### Scenario: Binding error found on the PC
- **WHEN** a slave binds an `rww` object to a `%Q` location and the user runs `openplc-canopen-deploy --check`
- **THEN** the check fails with the same message the plugin would log, before anything is uploaded

### Requirement: Slave EDS command
The deploy tool SHALL provide `openplc-canopen-deploy slave-eds <description.json> -o <file.eds>` (canopen-slave-eds), exiting non-zero with the reason when the description is invalid.

#### Scenario: Invalid description
- **WHEN** the description has an object without a type
- **THEN** the command exits non-zero naming the object
