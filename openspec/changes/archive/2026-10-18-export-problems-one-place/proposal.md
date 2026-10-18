## Why

When an export fails, the configurator says so twice: a red message bar at the top ("CODESYS export stopped: 2 problems (see Problems). Nothing was downloaded.") and the same problems in the Problems panel at the bottom. The top bar only repeats a count and points down the page, so the user reads the failure in two places and has to close a bar that adds nothing. The register map export does the opposite: it lists its findings only in the top bar, as one long joined sentence, and never in Problems. Failures of the same kind should be in one place, and that place is Problems, where each finding can be clicked to the field that causes it.

## What Changes

- A failed export (DCF, Documentation, Download for CODESYS, DBC, register map and Node-RED flow) shows **no message bar**. Its findings are listed in Problems, and Problems opens if the user had closed it and scrolls into view.
- Problems gets a one-line error bar at its top, above the list, while it shows a failed export's findings: "CODESYS export stopped. Nothing was downloaded. Fix the problems below and export again." It is announced to screen readers as an alert. It goes away when the next check after an edit replaces the export's findings, or when an export runs again.
- The register map and Node-RED flow exports put their findings in Problems like the other exports, each as its own row, instead of joining them into the top bar.
- Unchanged: a successful export still reports in the message bar ("Exported canworks_codesys.zip ..."); with warnings it says "with 2 warnings" and opens Problems, without "(see Problems)". Errors of the request itself (no answer, server error) stay in the message bar, since they are not in Problems. The register map preview's own section warning stays.
- If Problems cannot be shown on the current page, the export falls back to today's message bar, so a failure is never silent.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `canopen-configurator`: failed exports report only in Problems, with a summary line at the top of the panel; register map and Node-RED flow export findings join Problems; the success message drops "(see Problems)".

## Impact

- `tools/deploy/canworks/configurator/static/app.js` (`exportDcf`, `exportHtml`, `exportCodesys`, `exportDbc`, a shared `exportStopped()` helper, `applyCheck()` draws the summary bar), `bridge.js` (`bridgeExport`), `index.html` (a notice slot at the top of `#problems-box`), `style.css` if the slot needs spacing.
- `tools/deploy/canworks/configurator/server.py`: `/api/bridge/export` returns findings with their config paths if it does not already, so the rows can be clicked.
- Tests: `test_configurator_page.py`, `test_configurator_docs_page.py`, `test_configurator_ux_page.py` wait for `#banner.error` today; they change to the Problems summary bar and check that `#banner` stays hidden. The message bar placement test still passes.
- Docs: `docs/configurator.md` (Problems and message bars paragraphs), README line if it mentions the export bar.
- Not affected: the plugin, the config contract, `canworks-deploy` export output.
- Related: `consistent-message-bars` (#135) set "a message sits at the top of what it is about"; this applies that rule to export failures, whose subject is the Problems list.
