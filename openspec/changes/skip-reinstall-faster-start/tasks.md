## 1. Measure first

- [x] 1.1 Timing line in `configurator.log` (launch → python up → listening → browser asked → page loaded, ms; "from shortcut" or "from terminal")
- [x] 1.2 Windows (Toni's own PowerShell, or the Windows PC over Remote Control when the bench is free): with a build that has only 1.1, five starts from the shortcut and five from a terminal, warm; record the lines in this file. Done 2026-10-20 over Remote Control on 0.91.3 (the Remote Control shell sees its own sandboxed AppData copy of the tools, not Toni's 0.92.0), before any code change, with stopwatch timing instead of the timing line; Chrome already running, Defender on, medians of 5 warm runs: `python -c pass` 161 ms, `pythonw -c pass` 177 ms, `import canworks.configurator.server` 989 ms (http.server 274, canworks.axis 155 of it), terminal `canworks-config` to instance.json 1542 ms and to exit (page loaded) 2179 ms, shortcut command to instance.json 1660 ms and to exit 2301 ms. So a start was about 0.16 s Python, 0.8 s import in the starter, again in the background configurator, 0.5 s to listening and 0.6 s browser. The environment holds 1450 files (numpy and pywin32 most of them), which is what install-time bytecode compilation spends its 18 s on

## 2. Installer

- [x] 2.1 `install-pc.sh`, `install-pc.ps1`: read `uv tool list`; same version and no `--force`/`-Force`/`--wheel` → "canworks X is already installed; --force installs it again", exit 0, nothing changed
- [x] 2.2 Tests: skip on same version, install on older version, install with `--force`, install when `uv tool list` fails or prints something else

## 3. Start path

- [x] 3.1 `start.py` entry module with the parser and `main`; `canworks-config` entry point to `start:main`; `server` imported only when this process serves; import test: `start` imports neither `server` nor `diag`
- [x] 3.2 `--from-shortcut`: hand over to a running configurator, else serve in this process (log to file, instance file, open the browser, no-page message window after 15 s)
- [x] 3.3 Shortcuts on Windows, macOS and Linux run with `--from-shortcut`; `shortcut.windows()` without `-ExecutionPolicy Bypass`
- [x] 3.4 Terminal start: print the address, return right after the browser was asked; the background configurator logs the address when no page came in 15 s
- [x] 3.5 Tests for 3.2-3.4 (hand-over, race of two shortcut starts, terminal returns before the page loads, no message window from a terminal start)

## 4. Docs

- [x] 4.1 `docs/install-pc.md` and README: running the line again updates when there is a newer release and otherwise says it is up to date; `--force` / `-Force`
- [x] 4.2 `docs/configurator.md#start`: the address is always printed; the timing line in the log

## 5. Release

- [x] 5.1 PC tools minor version bump; banned-word check

## 6. Desktop checks (after release)

- [ ] 6.1 Windows: run the install line twice; the second run says it is up to date within a few seconds
- [ ] 6.2 Windows: five starts from the shortcut and five from a terminal; record the timing lines next to 1.2's and compare
- [ ] 6.3 macOS: the app starts the configurator; a second click opens a new tab; timing line in the log

## 7. Earlier results (ride this change's PR)

- [x] 7.1 Tick in archive/2026-10-20-windows-installer-defender/tasks.md, from Toni 2026-10-20 on 0.92.0: 5.1 passed (no Defender detection); 5.2 passed with the note that the rerun reinstalled everything (this change); 6.1 and 7.1 passed (icons, shortcut opens, tab close stops). Tick app-icon-from-logo 3.1 and configurator-survive-sleep 7.3 with the same note
