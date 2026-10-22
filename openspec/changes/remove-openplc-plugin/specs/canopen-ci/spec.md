## MODIFIED Requirements

### Requirement: Configurator and plugin agree on bad configs
A test in the tools job SHALL run a corpus of invalid configs through both the configurator's check and the bridge's config loader (the `canopen_check` build of the engine) and SHALL fail when one refuses a config the other accepts. The corpus SHALL cover at least: a missing interface, out-of-range values in hex and decimal, duplicate COB-IDs, a simulation source on an RPDO entry, overlapping words in a byte-addressed config, and a config with neither `bridge` nor `codesys`.

#### Scenario: New plugin check without a configurator check
- **WHEN** the bridge starts refusing a value that the configurator still accepts
- **THEN** the parity test fails naming the corpus entry

### Requirement: Browser run against the real plugin
A workflow of its own, separate from the CI workflow and like the integration workflow not awaited by `ci-ok`, SHALL run the configurator in Chromium against the real bridge running the virtual-plant example on its simulated bus (no CAN interface): connect, the node table, an object dictionary read and write, a simulation fault and its effect online, a device power cycle, a stopped TPDO raising its timeout bit, and a trace started, stopped and saved. It SHALL run weekly, on a manual run, and on pull requests that change the configurator's online or trace code or the engine's diagnostics or simulated bus.

#### Scenario: Plugin-only pull request
- **WHEN** a pull request changes only `plugin/src/canopen/bus.cpp`
- **THEN** the browser run runs on it, and the CI workflow's wall time is unchanged

### Requirement: Runtime release watch
A scheduled workflow SHALL check monthly, and on manual start, the newest release of the upstream OpenPLC runtime against `docker/local-runtime/runtime-version`, and the parts of upstream that canworks depends on: the runtime's Modbus master config model (`conf/modbus_master.json` fields and its word order) and the editor's remote device file format and its Modbus master config generator. When upstream is newer or one of those parts changed since the last recorded state, it SHALL open one issue naming the versions and the changed parts, or update the open one, and SHALL change nothing else. It SHALL have only the permissions it needs to read and to write issues.

#### Scenario: Upstream releases a new runtime
- **WHEN** the tested runtime is v4.3.1 and upstream's newest release is v4.3.2
- **THEN** after the next run there is one open issue "OpenPLC runtime v4.3.2 is out (tested: v4.3.1)", and a second run does not open another

#### Scenario: Remote device format changed
- **WHEN** upstream's editor renames a field of `devices/remote/*.json`
- **THEN** the issue names the editor format as changed, so the generator can follow

### Requirement: One runtime pin
Every CI job, test script and install path that uses the upstream OpenPLC runtime SHALL take its version from `docker/local-runtime/runtime-version`, and the upstream bootloader's from `docker/local-runtime/bootloader-version`. A test SHALL fail when a workflow, script, Dockerfile or the PC tools name either image by a literal tag other than the pin (such as `latest`), or run upstream's installer without the pinned versions. Test code is exempt; test shell scripts are not.

#### Scenario: Integration job
- **WHEN** the integration job runs while upstream's `latest` is newer than the pin
- **THEN** it runs the pinned, unchanged runtime image with the bridge built in the job next to it

#### Scenario: Literal tag added
- **WHEN** a change adds `ghcr.io/autonomy-logic/openplc-runtime:latest` to a workflow
- **THEN** the pin test fails and names the file and line

### Requirement: Device install tests in existing jobs
CI SHALL test the Devices workspace without a real device and without network access, inside the existing tools test job (no new job, CI time kept): the action plan from probe fixtures, the SSH layer and the install job against a local SSH server in the test process (host key trust and change, key and password login, key setup, sudo password on standard input, job start, log follow from an offset, reconnect, stop), password-free settings and logs, the probe script on fake roots, the script's step lines and `VERSION` files with the existing script tests, and the Devices page with the page tests (rows per target, main action, confirmation texts, job progress, entry points). The tests SHALL run only when files of these areas change, as the protocol-area selection does.

#### Scenario: Probe fixture for a moved runtime
- **WHEN** the plan is given a probe of a managed Docker runtime v4.3.2 with an OpenPLC project open and the pin v4.3.1
- **THEN** the test expects the main action **Switch runtime to v4.3.1**

## ADDED Requirements

### Requirement: No plugin jobs
CI SHALL NOT build or test an OpenPLC runtime plugin, an editor hook or a modified runtime image: no job builds against runtime sources, the integration workflow's only runtime job is the OpenPLC-through-Modbus job, and releases publish no local runtime image. The PR that removes them SHALL state the wall and summed job time against the median of the last five green `main` runs, and neither SHALL be higher.

#### Scenario: Release
- **WHEN** a `deploy-v` release runs
- **THEN** it publishes the wheel, the library, the scripts and the bridge image, and no `canworks-local-runtime` image
