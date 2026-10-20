## Context

Start path today (`launch.py`, `server.main`): the shortcut runs `pythonw -m canworks.configurator.server`; a terminal runs the `canworks-config` uv launcher. Either imports `server.py` (and through it `diag`, `contract`, `axis`, `http.server`), checks for a running instance, then `spawn()`s `pythonw -m canworks.configurator.server --child-background`, polls for its instance file every 100 ms, asks it for a start URL, calls `webbrowser.open`, and `wait_for_page` polls up to 15 s until the browser used the URL's one-time code; only then does the starter exit (or show the address). Measured on Linux (0.92.0, warm cache): 0.6 s from command to page loaded by a stand-in browser. Toni on Windows: about 5 s from shortcut or terminal, over 10 s on the first start after install; 1.8 s with 0.82.0 (foreground start). The Windows step times are not measured yet; task 1 does that with the timing line before the code changes land, and task 6 after.

## Goals / Non-Goals

**Goals:** a rerun of the install line on an up-to-date PC finishes in seconds and changes nothing; fewer process starts per configurator start; the terminal prompt back as soon as the browser was asked; a timing line that shows where a start spends its time.

**Non-Goals:** opening the browser before the configurator listens (would need handing a listening socket to the child); a native launcher `.exe`; changing what happens when a configurator already runs (still a new tab); Defender exclusions (never something the tools should set up).

## Decisions

- **Version check by `uv tool list`.** The installers run `uv tool list` and look for the line `canworks v<version>`. This is uv's own record of what it installed, works without starting the tools, and costs one uv call. Equal to the target and no `--force`/`--wheel`: print the "already installed" line, also the bin folder hint when it is not on PATH, and exit 0. Anything else (not installed, other version, uv list fails) installs as today. The shortcut is not recreated on a skip; `--force` recreates it. Alternative considered: `canworks-deploy --version`, which starts Python (seconds on Windows) to learn the same thing.
- **`--from-shortcut` makes the started process the configurator.** The shortcut's process already has no console (pythonw, the macOS app, a `.desktop` entry), so there is nothing to detach from. With `--from-shortcut`: a running configurator gets the usual hand-over (new tab) and the process exits; otherwise the process becomes the background configurator directly (log to file, publish the instance file, open the browser itself, the 15 s no-page message window). The race of two shortcut clicks is the one `server.publish` already settles (the loser hands over). Shortcuts made by an older version keep working (they run without the flag and take the starter path); the installer recreates them on update. Saves one full Python start (two processes on Windows) from every shortcut start.
- **Terminal start returns when the browser was asked.** The starter prints `canworks configurator: <url>` and the background line, then exits right after `webbrowser.open`. The background configurator owns the 15 s check: with no page by then it logs the address, and shows the message window only when it was started from the shortcut (from a terminal the address was already printed there). The spec's terminal scenario changes from "shows the address when no browser opened" to "always prints the address".
- **Light entry module.** New `canworks/configurator/start.py` holds the argument parser and `main`; it imports `launch` (standard library only) and imports `server` only when this process serves (foreground, `--child-background`, `--from-shortcut` without a running instance). `pyproject.toml` points `canworks-config` at `start:main`; `python -m canworks.configurator.server` keeps working by calling `start.main`. The fast-start import test (canopen-pc-install) gains a case: importing `start` imports neither `server` nor `diag`.
- **Timing line.** The starter puts its launch time (wall clock, ms) in the environment of the background configurator (`CANWORKS_START_T0`), or the shortcut process uses its own start time. The configurator logs one line once its first page loaded: `start timing: python 140 ms, listening 420 ms, browser asked 450 ms, page 1310 ms (from shortcut)`, all relative to the launch. A start whose page never loads logs the line without `page`. No option needed; the line is useful in every bug report.
- **Shortcut PowerShell without Bypass.** `shortcut.windows()` runs `powershell -NoProfile -NonInteractive -Command <script>`: execution policy applies to script files, not to `-Command` text, so Bypass bought nothing and is one of the patterns Defender weighs.

## Risks / Trade-offs

- [The 5 s is mostly the browser or Defender, not our processes] → task 1 measures before changing code; the changes still remove one Python start and the 15 s wait from the terminal, which cost real time on every PC. If Windows numbers show the browser dominates, the reply says so and nothing more is built for it.
- [`uv tool list` output format changes] → a line that does not parse means "not installed", so the installer installs as today; a test pins the parse against uv's current format.
- [Old shortcuts without `--from-shortcut`] → keep working through the starter path; recreated by the installer's next real install or `canworks-config --create-shortcut`.

## Open Questions

None; the Windows timings decide only how much of the gain each step gives.
