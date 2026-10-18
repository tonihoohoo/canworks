## Context

`banner()` in `app.js` is the page message bar under the header. The four config exports call `exportProblems()`/`exportCheck()` to put their findings in Problems and then also call `banner("<X> export stopped: N problems (see Problems). Nothing was downloaded.", true)`. `bridgeExport()` in `bridge.js` puts nothing in Problems and joins its findings into the bar. Problems is `#problems-box`, a `<details>` in the bottom panel whose open state is remembered in Configure.

## Decisions

**Problems is the one place for a failed export.** Its rows say what is wrong and click to the field; the top bar only repeated the count. Dropping the bar (not the panel) was Toni's stated minimum and keeps the clickable list.

**A summary bar at the top of Problems, not a bare list.** Without it the user loses two facts the old bar carried: which export stopped and that nothing was downloaded. The summary uses the existing `notice("error", ...)` component in a slot at the top of the panel body, so it looks like every other bar (consistent-message-bars) and sits at the top of what it is about.

**Open and reveal Problems.** If the user had closed the panel, a failed export opens it (the user asked for the export, so showing why it stopped is expected) and scrolls it into view. Focus stays on the button the user pressed; the summary's alert role announces the failure. This does not change the remembered "closed" choice for later edit-time checks beyond what the `toggle` handler already records.

**When the summary clears.** `exportProblems()` already keeps `S.check.base`; the summary is drawn while `S.check.export` names the stopped export. The next edit-time check replaces `S.check` and so removes it; running any export again replaces it.

**Register map and Node-RED flow.** `bridgeExport()` goes through `exportProblems()` like the others. If `/api/bridge/export` returns findings without paths, the rows are still listed (not clickable), and adding paths is a task.

**Fallback.** When `#problems` is hidden (a tool view or Commission a device, where these exports are not offered today), `exportStopped()` keeps the old message bar text so a failure is never silent.

## Risks

- Tests that wait for `#banner.error` need to change; covered in tasks.
- A long Problems list could push the summary off screen in a short window; the summary is the panel's first child, and the panel scrolls into view at its top.
