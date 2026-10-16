## Context

The Trace graph (`static/trace.js`) draws one uPlot chart per lane with a shared x range `T.zoom` (µs, or `null` for the whole trace). `loadGraph()` asks `/api/trace/series` for about two points per pixel in that range and redraws all lanes. Drag zoom, **Zoom out** (`zoomBy(2)`), ◀ ▶ (`pan()`), double-click and **Whole trace** all set `T.zoom` and call `loadGraph()`. While recording, the graph refreshes every second only when `T.zoom` is `null`. The page itself scrolls (the graph sits below the toolbar and may have up to four lanes).

## Goals / Non-Goals

**Goals:** wheel zoom at the pointer that feels immediate on a 2 million frame trace; pan with Shift+wheel and sideways trackpad scroll; no surprise page scroll or browser zoom over the plot; the page still scrollable with the wheel elsewhere.

**Also:** the user can make the lists and the graph taller or shorter, and the choice is kept.

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

## Risks / Trade-offs

- [Users who scroll the page with the pointer over a plot are stopped there] → plot areas are small, the rest of the graph block scrolls the page, and the hint says what the wheel does.
- [Coarse points while zoomed in before the fetch] → 150 ms later the detail arrives; same as today's drag zoom, which shows nothing new until the fetch returns.
- [A tall list or graph pushes the toolbar off screen] → the toolbar is above and the page scrolls; double-click on the bar returns to the default.
- [Many fetches while scrolling slowly] → one fetch per pause, older answers dropped.
