## MODIFIED Requirements

### Requirement: Runtime release watch
A scheduled workflow SHALL check monthly, and on manual start, the newest release of the upstream OpenPLC runtime against `docker/local-runtime/runtime-version`, and the parts of upstream that canworks depends on: the runtime's Modbus master config model (`conf/modbus_master.json` fields and its word order) and the editor's remote device file format and its Modbus master config generator. When upstream is newer or one of those parts changed since the last recorded state, it SHALL open one issue naming the versions and the changed parts, or update the open one, and SHALL change nothing else. It SHALL have only the permissions it needs to read and to write issues.

#### Scenario: Upstream releases a new runtime
- **WHEN** the tested runtime is v4.3.1 and upstream's newest release is v4.3.2
- **THEN** after the next run there is one open issue "OpenPLC runtime v4.3.2 is out (tested: v4.3.1)", and a second run does not open another

#### Scenario: Remote device format changed
- **WHEN** upstream's editor renames a field of `devices/remote/*.json`
- **THEN** the issue names the editor format as changed, so the generator can follow

### Requirement: Device install tests in existing jobs
CI SHALL test the Devices workspace without a real device and without network access, inside the existing tools test job (no new job, CI time kept): the action plan from probe fixtures, the SSH layer and the install job against a local SSH server in the test process (host key trust and change, key and password login, key setup, sudo password on standard input, job start, log follow from an offset, reconnect, stop), password-free settings and logs, the probe script on fake roots, the script's step lines and `VERSION` files with the existing script tests, and the Devices page with the page tests (rows per target, main action, confirmation texts, job progress, entry points). The tests SHALL run only when files of these areas change, as the protocol-area selection does.

#### Scenario: Probe fixture for a moved runtime
- **WHEN** the plan is given a probe of a managed Docker runtime v4.3.2 with an OpenPLC project open and the pin v4.3.1
- **THEN** the test expects the main action **Switch runtime to v4.3.1**

### Requirement: Parallel test jobs

The test work SHALL be split into jobs that run at the same time, and the C++ simulation scenarios SHALL be run as separate test cases that can run in parallel. Running the simulation binary without arguments SHALL still run every scenario. The vcan tests SHALL run in their own jobs, apart from the build and C++ tests, spread over more than one runner so that the runners' vcan test times are about equal; the workflow SHALL record the time each vcan test took when the split was made. The deploy tool tests and the configurator page tests SHALL each be spread over more than one runner by test class, with a split every runner computes the same way, so that every test runs exactly once per change; a shard that finds no tests SHALL fail. A class whose recorded time is over a set limit SHALL be split into parts of whole test methods, each part running the class's own set-up. Inside each runner the shard's tests SHALL run in as many worker processes as the runner has CPUs, each worker with its own temporary folder; the job SHALL fail when any worker fails, finds no tests or ends without a result, and its log SHALL show each worker's output in one piece. Every Playwright test file (`*_page.py`) SHALL run in the configurator page jobs and in no other job. The configurator page shards and the deploy tool shards SHALL be balanced by recorded class times kept in the repository, and a class without a recorded time SHALL count as the median recorded class. Jobs that create no vcan interface SHALL NOT install the vcan kernel module package. A job SHALL build only the targets its tests use: the vcan jobs SHALL NOT build the C++ unit and simulation test binaries. The bridge build SHALL use a compiler cache kept between runs, keyed so that a stale cache can only slow a build down, never change its result. Every CI job SHALL have a time limit.

#### Scenario: Code change wall time
- **WHEN** a code change runs the full suite on GitHub-hosted runners with the Lely cache warm and the package mirror answering normally
- **THEN** the run finishes in about 3.5 minutes or less

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
- **WHEN** a `tools` shard builds the bridge repository
- **THEN** it builds `canopen_check` and not the bridge's test binaries

#### Scenario: vcan build
- **WHEN** a `vcan` job builds the bridge repository
- **THEN** it builds the bridge, the standalone simulator and the helper programs its tests start, and not `unit_tests`, `sim_tests` or `sim_unit_tests`

#### Scenario: Warm compiler cache
- **WHEN** a pull request changes one bridge source file and the compiler cache from `main` is restored
- **THEN** the build step recompiles only what depends on that file

#### Scenario: Workers in a runner
- **WHEN** a configurator page job runs on a 4-CPU runner
- **THEN** its tests run in 4 worker processes at the same time, and the "class times:" line covers every class of the shard

#### Scenario: Failing worker
- **WHEN** one test fails in one worker and the other workers pass
- **THEN** the job fails and its log shows that worker's failure in one piece

#### Scenario: Large class
- **WHEN** a page test class's recorded time is three times the limit
- **THEN** its methods are run as three parts, possibly on different workers or runners, and each method runs exactly once

#### Scenario: Page test outside the configurator name pattern
- **WHEN** a test file `tools/deploy/tests/test_trace_decoding_page.py` uses Playwright
- **THEN** a configurator page job runs it with a browser, and no deploy tool job skips it

#### Scenario: Page shard balance
- **WHEN** the configurator page shards of one run finish
- **THEN** the longest page shard's test step took at most about a third longer than the shortest's

### Requirement: Bridge tests in existing jobs
The bridge's C++ tests SHALL run on the simulated bus inside the existing bridge test job, using a Modbus TCP client compiled into the tests and no extra package. The map export and Pack for Modbus tests SHALL run in the existing tools test shards. The area classifier SHALL count `plugin/src/bridge/**` and `scripts/install-bridge.sh` as `shared`. No new pull request job SHALL be added, and the container image SHALL be built only by the release workflow. The pull request SHALL state wall time and summed job time against the baseline.

#### Scenario: Bridge source change
- **WHEN** a pull request changes only `plugin/src/bridge/modbus_server.cpp`
- **THEN** the existing pull request jobs run the bridge tests, and no extra job appears

### Requirement: Python of the code under test
Each CI job SHALL run its Python on the version the code it tests runs on, without adding jobs: jobs that test code which runs on the runtime (`engine`, `vcan` and the `tools` shards) SHALL use the Python of the pinned runtime image (3.11), and jobs that test PC-only code (`configurator-page`, `browser`, `local-runtime` and the PC tools job on Windows and macOS) SHALL use the PC tools' default Python (3.14). The README's local test commands SHALL use the PC tools' default Python.

#### Scenario: Code the runtime cannot run
- **WHEN** a change uses a library function that exists only in Python 3.12 or newer in a module of the deploy tool
- **THEN** the `tools` shards fail on 3.11

#### Scenario: No added time
- **WHEN** the versions change
- **THEN** the number of jobs and shards is unchanged

### Requirement: OpenPLC through Modbus integration test
CI SHALL run the pinned runtime release's own Modbus master plugin (`core/src/drivers/plugins/python/modbus_master`, on an in-memory process image) against `canworks-bridge` running the shipped bridge example as an `openplc` config with its simulated CANopen nodes, polling with the `conf/modbus_master.json` the editor's Build makes from the generated remote device. It SHALL check the map hash and status coming in, an output reaching a node and coming back as its input, an SDO read through the SDO registers, that a PLC stop as the runtime does it (outputs zeroed for one more round, then the master stops) with `on_client_loss: "hold"` keeps the last values from before the stop, and that a program with another map hash leaves outputs off. CI SHALL also run the generated `canworks_in` and `canworks_out` programs and the library's blocks on STruC++ against a bridge register model. Both SHALL run in the CI job that builds the bridge, adding under 30 s to it.

#### Scenario: Stop holds the real values
- **WHEN** the program drove an RPDO value to 0x5A and the PLC stops, writing one round of zeroed outputs
- **THEN** the simulated node keeps receiving 0x5A, never 0

## ADDED Requirements

### Requirement: No jobs for the removed OpenPLC plugin
CI SHALL NOT build or test an OpenPLC runtime plugin, an editor hook or a modified runtime image: no job builds against runtime sources, the only job that checks out the runtime's sources is the `engine` job, for the OpenPLC through Modbus integration test's Modbus master, and releases publish no local runtime image. The PR that removes them SHALL state the wall and summed job time against the median of the last five green `main` runs, and neither SHALL be higher.

#### Scenario: Release
- **WHEN** a `deploy-v` release runs
- **THEN** it publishes the wheel, the library, the scripts and the bridge image, and no `canworks-local-runtime` image

### Requirement: Configurator and bridge agree on bad configs
A test in the tools job SHALL run a corpus of invalid configs through both the configurator's check and the bridge's config loader (the `canopen_check` build of the engine) and SHALL fail when one refuses a config the other accepts. The corpus SHALL cover at least: a missing interface, out-of-range values in hex and decimal, duplicate COB-IDs, a simulation source on an RPDO entry, overlapping words in a byte-addressed config, and a config with neither `bridge` nor `codesys`.

#### Scenario: New bridge check without a configurator check
- **WHEN** the bridge starts refusing a value that the configurator still accepts
- **THEN** the parity test fails naming the corpus entry

### Requirement: Browser run against the real bridge
A workflow of its own, separate from the CI workflow and like the local runtime workflow not awaited by `ci-ok`, SHALL run the configurator in Chromium against the real bridge running the virtual-plant example on its simulated bus (no CAN interface): connect, the node table, an object dictionary read and write, a simulation fault and its effect online, a device power cycle, a stopped TPDO raising its timeout bit, and a trace started, stopped and saved. It SHALL run weekly, on a manual run, and on pull requests that change the configurator's online or trace code or the engine's diagnostics or simulated bus.

#### Scenario: Engine-only pull request
- **WHEN** a pull request changes only `plugin/src/canopen/bus.cpp`
- **THEN** the browser run runs on it, and the CI workflow's wall time is unchanged

### Requirement: One runtime pin for the upstream runtime
Every CI job, test script and install path that uses the upstream OpenPLC runtime SHALL take its version from `docker/local-runtime/runtime-version`, and the upstream bootloader's from `docker/local-runtime/bootloader-version`. A test SHALL fail when a workflow, script, Dockerfile or the PC tools name either image by a literal tag other than the pin (such as `latest`), or run upstream's installer without the pinned versions. Test code is exempt; test shell scripts are not.

#### Scenario: Local runtime job
- **WHEN** the local runtime workflow runs while upstream's `latest` is newer than the pin
- **THEN** it runs the pinned, unchanged runtime image with the bridge image built in the job next to it

#### Scenario: Literal tag added
- **WHEN** a change adds `ghcr.io/autonomy-logic/openplc-runtime:latest` to a workflow
- **THEN** the pin test fails and names the file and line

### Requirement: Full suite for engine and tool changes

CI SHALL run the pull request suite (C++ unit and simulation tests, deploy tool and configurator tests including the browser page tests and the DCF parity check, and the vcan tests) for every push to `main` and every pull request that changes any file outside the documentation allow-list, with the protocol-area selection below. No test of this suite SHALL be skipped or removed to save time.

Upstream drift SHALL be caught by the local runtime workflow (canopen-local-runtime), which runs the pinned upstream runtime image with the bridge weekly, and by the runtime release watch; there SHALL be no separate integration workflow.

#### Scenario: Bridge source change
- **WHEN** a pull request changes a shared file under `plugin/src/`
- **THEN** every job of the pull request suite runs and the pull request shows each of them

#### Scenario: Workflow change
- **WHEN** a pull request changes only `.github/workflows/ci.yml`
- **THEN** the full pull request suite runs

#### Scenario: Install route change
- **WHEN** a pull request changes `scripts/install-bridge.sh`
- **THEN** the pull request suite and the bridge image workflow both run

#### Scenario: Upstream drift
- **WHEN** a new upstream runtime image no longer runs with the bridge and no pull request touches the local runtime
- **THEN** the next weekly local runtime run fails

### Requirement: Page tests selected by changed paths
The change classification SHALL report whether the configurator's front end or what it uses changed (its static files and server, the PC tools' modules it imports, the schemas, the shipped examples, the page tests and their data). The configurator page jobs SHALL run only then, or when shared CI files changed, or on every push to `main`; otherwise they SHALL report as skipped.

#### Scenario: Bridge-only change
- **WHEN** a pull request changes only `plugin/src/canopen/network.cpp`
- **THEN** the configurator page jobs report as skipped and `ci-ok` passes

## REMOVED Requirements

### Requirement: Configurator and plugin agree on bad configs
**Reason**: It described the removed OpenPLC plugin; its scenarios change with the plugin gone.
**Migration**: Requirement: Configurator and bridge agree on bad configs.

### Requirement: Browser run against the real plugin
**Reason**: It described the removed OpenPLC plugin; its scenarios change with the plugin gone.
**Migration**: Requirement: Browser run against the real bridge.

### Requirement: One runtime pin
**Reason**: It described the removed OpenPLC plugin; its scenarios change with the plugin gone.
**Migration**: Requirement: One runtime pin for the upstream runtime.

### Requirement: Full suite for code changes
**Reason**: It described the removed OpenPLC plugin; its scenarios change with the plugin gone.
**Migration**: Requirement: Full suite for engine and tool changes.

### Requirement: Page tests selected by path
**Reason**: It described the removed OpenPLC plugin; its scenarios change with the plugin gone.
**Migration**: Requirement: Page tests selected by changed paths.
