# Design: configurator-survive-sleep

## What the server can and cannot know

The server sees two signals from a page: the `pagehide` beacon (`/api/page/closed`) and the heartbeat (`/api/heartbeat {page, unsaved}`, every 30 s, on becoming visible, on `pageshow` from the back/forward cache, and within a second of the page's unsaved state changing). From silence alone it cannot tell a crashed browser from a tab whose timers the browser stopped (locked screen, Safari's background tab policy, a laptop lid). Any silence rule is a trade between stopping a configurator someone still uses and keeping one nobody can reach (with its adapter connection open).

The beacon is the reliable signal for the normal ways a page ends: closing the tab, closing the window, quitting the browser, a reload (followed by the new page's heartbeat). The silence rule only exists for the abnormal ones: a browser crash, a killed browser process, a machine that never came back. Those are rare, and in all of them a later `canworks-config` finds the running configurator through `instance.json` and opens a page on it, so a long silence limit costs little. A short one, as 0.91.0 showed, stops configurators that are in use.

## Chosen rules

`Server.unused()` keeps one table of pages (`seen`, `closed`, `unsaved`) and decides per page when it ended:

| Page's last state | Ends at |
|---|---|
| Close beacon received | `closed + PAGE_CLOSED_S` (10 s, unchanged) |
| Silent, last heartbeat said `unsaved: true` | never by silence |
| Silent, last heartbeat said `unsaved: false` | `seen + PAGE_SILENT_S`, now 3600 s (was 180 s) |

The configurator stops when every page has ended, as today. `--keep-running`, Quit and SIGTERM/SIGHUP are unchanged.

- **Unsaved pages never time out.** A page's unsaved changes are its own memory; the server is the only way to save them. Stopping the server under them is the one outcome that loses work, so silence alone never does it. The cost is a configurator that stays up after a browser crash with unsaved changes, until the user starts `canworks-config` again (which opens a page on it) or presses Quit there. That is the right default for unsaved work.
- **A second start does not wait for a silent unsaved page.** `second_start` asks "the page with unsaved changes" first only when that page is answering (`_live`, heartbeat within 3 minutes as today, kept as `PAGE_ANSWERING_S`). A silent unsaved page does not hold a second start's PATH; the new page opens it.
- **A silent unsaved page stays counted when other pages close.** After a browser crash with unsaved changes, a later page opened on the same configurator and then closed leaves it running; Quit on that page stops it. Keeping the rule to one sentence ("silence alone never ends an unsaved page") is easier to test and explain than a rule that depends on other pages.
- **60 minutes for the rest.** Long enough for a locked screen during a meeting or lunch; short enough that a crashed browser does not leave an adapter connection open for the rest of the day. It is a constant, as today, so tests set it short.

## Sleep does not count

`time.monotonic()` stops during system sleep on Linux and macOS and keeps going on Windows. Rather than depend on that, the watch loop (`_watch_pages`, a 1 s tick) remembers the monotonic time of its last tick. When a tick arrives more than `SLEEP_GAP_S` (30 s) after the previous one, the process did not run in between: the gap minus one tick is added to every page's `seen`, so it is not counted as silence. The same correction applies to the startup grace. This is deterministic, needs no wall clock, and is tested by calling the tick function with chosen times.

It does not cover the locked-screen case on an awake machine (the server runs, the page does not), which the two rules above cover.

## Distinct stop reasons

`unused()` records why each page ended (`"closed"` or `"silent"`) and returns the reason of the page that ended last:
- `its last page was closed` (beacon),
- `its last page sent no heartbeat for 60 minutes` (silence; the minutes from `PAGE_SILENT_S`),
- `no page was opened within 10 minutes of its start` (unchanged).

The log line stays `canworks-config stopped: <reason>.`

## The page side

`life.js`:
- `heartbeat()` also runs on `focus` and on every `pageshow` (not only persisted ones), so a page that comes back asks at once.
- A heartbeat that fails with a network error (fetch rejects: connection refused, reset) or gets no answer within 5 s counts as a miss; an HTTP error does not (the server answered). Two misses in a row, the second 2 s after the first, show the gone notice. One miss alone stays silent: a reload of the server's port or a slow answer is not a stop.
- The gone notice reuses `showStopped()` with a different heading: "canworks-config is not running any more." and "It may have been stopped from another tab, by the system, or because this page was away too long." It says how to start it again: the **canworks configurator** shortcut, or `canworks-config` in a terminal, which opens a new tab. With unsaved work it adds "This page's unsaved changes could not be saved." and **Download canworks.json**, which saves `fileConfig()` as JSON through a Blob link, and names what cannot be downloaded (EDS and notes files imported since the last save, the simulation's unsaved edits).

### Why the page cannot restart the configurator

A browser page cannot start a program. The alternatives were:
- a custom URL scheme (`canworks-config://start`) registered by the shortcut: needs per-OS registration (Windows registry, a macOS app bundle's `CFBundleURLTypes`, a Linux `x-scheme-handler`), the browser asks before opening it, and a new configurator still has a new port and session, so the old page cannot carry on with its draft. Too much for a rare case.
- the new configurator reusing the old port and accepting the old session cookie: the port may be taken, and keeping the session secret on disk weakens the one-time start code design.

The shortcut is one click away, and the download keeps the draft, so the notice is enough.

## Alternatives considered for the main problem

- **Only stretch `PAGE_SILENT_S`** (no unsaved rule): simplest, but any finite limit can still drop unsaved work, and a very long one keeps a crashed configurator's adapter open for hours.
- **Only the sleep gap correction:** fixes a sleeping machine but not a locked screen on an awake one, which is what the desktop check hit.
- **Keep-alive from the page with a Web Worker, Web Lock or audio context:** Safari throttles or suspends these too under a locked screen; fighting the browser's power policy is fragile.
- **Persist the draft in the browser (`localStorage`) and restore it in the next configurator:** keeps unsaved work across any stop, but drafts are per folder, can be large, and restoring needs a merge question when the file changed. Worth a change of its own if stops with unsaved work still happen after this one.

## Small fixes

- **a. Lock texts.** `app.js` sets `NO_CHANGES` from `st.local`; with `st.remote` it uses a text that names the host: "Changes are off for this connection to the adapter on HOST (press Unlock… in the connection bar)." Other "USB adapter" words on the remote path (`trace.js` "Recording via the USB adapter", `tracewin.js`) are checked in the same pass.
- **b. Trace drops.** `kernel_drops` is the drop count of the kernel that reads the bus: the PLC's on a runtime, the adapter machine's on a remote adapter (a local USB adapter reports 0). `trace.js` and `diag.py`'s summary line pick the words from the connection: "dropped by the PLC's kernel" or "dropped by the adapter machine's kernel (HOST)".
- **c. Dependencies.** `iroh` stays a runtime dependency with its platform markers: the remote link to runtimes from the configurator and `canworks-diag` is a core PC feature and must work after the one-line install, its wheels have no dependencies, and a missing optional extra would show up as a confusing "remote link not available" on a fresh install. `pytest` arrives through `can-j1939` 2.0.12, which lists it (with `numpy`) as a runtime requirement; `can-j1939` never imports it, while it does import `numpy`. `can-j1939` stays (the J1939 simulator and trouble-code tools need it). The one-line installers pass `uv tool install --overrides` a file with `pytest; sys_platform == 'never'`, uv's documented way to drop a transitive requirement; it works on old and new uv releases and is kept on `uv tool upgrade`. A `pip` install still gets `pytest`; `docs/install-pc.md` says why. An upstream report asks `can-j1939` to move `pytest` to a test extra.
- **d. adapter-serve stop line.** `serve()` records which signal ended it and logs `stopped (SIGTERM), N PCs were connected` (or `Ctrl-C`) after `server_close()`, so the systemd journal shows the stop.
- **e. Remote errors.** Errors that the adapter server raises from its own adapter code are worded for "this machine" there; the PC side (`remote:` client) adds the host, so the PC shows "no CAN interface slcan0 on the adapter machine HOST". `localbus/adapter.py` words its message "on this machine" instead of "on this PC" so the same text is right on a PC and on a server.
- **f. Installer PATH warning.** `install-pc.sh` runs `uv tool install` with `PATH="$BIN:$PATH"` for that one call, so uv does not warn, then keeps today's `uv tool update-shell` and "open a new terminal" hint when `$BIN` is not on the user's PATH. The uv installer's own PATH message is kept quiet with its quiet option when the installer supports it (checked in the installer test with a stub).

## Version

0.91.1: fixes and changed defaults, no new options or commands (the project bumps the minor version for new features and the patch version for fixes).
