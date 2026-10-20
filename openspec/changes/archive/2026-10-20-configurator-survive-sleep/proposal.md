# Proposal: configurator-survive-sleep

## Why

Desktop checks of PC tools 0.91.0 (configurator-quit-and-background, add-remote-adapter) found one real problem and a handful of small ones.

**The configurator stops under a locked screen.** The configurator stops when its last page is gone: 10 s after the page's `pagehide` beacon, or 3 minutes after the last heartbeat (`PAGE_SILENT_S`, the page beats every 30 s). With the screen locked on a Mac, Safari stops the page's timers, so no heartbeat arrives; after 3 minutes the server stops while its tab is still open. On return the tab looks alive but every request fails, and the log says `canworks-config stopped: its last page was closed.`, the same line as for a closed tab.

Read in the code (`configurator/server.py` `Server.unused`, `_live`; `static/life.js`):
- The heartbeat carries `unsaved`, but `unused()` ignores it: a page with unsaved changes times out like any other. The draft config lives in the page (`fileConfig()`), so it is not gone from memory, but Save needs the server, a new `canworks-config` gets a new port and a new session, and the old page cannot reach it. In practice the edits are lost, and so are EDS and notes imports that were not saved (they live in the server's session).
- `unused()` returns one reason, "its last page was closed", whether the page sent its close beacon or just went quiet.
- A failed heartbeat is ignored ("the next beat tells"), so the page never says that the configurator has gone.
- The silence is counted on `time.monotonic()`, which on some systems keeps counting while the machine sleeps and on others does not; nothing in the code decides which.

**Small problems found on the same run:**
- a. With `--adapter remote:...` (Adapter on another machine) the lock banner says "Changes are off for this USB adapter connection".
- b. A trace on a remote adapter reports frames "dropped by the PLC's kernel"; there is no PLC, the drops are the adapter machine's.
- c. Installing 0.91.0 pulls `pytest` and `iroh` into the tools' environment. `pytest` is not ours: `can-j1939` 2.0.12 lists `pytest` (and `numpy`) as runtime requirements in its wheel. `iroh` is ours and is used by the remote link on the PC (`canworks-config` connect panel, `canworks-diag`) and by `canworks-link`.
- d. `canworks-diag adapter-serve` logs a start line but nothing when SIGTERM (systemd stop) or Ctrl-C ends it.
- e. A remote adapter whose server cannot find its interface reports `no CAN interface slcan0 on this PC` on the client PC, which reads as if the PC were missing it.
- f. The one-line Linux installer over a non-login SSH shell prints uv's own "not on your PATH" warning, next to the installer's own hint.

## What Changes

- **A page with unsaved changes keeps the configurator.** Silence alone never stops a configurator whose last page reported unsaved changes; only its close beacon (plus the 10 s grace), Quit, or a signal stop it.
- **A longer silence limit for the rest.** A page without unsaved changes counts as gone after 60 minutes without a heartbeat (was 3 minutes). Closing the tab, closing the browser and Quit still stop it within 15 s, because those send the close beacon; the silence limit is only the fallback for a crashed browser.
- **Sleep does not count.** The server's watch loop measures the gap between its own ticks; a gap far longer than a tick means the process did not run (the machine slept), and that time is not counted as silence on any operating system.
- **Distinct stop reasons in the log:** "its last page was closed" (beacon), "its last page sent no heartbeat for 60 minutes" (silence), and the existing startup and Quit reasons.
- **A page notices a configurator that has gone.** When a page becomes visible again, returns from the back/forward cache or gets focus, it beats at once; when the configurator does not answer (twice, 2 s apart, connection refused or no answer), the page shows that canworks-config is not running any more, how to start it again (the shortcut, or `canworks-config` in a terminal), and, with unsaved changes, a **Download canworks.json** button that saves the page's draft config. Starting the configurator from the page itself is not possible (see design).
- **Small fixes:**
  - a. The lock texts name the connection: "this connection to the adapter on HOST" for a remote adapter, "this USB adapter connection" for a local one.
  - b. Trace drop counts on a remote adapter say "dropped by the adapter machine's kernel (HOST)", in the page and in `canworks-diag trace`.
  - c. `iroh` stays a runtime dependency (it is the remote link, a core PC feature, and has no dependencies of its own). `pytest` is kept out of the one-line installs: the installers pass uv an override that drops `can-j1939`'s `pytest` requirement, the J1939 tools are tested without it, and `docs/install-pc.md` says why a `pip` install still gets it.
  - d. `adapter-serve` logs `stopped (SIGTERM)` or `stopped (Ctrl-C)` with the number of PCs that were connected, before it exits.
  - e. Errors that come from the adapter server name its machine: "no CAN interface slcan0 on the adapter machine HOST".
  - f. `install-pc.sh` runs `uv tool install` with uv's bin folder on PATH for that call, so uv prints no PATH warning, and keeps its own one-line hint to open a new terminal.
- README, `docs/configurator.md` (Start: when it stops), `docs/pc-adapter.md`, `docs/install-pc.md` and `docs/diagnostics.md` updated in the same PR.
- PC tools version 0.91.1 (patch: fixes, no new options or commands).

## Capabilities

### Modified Capabilities
- `canopen-configurator`: Closing the last tab stops the configurator (unsaved pages and sleep do not time out, longer silence limit, distinct log reasons); new requirement for a page whose configurator has stopped; lock and trace texts on a remote adapter.
- `canopen-remote-adapter`: messages that name the adapter machine; a stop line in the server's log.
- `canopen-pc-install`: no `pytest` in the one-line installs; no uv PATH warning from the installer.

## Impact

- `tools/deploy/canworks/configurator/server.py` (`Server.heartbeat`, `unused`, `_watch_pages`, constants), `static/life.js`, `static/app.js` (lock text), `static/trace.js`, `static/style.css` (stopped notice).
- `tools/deploy/canworks/localbus/serve.py`, `localbus/adapter.py`, the remote adapter client, `diag.py` (trace summary line).
- `scripts/install-pc.sh`, `scripts/install-pc.ps1`, `tools/deploy/pyproject.toml` and `canworks/__init__.py` (version only).
- Tests: `tools/deploy/tests/test_configurator_instance.py`, `test_configurator_quit_page.py`, `test_configurator_remote_adapter*.py`, `test_localbus_serve.py`, `test/pc-tools/test_install_scripts.py`.
