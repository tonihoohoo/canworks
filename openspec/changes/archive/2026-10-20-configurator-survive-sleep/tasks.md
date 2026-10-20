# Tasks

## 1. Server: when a page ends

- [x] 1.1 `Server.unused()`: per-page end (`closed + PAGE_CLOSED_S`; silent and `unsaved` never; silent and saved `seen + PAGE_SILENT_S`, now 3600 s) and the end reason (`closed` / `silent`); keep `_live` for "answering" with `PAGE_ANSWERING_S` = 180 s for `second_start`'s ask-first and the heartbeat's `waiting` answer.
- [x] 1.2 Stop reasons: `its last page was closed`, `its last page sent no heartbeat for N minutes`, startup reason unchanged; the log line keeps `canworks-config stopped: <reason>.`
- [x] 1.3 Sleep gap: `_watch_pages` passes each tick's monotonic time to a tick function that adds any gap over `SLEEP_GAP_S` (30 s, minus one tick) to every page's `seen`, `since` and `last_end`.
- [x] 1.4 Unit tests (`test_configurator_instance.py`, times injected): beacon stops after the grace with the "closed" reason; saved page silent past the limit stops with the "silent" reason; unsaved page silent for 10x the limit keeps running, then its beacon stops it; a page that turns saved again times out normally; a sleep gap does not count; startup grace with a gap; a second start with a silent unsaved page opens PATH at once; `--keep-running` unchanged.

## 2. Page: noticing a stopped configurator

- [x] 2.1 `life.js`: beat on `focus` and every `pageshow`; count misses (fetch rejected or no answer in 5 s; HTTP errors are not misses); two misses 2 s apart show the gone notice; one miss stays silent.
- [x] 2.2 Gone notice from `showStopped()`: heading, how to start again, with unsaved work the line that they could not be saved, **Download canworks.json** (Blob of `fileConfig()`) and what it does not hold; styles in light and dark theme.
- [x] 2.3 Page tests (`test_configurator_quit_page.py`): server stopped under an open page, then `visibilitychange` → notice within 5 s; one refused beat → no notice; unsaved node change → download holds the change and the new configurator opens it as edited; 1000/1280/1440 px with no clipped text.

## 3. Remote adapter wording and stop line

- [x] 3.1 a: lock text from the connection (`app.js` `NO_CHANGES`) naming HOST for a remote adapter; check `trace.js` and `tracewin.js` remote texts in the same pass; page test on a remote adapter (fake server) that the lock message names the host and has no "USB adapter".
- [x] 3.2 b: trace drop words from the connection in `trace.js` and `diag.py`'s summary line; unit test of the summary line and a page test with `kernel_drops` from a fake remote.
- [x] 3.3 e: `localbus/adapter.py` says "on this machine"; the `remote:` client adds "the adapter machine HOST" to errors the server raised about its adapter; test with a server whose interface is missing.
- [x] 3.4 d: `adapter-serve` logs `stopped (SIGTERM|Ctrl-C), N PCs were connected`; test that sends SIGTERM to a server subprocess and reads the log line (`test_localbus_serve.py`).

## 4. Install

- [x] 4.1 c: overrides file with `pytest; sys_platform == 'never'` passed by `install-pc.sh` and `install-pc.ps1` to `uv tool install --overrides`; test (stubbed uv) that the option is passed; CI PC tools job asserts no `pytest` in the installed tool environment and runs `canworks-j1939-sim --help` there.
- [x] 4.2 c: `iroh` kept as is; one comment line in `pyproject.toml` on why it is a runtime dependency; upstream report to `can-j1939` to move `pytest` to a test extra (link in the PR). The `pyproject.toml` comment is done; the upstream report was dropped by the project owner, since the one-line installers already leave `pytest` out.
- [x] 4.3 f: `install-pc.sh` runs `uv tool install` with `$BIN` first on PATH for that call, and the uv installer quietly when it supports it; installer test without `$BIN` on PATH: no uv PATH warning, the installer's own hint once; `shellcheck` clean.

## 5. Docs and version

- [x] 5.1 README and `docs/configurator.md` Start: when the configurator stops (closed tab, browser quit, 60 minutes of silence without unsaved changes, never by silence with them, sleep not counted), the gone notice and its download.
- [x] 5.2 `docs/pc-adapter.md` and `docs/diagnostics.md`: remote adapter messages and the stop line; `docs/install-pc.md`: what a `pip` install gets in addition (`pytest` through `can-j1939`) and why `iroh` is installed.
- [x] 5.3 Version 0.91.1 in `pyproject.toml` and `canworks/__init__.py` (patch: fixes, no new options or commands); release notes.

## 6. CI time

- [ ] 6.1 Compare the PR's CI wall and summed job time with the main baseline and note both in the PR.

## 7. Desktop and hardware checks (manual)

- [ ] 7.1 macOS, Safari: open the configurator, lock the screen for more than 3 minutes (20 minutes once with nothing unsaved, once with an unsaved node change); after unlocking the page works without a reload, Save works, and the log has no stop line. Partly passed 2026-10-20 with 0.91.2: started from the app shortcut in Safari, display asleep for 20 minutes with nothing unsaved; the configurator answered at every 5-minute check and the log has no stop line. Not run: the unsaved-change round (Safari did not accept scripted input), and the after-unlock page and Save check. The machine stayed out of system sleep during the run.
- [ ] 7.2 macOS: let the Mac sleep with the tab open for more than 60 minutes and nothing unsaved; after waking the configurator still runs.
- [x] 7.3 Windows: closing the configurator's only tab still stops it within 15 s, the log says its last page was closed, and a USB adapter is free; quitting the browser does the same. Partly passed 2026-10-20 with 0.91.2: closing the only tab stopped it 10 s later with "its last page was closed"; a reload kept it; a second start opened a page on the same server and it stopped after its last page closed; a page with an unsaved change whose browser was killed kept it running past 4 minutes with no stop line. Not run: the USB adapter check and quitting the browser normally. Rest passed 2026-10-20 with 0.92.0 from Toni's own install: the desktop shortcut opens the configurator and closing the tab stops it (windows-installer-defender 7.1).
- [ ] 7.4 Windows or macOS: stop the configurator from a terminal while its tab is in the background; returning to the tab shows the gone notice; with an unsaved change the downloaded canworks.json opens with the change in a new configurator.
- [ ] 7.5 Remote adapter from a PC to a Linux machine: lock text and trace drop words name the host; a missing interface on the server gives the adapter machine message; `systemctl stop` of the service leaves the stop line in its journal.
- [ ] 7.6 One-line Linux installer through a non-login SSH command on a machine without uv: no uv PATH warning, the installer's hint once, and no `pytest` in the tools' environment.
