## Why

The Trace view's graph zooms only by dragging a range, the **Zoom out** button (×2 around the middle), double-click and **Whole trace**, and pans only with the ◀ ▶ buttons. Looking around a long trace takes many clicks and drags, and there is no quick way to zoom in a little or out a little at the spot being looked at. The mouse wheel does nothing on the graph except scroll the page. In most trace and scope tools the wheel zooms the time axis at the pointer, so users reach for it first.

## What Changes

- Scrolling the wheel with the pointer over a graph's plot area zooms the shared time axis in or out, keeping the time under the pointer in place. Plain wheel and Ctrl+wheel (a trackpad pinch sends Ctrl+wheel) both zoom, and the page and the browser do not scroll or zoom while the pointer is over a plot.
- Shift+wheel and a sideways trackpad swipe pan the time axis instead, kept inside the trace.
- With the pointer anywhere else (the series list, legend, axis labels, cursor table) the wheel scrolls the page as before.
- One wheel notch zooms by a factor of 1.25; trackpad scrolling zooms smoothly in proportion to the scroll distance.
- Zooming out past the whole trace shows the whole trace (the same state as **Whole trace**, so a recording's graph follows live again). Zooming in stops at a window of 100 µs.
- Each wheel step redraws all lanes at once from the points already loaded; the detailed points for the new range are fetched once the wheel has been still for 150 ms, and an answer for an older range is dropped.
- Wheel zoom behaves like drag zoom otherwise: cursors A and B stay, the zoom range is what "Graph zoom" export uses, and while recording a zoomed graph stops following live.
- The hint above the graph and docs/configurator.md mention scroll to zoom and Shift+scroll to pan.
- PC tools 0.76.0 (minor).

Drag, the buttons and double-click are unchanged. The watch graph in the online view (which uses the same plotting) is not part of this change.

## Capabilities

### New Capabilities
None.

### Modified Capabilities
- `canopen-bus-trace`: the Graphs requirement names wheel zoom at the pointer and Shift+wheel pan, with scenarios.

## Impact

- `tools/deploy/canworks/configurator/static/trace.js` (wheel handler on each plot, a shared zoom helper used by the wheel and **Zoom out**, request counter in `loadGraph()`, hint text).
- `tools/deploy/tests/test_configurator_trace_page.py` (browser tests).
- `docs/configurator.md` (Graph paragraph).
- `tools/deploy/pyproject.toml`, `tools/deploy/canworks/__init__.py`, the doc golden files (they carry the version).
- README: lists no graph controls, so no change unless it gains a line on the trace graph (check at apply time).
- No file format, server protocol, plugin or CLI changes. No hardware tasks.
