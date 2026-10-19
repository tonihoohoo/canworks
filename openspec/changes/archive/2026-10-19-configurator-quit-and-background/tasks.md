# Tasks

## 1. Quit

- [x] 1.1 Header Quit button (every page, start page included) always confirming (Quit / Cancel; Save and quit / Quit without saving / Cancel with unsaved changes) and the jobs line; stopped notice after `POST /api/quit`.
- [x] 1.2 Browser tests: quit clean (asks, Cancel keeps it), quit dirty (each choice), quit with a `virtual:` adapter connection and a send job (adapter free afterwards); 1000/1280/1440 px with no clipped text.

## 2. One configurator per user

- [x] 2.1 `instance.json` (0600, O_EXCL, removed on close), `POST /api/instance/start` with `X-Canworks-Instance`; tests: wrong secret 403, new URL works once, path queued.
- [x] 2.2 Second start: ask, open, exit 0; stale file ignored (dead pid, no answer in 2 s); `--new-instance`; tests.
- [x] 2.3 Page: queued "open PATH" opens at once, or asks when unsaved changes.

## 3. Closing the last tab

- [x] 3.1 Page id, heartbeat every 30 s and on becoming visible, `pagehide` beacon to `/api/page/closed` (cookie only, marks one page closed); server page table, stop 10 s after the last close or 3 min after the last heartbeat; `--keep-running`.
- [x] 3.2 `beforeunload` always asks (not only with unsaved work).
- [x] 3.3 Tests: beacon stops the server within the grace and frees a `virtual:` adapter, reload (beacon then heartbeat) keeps it, two pages keep it, heartbeat timeout with a short timeout, beacon without cookie refused, `--keep-running` keeps it; browser test that `beforeunload` asks with nothing unsaved.

## 4. Background

- [x] 4.1 Background by default, `--foreground`, foreground by itself with `--no-browser`/`--keep-running`/SSH/no display; hidden `--child-background`: detached child (POSIX new session; Windows DETACHED_PROCESS, CREATE_NO_WINDOW, pythonw when present), wait for the instance, open browser, print log tail on failure; log rotation at 1 MB; 10-minute startup grace.
- [x] 4.3 No page 15 s after asking the browser: print the address (terminal) or a message window (Windows MessageBoxW, macOS osascript dialog, Linux zenity/kdialog/notify-send), always the log; tests with `webbrowser.open` stubbed to do nothing and the window call stubbed.
- [x] 4.2 Tests: foreground rules per environment, child detached (no inherited stdin), failure prints the log reason, startup grace and the 15 s check with short times; update every test and script that runs `canworks-config` and expects it in the foreground.

## 4b. App shortcut

- [x] 4b.1 Icons from the logo into the package (ico, icns, png).
- [x] 4b.2 `--create-shortcut` / `--remove-shortcut`: Windows .lnk (Start menu + desktop, pythonw) via PowerShell, macOS .app in ~/Applications, Linux .desktop; markers so remove touches only ours. Tests per OS on a temporary home (Windows test in the Windows CI row).
- [x] 4b.3 `install-pc.sh` / `install-pc.ps1`: create after install, `--no-shortcut` / `-NoShortcut`, remove on uninstall; installer tests.

## 5. Session

- [x] 5.1 Cookie `canopen_session_<port>`; test with two servers and one cookie jar.

## 6. Docs and version

- [x] 6.1 README and `docs/configurator.md` Start and `docs/install-pc.md`: shortcut, Quit, closing the tab stops it, `--foreground`, `--keep-running`, second start, `--new-instance`, log file; tour line if the tour covers the header.
- [x] 6.2 Bump the PC tools version (minor), release notes.

## 7. CI time

- [ ] 7.1 Compare the PR's CI wall and summed job time with the main baseline and note both in the PR.

## 8. Desktop checks (manual)

- [ ] 8.1 Windows: one-line installer creates the shortcut; double-click opens the page with no console window; second double-click opens a tab on it; closing the tab stops it; `canworks-config` from a terminal returns at once; Quit; uninstall removes the shortcut.
- [ ] 8.2 macOS: the same with the app in ~/Applications (Gatekeeper lets it start); closing the tab stops it and frees a USB adapter; reload keeps it.
- [ ] 8.3 Pi over SSH: `canworks-config` stays in the foreground and prints the address.
- [ ] 8.4 Windows: with the default browser broken (for example its program renamed), the shortcut shows the address in a message box and the copied address opens the page.
