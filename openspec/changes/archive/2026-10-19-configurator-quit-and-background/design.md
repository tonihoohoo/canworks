# Design: configurator-quit-and-background

## Quit

Header button `#btn-quit` after the Settings menu, always visible. Flow:
1. Always a dialog: Quit / Cancel, or with `S.dirty` Save and quit / Quit without saving / Cancel (Save runs the normal save; a failed save stays on the page).
2. Open connection with jobs (`/api/online/jobs`, adapter connection, traces) → one line in the same dialog: "The adapter connection and 2 send jobs will stop."
3. `POST /api/quit` (exists), then the page replaces its body with the stopped notice. `window.close()` is not used: browsers only allow it on windows a script opened.
`server_close` already stops traces, connections and senders.

## One configurator per user

`instance.json` in the configurator's settings folder (`userdirs`), written with mode 0600 after the port is bound: `{"pid", "port", "secret"}`; removed in `server_close`. The secret is a separate `secrets.token_urlsafe(32)`, not the session token.

A second start reads it and calls `POST /api/instance/start` on `127.0.0.1:<port>` with header `X-Canworks-Instance: <secret>` and optional `{"path": PATH}`. That route is the only one not needing the session token, and it needs the secret instead (compare_digest). It answers `{"url": <new start address>}`; with a path it queues "open PATH" for the page (opened at once when nothing unsaved, else the page asks). The second start opens the URL (or prints it with `--no-browser`) and exits 0.

A running configurator is found only while it has a page or `--keep-running`, since it stops otherwise. A stale file (no answer within 2 s, or a pid that does not run) is ignored and replaced. Two starts at the same moment: the file is created with `O_EXCL`; the loser retries the ask once.

## Background start

Default start (no `--foreground`): re-run the same command with hidden `--child-background` as a detached process. Foreground instead when `--foreground`, `--no-browser` or `--keep-running` is given, `SSH_CONNECTION` is set, or on Linux neither `DISPLAY` nor `WAYLAND_DISPLAY` is set (the browser could not open, and the user needs the printed address). Detached process:
- POSIX: `subprocess.Popen(..., start_new_session=True, stdin=DEVNULL, stdout/stderr=log)`.
- Windows: `creationflags=DETACHED_PROCESS | CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP`, with `pythonw.exe` next to the running interpreter when present.
The parent waits until `instance.json` names a port that answers (up to 10 s), then opens the browser through the second-start path and exits; on failure it prints the log's last lines. Log `configurator.log` in the settings folder, kept to 1 MB (one old file).

## Closing the last tab

Two signals, so the stop is quick when the tab closes and still happens when the browser crashes or the PC sleeps:
- **Page closed:** on `pagehide` the page sends `navigator.sendBeacon("/api/page/closed", {page})`. A beacon cannot carry the token header, so this one route accepts the session cookie alone (SameSite=Strict keeps other sites from sending it) and can only mark a page closed. A reload sends the beacon and then the new page's first heartbeat, so the server waits 10 s before stopping.
- **Heartbeat missing:** each page has a random page id and sends `POST /api/heartbeat {page}` every 30 s and on becoming visible. Browsers throttle timers in hidden tabs to about once a minute, so a page counts as gone after 3 minutes without a heartbeat, not sooner.

No page left → `server.shutdown()` as Quit does (`server_close` already closes connections, traces and senders). `--keep-running` turns this off.

Leave-page question (Toni 18:07Z: "it needs to confirm before close"): the `beforeunload` handler always asks, not only with `unsavedWork()`. Browsers show their own text (the page cannot say "this stops canworks-config") and only after the user has clicked or typed on the page; a tab opened and closed untouched closes without asking, which loses nothing. A reload asks too.

Why not stop at once on the beacon: a reload and the browser's back/forward would stop it. Why not a WebSocket: the server is `http.server`; the beacon plus heartbeat is enough and adds no dependency.

## Cookie per port

Cookie name `canopen_session_<port>` (the port from the request's Host), set on the start-code redirect and read on each request.

## Not done

Signing a Windows .exe or a macOS app: not needed, see App shortcut.

## Browser that does not open

`webbrowser.open` often returns True when nothing opened (a broken default browser, a text browser, a desktop without one), so the check is whether a page arrives, not the call's result. 15 s after asking the browser, if no heartbeat came:
- started from a terminal (the parent of the background child is still waiting, or foreground): print `No browser opened. Open this address in a browser: <url>` and return the prompt;
- started from the shortcut (no terminal): a message window with the address. Windows: `MessageBoxW` through `ctypes` (Ctrl+C copies a message box's text); macOS: `osascript` `display dialog` with the address in an editable field; Linux: `zenity --entry` or `kdialog`, else `notify-send`, else the log only.
The address is always written to the log too. Each shown address is a fresh one-time code.

## Startup grace

A configurator whose first page has not sent a heartbeat within 10 minutes of start stops, so a configurator nobody reached does not stay running. `--keep-running` turns it off with the rest of the page rule.

## App shortcut

`canworks/configurator/shortcut.py`, `--create-shortcut` / `--remove-shortcut`. The target is the `canworks-config` launcher that the install put on PATH (found with `shutil.which`, else next to `sys.executable`), so a `uv tool install --force` update keeps the shortcut working.
- **Windows:** `.lnk` files in `%APPDATA%\Microsoft\Windows\Start Menu\Programs\canworks configurator.lnk` and on the desktop, written through PowerShell's `WScript.Shell` COM object (no new dependency), target `pythonw.exe -m canworks.configurator.server` of the tool's environment with `--child-background` semantics, icon from the package's `logo.ico`. pythonw has no console, so nothing flashes. No .exe of ours, so nothing to sign and no SmartScreen prompt.
- **macOS:** `~/Applications/canworks configurator.app` with `Contents/Info.plist`, `Contents/MacOS/canworks-configurator` (a two-line `#!/bin/sh` running the launcher with `exec`), and `Contents/Resources/logo.icns`. Made on the Mac, so it has no quarantine flag and Gatekeeper lets it run.
- **Linux:** `~/.local/share/applications/canworks-configurator.desktop` (`Exec=<launcher>`, `Terminal=false`, `Icon=` the package's PNG, `Categories=Development;Engineering;`), then `update-desktop-database` when present.
Each file carries a marker (`X-Canworks=1`, a plist key, the .lnk description) so `--remove-shortcut` removes only its own files.

Icons: generated from the README logo at build time into the package (`logo.ico`, `logo.icns`, `logo-256.png`).

Installers: `scripts/install-pc.sh` and `install-pc.ps1` call `canworks-config --create-shortcut` after the tool install unless `--no-shortcut` / `-NoShortcut`; `--uninstall` / `-Uninstall` calls `--remove-shortcut` first.
