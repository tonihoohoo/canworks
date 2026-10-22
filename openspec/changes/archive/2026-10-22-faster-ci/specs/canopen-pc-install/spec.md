## MODIFIED Requirements

### Requirement: Tested on Windows, macOS and Linux

CI SHALL install the wheel with uv on a Windows runner, a macOS runner, a Linux x86_64 runner and a Linux ARM64 runner, run the tools' test suite there in as many worker processes as the runner has CPUs (classes named in the workflow's serial list run alone afterwards), and run each of the three commands at least once (deploy tool: schema/EDS check, DCF export and DBC export of a shipped example config; configurator: start and answer its page with its access token; diagnostics: `--help`). The job SHALL run on pushes to `main` that change `tools/deploy/pyproject.toml` (where a version bump is released), on release tags, and when started by hand on any branch; it SHALL NOT run on pull requests, whose Linux run covers the same code. An automatic release SHALL wait for this job's run on the released commit. The README SHALL give the commands to run the same checks on a Windows PC, a Mac or a Linux PC. A test SHALL NOT be skipped on these runners unless it needs something the job does not install (a browser for page tests, the C++ parity binary, CAN hardware), and each such skip SHALL say why.

#### Scenario: Version bump merged
- **WHEN** a pull request that raises the version in `tools/deploy/pyproject.toml` is merged to `main`
- **THEN** the Windows, macOS and both Linux jobs run on the merge commit and the release waits for them

#### Scenario: Suite in parallel
- **WHEN** the Windows job runs the tools' test suite on a 4-CPU runner
- **THEN** the tests run in 4 worker processes and every test runs once

#### Scenario: Linux job fails
- **WHEN** a version bump is merged and the installed-wheel job fails on the Linux ARM64 runner only
- **THEN** no release is created for that commit

#### Scenario: Change to the tools
- **WHEN** a pull request changes files under `tools/deploy/`
- **THEN** the installed-wheel jobs do not run unless started by hand on its branch; the Linux tests in CI still run

#### Scenario: Unrelated change
- **WHEN** a commit on `main` changes only plugin C++ code or docs
- **THEN** the installed-wheel jobs do not run
