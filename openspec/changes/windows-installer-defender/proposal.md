# Proposal

## Why

Microsoft Defender reported the Windows one-line PC tools installer from the README as malware. The exact detection was not recorded, so the cause is inferred, not reproduced. Our Windows install path has every pattern that Defender's script and behaviour checks flag in real malware:

- The README line starts PowerShell with `-ExecutionPolicy ByPass` and pipes a downloaded script into `iex` (`irm <url> | iex`), the classic "download cradle".
- When uv is missing, `scripts/install-pc.ps1` starts a second, hidden-console `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`: a PowerShell that spawns another PowerShell to download and run code. This child process is the most likely trigger, and it is fully in our hands.
- The option forms and the runtime and bridge lines use `& ([scriptblock]::Create((irm <url>)))`, the same pattern written differently.

A tool for industrial engineers cannot start with an antivirus warning; many company PCs block it outright.

At the same time the README's install code blocks mix operating systems in one block (`# macOS, Linux` / `# Windows` comments on adjacent lines), so a reader copying the block gets the other system's line too. Toni asked for one block per operating system.

## What Changes

- **uv without a script download-and-run.** `install-pc.ps1` installs a missing uv by downloading uv's Windows zip for the PC's architecture (`uv-x86_64-pc-windows-msvc.zip` or `uv-aarch64-pc-windows-msvc.zip`) from uv's GitHub release, checking it against the `.sha256` file published next to it, and extracting `uv.exe`, `uvx.exe` and `uvw.exe` into `%USERPROFILE%\.local\bin`, where uv's own installer puts them. No child PowerShell, no `iex`, no `-ExecutionPolicy` switch inside the script. A checksum mismatch stops the install and leaves nothing behind.
- **No `iex` or script blocks in any Windows line.** The documented Windows lines download the script to a file and run it with `powershell -NoProfile -ExecutionPolicy RemoteSigned -File <file>`, options after the file name (`-Version 0.82.0`, `-Uninstall`, `-Ssh pi@rpi.local`). This applies to `install-pc.ps1`, `install-runtime.ps1` and `install-bridge.ps1` in the README, `docs/install-pc.md`, `docs/install-stock.md`, `docs/modbus-bridge.md` and the release notes template.
- **Windows scripts as release assets.** Each `deploy-v` release attaches `install-pc.ps1`, `install-runtime.ps1` and `install-bridge.ps1`. The documented lines download them from `releases/latest/download/`, so the script a user runs is the released one (not whatever is on `main`), and the URL is a GitHub release download rather than a raw file. Pinning to a release uses `releases/download/deploy-v<version>/`.
- **A guard in CI.** A test fails when a `.ps1` script under `scripts/` uses `Invoke-Expression`/`iex`, `[scriptblock]::Create`, `-EncodedCommand` or starts `powershell`/`pwsh`, or when a Windows line in the README, `docs/` or the release notes template pipes into `iex` or uses `ExecutionPolicy Bypass`.
- **README: one code block per operating system.** Every install block in the README is split into separate blocks headed by the system ("Windows (PowerShell)", "macOS and Linux", "On the PLC"), each holding only lines for that system, with no trailing `# Windows` comments, so the whole block can be copied. The same for the plugin install (on the PLC, from macOS/Linux over SSH, from Windows over SSH) and the bridge.
- **Manual uv step on Windows.** `docs/install-pc.md` step 1 gives `winget install --id astral-sh.uv -e` first on Windows, with uv's own PowerShell line as the alternative.
- PC tools minor version bump (0.92.0), so a release with the new assets exists as soon as the change merges.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `canopen-pc-install`: Requirement One-line installer changes how the Windows line runs and how a missing uv is installed; new requirements Windows installers without download-and-run (with the CI guard), Windows scripts from the release, uv from a checked zip on Windows, and README install blocks per system.

## Impact

- `scripts/install-pc.ps1` (uv zip install with checksum, comment header with the new lines), `scripts/install-runtime.ps1` and `scripts/install-bridge.ps1` (comment headers only).
- `.github/workflows/release-deploy.yml` (three more assets on `gh release create`), `.github/workflows/pc-tools.yml` (Windows job also runs the installer once with uv hidden from PATH, so the zip route runs for real).
- `test/pc-tools/test_install_scripts.py` (uv zip install, checksum mismatch, the guard), `tools/deploy/release-notes.md` (Windows line, names the new assets; the template test already enforces that).
- README.md (Quick start blocks per OS), `docs/install-pc.md`, `docs/install-stock.md`, `docs/modbus-bridge.md`.
- Nothing changes for macOS and Linux lines, the runtime plugin or the tools themselves.
- Existing installs need nothing: running the new line updates as before.
