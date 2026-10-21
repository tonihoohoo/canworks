## ADDED Requirements

### Requirement: Python of the code under test
Each CI job SHALL run its Python on the version the code it tests runs on, without adding jobs: jobs that test code which runs on the runtime (`plugin`, `vcan`, the `tools` shards and `integration`) SHALL use the Python of the pinned runtime image (3.11), and jobs that test PC-only code (`configurator-page`, `browser`, `local-runtime` and the PC tools job on Windows and macOS) SHALL use the PC tools' default Python (3.14). The README's local test commands SHALL use the PC tools' default Python.

#### Scenario: Code the runtime cannot run
- **WHEN** a change uses a library function that exists only in Python 3.12 or newer in a module of the deploy tool
- **THEN** the `tools` shards fail on 3.11

#### Scenario: No added time
- **WHEN** the versions change
- **THEN** the number of jobs and shards is unchanged
