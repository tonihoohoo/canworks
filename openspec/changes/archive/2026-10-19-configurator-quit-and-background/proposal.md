# Proposal: configurator-quit-and-background

## Why

Toni (2026-10-19): "There should be exit button in the app. Now only way is ctrl+c. Any way to run this without leaving the terminal open? or is it good idea?"

- The server has had a quit request (`POST /api/quit`) for a long time, but the page has no button for it, so the only way to stop `canworks-config` is Ctrl-C in its terminal.
- The configurator needs its terminal open the whole time. Closing the terminal stops it, and a closed browser tab can only be reopened by starting it again (the start address works once).
- Starting it a second time starts a second server on another port. Both use the same cookie name, and browsers share cookies across ports of one host, so the two pages log each other out.

Toni then asked (18:06Z) whether closing the tab should be the main way to exit. It should: the configurator is a page in the browser, so closing it is what people expect to end it, and it frees USB adapters at once. Quit stays for an explicit stop, and the browser's leave-page question comes first every time. With that, running without a terminal is safe, because a forgotten background configurator stops when its tab goes.

## What Changes

- **Quit** button at the right end of the header, on every page including the start page. It always asks first (Quit / Cancel, or Save and quit / Quit without saving / Cancel with unsaved changes); with an open adapter connection or running send jobs, traces or PDO tests it says they will stop. After quitting the tab shows "canworks-config has stopped. You can close this tab." with how to start it again.
- **Closing the last tab stops the configurator**, 10 s after the page said it was closing (a reload comes back sooner), or 3 minutes after the last page stopped answering (crash, sleep). Every connection closes as Disconnect does, so a USB adapter is free at once. Closing or reloading always gets the browser's leave-page question first (Toni: "it needs to confirm before close"). `--keep-running` keeps today's behaviour for scripts and remote use.
- **One configurator per user:** a running configurator writes `instance.json` (port and a random secret, readable only by the user) to its settings folder. A second `canworks-config` opens a new tab on the running one and exits; with a PATH it asks the running one to open that folder (the page asks first when it has unsaved changes). `--new-instance` starts a separate one.
- **Without a terminal, by default:** `canworks-config` starts the configurator detached from the terminal (no console window on Windows), opens the browser and returns at once; output goes to a log in the settings folder. It stops when its last tab closes. `--foreground` keeps it in the terminal with Ctrl-C as before; it stays in the foreground by itself over SSH, on Linux without a display, and with `--no-browser` or `--keep-running`. When no page opens 15 s after starting (the browser failed), it shows the start address: in the terminal, or from the shortcut in a message window to copy it from, and in the log; a configurator whose page never opens stops after 10 minutes. (Toni 18:58Z agreed to background as the default.)
- **App shortcut:** `canworks-config --create-shortcut` adds a shortcut that starts it with no terminal: Start menu and desktop on Windows (`pythonw`, no console window, no unsigned .exe), an app in `~/Applications` on macOS (made on the Mac, so Gatekeeper does not block it), a `.desktop` entry on Linux. `--remove-shortcut` removes it. The one-line PC installers create it (`--no-shortcut` / `-NoShortcut` to skip) and their uninstall removes it.
- **Cookie per port:** the session cookie's name includes the port, so two configurators (`--new-instance`) keep their own sessions.
- README, `docs/configurator.md` Start and `docs/install-pc.md`: the shortcut, closing the tab stops it, Quit, `--foreground`, `--keep-running`, second start brings back the running one, the log file.

Breaking: `canworks-config` no longer stays in the terminal by default; scripts that relied on that use `--foreground` (the project is not in real use, so no compatibility mode).

## Capabilities

### Modified Capabilities
- `canopen-configurator`: Local access only (cookie per port); new requirements for Quit, closing the last tab, one configurator per user, background start by default, and the app shortcut.
