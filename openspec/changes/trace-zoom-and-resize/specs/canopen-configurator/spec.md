## MODIFIED Requirements

### Requirement: Trace toolbar and views
The Trace tool tab SHALL have one toolbar with:
- one Start / Stop button;
- Clear and Open…;
- a Save menu with "Save to traces folder" and "Download as…", each with its format, and the range;
- Capture… for capture filters and error frames;
- Decoding… for DBC files and the nodes' PDO layouts (see "Decoding panel in the Trace view");
- the time mode.

Under it SHALL be the header with the statistics and the view tabs **By identifier**, **Chronological**, **Graph**, **Sequences** (not on J1939) and **Trigger**.

The height of the By identifier list, the Chronological list and the Graph SHALL be adjustable by dragging a resize bar under each, bigger or smaller, with the arrow keys on the focused bar (Up smaller, Down bigger, 40 px a step) and double-click on the bar back to the default. The lists SHALL be between 120 px and 3000 px high, and one setting SHALL cover both lists. The graph's height SHALL be set per lane, between 80 px and 1000 px, and all lanes SHALL share it; the default stays 200 px per lane (150 px with more than two lanes) until the user resizes. The heights SHALL be kept on this PC with the other trace view settings and SHALL be used again after a reload. While the list and the inspector share the window height (between the phone and the wide layout), the list's bar SHALL be hidden and that layout is unchanged.

#### Scenario: One Start / Stop button
- **WHEN** the user presses Start
- **THEN** the same button reads Stop until the recording stops

#### Scenario: Make the list taller
- **WHEN** the user drags the bar under the Chronological list 300 px down and reloads the page
- **THEN** the list is 300 px taller, shows more rows, and is still that height after the reload and in By identifier

#### Scenario: Make the graph lanes taller
- **WHEN** two lanes are graphed and the user drags the bar under the graph 200 px down
- **THEN** each lane is 300 px high, the graph is redrawn at that height with the cursors kept, and double-click on the bar returns both lanes to 200 px
