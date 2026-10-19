# Tasks

## 1. Quit

- [ ] 1.1 Header Quit button (every page, start page included) with the unsaved-changes dialog (Save and quit / Quit without saving / Cancel) and the jobs line; stopped notice after `POST /api/quit`.
- [ ] 1.2 Browser tests: quit clean, quit dirty (each choice), quit with a `virtual:` adapter connection and a send job (adapter free afterwards); 1000/1280/1440 px with no clipped text.

## 2. One configurator per user

- [ ] 2.1 `instance.json` (0600, O_EXCL, removed on close), `POST /api/instance/start` with `X-Canworks-Instance`; tests: wrong secret 403, new URL works once, path queued.
- [ ] 2.2 Second start: ask, open, exit 0; stale file ignored (dead pid, no answer in 2 s); `--new-instance`; tests.
- [ ] 2.3 Page: queued "open PATH" opens at once, or asks when unsaved changes.

## 3. Background

- [ ] 3.1 `--background` / hidden `--child-background`: detached child (POSIX new session; Windows DETACHED_PROCESS, CREATE_NO_WINDOW, pythonw when present), wait for the instance, open browser, print log tail on failure; log rotation at 1 MB.
- [ ] 3.2 Heartbeat every 30 s and on becoming visible; idle stop after 10 minutes without requests and without traces, send jobs or PDO tests (background only); tests with a short idle time.

## 4. Session

- [ ] 4.1 Cookie `canopen_session_<port>`; test with two servers and one cookie jar.
- [ ] 4.2 Enter prints a new start address (stdin a terminal), at most 16 unused codes; tests.

## 5. Docs and version

- [ ] 5.1 README and `docs/configurator.md` Start: Quit, `--background`, second start, `--new-instance`, log file; tour line if the tour covers the header.
- [ ] 5.2 Bump the PC tools version (minor), release notes.

## 6. CI time

- [ ] 6.1 Compare the PR's CI wall and summed job time with the main baseline and note both in the PR.

## 7. Desktop checks (manual)

- [ ] 7.1 Windows: `canworks-config --background` from a terminal, close the terminal, page keeps working; no console window; second start opens a tab on it; Quit.
- [ ] 7.2 macOS: the same, plus idle stop after the last tab closes.
