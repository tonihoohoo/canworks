## MODIFIED Requirements

### Requirement: Windows installers without download-and-run
The Windows install scripts (`install-pc.ps1`, `install-bridge.ps1`) and every documented Windows line that runs them SHALL NOT use `Invoke-Expression`/`iex`, `[scriptblock]::Create`, `-EncodedCommand` or `-ExecutionPolicy Bypass`, and no script SHALL start another `powershell` or `pwsh` process. CI SHALL fail, naming the file and line, when a `.ps1` script under `scripts/` or a documented Windows line uses one of these.

#### Scenario: Fresh Windows PC with Defender on
- **WHEN** a Windows user with Defender real-time protection on and no uv pastes the README's Windows line
- **THEN** the script runs from a file, the tools are installed, and the script starts no PowerShell process

#### Scenario: Pattern added back
- **WHEN** a pull request adds `| iex` to a Windows line in `docs/` or `Invoke-Expression` to `install-bridge.ps1`
- **THEN** CI fails naming that file and line

### Requirement: Install scripts from the release
Each `deploy-v` release SHALL attach the install scripts `install-pc` and `install-bridge`, each as `.sh` and `.ps1`, and the device probe `device-probe.sh`, from the released commit as assets. Every documented install line, on every system, SHALL fetch the script from `releases/latest/download/`. Windows lines SHALL save it to a file and run it with `powershell -NoProfile -ExecutionPolicy RemoteSigned -File`, on one line.

#### Scenario: Release assets
- **WHEN** release `deploy-v0.92.0` is created
- **THEN** it has the assets `install-pc.sh`, `install-pc.ps1`, `install-bridge.sh`, `install-bridge.ps1` and `device-probe.sh` from the released commit, and no `install-runtime` script

#### Scenario: macOS line
- **WHEN** a Mac user pastes the README's macOS and Linux line
- **THEN** `curl` fetches `install-pc.sh` from the newest release's assets, not from `main`, and pipes it into `sh`

#### Scenario: Options on Windows
- **WHEN** a user wants a given release or to uninstall
- **THEN** the documentation shows the same download line with `-Version 0.82.0` or `-Uninstall` after the file name, and no script block form
- **AND** a pinned line uses `releases/download/deploy-v0.82.0/`
