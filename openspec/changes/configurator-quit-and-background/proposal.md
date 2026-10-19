# Proposal: configurator-quit-and-background

## Why

Toni (2026-10-19): "There should be exit button in the app. Now only way is ctrl+c. Any way to run this without leaving the terminal open? or is it good idea?"

- The server has had a quit request (`POST /api/quit`) for a long time, but the page has no button for it, so the only way to stop `canworks-config` is Ctrl-C in its terminal.
- The configurator needs its terminal open the whole time. Closing the terminal stops it, and a closed browser tab can only be reopened by starting it again (the start address works once).
- Starting it a second time starts a second server on another port. Both use the same cookie name, and browsers share cookies across ports of one host, so the two pages log each other out.

Running without a terminal is a good idea once three things are there: a way to quit from the page, a second start that brings back the running one instead of starting another, and a stop by itself when no page has been open for a while, so a forgotten background server does not hold USB adapters or keep running for days.

## What Changes

- **Quit** button at the right end of the header, on every page including the start page. With unsaved changes it asks first (Save and quit / Quit without saving / Cancel); with an open adapter connection or running send jobs, traces or PDO tests it says they will stop. After quitting the tab shows "canworks-config has stopped. You can close this tab." with how to start it again.
- **One configurator per user:** a running configurator writes `instance.json` (port and a random secret, readable only by the user) to its settings folder. A second `canworks-config` asks the running one for a new start address with that secret, opens it in the browser and exits. With a PATH it asks the running one to open that folder; when the open config has unsaved changes the page asks first. `--new-instance` starts a separate one anyway.
- **Without a terminal:** `canworks-config --background` starts the configurator detached from the terminal (no console window on Windows), opens the browser and returns at once; output goes to a log in the settings folder. A background configurator stops by itself 10 minutes after its last page closed (the page sends a heartbeat). Quit and a second start work as above.
- **Cookie per port:** the session cookie's name includes the port, so two configurators (`--new-instance`) keep their own sessions.
- **Enter for a new start address** in a configurator started in a terminal, for the closed-tab case without a second start.
- README and `docs/configurator.md` Start section: Quit, `--background`, second start brings back the running one, the log file.

Default stays as today: in a terminal, Ctrl-C still stops it.

## Capabilities

### Modified Capabilities
- `canopen-configurator`: Local access only (cookie per port); new requirements for Quit, one configurator per user, background start, and a new start address.
