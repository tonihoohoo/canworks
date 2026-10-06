# canopen-ci Specification

## Purpose
What CI runs for which change (the full suite for code, spec validation only for documentation and specs), what it must keep covering, how the test work runs in parallel, and how superseded runs are cancelled.

## Requirements

### Requirement: Full suite for code changes

CI SHALL run the complete test suite (C++ unit and simulation tests, deploy tool and configurator tests including the browser page tests and the DCF parity check, editor hook tests, the stock runtime test against upstream `development`, the vcan tests and the Docker job) for every push to `main` and every pull request that changes any file outside the documentation allow-list. No test SHALL be skipped, removed or moved out of the pull request run to save time.

#### Scenario: Plugin source change
- **WHEN** a pull request changes a file under `src/`
- **THEN** every test job runs and the pull request shows each of them

#### Scenario: Workflow change
- **WHEN** a pull request changes only `.github/workflows/ci.yml`
- **THEN** the full suite runs

### Requirement: Light run for documentation and spec changes

When every changed file is in the documentation allow-list (`openspec/**`, `docs/**`, or a `*.md` file outside `test/`, `config/` and `tools/`), CI SHALL skip the build and test jobs and SHALL run `openspec validate --all --strict`. Skipped jobs SHALL report as skipped, not as pending, so required checks do not block the pull request. A file that any test reads SHALL NOT be in the allow-list.

#### Scenario: Archive commit
- **WHEN** a pull request only moves a change folder into `openspec/changes/archive/` and updates `openspec/specs/`
- **THEN** only the change classification and the spec validation run, and the run finishes in under a minute

#### Scenario: Invalid spec
- **WHEN** a documentation-only pull request leaves a spec that fails strict validation
- **THEN** the spec validation job fails

#### Scenario: Markdown fixture
- **WHEN** a pull request changes only a Markdown file under `test/`
- **THEN** the full suite runs

#### Scenario: Unknown base
- **WHEN** the base commit of a push cannot be compared (new branch, force push)
- **THEN** the full suite runs

### Requirement: Parallel test jobs

The test work SHALL be split into jobs that run at the same time, and the C++ simulation scenarios SHALL be run as separate test cases that can run in parallel. Running the simulation binary without arguments SHALL still run every scenario.

#### Scenario: Code change wall time
- **WHEN** a code change runs the full suite on GitHub-hosted runners with the Lely cache warm
- **THEN** the run finishes in about 5 minutes instead of about 11.5

#### Scenario: Every scenario registered
- **WHEN** a new `TEST()` case is added to the simulation tests
- **THEN** it appears as its own ctest test without editing the CMake file

### Requirement: Superseded runs cancelled

A pull request run SHALL be cancelled when a newer commit to the same pull request starts a run of the same workflow. Runs for pushes to `main` SHALL NOT be cancelled.

#### Scenario: Two pushes in a row
- **WHEN** a second commit is pushed to a pull request while the first commit's CI is still running
- **THEN** the first run is cancelled and the second runs to completion

#### Scenario: Merges to main
- **WHEN** two pull requests are merged into `main` shortly after each other
- **THEN** both `main` runs complete
