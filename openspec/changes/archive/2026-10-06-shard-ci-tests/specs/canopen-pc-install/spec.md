## MODIFIED Requirements

### Requirement: Tested on Windows and macOS

CI SHALL install the wheel with uv on a Windows runner and a macOS runner, run the tools' test suite there, and run each of the three commands at least once (deploy tool: schema/EDS check, DCF export and DBC export of a shipped example config; configurator: start and answer its page with its access token; diagnostics: `--help`). The job SHALL run on pushes to `main` that change `tools/deploy/pyproject.toml` (where a version bump is released), on release tags, and when started by hand on any branch; it SHALL NOT run on pull requests, whose Linux run covers the same code. An automatic release SHALL wait for this job's run on the released commit. The README SHALL give the commands to run the same checks on a Windows PC or Mac. A test SHALL NOT be skipped on Windows or macOS unless it needs something the runner cannot provide (a browser for page tests, the C++ parity binary, CAN hardware), and each such skip SHALL say why.

#### Scenario: Version bump merged
- **WHEN** a pull request that raises the version in `tools/deploy/pyproject.toml` is merged to `main`
- **THEN** the Windows and macOS jobs run on the merge commit and the release waits for them

#### Scenario: Change to the tools
- **WHEN** a pull request changes files under `tools/deploy/`
- **THEN** the Windows and macOS jobs do not run unless started by hand on its branch; the Linux tests in CI still run

#### Scenario: Unrelated change
- **WHEN** a commit on `main` changes only plugin C++ code or docs
- **THEN** the Windows and macOS jobs do not run
