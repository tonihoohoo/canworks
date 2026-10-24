## ADDED Requirements

### Requirement: Adapter server file test
CI SHALL build the adapter server file and test it inside an existing job (no new job): run it with a Python 3.11 started with `-I` and no site packages, serve a virtual adapter, and through it from a client with the full tools run status, scan, an SDO read, a frame send and a short trace. The test SHALL run only when the server, `diag.py`, `localbus/`, the build script, `install-adapter.sh`, the lock file or the release workflow change.

#### Scenario: Unrelated change
- **WHEN** a pull request changes only the configurator's page code
- **THEN** the file test does not run

### Requirement: Adapter server file limits checked
The file test SHALL fail when the file needs a module that is neither in the standard library nor in the file, or when the file is larger than 2 MB.

#### Scenario: A new import
- **WHEN** a change makes `localbus/serve.py` import `jsonschema` at start
- **THEN** the file test fails naming `jsonschema`
