## 1. Wheel zoom and pan

- [ ] 1.1 Shared zoom helper in `static/trace.js`: zoom the view range by a factor around a trace time, with the whole-trace (`T.zoom = null`) and 100 µs limits; **Zoom out** uses it around the middle
- [ ] 1.2 Wheel listener (`passive: false`) on each lane plot's `u.over`: plain wheel and Ctrl+wheel zoom at the pointer (factor from the pixel delta, line and page delta modes converted), Shift+wheel and sideways scroll pan inside the trace; `preventDefault()` only for these
- [ ] 1.3 Each wheel step sets the new x scale on every lane plot at once; `loadGraph()` runs 150 ms after the last wheel event; `loadGraph()` drops answers for older requests
- [ ] 1.4 Hint text above the graph names scroll to zoom and Shift+scroll to pan

## 2. Resizing

- [ ] 2.1 Resize bar component (drag with pointer capture, Up/Down 40 px, double-click reset, separator role and value) shared by the lists and the graph
- [ ] 2.2 List bar under Chronological and By identifier: one `list_h` pref (120–3000 px) through a CSS variable used by `.trace-list` and `.ids-grid`; hidden in the shared-height layout
- [ ] 2.3 Graph bar under the plots: `lane_h` pref (80–1000 px per lane, default 200/150), plots resized with `setSize()` while dragging, cursors and zoom kept
- [ ] 2.4 Save `list_h` and `lane_h` with `tracePrefs()` and read them in `traceLoadPrefs()`; let `tracing.py` accept them if prefs are checked

## 3. Tests

- [ ] 3.1 Browser test in `test_configurator_trace_page.py` (opened trace file, two lanes): wheel up over a plot zooms in with the time under the pointer kept (within one pixel) and both lanes show the same range; wheel down back past the whole trace returns to the whole trace
- [ ] 3.2 Browser test: Shift+wheel pans and stops at the trace start; the window never goes below 100 µs; the page's scroll position does not change while wheeling over a plot, and does change when wheeling over the series list
- [ ] 3.3 Browser test: after a burst of wheel steps, one series request is made for the final range, and "Graph zoom" export uses that range
- [ ] 3.4 Browser test: dragging the list bar 300 px down makes the Chronological list 300 px taller, By identifier uses the same height, and it survives a reload; double-click returns to the default; arrow keys change 40 px
- [ ] 3.5 Browser test: with two lanes, dragging the graph bar 200 px down makes each lane 300 px; cursor A stays; the height survives a reload; at 1000 px width the list bar is hidden in the shared-height layout
- [ ] 3.6 Run the configurator trace page tests locally (Playwright)

## 4. Docs and release

- [ ] 4.1 `docs/configurator.md` Graph paragraph: scroll to zoom at the pointer, Shift+scroll to pan, the resize bars under the lists and the graph; README if it describes the graph controls
- [ ] 4.2 PC tools version 0.76.0 (pyproject, `canworks/__init__.py`, doc golden files with `UPDATE_GOLDEN=1`)
