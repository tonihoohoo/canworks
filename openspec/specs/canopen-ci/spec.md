# canopen-ci Specification

## Purpose
What CI runs for which change (the pull request suite for code, spec validation only for documentation and specs, the upstream install tests in a separate integration workflow), what it must keep covering, how the test work runs in parallel, the one check a ruleset needs, and how superseded runs are cancelled.

## Requirements

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

### Requirement: Tests selected by protocol area
The change classification SHALL put each changed code file in the area `canopen`, `j1939` or `shared` by path rules kept in one file (`.github/ci/areas.txt`). Tests that exercise only one protocol SHALL run when their area or `shared` changed; every push to `main`, every workflow change and every unknown base SHALL run all areas. Adding J1939 tests SHALL NOT add a CI job, and the wall time of a full run SHALL NOT exceed the median of the last 5 green `main` runs before this change.

#### Scenario: CANopen-only change
- **WHEN** a pull request changes only `plugin/src/canopen/network.cpp`
- **THEN** the J1939 test steps report as skipped and all CANopen tests run

#### Scenario: J1939-only change
- **WHEN** a pull request changes only `plugin/src/j1939/j1939_network.cpp`
- **THEN** the J1939 tests run and the CANopen-only vcan and simulation tests report as skipped

#### Scenario: Push to main
- **WHEN** a J1939-only pull request merges to `main`
- **THEN** the run on `main` runs every area

### Requirement: Shipped examples swept in the browser
The page tests SHALL open each shipped example (`examples/virtual-plant`, `examples/j1939`, `examples/pdo-link`) and visit every view of every network, failing on a console error, an uncaught page error, an HTTP error answer, a clipped control or sideways scrolling, or a decoding note. The existing all-views layout test SHALL run at two widths instead of three, so the configurator page jobs' summed time does not grow.

#### Scenario: Overflow in an example
- **WHEN** a change makes the gateway routes table clip a route name at 1280 px
- **THEN** the sweep fails naming the example, network, view and the clipped field

### Requirement: Bridge tests in existing jobs
The bridge's C++ tests SHALL run on the simulated bus inside the existing bridge test job, using a Modbus TCP client compiled into the tests and no extra package. The map export and Pack for Modbus tests SHALL run in the existing tools test shards. The area classifier SHALL count `plugin/src/bridge/**` and `scripts/install-bridge.sh` as `shared`. No new pull request job SHALL be added, and the container image SHALL be built only by the release workflow. The pull request SHALL state wall time and summed job time against the baseline.

#### Scenario: Bridge source change
- **WHEN** a pull request changes only `plugin/src/bridge/modbus_server.cpp`
- **THEN** the existing pull request jobs run the bridge tests, and no extra job appears

### Requirement: Concurrency check of the frame blocks
The weekly browser workflow SHALL also build the frame block stress test with ThreadSanitizer and run it; the plain stress test SHALL run in the pull request suite.

#### Scenario: Data race added
- **WHEN** a change adds an unsynchronised write to a transmit slot
- **THEN** the weekly run fails with a ThreadSanitizer report

### Requirement: Written EDS and DCF files checked against CiA 306
CI SHALL run the PC tools' CiA 306 check on every slave EDS that canworks generates for the fixtures and examples, and on every DCF the DCF export tests write, and SHALL fail naming the file, section and key of each finding. The check SHALL run inside an existing PC tools test job, SHALL install no package, and SHALL NOT run on vendor EDS files that canworks only reads.

#### Scenario: Wrong default slips in
- **WHEN** a change makes the slave EDS generator write `DefaultValue=8` on 0x1003 sub 0
- **THEN** the CI run fails naming the generated file, `[1003sub0]` and `DefaultValue`

#### Scenario: Vendor EDS without OrderCode
- **WHEN** a fixture vendor EDS has no `OrderCode`
- **THEN** the CiA 306 check does not run on it and CI does not fail for it

### Requirement: Least-privilege workflows
Every workflow SHALL declare a top-level read-only token permission and widen it only in jobs that need it. Every action SHALL be pinned by full commit SHA, kept current by automated update requests. The repository SHALL have a security policy.

#### Scenario: New workflow
- **WHEN** a workflow file is added without `permissions:`
- **THEN** review finds it missing against this rule

### Requirement: Node-RED flow tests
The Node-RED tests SHALL run in the existing tools test shard and SHALL skip with a message where `node` is missing: the golden flow of the example configs, the package's `node --test` suite (built-in runner, a minimal Node-RED stub, a scripted model of the bridge's registers in place of the Modbus client, no npm packages), the value codec against images packed in Python, the generated layout check and the package `.tgz` contents. The engine job, which already builds the bridge and runs it with simulated nodes, SHALL also run the package's nodes on the minimal stub against it (`test/nodered/run.py`) for values in and out, short and long SDO reads, NMT, a CAN receive with acknowledgement, a cyclic job start and stop, and a bridge restart. No Node-RED installation and no new pull request job SHALL be added, and the PR SHALL report the CI time against the baseline.

#### Scenario: No new job
- **WHEN** a pull request changes only `tools/deploy/canworks/nodered_package/nodes/canworks.js`
- **THEN** the package tests run in the existing tools shard and the pull request's job list is the same as before

#### Scenario: Restart baseline against the real bridge
- **WHEN** the engine job's run restarts the bridge after a CAN send whose request is still in its holding registers, and the bridge node reconnects
- **THEN** no frame goes out and the client's next send ends done

### Requirement: Python of the code under test
Each CI job SHALL run its Python on the version the code it tests runs on, without adding jobs: jobs that test code which runs on the runtime (`engine`, `vcan` and the `tools` shards) SHALL use the Python of the pinned runtime image (3.11), and jobs that test PC-only code (`configurator-page`, `browser`, `local-runtime` and the PC tools job on Windows and macOS) SHALL use the PC tools' default Python (3.14). The README's local test commands SHALL use the PC tools' default Python.

#### Scenario: Code the runtime cannot run
- **WHEN** a change uses a library function that exists only in Python 3.12 or newer in a module of the deploy tool
- **THEN** the `tools` shards fail on 3.11

#### Scenario: No added time
- **WHEN** the versions change
- **THEN** the number of jobs and shards is unchanged

### Requirement: Device install tests in existing jobs
CI SHALL test the Devices workspace without a real device and without network access, inside the existing tools test job (no new job, CI time kept): the action plan from probe fixtures, the SSH layer and the install job against a local SSH server in the test process (host key trust and change, key and password login, key setup, sudo password on standard input, job start, log follow from an offset, reconnect, stop), password-free settings and logs, the probe script on fake roots, the script's step lines and `VERSION` files with the existing script tests, and the Devices page with the page tests (rows per target, main action, confirmation texts, job progress, entry points, the device list's summary line). The tests SHALL run only when files of these areas change, as the protocol-area selection does.

#### Scenario: Probe fixture with backup folders
- **WHEN** the probe runs on a fake root with the instances `line1` and `line1.bak-271`
- **THEN** the test expects one instance, `line1`, and the plan's bridge row and summary line name only `line1`

#### Scenario: Probe fixture for a moved runtime
- **WHEN** the plan is given a stored probe of the old shape (managed Docker runtime v4.3.2 under `runtime`) with an OpenPLC project open and its bridge current and running
- **THEN** the test expects "Up to date", no runtime row and no **Switch runtime** action

#### Scenario: No runtime actions
- **WHEN** the plan is given any probe fixture and target
- **THEN** no main action is `install_openplc_bridge` or `switch_runtime`, and no row is the OpenPLC runtime

### Requirement: Lock file checked and tested
CI SHALL fail when `tools/deploy/uv.lock` does not match `tools/deploy/pyproject.toml`, checked only in runs that change one of those two files. CI jobs that install the tools' dependencies SHALL install the locked versions. Test-only packages SHALL stay unlocked. The change SHALL add no job.

#### Scenario: Dependency added without the lock
- **WHEN** a pull request adds a dependency to `pyproject.toml` and does not update `uv.lock`
- **THEN** CI fails, saying the lock is out of date

#### Scenario: CI uses the locked versions
- **WHEN** the `tools` shards install their dependencies
- **THEN** the installed versions of the packages in `uv.lock` are the locked ones

### Requirement: Dependency updates on purpose
Automated update requests SHALL cover the GitHub Actions pins and `tools/deploy/uv.lock`, each grouped into at most one pull request a month, plus security updates when an advisory names a locked version. Each such pull request SHALL pass CI like any other.

#### Scenario: Monthly lock update
- **WHEN** several locked packages have new releases during a month
- **THEN** one pull request updates them together in `uv.lock`, and CI runs on it

### Requirement: Runtime release watch
A scheduled workflow SHALL check monthly, and on manual start, the newest release of the upstream OpenPLC runtime against `docker/local-runtime/runtime-version`, and the parts of upstream that canworks depends on: the runtime's Modbus master config model (`conf/modbus_master.json` fields and its word order) and the editor's remote device file format and its Modbus master config generator. When upstream is newer or one of those parts changed since the last recorded state, it SHALL open one issue naming the versions and the changed parts, or update the open one, and SHALL change nothing else. It SHALL have only the permissions it needs to read and to write issues.

#### Scenario: Upstream releases a new runtime
- **WHEN** the tested runtime is v4.3.1 and upstream's newest release is v4.3.2
- **THEN** after the next run there is one open issue "OpenPLC runtime v4.3.2 is out (tested: v4.3.1)", and a second run does not open another

#### Scenario: Remote device format changed
- **WHEN** upstream's editor renames a field of `devices/remote/*.json`
- **THEN** the issue names the editor format as changed, so the generator can follow

### Requirement: OpenPLC through Modbus integration test
CI SHALL run the pinned runtime release's own Modbus master plugin (`core/src/drivers/plugins/python/modbus_master`, on an in-memory process image) against `canworks-bridge` running the shipped bridge example with an OpenPLC connection added and its simulated CANopen nodes, polling with the `conf/modbus_master.json` the editor's Build makes from the generated remote device. It SHALL check the map hash and status coming in, an output reaching a node and coming back as its input, an SDO read through the SDO registers, that a PLC stop as the runtime does it (outputs zeroed for one more round, then the master stops) with `on_client_loss: "hold"` keeps the last values from before the stop, and that a program with another map hash leaves outputs off. CI SHALL also run the generated `canworks_in` and `canworks_out` programs and the library's blocks on STruC++ against a bridge register model. Both SHALL run in the CI job that builds the bridge, adding under 30 s to it.

#### Scenario: Stop holds the real values
- **WHEN** the program drove an RPDO value to 0x5A and the PLC stops, writing one round of zeroed outputs
- **THEN** the simulated node keeps receiving 0x5A, never 0

### Requirement: No jobs for the removed OpenPLC plugin
CI SHALL NOT build or test an OpenPLC runtime plugin, an editor hook or a modified runtime image: no job builds against runtime sources, the only job that checks out the runtime's sources is the `engine` job, for the OpenPLC integration test's Modbus master, and releases publish no local runtime image. The PR that removes them SHALL state the wall and summed job time against the median of the last five green `main` runs, and neither SHALL be higher.

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

### Requirement: Mailbox block tests
CI SHALL build the mailbox blocks with STruC++ and run them against a scripted model of the request and receive mailboxes (one call is one poll round), covering the handshake, chunked reads and writes, ticket order with one mailbox and several instances, a skipped waiting instance, receive batches with several receivers, a stalled receiver, cyclic keepalive, ERROR_IDs 20 and 22, and timeouts. CI SHALL test the bridge's mailboxes in `test/bridge/` against a scripted engine (operations, chunks, FIFOs and drops, long J1939 messages fetched in parts, the 1 s stall rule, the link-stop cleanup, cyclic jobs and keepalive) and SHALL add to the OpenPLC integration job, which runs the pinned runtime's own Modbus master against the bridge, an SDO read through a request mailbox and a CAN receiver's frames through the receive mailbox from the simulated nodes, written and read as the blocks do. The ST tests SHALL also build the PLC link file `--export-modbus-map OUT.st` writes for another PLC together with the library. These SHALL run in the existing jobs under their path filters, and the PR SHALL report the CI time against the baseline.

#### Scenario: Integration with blocks
- **WHEN** the integration job runs against the example's simulated CANopen nodes
- **THEN** an SDO read through the request mailbox returns the node's object, a CAN receiver for a node's TPDO gets its frames in the receive mailbox, and the next batch comes after the acknowledgement

### Requirement: PLCopen export tests
The PLCopen export SHALL be tested in the existing tools test shard, selected by the path rules in `.github/ci/plcopen-paths.txt` (the PLCopen writer and targets, the copy programs, the library, the PLCopen tests and their data): golden files for the `generic` target, a check of each written file against the PLCopen TC6 schema, the refusal of `--for codesys`, and an import-and-compile check of the generic output, with the whole library and all mailboxes, by a pinned truST release binary (version and SHA-256 in one file). Where the binary can't be fetched, the compile check SHALL skip with a message. No new pull request job SHALL be added.

#### Scenario: Export code change
- **WHEN** a pull request changes only `tools/deploy/canworks/plcopen.py`
- **THEN** the tools shard runs the PLCopen tests including the compile check, and the job list is the same as before

#### Scenario: Unrelated change
- **WHEN** a pull request changes only `plugin/src/canopen/network.cpp`
- **THEN** the truST binary is not fetched

### Requirement: Multi-network stop and upload test
CI SHALL start the bridge on a config with at least two CANopen networks under forced simulation, stop it with SIGTERM and require exit code 0, every network's stop NMT and no run marker, and SHALL upload a config to it and require the new config applied.

#### Scenario: Regression
- **WHEN** a change makes the bridge die on stop with two networks
- **THEN** the test fails naming the exit status

### Requirement: Doc references in every page
The doc reference test SHALL check links, anchors, paths, subcommands and options, per subcommand, in README.md, docs/*.md, SECURITY.md, tools/deploy/README.md, the release notes template and every example and config README.

#### Scenario: Removed option in a doc page
- **WHEN** docs/diagnostics.md names a `canworks-diag sim fault` kind the tool does not have
- **THEN** the test fails naming the file, line and option

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

### Requirement: Node-RED dashboard example check
The tools test shard SHALL check `examples/node-red-dashboard` without Node-RED, node or Docker. The check SHALL confirm that:
- the plant files are byte-identical to `examples/modbus-bridge`;
- the config passes the deploy tool's config check;
- every canworks node in `dashboard.json` uses the bridge node id of `nodered.flow(cfg, "plant")`;
- every topic it reads exists among the export's names and status topics, and every topic sent to **canworks out** is an output;
- `docker-compose.yml` and `start.sh` name files that exist in the folder.

The check SHALL add no job and no measurable CI time.

#### Scenario: Renamed PDO entry
- **WHEN** a change renames the `rtd_temp1` entry in the example config but leaves `dashboard.json` unchanged
- **THEN** the check fails naming the topic `rtd_temp1` and the dashboard node that uses it
