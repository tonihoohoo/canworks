## MODIFIED Requirements

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

## ADDED Requirements

### Requirement: CI time kept when tests are added

A pull request that adds or changes tests SHALL state in its description its CI wall time and its summed job time, next to the median of the five last green `main` runs of the CI workflow before its branch. Neither SHALL be higher unless the description says why and the maintainer accepts it. A change that adds test time SHALL save at least as much elsewhere in the same workflow; it SHALL NOT move tests to another workflow, skip tests or drop coverage to do so.

#### Scenario: Change with new tests
- **WHEN** a change adds a simulated-bus case and a page test to the suite
- **THEN** its pull request shows wall time and summed job time equal to or below the `main` median, and says where the time was saved
