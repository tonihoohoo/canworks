## MODIFIED Requirements

### Requirement: Full suite for code changes

CI SHALL run the pull request suite (C++ unit and simulation tests, deploy tool and configurator tests including the browser page tests and the DCF parity check, editor hook tests, the install script's Docker-mode tests with a stub `docker`, and the vcan tests) for every push to `main` and every pull request that changes any file outside the documentation allow-list, with the protocol-area selection below. No test of this suite SHALL be skipped or removed to save time.

The two end-to-end install tests against things outside this repository (the stock runtime install against upstream `development`, and the managed Docker route against the published runtime image) SHALL run in a separate integration workflow: weekly, when started by hand, and on pull requests that change the install routes (`scripts/install-stock.sh`, `scripts/docker_spec.py`, `scripts/build-lely.sh`, `test/stock/`, `test/docker/`, the editor hook, the shared build action or that workflow). The README SHALL give the commands to run both on a development machine.

#### Scenario: Plugin source change
- **WHEN** a pull request changes a shared file under `plugin/src/`
- **THEN** every job of the pull request suite runs and the pull request shows each of them; the integration workflow does not run

#### Scenario: Workflow change
- **WHEN** a pull request changes only `.github/workflows/ci.yml`
- **THEN** the full pull request suite runs

#### Scenario: Install route change
- **WHEN** a pull request changes `scripts/install-stock.sh`
- **THEN** the pull request suite and the integration workflow both run

#### Scenario: Upstream drift
- **WHEN** upstream `development` breaks the stock install and no pull request touches the install routes
- **THEN** the next weekly integration run fails

## ADDED Requirements

### Requirement: Tests selected by protocol area
The change classification SHALL put each changed code file in the area `canopen`, `j1939` or `shared` by path rules kept in one file. Tests that exercise only one protocol SHALL run when their area or `shared` changed; every push to `main`, every workflow change and every unknown base SHALL run all areas. Adding J1939 tests SHALL NOT add a CI job, and the wall time of a full run SHALL NOT exceed the median of the last 5 green `main` runs before this change.

#### Scenario: CANopen-only change
- **WHEN** a pull request changes only `plugin/src/network.cpp`
- **THEN** the J1939 test steps report as skipped and all CANopen tests run

#### Scenario: J1939-only change
- **WHEN** a pull request changes only `plugin/src/j1939/ecu.cpp`
- **THEN** the J1939 tests run and the CANopen-only vcan and simulation tests report as skipped

#### Scenario: Push to main
- **WHEN** a J1939-only pull request merges to `main`
- **THEN** the run on `main` runs every area
