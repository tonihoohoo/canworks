# canopen-ci Specification

## Purpose
What CI runs for which change (the pull request suite for code, spec validation only for documentation and specs, the upstream install tests in a separate integration workflow), what it must keep covering, how the test work runs in parallel, the one check a ruleset needs, and how superseded runs are cancelled.

## Requirements

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

The test work SHALL be split into jobs that run at the same time, and the C++ simulation scenarios SHALL be run as separate test cases that can run in parallel. Running the simulation binary without arguments SHALL still run every scenario. The vcan tests SHALL run in their own jobs, apart from the build and C++ tests, spread over more than one runner so that the runners' vcan test times are about equal; the workflow SHALL record the time each vcan test took when the split was made. The deploy tool tests and the configurator page tests SHALL each be spread over more than one runner by whole test class, with a split every runner computes the same way, so that every test runs exactly once per change; a shard that finds no tests SHALL fail. The configurator page shards SHALL be balanced by recorded class times kept in the repository, and a class without a recorded time SHALL count as the median recorded class. Jobs that create no vcan interface SHALL NOT install the vcan kernel module package. A job SHALL build only the targets its tests use: the vcan jobs SHALL NOT build the C++ unit and simulation test binaries. The plugin build SHALL use a compiler cache kept between runs, keyed so that a stale cache can only slow a build down, never change its result. Every CI job SHALL have a time limit.

#### Scenario: Code change wall time
- **WHEN** a code change runs the full suite on GitHub-hosted runners with the Lely cache warm and the package mirror answering normally
- **THEN** the run finishes in about 4 minutes or less

#### Scenario: vcan balance
- **WHEN** the vcan jobs of one run finish
- **THEN** the longest vcan runner's test steps took at most about half as long again as the shortest's

#### Scenario: Every scenario registered
- **WHEN** a new `TEST()` case is added to the simulation tests
- **THEN** it appears as its own ctest test without editing the CMake file

#### Scenario: New test class
- **WHEN** a new test class is added to the deploy tool tests
- **THEN** exactly one `tools` shard runs it, without editing the workflow

#### Scenario: Shard split
- **WHEN** the `tools` shards and the `configurator-page` shards of one run are added up
- **THEN** they ran every deploy tool, configurator page and layout test once

#### Scenario: Tools build
- **WHEN** a `tools` shard builds the plugin repository
- **THEN** it builds `canopen_check` and not the plugin's test binaries

#### Scenario: vcan build
- **WHEN** a `vcan` job builds the plugin repository
- **THEN** it builds the plugin, the standalone simulator and the helper programs its tests start, and not `unit_tests`, `sim_tests` or `sim_unit_tests`

#### Scenario: Warm compiler cache
- **WHEN** a pull request changes one plugin source file and the compiler cache from `main` is restored
- **THEN** the build step recompiles only what depends on that file

#### Scenario: Page shard balance
- **WHEN** the configurator page shards of one run finish
- **THEN** the longest page shard's test step took at most about a third longer than the shortest's

### Requirement: Superseded runs cancelled

A pull request run SHALL be cancelled when a newer commit to the same pull request starts a run of the same workflow. Runs for pushes to `main` SHALL NOT be cancelled.

#### Scenario: Two pushes in a row
- **WHEN** a second commit is pushed to a pull request while the first commit's CI is still running
- **THEN** the first run is cancelled and the second runs to completion

#### Scenario: Merges to main
- **WHEN** two pull requests are merged into `main` shortly after each other
- **THEN** both `main` runs complete

### Requirement: One required check

CI SHALL end with one job, `ci-ok`, that runs after every other CI job whatever their outcome, passes when each of them passed or was skipped, and fails when any of them failed or was cancelled. A branch ruleset SHALL need only this check, so jobs can be renamed or split without changing the ruleset.

#### Scenario: Documentation-only change
- **WHEN** only documentation changed and the test jobs are skipped
- **THEN** `ci-ok` passes

#### Scenario: One shard fails
- **WHEN** one `configurator-page` shard fails and every other job passes
- **THEN** `ci-ok` fails and names that job

### Requirement: Bounded package installs

Every step that installs system packages or a browser SHALL skip what the runner already has, SHALL NOT refresh the package lists when nothing is missing, and SHALL install packages downloaded by an earlier run on the same runner image from a cache without the network, and SHALL limit how long one attempt may wait on the network and retry, so that a stalled package mirror delays the job by about a minute rather than several. A package install SHALL run only in the jobs whose tests use the package, and a test that needs an optional tool SHALL fail instead of skipping in the job that installs it.

#### Scenario: Stalled mirror
- **WHEN** the package mirror stops answering during an install
- **THEN** the attempt ends within about two minutes and is retried, and the step fails if every retry fails too

#### Scenario: Nothing missing
- **WHEN** every package a step asks for is already installed
- **THEN** the step installs nothing and does not refresh the package lists

#### Scenario: Warm package cache
- **WHEN** a job installs the same packages as an earlier run on the same runner image
- **THEN** it installs them from the cache and does not contact the package mirror

#### Scenario: Wireshark decode test
- **WHEN** the deploy tool tests are sharded
- **THEN** only the shard that runs the Wireshark decode test installs `tshark`, and that test fails there if `tshark` is missing

#### Scenario: Browser cache
- **WHEN** the configurator page tests run with an unchanged Playwright version
- **THEN** Chromium comes from the cache instead of being downloaded

### Requirement: CI time kept when tests are added

A pull request that adds or changes tests SHALL state in its description its CI wall time and its summed job time, next to the median of the five last green `main` runs of the CI workflow before its branch. Neither SHALL be higher unless the description says why and the maintainer accepts it. A change that adds test time SHALL save at least as much elsewhere in the same workflow; it SHALL NOT move tests to another workflow, skip tests or drop coverage to do so.

#### Scenario: Change with new tests
- **WHEN** a change adds a simulated-bus case and a page test to the suite
- **THEN** its pull request shows wall time and summed job time equal to or below the `main` median, and says where the time was saved
