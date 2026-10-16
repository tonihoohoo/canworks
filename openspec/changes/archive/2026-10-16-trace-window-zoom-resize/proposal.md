## Why

The Trace view's graph zooms only by dragging a range, the **Zoom out** button (×2 around the middle), double-click and **Whole trace**, and pans only with the ◀ ▶ buttons. Looking around a long trace takes many clicks and drags, and there is no quick way to zoom in a little or out a little at the spot being looked at. The mouse wheel does nothing on the graph except scroll the page. In most trace and scope tools the wheel zooms the time axis at the pointer, so users reach for it first.

The trace areas also have fixed heights: the Chronological and By identifier lists fill the window height less a fixed amount, and each graph lane is 200 px (150 px with more than two lanes). On a big screen a lane is too flat to read a signal, and the user cannot give the list more rows or make room for the toolbar and statistics.

The trace also lives in a tab of the page, so the user cannot watch it while sending messages from the online view, the PDO test or SDO reads and writes; switching to those views hides the trace.

## What Changes

- Scrolling the wheel with the pointer over a graph's plot area zooms the shared time axis in or out, keeping the time under the pointer in place. Plain wheel and Ctrl+wheel (a trackpad pinch sends Ctrl+wheel) both zoom, and the page and the browser do not scroll or zoom while the pointer is over a plot.
- Shift+wheel and a sideways trackpad swipe pan the time axis instead, kept inside the trace.
- With the pointer anywhere else (the series list, legend, axis labels, cursor table) the wheel scrolls the page as before.
- One wheel notch zooms by a factor of 1.25; trackpad scrolling zooms smoothly in proportion to the scroll distance.
- Zooming out past the whole trace shows the whole trace (the same state as **Whole trace**, so a recording's graph follows live again). Zooming in stops at a window of 100 µs.
- Each wheel step redraws all lanes at once from the points already loaded; the detailed points for the new range are fetched once the wheel has been still for 150 ms, and an answer for an older range is dropped.
- Wheel zoom behaves like drag zoom otherwise: cursors A and B stay, the zoom range is what "Graph zoom" export uses, and while recording a zoomed graph stops following live.
- A resize bar under the Chronological list, the By identifier list and the graph makes each taller or shorter by dragging, by the arrow keys on the focused bar (40 px a step) and back to the default by double-click. The lists share one height (120 to 3000 px); the graph height is per lane (80 to 1000 px), the same for all lanes. Both are kept with the other trace view settings on this PC (`trace.json`), so they come back after a reload. In the in-between layout where the list and the inspector share the window height, the list's bar is hidden.
- **Open in new window** in the Trace view opens the trace in its own browser window: just the Trace view (toolbar, header, view tabs, transmit list) under a one-line bar naming the project, network and connection. It uses the same session, recording and connection as the main window. The main window's Trace tab then says the trace is open in its own window, with **Show trace window** and **Bring trace back here**, and stops drawing the trace. **Explain in Frame lab** in the trace window acts in the main window, and **Back to trace** there selects the frame in the trace window. Recording goes on when either window closes; a window asks about an unsaved recording only when it is the last one showing it. Not offered below phone width.
- The hint above the graph and docs/configurator.md mention scroll to zoom, Shift+scroll to pan and the resize bars.
- PC tools 0.76.0 (minor).

Drag, the buttons and double-click are unchanged. The watch graph in the online view (which uses the same plotting) is not part of this change.

## Capabilities

### New Capabilities
None.

### Modified Capabilities
- `canopen-bus-trace`: the Graphs requirement names wheel zoom at the pointer and Shift+wheel pan, with scenarios.
- `canopen-configurator`: the Trace toolbar and views requirement adds the resize bars for the lists and the graph, with scenarios; new requirements "Trace in its own window", "Trace window contents", "Main window while the trace has its own window" and "Closing a trace window".

## Impact

- `tools/deploy/canworks/configurator/static/trace.js` (wheel handler on each plot, a shared zoom helper used by the wheel and **Zoom out**, request counter in `loadGraph()`, resize bars, hint text); `static/style.css` (list heights from a CSS variable, the bar's look, the trace window's top bar); `static/app.js` / `static/shell.js` / `static/boot.js` (start in trace-window mode from the URL, the main window's "open in its own window" note, the window channel).
- `tools/deploy/canworks/configurator/tracing.py` if the trace prefs only accept known keys (`list_h`, `lane_h`).
- `tools/deploy/tests/test_configurator_trace_page.py` (browser tests for wheel zoom and resizing).
- `docs/configurator.md` (Graph paragraph).
- `tools/deploy/pyproject.toml`, `tools/deploy/canworks/__init__.py`, the doc golden files (they carry the version).
- README: one line on the trace in its own window (user-visible feature).
- `tools/deploy/canworks/configurator/server.py` only if the page needs a route for the trace window URL (the plan is the same page with `?window=trace`, so likely none).
- No file format, plugin or CLI changes; no new server operations. No hardware tasks.
