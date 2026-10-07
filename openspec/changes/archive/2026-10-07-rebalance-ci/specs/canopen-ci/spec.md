## MODIFIED Requirements

### Requirement: Parallel test jobs

The test work SHALL be split into jobs that run at the same time, and the C++ simulation scenarios SHALL be run as separate test cases that can run in parallel. Running the simulation binary without arguments SHALL still run every scenario. The vcan tests SHALL run in their own jobs, apart from the build and C++ tests, spread over more than one runner so that the runners' vcan test times are about equal; the workflow SHALL record the time each vcan test took when the split was made. The deploy tool tests and the configurator page tests SHALL each be spread over more than one runner by whole test class, with a split every runner computes the same way, so that every test runs exactly once per change; a shard that finds no tests SHALL fail. Jobs that create no vcan interface SHALL NOT install the vcan kernel module package. A job SHALL build only the targets its tests use. Every CI job SHALL have a time limit.

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

## ADDED Requirements

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
