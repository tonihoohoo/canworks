## MODIFIED Requirements

### Requirement: One-line installer

The repository SHALL provide `scripts/install-pc.sh` (macOS and Linux, POSIX `sh`) and `scripts/install-pc.ps1` (Windows, PowerShell 5.1), and the documentation SHALL give, first among the install routes, the one line per operating system that runs them from the newest release's assets on GitHub (Requirement: Install scripts from the release): on macOS and Linux piped into `sh`, on Windows downloaded to a file and run from it (Requirement: Windows installers without download-and-run). Each script SHALL install uv when uv is not found (`install-pc.sh` with uv's official installer, `install-pc.ps1` from uv's release zip checked against its published SHA-256), use it in the same session, and install the wheel of the newest `deploy-v` release (or of `--version <version>`) from its release download URL with `uv tool install --force --compile-bytecode --python 3.12`, so running the same line again updates to the newest release. The script SHALL find the newest release from the `releases/latest` redirect without the GitHub API, SHALL install only released wheels (never the code on `main`), and with `--wheel <file>` SHALL install that local wheel instead. `--uninstall` SHALL remove the tools and leave uv and the settings folder. When uv's bin folder is not on PATH, the script SHALL add it (`uv tool update-shell`) and say to open a new terminal. The script SHALL print the installed version at the end and exit non-zero, saying why, when any step fails. The documentation SHALL also show the same scripts pinned to a release and how to download and read a script before running it.

CI SHALL run `shellcheck` on `install-pc.sh` and test both scripts' release lookup and argument handling without network access, and the PC tools job SHALL install through the scripts (with `--wheel`) on each of its runners.

#### Scenario: Fresh PC
- **WHEN** a Windows user with neither uv nor Python pastes the documented PowerShell line
- **THEN** uv is installed from its release zip into `%USERPROFILE%\.local\bin` without starting another PowerShell, the newest release's wheel is installed, `canworks-deploy --version` in a new terminal prints that release's version, and `canworks-config` opens the configurator

#### Scenario: Update with the same line
- **WHEN** a Mac user who has 0.82.0 installed pastes the documented line after 0.83.0 was released
- **THEN** 0.83.0 is installed over it, uv is not reinstalled, and the configurator's saved settings are kept

#### Scenario: Given version
- **WHEN** the user runs the script with `--version 0.82.0`
- **THEN** the wheel of `deploy-v0.82.0` is installed, also when a newer release exists

#### Scenario: Uninstall
- **WHEN** the user runs the script with `--uninstall`
- **THEN** the tools' commands are no longer on PATH and uv is still installed

#### Scenario: No release reachable
- **WHEN** the script cannot reach github.com
- **THEN** it exits non-zero, names the URL it could not reach and the proxy setting the docs describe, and changes nothing that was installed

## ADDED Requirements

### Requirement: Windows installers without download-and-run
The Windows install scripts (`install-pc.ps1`, `install-runtime.ps1`, `install-bridge.ps1`) and every documented Windows line that runs them SHALL NOT use `Invoke-Expression`/`iex`, `[scriptblock]::Create`, `-EncodedCommand` or `-ExecutionPolicy Bypass`, and no script SHALL start another `powershell` or `pwsh` process. CI SHALL fail, naming the file and line, when a `.ps1` script under `scripts/` or a documented Windows line uses one of these.

#### Scenario: Fresh Windows PC with Defender on
- **WHEN** a Windows user with Defender real-time protection on and no uv pastes the README's Windows line
- **THEN** the script runs from a file, the tools are installed, and the script starts no PowerShell process

#### Scenario: Pattern added back
- **WHEN** a pull request adds `| iex` to a Windows line in `docs/` or `Invoke-Expression` to `install-bridge.ps1`
- **THEN** CI fails naming that file and line

### Requirement: Install scripts from the release
Each `deploy-v` release SHALL attach the install scripts `install-pc`, `install-runtime` and `install-bridge`, each as `.sh` and `.ps1`, from the released commit as assets. Every documented install line, on every system, SHALL fetch the script from `releases/latest/download/`. Windows lines SHALL save it to a file and run it with `powershell -NoProfile -ExecutionPolicy RemoteSigned -File`, on one line.

#### Scenario: Release assets
- **WHEN** release `deploy-v0.92.0` is created
- **THEN** it has the assets `install-pc.sh`, `install-pc.ps1`, `install-runtime.sh`, `install-runtime.ps1`, `install-bridge.sh` and `install-bridge.ps1` from the released commit

#### Scenario: macOS line
- **WHEN** a Mac user pastes the README's macOS and Linux line
- **THEN** `curl` fetches `install-pc.sh` from the newest release's assets, not from `main`, and pipes it into `sh`

#### Scenario: Options on Windows
- **WHEN** a user wants a given release or to uninstall
- **THEN** the documentation shows the same download line with `-Version 0.82.0` or `-Uninstall` after the file name, and no script block form
- **AND** a pinned line uses `releases/download/deploy-v0.82.0/`

### Requirement: uv from a checked zip on Windows
When `install-pc.ps1` installs uv, it SHALL download uv's Windows zip for the PC's architecture (x86_64 or ARM64) and its `.sha256` file from uv's GitHub release, compare the zip's SHA-256 with it before extracting anything, and put `uv.exe`, `uvx.exe` and `uvw.exe` into `%USERPROFILE%\.local\bin`. On a mismatch or a failed download it SHALL exit non-zero, name the URL, and add nothing to that folder.

#### Scenario: Tampered uv download
- **WHEN** the uv zip downloaded by `install-pc.ps1` does not match its `.sha256`
- **THEN** the script exits non-zero saying the uv download did not match its checksum, and no `uv.exe` was added to `%USERPROFILE%\.local\bin`

#### Scenario: Tested in CI
- **WHEN** a version bump is merged
- **THEN** the PC tools Windows job runs `install-pc.ps1` once with no uv on PATH, so the zip route runs for real

#### Scenario: ARM64 PC
- **WHEN** `install-pc.ps1` installs uv on Windows on ARM
- **THEN** it downloads `uv-aarch64-pc-windows-msvc.zip`

### Requirement: README install blocks per system
In the README, each install step SHALL give one fenced code block per system (Windows; macOS and Linux; the PLC or Linux device), labelled with the system, so that copying a whole block copies only lines for that system.

#### Scenario: Copying the README block
- **WHEN** a Windows user copies the whole Windows code block of the PC tools step in the README
- **THEN** the block holds only PowerShell lines, with no macOS or Linux command
