## ADDED Requirements

### Requirement: Mailboxes in the schema
The version 2 schema SHALL define an optional `mailboxes` object inside `bridge` with `requests` (integer 0-4), `receive` (boolean), `cyclic_jobs` (integer 0-16), `network_info` (boolean), `input_location` (a `%IB` byte location) and `output_location` (a `%QB` byte location), and no other members. A bridge config without `mailboxes` SHALL behave as before this change.

#### Scenario: Mailboxes validate
- **WHEN** the shipped OpenPLC Modbus example with `"mailboxes": {"requests": 2, "cyclic_jobs": 8}` is validated against the published schema
- **THEN** it is valid

#### Scenario: Too many mailboxes
- **WHEN** a config has `"mailboxes": {"requests": 5}`
- **THEN** schema validation and the bridge's check both refuse it, naming `requests` and its range
