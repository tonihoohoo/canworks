## Why

On a USB adapter connection, the connection bar shows a checkbox labelled **Read-only**. Clicking it opens "Allow changes on this adapter connection?", which reads as the wrong popup: the user asked for read-only and is offered the opposite.

Cause: `allowControl()` (`tools/deploy/canworks/configurator/static/connection.js`) draws one checkbox whose checked state is "changes allowed", but whose label is the *current state*: " Read-only" while unticked, " Changes allowed" while ticked. So the box reads as "Read-only: off" while the connection is in fact read-only, and ticking it switches changes **on**. The label means the opposite of what ticking does. The Locked hint under write controls adds to it: it says to tick "Allow changes" in the connection banner, but no control in the bar is called that while it is off.

## What Changes

- The adapter lock in the connection bar becomes a state plus one action, the way a runtime's setting is already shown:
  - read-only: "🔒 Read-only" and an **Unlock…** button, which asks the same question as today ("Allow changes on this adapter connection? …", **Allow changes** / **Cancel**) and allows changes on the open connection when confirmed;
  - changes allowed: "🔓 Changes allowed" and a **Lock** button, which goes back to read-only at once without asking.
  - Both keep `data-conn="allow"`, so focus stays on the button across the bar's redraw, and its tooltip says that changes are off for every new connection and that switching keeps the connection open.
- The checkbox is removed, so no label can disagree with what the click does. **Unlock…** matches the Unlock… buttons beside locked controls, which ask the same question.
- The locked text for an adapter says "press Unlock… in the connection bar" instead of "tick "Allow changes" in the connection banner".
- The connect panel's **Allow changes (SDO writes, NMT, LSS, restore)** checkbox stays as it is: its label is fixed and means what ticking does.
- Browser tests: the bar on a read-only adapter shows "Read-only" and Unlock…; Unlock… opens the Allow changes question, Cancel leaves it read-only, Allow changes shows "Changes allowed" and Lock; Lock goes back to read-only with no question; focus stays on the bar's button. The existing tests that tick `#conn-bar input[data-conn="allow"]` move to the button.
- `docs/configurator.md`, `docs/pc-adapter.md` and `docs/wording.md` describe Unlock…/Lock instead of ticking.
- PC tools 0.75.1 (patch).

No file format, server protocol or CLI changes.

## Capabilities

### New Capabilities
None.

### Modified Capabilities
- `canopen-configurator`: "Allow changes in the connection bar" says the adapter lock shows its state with an Unlock…/Lock button, not a checkbox; "Unlock from a locked control" names the bar's Unlock….

## Impact

- `tools/deploy/canworks/configurator/static/connection.js` (`allowControl()`), `static/app.js` (`ADAPTER_NO_CHANGES`), maybe `static/style.css` for the button spacing.
- `tools/deploy/tests/test_configurator_localbus_page.py` (bar lock tests), `test_configurator_shell_page.py` if it checks the adapter form.
- `docs/configurator.md`, `docs/pc-adapter.md`, `docs/wording.md`.
- `tools/deploy/pyproject.toml`, `tools/deploy/canworks/__init__.py`, the doc golden files (they carry the version).
- README: does not describe the lock, so no update.
