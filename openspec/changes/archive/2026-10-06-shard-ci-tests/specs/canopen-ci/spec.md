## MODIFIED Requirements

### Requirement: Full suite for code changes

CI SHALL run the pull request suite (C++ unit and simulation tests, deploy tool and configurator tests including the browser page tests and the DCF parity check, editor hook tests, the install script's Docker-mode tests with a stub `docker`, and the vcan tests) for every push to `main` and every pull request that changes any file outside the documentation allow-list. No test of this suite SHALL be skipped or removed to save time.

The two end-to-end install tests against things outside this repository (the stock runtime install against upstream `development`, and the managed Docker route against the published runtime image) SHALL run in a separate integration workflow: weekly, when started by hand, and on pull requests that change the install routes (`scripts/install-stock.sh`, `scripts/docker_spec.py`, `scripts/build-lely.sh`, `test/stock/`, `test/docker/`, the editor hook, the shared build action or that workflow). The README SHALL give the commands to run both on a development machine.

#### Scenario: Plugin source change
- **WHEN** a pull request changes a file under `src/`
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


### Requirement: Parallel test jobs

The test work SHALL be split into jobs that run at the same time, and the C++ simulation scenarios SHALL be run as separate test cases that can run in parallel. Running the simulation binary without arguments SHALL still run every scenario. The vcan tests SHALL run in their own jobs, apart from the build and C++ tests, spread over more than one runner. The deploy tool tests and the configurator page tests SHALL each be spread over more than one runner by whole test class, with a split every runner computes the same way, so that every test runs exactly once per change; a shard that finds no tests SHALL fail. Jobs that create no vcan interface SHALL NOT install the vcan kernel module package. Every CI job SHALL have a time limit.

#### Scenario: Code change wall time
- **WHEN** a code change runs the full suite on GitHub-hosted runners with the Lely cache warm
- **THEN** the run finishes in about 3 minutes instead of about 5

#### Scenario: Every scenario registered
- **WHEN** a new `TEST()` case is added to the simulation tests
- **THEN** it appears as its own ctest test without editing the CMake file

#### Scenario: New test class
- **WHEN** a new test class is added to the deploy tool tests
- **THEN** exactly one `tools` shard runs it, without editing the workflow

#### Scenario: Shard split
- **WHEN** the `tools` shards and the `configurator-page` shards of one run are added up
- **THEN** they ran every deploy tool, configurator page and layout test once

## ADDED Requirements

### Requirement: One required check

CI SHALL end with one job, `ci-ok`, that runs after every other CI job whatever their outcome, passes when each of them passed or was skipped, and fails when any of them failed or was cancelled. A branch ruleset SHALL need only this check, so jobs can be renamed or split without changing the ruleset.

#### Scenario: Documentation-only change
- **WHEN** only documentation changed and the test jobs are skipped
- **THEN** `ci-ok` passes

#### Scenario: One shard fails
- **WHEN** one `configurator-page` shard fails and every other job passes
- **THEN** `ci-ok` fails and names that job
