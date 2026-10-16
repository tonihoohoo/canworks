## Context

The Trace graph (`static/trace.js`) draws one uPlot chart per lane with a shared x range `T.zoom` (µs, or `null` for the whole trace). `loadGraph()` asks `/api/trace/series` for about two points per pixel in that range and redraws all lanes. Drag zoom, **Zoom out** (`zoomBy(2)`), ◀ ▶ (`pan()`), double-click and **Whole trace** all set `T.zoom` and call `loadGraph()`. While recording, the graph refreshes every second only when `T.zoom` is `null`. The page itself scrolls (the graph sits below the toolbar and may have up to four lanes).

## Goals / Non-Goals

**Goals:** wheel zoom at the pointer that feels immediate on a 2 million frame trace; pan with Shift+wheel and sideways trackpad scroll; no surprise page scroll or browser zoom over the plot; the page still scrollable with the wheel elsewhere.

**Also:** the user can make the lists and the graph taller or shorter, and the choice is kept.

**Also:** the trace in its own browser window, watched while the main window sends messages.

**Non-Goals:** keyboard zoom, zooming the value (y) axis, the watch graph, touch pinch on phones.

## Decisions

1. **Plain wheel zooms, not Ctrl+wheel only.** That is what Toni asked for and what scope and trace tools do. The catch is that the page cannot be scrolled with the wheel while the pointer is on a plot; the plot areas are at most 200 px high per lane and the page scrolls with the wheel over the series list, axes, legend and cursor table, so the page stays reachable. Ctrl+wheel also zooms, because a trackpad pinch arrives as Ctrl+wheel and would otherwise zoom the whole browser page.
2. **Listener on each plot's `u.over`**, `{ passive: false }`, calling `preventDefault()`. The axes and legend are outside `u.over`, which is what leaves them for page scrolling.
3. **Zoom at the pointer.** `p = u.posToVal(e.offsetX, "x")` in trace time; new range `[p - (p - r0) * f, p + (r1 - p) * f]`. Factor `f = Math.exp(dy * 0.002)` with `dy` the vertical delta in pixels (`deltaMode` 1 lines × 16, 2 pages × plot height), clamped to one notch-sized step per event so a mouse notch (about 100 px) gives about ×1.22–1.25 and a trackpad gives small steps. Up / away zooms in, as in maps and scope tools.
4. **Limits.** If the new range covers the trace from `first_us` to `last_us`, set `T.zoom = null` (whole trace, live again). The smallest window is 100 µs (about one frame at 1 Mbit/s); zooming further keeps 100 µs centred at the pointer. **Zoom out** reuses the same helper so both behave the same at the ends.
5. **Pan.** Shift+wheel uses `deltaY`, a sideways swipe uses `deltaX`; the shift is the delta as a fraction of the plot width, so content follows the fingers. Wheel pan is kept inside the trace; the ◀ ▶ buttons keep their current behaviour.
6. **Immediate redraw, delayed fetch.** Each event calls `setScale("x", …)` on every lane plot (the data already loaded is drawn at the new scale, coarse when zoomed far in), so all lanes move together. `loadGraph()` runs 150 ms after the last wheel event. `loadGraph()` gets a request counter; an answer for an older request is ignored, so a slow answer cannot put back an old range. Wheel zoom on a graph with no series does nothing.
7. **Hint text**: "Scroll to zoom at the pointer, Shift+scroll to pan, drag to zoom to a range, click to set cursor A, Shift+click for B, double-click for the whole trace."

8. **Resize bars, not CSS `resize`.** A full-width 8 px bar (`role="separator"`, `aria-orientation="horizontal"`, row-resize cursor, focusable) under each area, the same look as the inspector's split handle in its stacked layout. CSS `resize: vertical` only gives a small corner grip and no keyboard or reset. Drag uses pointer capture like the split handle; Up/Down change 40 px, double-click resets, `aria-valuenow` is the height in px.
9. **One list height, per-lane graph height.** `list_h` (px, or none for the default viewport formula) sets a CSS variable used by `.trace-list` and `.ids-grid`, so switching between the two lists keeps the height. `lane_h` (px, or none for the 200/150 default) is used by `drawPlots()`; dragging the graph bar changes the total height and divides it by the lane count, so adding a lane later does not squash the others. The plots get `setSize()` while dragging (no refetch); cursors and the zoom stay. Saved 300 ms after the last change with `tracePrefs()`, like the split.
10. **Shared-height layout untouched.** Between `SPLIT_PHONE` and `SPLIT_WIDE` the list and inspector already share the window height; a list height there would fight it, so the list bar is hidden in that layout and the saved height applies again when the window is wider or narrower.

11. **Trace window = same page, `?window=trace`.** `window.open("/?window=trace", "canworks-trace", "popup,width=…,height=…")` from the button's click (no popup blocker). The session cookie is shared, so no login. At boot, `?window=trace` puts the page in trace-window mode: `S.view = "trace"` fixed, the header, workspace and tool tabs, bottom panel and connection bar are hidden and replaced by a one-line top bar. The recording, decoding and connection are already server-side (one trace per project folder), so the window needs no new server operations.
12. **One window shows the trace.** A `BroadcastChannel("canworks-trace")` carries: `open`/`closed` from the trace window (also on `pagehide`), `ping`/`here` so a reloaded main window learns that a trace window is open, `network` and `folder` from the main window when they change, `goto` (Explain in Frame lab) from the trace window to the main window, `select` (Back to trace) the other way, and `bring-back` (the trace window closes itself). The main window's Trace tab shows the note instead of the trace while a trace window answers, so the two windows never both poll or both write view prefs. If no main window answers a `goto` within 300 ms, the trace window opens `/` in a new window with the target in the URL hash.
13. **Close question.** `unsavedWork()` counts the unsaved recording only in the last window showing it: the main window while no trace window answers, the trace window when no main window has spoken for 5 s. The trace window ignores the config's unsaved changes (they are the main window's). The main window closes the trace window it opened on **Bring trace back here** (a page may only close windows it opened).
16. **Connection in the trace window.** The connection bar's state (runtime, adapter or simulator on, the picked network) lives in the main page, so the main window sends it in `conn` messages (on change and every 2 s) and the trace window does not poll `/api/online/status` or the jobs itself. Start in the trace window asks the main window to open the runtime connection (`ensure`), as Start in the main window does. A `conn` for another folder reloads the trace window; with no folder open it says to open one in the main window.
14. **Window size.** Saved as `window_w`/`window_h` in the trace prefs on `resize` (debounced), used in the `open` features next time; default 1200 × 800, never larger than the screen.
15. **Button place.** In the Trace toolbar's right end, label "Open in new window" with the ⧉ icon; hidden below `SPLIT_PHONE` and in the trace window itself.

## Risks / Trade-offs

- [Users who scroll the page with the pointer over a plot are stopped there] → plot areas are small, the rest of the graph block scrolls the page, and the hint says what the wheel does.
- [Coarse points while zoomed in before the fetch] → 150 ms later the detail arrives; same as today's drag zoom, which shows nothing new until the fetch returns.
- [A tall list or graph pushes the toolbar off screen] → the toolbar is above and the page scrolls; double-click on the bar returns to the default.
- [Browser blocks or ignores popup features] → the window still opens as a tab, which works the same; the note in the main window still applies.
- [BroadcastChannel missing] → all supported browsers have it; without it the button is hidden.
- [Many fetches while scrolling slowly] → one fetch per pause, older answers dropped.
