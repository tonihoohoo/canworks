## 1. Wheel zoom and pan

- [x] 1.1 Shared zoom helper in `static/trace.js`: zoom the view range by a factor around a trace time, with the whole-trace (`T.zoom = null`) and 100 µs limits; **Zoom out** uses it around the middle
- [x] 1.2 Wheel listener (`passive: false`) on each lane plot's `u.over`: plain wheel and Ctrl+wheel zoom at the pointer (factor from the pixel delta, line and page delta modes converted), Shift+wheel and sideways scroll pan inside the trace; `preventDefault()` only for these
- [x] 1.3 Each wheel step sets the new x scale on every lane plot at once; `loadGraph()` runs 150 ms after the last wheel event; `loadGraph()` drops answers for older requests
- [x] 1.4 Hint text above the graph names scroll to zoom and Shift+scroll to pan

## 2. Resizing

- [x] 2.1 Resize bar component (drag with pointer capture, Up/Down 40 px, double-click reset, separator role and value) shared by the lists and the graph
- [x] 2.2 List bar under Chronological and By identifier: one `list_h` pref (120–3000 px) through a CSS variable used by `.trace-list` and `.ids-grid`; hidden in the shared-height layout
- [x] 2.3 Graph bar under the plots: `lane_h` pref (80–1000 px per lane, default 200/150), plots resized with `setSize()` while dragging, cursors and zoom kept
- [x] 2.4 Save `list_h` and `lane_h` with `tracePrefs()` and read them in `traceLoadPrefs()`; let `tracing.py` accept them if prefs are checked

## 3. Trace in its own window

- [x] 3.1 **Open in new window** button in the Trace toolbar (⧉; hidden below phone width and in the trace window; focuses an open trace window); opens `/?window=trace` with the saved size
- [x] 3.2 Trace-window mode at boot: only the Trace view, one-line top bar (project folder, network, connection), title "Trace – <folder>", no header tabs, Problems panel or Connect button; no-connection text points to Connect… in the main window
- [x] 3.3 `BroadcastChannel` messages (open/closed, ping/here, network, folder, goto, bring-back); main window's Trace tab note with **Show trace window** and **Bring trace back here**, no trace polling while the window is open
- [x] 3.4 Explain in Frame lab from the trace window acts in the main window (or opens the main page when none answers); Back to trace selects the frame in the trace window
- [x] 3.5 Unsaved-recording question only in the last window showing it; window size saved in trace prefs

## 4. Tests

- [x] 4.1 Browser test in `test_configurator_trace_page.py` (opened trace file, two lanes): wheel up over a plot zooms in with the time under the pointer kept (within one pixel) and both lanes show the same range; wheel down back past the whole trace returns to the whole trace
- [x] 4.2 Browser test: Shift+wheel pans and stops at the trace start; the window never goes below 100 µs; the page's scroll position does not change while wheeling over a plot, and does change when wheeling over the series list
- [x] 4.3 Browser test: after a burst of wheel steps, one series request is made for the final range, and "Graph zoom" export uses that range
- [x] 4.4 Browser test: dragging the list bar 300 px down makes the Chronological list 300 px taller, By identifier uses the same height, and it survives a reload; double-click returns to the default; arrow keys change 40 px
- [x] 4.5 Browser test: with two lanes, dragging the graph bar 200 px down makes each lane 300 px; cursor A stays; the height survives a reload; at 1000 px width the list bar is hidden in the shared-height layout
- [x] 4.6 Browser test (two pages, same context): open the trace window, record from the fake plugin while the main window shows the online view and see the frames arrive in the trace window; the main Trace tab shows the note; Bring trace back here closes the window and shows the same frames; Explain in Frame lab from the trace window opens it in the main window and Back to trace selects the frame in the trace window; closing the main window asks nothing and keeps the trace window recording
- [x] 4.7 Run the configurator trace page tests locally (Playwright)

## 5. Docs and release

- [x] 5.1 `docs/configurator.md` Graph paragraph: scroll to zoom at the pointer, Shift+scroll to pan, the resize bars under the lists and the graph; Trace section: Open in new window; README: one line on the trace in its own window
- [x] 5.2 PC tools version 0.76.0 (pyproject, `canworks/__init__.py`, doc golden files with `UPDATE_GOLDEN=1`)
