## MODIFIED Requirements

### Requirement: Graphs
The configurator SHALL plot chosen series against time on a shared time axis: decoded PDO signals, SDO variable values, node NMT states, bus state and error counters, frame rate and estimated bus load. It SHALL offer zoom, pan, a value cursor across all lanes, two measurement cursors showing the time and value difference, and jumping from a point to its frame in the trace and back. Graphs SHALL stay responsive with a 2 million frame trace and update while recording.

Zoom SHALL be possible by dragging a range, with the mouse wheel and with buttons. With the pointer over a graph's plot area, the wheel (with or without Ctrl, so a trackpad pinch works too) SHALL zoom all lanes' time axis in or out around the time under the pointer, about ×1.25 per wheel notch and in proportion for trackpad scrolling, without scrolling or zooming the page. Shift+wheel and sideways trackpad scrolling over a plot SHALL pan the time axis, kept inside the trace. With the pointer elsewhere in the Trace view, the wheel SHALL scroll the page as usual. Zooming out to the whole trace or beyond SHALL show the whole trace, the same as **Whole trace**; zooming in SHALL stop at a 100 µs window. Each wheel step SHALL redraw all lanes at once, and the detailed points for the new range SHALL be loaded when the wheel stops. A wheel zoom SHALL be the graph's zoom like a drag zoom: cursors stay, "Graph zoom" export uses it, and while recording a zoomed graph stops following live until the whole trace is shown again.

#### Scenario: Plot a valve signal
- **WHEN** the user adds node 23's valve output signal and the bus load to the graph during recording
- **THEN** both series update live on the same time axis

#### Scenario: Measure a delay
- **WHEN** the user places one measurement cursor on a SYNC and the other on the following TPDO of node 23
- **THEN** the graph shows the time between them

#### Scenario: Wheel zoom at the pointer
- **WHEN** a 60 s trace is graphed in two lanes and the user turns the wheel up three notches with the pointer at 12.0 s on the lower lane
- **THEN** both lanes show about 5.9 s to 36.6 s with 12.0 s still under the pointer, the page does not scroll, and the detailed points for that range are loaded once the wheel stops

#### Scenario: Wheel out to the whole trace
- **WHEN** the graph is zoomed in during a recording and the user turns the wheel down until the range covers the whole trace
- **THEN** the graph shows the whole trace and follows the recording live again

#### Scenario: Shift+wheel pans
- **WHEN** the graph shows 10 s to 20 s of a 60 s trace and the user turns the wheel with Shift held, towards the start
- **THEN** the range moves towards 0 s with the same width and stops when it reaches the trace start

#### Scenario: Page scroll outside the plot
- **WHEN** the pointer is over the series list beside the graph and the user turns the wheel
- **THEN** the page scrolls and the graph's range does not change
