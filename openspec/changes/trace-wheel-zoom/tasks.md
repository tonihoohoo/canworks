## 1. Wheel zoom and pan

- [ ] 1.1 Shared zoom helper in `static/trace.js`: zoom the view range by a factor around a trace time, with the whole-trace (`T.zoom = null`) and 100 µs limits; **Zoom out** uses it around the middle
- [ ] 1.2 Wheel listener (`passive: false`) on each lane plot's `u.over`: plain wheel and Ctrl+wheel zoom at the pointer (factor from the pixel delta, line and page delta modes converted), Shift+wheel and sideways scroll pan inside the trace; `preventDefault()` only for these
- [ ] 1.3 Each wheel step sets the new x scale on every lane plot at once; `loadGraph()` runs 150 ms after the last wheel event; `loadGraph()` drops answers for older requests
- [ ] 1.4 Hint text above the graph names scroll to zoom and Shift+scroll to pan

## 2. Tests

- [ ] 2.1 Browser test in `test_configurator_trace_page.py` (opened trace file, two lanes): wheel up over a plot zooms in with the time under the pointer kept (within one pixel) and both lanes show the same range; wheel down back past the whole trace returns to the whole trace
- [ ] 2.2 Browser test: Shift+wheel pans and stops at the trace start; the window never goes below 100 µs; the page's scroll position does not change while wheeling over a plot, and does change when wheeling over the series list
- [ ] 2.3 Browser test: after a burst of wheel steps, one series request is made for the final range, and "Graph zoom" export uses that range
- [ ] 2.4 Run the configurator trace page tests locally (Playwright)

## 3. Docs and release

- [ ] 3.1 `docs/configurator.md` Graph paragraph: scroll to zoom at the pointer, Shift+scroll to pan; README if it describes the graph controls
- [ ] 3.2 PC tools version 0.76.0 (pyproject, `canworks/__init__.py`, doc golden files with `UPDATE_GOLDEN=1`)
