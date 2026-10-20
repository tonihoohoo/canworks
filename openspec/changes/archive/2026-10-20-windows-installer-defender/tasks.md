## 1. Detection (Toni, own PowerShell, not the Claude app)

- [ ] 1.1 Windows Security → Virus & threat protection → Protection history: note the detection name and the blocked item of the earlier install (or `Get-MpThreatDetection | Select-Object -Last 5` in an admin PowerShell), and add it to design.md

## 2. Installer

- [x] 2.1 `install-pc.ps1`: install a missing uv from uv's release zip for the PC's architecture, check it against its `.sha256`, extract `uv.exe`, `uvx.exe`, `uvw.exe` into `%USERPROFILE%\.local\bin`; `CANWORKS_UV_DOWNLOAD` overrides the base URL; `-DryRun` prints the download and the target folder; no child PowerShell
- [x] 2.2 Comment headers of `install-pc.ps1`, `install-runtime.ps1`, `install-bridge.ps1` show the download-then-`-File` lines with options; headers of the `.sh` scripts show the `releases/latest/download/` URL
- [x] 2.3 `release-deploy.yml`: attach the three `.ps1` and the three `.sh` install scripts to each `deploy-v` release; `tools/deploy/release-notes.md` names them and uses the new lines

## 3. Docs

- [x] 3.1 README Quick start: one code block per system for the PC tools, the plugin (on the PLC, from macOS/Linux, from Windows) and the bridge; every line downloads from `releases/latest/download/`; Windows lines run with `-ExecutionPolicy RemoteSigned -File`
- [x] 3.2 `docs/install-pc.md`: new Windows line, options after the file name, pinning with `releases/download/deploy-v<version>/`; step 1 gives `winget install --id astral-sh.uv -e` first on Windows; a short note that the line runs no downloaded code through `iex`
- [x] 3.3 `docs/install-pc.md`, `docs/install-stock.md`, `docs/modbus-bridge.md`, `docs/deploy.md`: every system's line from the release assets, Windows lines in the new form, one block per system

## 4. Checks

- [x] 4.1 Tests: uv zip install from the fake release server (files land in `.local\bin`), checksum mismatch stops and copies nothing, ARM64 picks the aarch64 zip
- [x] 4.2 Guard test: no `iex`/`Invoke-Expression`/`scriptblock]::Create`/`-EncodedCommand`/nested `powershell` in `scripts/*.ps1`, and no `| iex` or `ExecutionPolicy Bypass` in the documented Windows lines
- [x] 4.3 PC tools Windows job: a second installer run with setup-uv's uv hidden from PATH, so uv comes from its zip into `~/.local/bin`
- [x] 4.4 PC tools minor version bump (0.92.0); banned-word check on the changed files

## 5. Windows check (after the 0.92.0 release; Toni, own PowerShell with Defender real-time protection on)

- [x] 5.1 On a PC (or user) without uv: paste the README Windows line; no Defender detection, uv lands in `.local\bin`, the tools and the shortcut are installed, `canworks-deploy --version` prints 0.92.0 in a new terminal Passed 2026-10-20 with 0.92.0 (Toni, own PowerShell): no Defender detection, installed.
- [x] 5.2 Paste it again: updates without reinstalling uv, no detection Passed 2026-10-20 with 0.92.0, no detection; the rerun reinstalled everything (uv `--force`, bytecode compile about 18 s), fixed by skip-reinstall-faster-start.
- [ ] 5.3 The runtime line from Windows over SSH with `-DryRun`: prints the ssh command, no detection
- [ ] 5.4 macOS: paste the README macOS line; the release asset script updates the tools (uv already there)

## 6. App icon checks carried over from app-icon-from-logo (run with section 5)

- [x] 6.1 (app-icon-from-logo 3.1) Windows: after the normal install in 5.1 (from your own PowerShell, not the Claude app, whose sandboxed install made the shortcuts fail with "No Python at"), the desktop and Start menu "canworks configurator" shortcuts show the new icon in Explorer (small "c" over the two wires, "can" over the bus at 48 px and up) and open the configurator; run `ie4uinit.exe -show` if Explorer still shows the cached old icon Passed 2026-10-20 with 0.92.0 (Toni).
- [ ] 6.2 (app-icon-from-logo 3.2) macOS: update from a normal terminal to 0.91.3 or newer; `~/Applications/canworks configurator.app` shows the new icon in Finder (list view: the "c", icon view: "can" over the bus) and opens the configurator

## 7. Desktop check carried over from configurator-survive-sleep (run with section 5)

- [x] 7.1 (configurator-survive-sleep 7.3, tick it there too) Windows: after the normal install in 5.1, double-click the desktop shortcut; the configurator opens in the browser with no console window. Close the tab: it stops within about 15 s and `configurator.log` says "stopped: its last page was closed". Optional: with an unsaved change, kill the browser in Task Manager; it keeps running past 4 minutes Passed 2026-10-20 with 0.92.0 (Toni). Starts took about 5 s (over 10 s right after the install); see skip-reinstall-faster-start.
