## 1. Measure first

- [ ] 1.1 Timing line in `configurator.log` (launch → python up → listening → browser asked → page loaded, ms; "from shortcut" or "from terminal")
- [ ] 1.2 Windows (Toni's own PowerShell, or the Windows PC over Remote Control when the bench is free): with a build that has only 1.1, five starts from the shortcut and five from a terminal, warm; record the lines in this file

## 2. Installer

- [ ] 2.1 `install-pc.sh`, `install-pc.ps1`: read `uv tool list`; same version and no `--force`/`-Force`/`--wheel` → "canworks X is already installed; --force installs it again", exit 0, nothing changed
- [ ] 2.2 Tests: skip on same version, install on older version, install with `--force`, install when `uv tool list` fails or prints something else

## 3. Start path

- [ ] 3.1 `start.py` entry module with the parser and `main`; `canworks-config` entry point to `start:main`; `server` imported only when this process serves; import test: `start` imports neither `server` nor `diag`
- [ ] 3.2 `--from-shortcut`: hand over to a running configurator, else serve in this process (log to file, instance file, open the browser, no-page message window after 15 s)
- [ ] 3.3 Shortcuts on Windows, macOS and Linux run with `--from-shortcut`; `shortcut.windows()` without `-ExecutionPolicy Bypass`
- [ ] 3.4 Terminal start: print the address, return right after the browser was asked; the background configurator logs the address when no page came in 15 s
- [ ] 3.5 Tests for 3.2-3.4 (hand-over, race of two shortcut starts, terminal returns before the page loads, no message window from a terminal start)

## 4. Docs

- [ ] 4.1 `docs/install-pc.md` and README: running the line again updates when there is a newer release and otherwise says it is up to date; `--force` / `-Force`
- [ ] 4.2 `docs/configurator.md#start`: the address is always printed; the timing line in the log

## 5. Release

- [ ] 5.1 PC tools minor version bump; banned-word check

## 6. Desktop checks (after release)

- [ ] 6.1 Windows: run the install line twice; the second run says it is up to date within a few seconds
- [ ] 6.2 Windows: five starts from the shortcut and five from a terminal; record the timing lines next to 1.2's and compare
- [ ] 6.3 macOS: the app starts the configurator; a second click opens a new tab; timing line in the log

## 7. Earlier results (ride this change's PR)

- [ ] 7.1 Tick in archive/2026-10-20-windows-installer-defender/tasks.md, from Toni 2026-10-20 on 0.92.0: 5.1 passed (no Defender detection); 5.2 passed with the note that the rerun reinstalled everything (this change); 6.1 and 7.1 passed (icons, shortcut opens, tab close stops). Tick app-icon-from-logo 3.1 and configurator-survive-sleep 7.3 with the same note
