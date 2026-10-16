## 1. Fix

- [x] 1.1 `allowControl()` in `static/connection.js`: on an adapter, draw "🔒 Read-only" with an **Unlock…** button, or "🔓 Changes allowed" with a **Lock** button (`data-conn="allow"`, tooltip: off for every new connection, switching keeps the connection open)
- [x] 1.2 Unlock… asks the existing Allow changes question and saves `allow_changes: true`; Lock saves `allow_changes: false` without asking; both update `S.onlineLast` and redraw as today, and a failed save leaves the state as it was
- [x] 1.3 `ADAPTER_NO_CHANGES` in `static/app.js`: "press Unlock… in the connection bar"

## 2. Tests

- [x] 2.1 Browser test: read-only adapter bar shows "Read-only" and Unlock…, no checkbox; Unlock… → Cancel stays read-only; Unlock… → Allow changes shows "Changes allowed" and Lock, write controls enabled without reconnecting; Lock → read-only with no question; focus on the bar's button after each
- [x] 2.2 Move the existing tests that tick `#conn-bar input[data-conn="allow"]` to the button
- [ ] 2.3 Run the configurator page tests locally (Playwright)

## 3. Docs and release

- [x] 3.1 `docs/configurator.md`, `docs/pc-adapter.md`, `docs/wording.md`: Unlock…/Lock in the connection bar instead of ticking
- [x] 3.2 PC tools version 0.75.2 (pyproject, `canworks/__init__.py`, doc golden files)

## 4. Hardware

- [ ] 4.1 Windows PC with the USB adapter, Commission a device: Unlock… in the bar, confirm, write an SDO; Lock; the write is refused with the Locked text
