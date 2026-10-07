# canopen-pc-install Specification

## Purpose
How the PC-side CANopen tools (configurator, deploy tool, diagnostics) reach a developer's Windows PC or Mac: a released wheel installed with uv, without a preinstalled Python, and tested on those systems.

## Requirements

### Requirement: Release wheel

Each release of the PC-side tools SHALL publish exactly one platform-independent wheel (`py3-none-any`) of the tools package as an asset of a GitHub release named and tagged `deploy-v<version>`, where `<version>` is the package version.

The release SHALL be created automatically, without a person pushing a tag, for a commit on `main` when all of these hold: the package version in `pyproject.toml` equals `__version__`; no release or tag `deploy-v<version>` exists yet; the `CI` workflow succeeded on that commit; and the PC tools workflow succeeded on that commit or did not run for it. The tag SHALL point at that commit. While a required run on the commit is still pending, nothing SHALL be published yet, and a later completion SHALL publish it. When a required run failed, nothing SHALL be published for that commit.

An existing release SHALL never be replaced, re-tagged or given a new asset by the automation; running it again for a released version SHALL do nothing and succeed.

Pushing a tag `deploy-v<version>` by hand SHALL still publish a release, and SHALL fail without publishing anything when `<version>` differs from the package version.

Each release's notes SHALL give the install command and list the pull requests merged since the previous `deploy-v` release.

#### Scenario: Version bump merged
- **WHEN** a pull request that changes the package version from 0.20.0 to 0.21.0 is merged to `main`, and `CI` and the PC tools workflow both succeed on the merge commit
- **THEN** a GitHub release `deploy-v0.21.0` exists, its tag points at the merge commit, and it has the asset `openplc_canopen_deploy-0.21.0-py3-none-any.whl`

#### Scenario: No version change
- **WHEN** a commit on `main` keeps the package version 0.21.0 and `deploy-v0.21.0` is already released
- **THEN** no release is created or changed

#### Scenario: Tests failed
- **WHEN** a version bump is merged and the PC tools workflow fails on that commit
- **THEN** no release `deploy-v<version>` is created for that commit

#### Scenario: Second workflow still running
- **WHEN** `CI` finishes green on a version-bump commit while the PC tools workflow on the same commit is still running
- **THEN** nothing is published until the PC tools workflow finishes, and the release is created then if it succeeded

#### Scenario: Older versions are not backfilled
- **WHEN** `main` carries version 0.21.0 and versions 0.18.0 and 0.19.0 were never released
- **THEN** only `deploy-v0.21.0` is released

#### Scenario: Tag matches the package version
- **WHEN** the tag `deploy-v0.16.0` is pushed by hand and the package version at that commit is 0.16.0
- **THEN** a GitHub release `deploy-v0.16.0` exists with the asset `openplc_canopen_deploy-0.16.0-py3-none-any.whl`

#### Scenario: Tag does not match
- **WHEN** the tag `deploy-v0.16.1` is pushed and the package version is 0.16.0
- **THEN** the release job fails, names both versions, and no release asset is published

### Requirement: Install on a PC without Python

The documentation SHALL give, for Windows, for macOS and for Linux, the commands that install the tools on a PC with no Python and no admin rights: install uv with its official installer, then install the release wheel with uv using a uv-managed Python. After these commands the user's shell SHALL find `openplc-canopen-config`, `openplc-canopen-deploy` and `openplc-canopen-diag`, and they SHALL behave as when installed with pip. The documentation SHALL name, per operating system, the folder uv links the commands into and the configurator's settings folder, and SHALL say that the tools reach the CAN bus only through the runtime, so a CAN adapter on the PC is used only by a runtime running on that PC.

#### Scenario: Fresh Windows PC
- **WHEN** a Windows user with no Python installed runs the documented uv install command and then the documented `uv tool install` command on the downloaded wheel, and opens a new terminal
- **THEN** `openplc-canopen-deploy --version` prints the wheel's version and `openplc-canopen-config` opens the configurator in the browser

#### Scenario: Fresh Mac
- **WHEN** a macOS user with no Python installed runs the documented commands
- **THEN** the three commands are on PATH and `openplc-canopen-deploy --version` prints the wheel's version

#### Scenario: Fresh Linux desktop
- **WHEN** a Linux user (x86_64 or ARM64, glibc) runs the documented uv install command and the documented `uv tool install` command, and opens a new terminal
- **THEN** the three commands are in `~/.local/bin` and on PATH, `openplc-canopen-deploy --version` prints the wheel's version, and `openplc-canopen-config` opens the configurator in the default browser

#### Scenario: Linux without a browser
- **WHEN** `openplc-canopen-config` starts on a Linux machine with no browser to open (for example over SSH)
- **THEN** it still serves the page and prints its URL with the access token, and `--no-browser` skips the attempt

#### Scenario: Editor CLI on Linux
- **WHEN** the OpenPLC Editor AppImage has run `openplc-cli install-cli` and the user runs the deploy tool's Build only or New editor project
- **THEN** the tools find `openplc-cli` on PATH and run it

#### Scenario: Corporate proxy
- **WHEN** the PC reaches the internet through a TLS-inspecting proxy
- **THEN** the documentation names the uv option that makes uv trust the operating system's certificate store

### Requirement: Update and uninstall

The documentation SHALL give one command to replace an installed version with a newer wheel and one command to remove the tools, both working without Python on the PC.

#### Scenario: Update
- **WHEN** the user runs the documented update command on a newer wheel
- **THEN** `openplc-canopen-deploy --version` prints the newer version and the configurator's saved settings are kept

#### Scenario: Uninstall
- **WHEN** the user runs the documented uninstall command
- **THEN** the three commands are no longer on PATH

### Requirement: Tested on Windows, macOS and Linux

CI SHALL install the wheel with uv on a Windows runner, a macOS runner, a Linux x86_64 runner and a Linux ARM64 runner, run the tools' test suite there, and run each of the three commands at least once (deploy tool: schema/EDS check, DCF export and DBC export of a shipped example config; configurator: start and answer its page with its access token; diagnostics: `--help`). The job SHALL run on pushes to `main` that change `tools/deploy/pyproject.toml` (where a version bump is released), on release tags, and when started by hand on any branch; it SHALL NOT run on pull requests, whose Linux run covers the same code. An automatic release SHALL wait for this job's run on the released commit. The README SHALL give the commands to run the same checks on a Windows PC, a Mac or a Linux PC. A test SHALL NOT be skipped on these runners unless it needs something the job does not install (a browser for page tests, the C++ parity binary, CAN hardware), and each such skip SHALL say why.

#### Scenario: Version bump merged
- **WHEN** a pull request that raises the version in `tools/deploy/pyproject.toml` is merged to `main`
- **THEN** the Windows, macOS and both Linux jobs run on the merge commit and the release waits for them

#### Scenario: Linux job fails
- **WHEN** a version bump is merged and the installed-wheel job fails on the Linux ARM64 runner only
- **THEN** no release is created for that commit

#### Scenario: Change to the tools
- **WHEN** a pull request changes files under `tools/deploy/`
- **THEN** the installed-wheel jobs do not run unless started by hand on its branch; the Linux tests in CI still run

#### Scenario: Unrelated change
- **WHEN** a commit on `main` changes only plugin C++ code or docs
- **THEN** the installed-wheel jobs do not run

### Requirement: pip route kept

Installing the tools with pip or pipx into an existing Python 3.8+ SHALL keep working and stay documented as an alternative to uv. The documentation SHALL say that Linux distributions that mark their Python as externally managed (PEP 668) refuse a plain `pip install`, and SHALL point those users at uv, pipx or a virtual environment.

#### Scenario: pipx install from a checkout
- **WHEN** a user runs `pipx install ./tools/deploy` from a checkout
- **THEN** the same three commands are installed as with uv

#### Scenario: Externally managed Python
- **WHEN** a Debian or Ubuntu user follows the pip section and their distribution refuses `python3 -m pip install` with "externally-managed-environment"
- **THEN** the same section tells them to use uv, pipx or a virtual environment instead
