# Proposal

## Why

Two slow spots Toni found on Windows with PC tools 0.92.0:

- **Running the install line again reinstalls everything.** The installers always run `uv tool install --force`, which rebuilds the tools' environment and compiles bytecode for every package, even when the newest release is already installed. On Windows that is close to a minute for nothing.
- **The configurator takes about 5 s to open**, from the desktop shortcut and from a terminal alike (over 10 s on the first start after an install, while Defender scans the new files once). Before the background start of 0.91.0 the page opened in about 1.8 s on the same PC. On Linux the whole start takes 0.6 s, so the extra is Windows process start cost multiplied by how many processes a start runs: the shortcut or `canworks-config` starts Python, which imports the whole configurator just to start a second Python for the background configurator, waits for it, opens the browser, and then waits until the browser has loaded the page before it returns. On Windows each uv `python`/`pythonw` is a launcher that starts the real interpreter, so one start is four processes, each scanned by Defender.

## What Changes

- **Skip an up-to-date install.** `install-pc.sh` and `install-pc.ps1` read the installed version (`uv tool list`) first. When it equals the release they would install, they say so ("canworks 0.92.0 is already installed; --force installs it again") and exit 0 without touching the environment or the shortcut. `--force` (`-Force`) installs anyway; `--wheel` always installs; a newer release installs as before.
- **Start timing in the log.** Every start writes one line to `configurator.log` with the time of each step since the start was launched (starter up, background configurator listening, browser asked, first page loaded), so a slow start can be measured on any PC without tools.
- **The shortcut starts one configurator, not a starter.** The Windows shortcut runs `pythonw -m canworks.configurator.server --from-shortcut`: with no configurator running, that process is the background configurator itself (it has no console already) and opens the browser; with one running, it opens a tab of that one and exits. macOS and Linux shortcuts do the same through their launchers.
- **The terminal start returns at once.** `canworks-config` prints the start address and returns as soon as the background configurator listens and the browser was asked, instead of waiting up to 15 s for the page. The 15 s "no page opened" check moves into the background configurator, which shows the message window (shortcut) or only logs the address (terminal, where it was already printed).
- **A light starter.** `canworks-config` points at a small entry module that parses the arguments and starts or hands over, importing the configurator itself only in the process that serves pages.
- **No `-ExecutionPolicy Bypass` when writing shortcuts.** `canworks-config --create-shortcut` runs PowerShell with `-Command` only (execution policy does not apply to a command string), removing the last Bypass from the Windows install path.
- PC tools minor version bump.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `canopen-pc-install`: new requirement Skip an up-to-date install.
- `canopen-configurator`: Start without a terminal (returns once the browser was asked; the no-page check in the background configurator), App shortcut (one process, no starter), new requirement Start timing in the log.

## Impact

- `scripts/install-pc.sh`, `scripts/install-pc.ps1` (version check, `--force`/`-Force`), their tests.
- `tools/deploy/canworks/configurator/launch.py`, `server.py` (entry split, `--from-shortcut`, timing line, no-page check moved), a new small entry module, `shortcut.py` (target arguments, no Bypass), `pyproject.toml` (the `canworks-config` entry point), their tests.
- `docs/install-pc.md`, `docs/configurator.md#start`, README (rerun wording).
