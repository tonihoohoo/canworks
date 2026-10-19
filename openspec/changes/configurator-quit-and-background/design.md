# Design: configurator-quit-and-background

## Quit

Header button `#btn-quit` after the Settings menu, always visible. Flow:
1. `S.dirty` → dialog Save and quit / Quit without saving / Cancel (Save runs the normal save; a failed save stays on the page).
2. Open connection with jobs (`/api/online/jobs`, adapter connection, traces) → one line in the same dialog: "The adapter connection and 2 send jobs will stop."
3. `POST /api/quit` (exists), then the page replaces its body with the stopped notice. `window.close()` is not used: browsers only allow it on windows a script opened.
`server_close` already stops traces, connections and senders.

## One configurator per user

`instance.json` in the configurator's settings folder (`userdirs`), written with mode 0600 after the port is bound: `{"pid", "port", "secret"}`; removed in `server_close`. The secret is a separate `secrets.token_urlsafe(32)`, not the session token.

A second start reads it and calls `POST /api/instance/start` on `127.0.0.1:<port>` with header `X-Canworks-Instance: <secret>` and optional `{"path": PATH}`. That route is the only one not needing the session token, and it needs the secret instead (compare_digest). It answers `{"url": <new start address>}`; with a path it queues "open PATH" for the page (opened at once when nothing unsaved, else the page asks). The second start opens the URL (or prints it with `--no-browser`) and exits 0.

A stale file (no answer within 2 s, or a pid that does not run) is ignored and replaced. Two starts at the same moment: the file is created with `O_EXCL`; the loser retries the ask once.

## Background start

`--background`: re-run the same command with `--child-background` as a detached process:
- POSIX: `subprocess.Popen(..., start_new_session=True, stdin=DEVNULL, stdout/stderr=log)`.
- Windows: `creationflags=DETACHED_PROCESS | CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP`, with `pythonw.exe` next to the running interpreter when present.
The parent waits until `instance.json` names a port that answers (up to 10 s), then opens the browser through the second-start path and exits; on failure it prints the log's last lines. Log `configurator.log` in the settings folder, kept to 1 MB (one old file).

## Idle stop

The page sends `POST /api/heartbeat` every 30 s while open (and on `visibilitychange` to visible). A background configurator stops when no heartbeat or other request came for 10 minutes and no trace recording, send job or PDO test runs. A terminal configurator does not stop by itself.

## Cookie per port

Cookie name `canopen_session_<port>` (the port from the request's Host), set on the start-code redirect and read on each request.

## New start address with Enter

When stdin is a terminal, a thread reads lines; each Enter prints a new start address and opens it when browsers are opened. At most 16 unused codes are kept, oldest dropped.

## Not done

A desktop or Start menu shortcut; it can come later on top of `--background`.
