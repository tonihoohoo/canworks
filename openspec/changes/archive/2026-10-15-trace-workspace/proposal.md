## Why

This is the fourth of five changes in the configurator's UI overhaul (research note of 2026-10-15, kept outside the repository). `ui-shell-and-connection` made Trace a full-width tool tab that records through the connection in the connection bar. Inside the tab, the view is still the old side bar page:

- **The first thing shown is a scrolling list.** On a busy bus the chronological list scrolls faster than anyone can read. The bus analysers compared (receive list by identifier, "fixed position" trace) open on one row per identifier instead, with its count, cycle time and last data updating in place. The configurator has that table, but as the second tab ("Identifiers"), refreshed once a second, without the last data's changes and without the inspector.
- **Finding a signal is guesswork.** Nothing shows which bytes or bits of a frame changed, so finding the byte that follows a switch or a sensor means reading hex. One of the analysers compared marks changed bytes and bits and lets the user set a reference to compare with.
- **A silent node looks like a quiet one.** An identifier that stopped arriving stays in the table with its old numbers.
- **Sending is a one-off form.** The Send panel holds one frame at a time. Its cyclic jobs stop when the user leaves the Trace view, and nothing can be kept for the next session. The analysers compared have a transmit list with several frames, each sent once or cyclic, that can be saved and loaded again.
- **Trace and Frame lab do not talk.** Both show the same frame inspector, but a frame seen in the trace cannot be taken to the Frame lab to change a bit and see the result, and a frame built in the Frame lab cannot be sent.
- **The toolbar is a row of everything.** Start, Stop, Clear, Open, two format pickers, a range picker, capture filters and the Send panel all sit above the list, each fully expanded.
- **A dropped connection ends the trace silently.** When the bus or runtime connection ends, the recording stops with an error line, and Start begins a new trace.

## What Changes

- **Layout.** The Trace tab gets one toolbar:
  - a single **Start / Stop** button;
  - **Clear** and **Open…**;
  - one **Save ▾** menu ("Save to traces folder" and "Download as…", each with its format, and the range);
  - **Capture…** opening the capture filters;
  - the time mode.

  Under it are the view switch (**By identifier**, **Chronological**, **Graph**, **Sequences**, **Trigger**) and the statistics line. The frame inspector is docked beside the list on wide windows and under it on narrow ones, with a split the user can drag. The transmit list is a collapsible pane under the views.
- **By identifier view, the default.** One row per identifier, in identifier order, updating in place four times a second without moving focus or the scroll position:
  - direction, identifier, decoded name, DLC;
  - last data with the bytes that changed since the identifier's previous frame marked, and the changed bits on hover or focus;
  - last decoded values;
  - count, last cycle time, average, minimum and maximum cycle time;
  - time since last seen.

  It also offers:
  - **Set reference**, so the bytes that differ from a moment the user picks stay marked (finding the byte that follows a switch);
  - a **silent** mark on identifiers not heard for three of their average cycles (at least 1 s);
  - **Pause view** while recording continues;
  - sorting by any column;
  - the same display filters as the chronological list.

  Selecting a row shows its latest frame in the inspector. Row actions are "Show frames", "Explain in Frame lab", "Send…" and "Graph signals". The per-identifier table of today's Identifiers tab becomes this view.
- **Chronological view.** Today's Frames list, renamed, with the inspector beside it.
- **Recording through any connection.** Recording uses whatever connection the bar holds, runtime or adapter, in either workspace. The trace header names that connection. When the connection ends while recording:
  - the recording stops and keeps its frames;
  - an end marker with the reason is added;
  - the next Start offers **Continue this trace** (the default, with a gap marker) or **New trace**.
- **Transmit list.** It replaces the Send panel. Each row has:
  - an optional name;
  - the identifier (hex), extended and remote options, DLC and data;
  - a period for cyclic sending (blank for one frame) and an optional count;
  - its state and sent count;
  - a decoded name preview from the config.

  Rows can be added, edited in place, duplicated, reordered and removed. The list also has **Stop all**, and **Save list…** and **Open list…** for a small JSON file. The current list is kept on this PC per folder and per network, so it is there next time. The send rules stay: Allow changes, the `force` confirmation, and 8 cyclic jobs per network. Cyclic jobs now keep running when the user leaves the Trace tab. They are listed in the status bar with Cancel, and they stop on Stop, Disconnect, a connection end or closing the page.
- **Send… everywhere.** "Send this frame" on a trace row becomes **Send…**, also in the By identifier view and the Frame lab. It adds the frame to the transmit list as an unsent row and focuses that row's Send button. Nothing goes on the bus until the user presses Send there. Send… is offered while a connection with Allow changes is open, and says why when it is not.
- **Shared frame inspector.** Trace and Frame lab use one inspector component, so a fix or feature lands in both. **Explain in Frame lab** on a trace row or identifier opens the Frame lab with that frame, the trace's network and bit rate, and its SDO context. The Frame lab shows where the frame came from and drops the context once the frame is edited.
- **Frame lab in Commission a device.** Its example frames come from the EDS files on the Nodes tab, and the trace decodes SDO object names with them.
- **BREAKING (UI only):**
  - The Trace view's tabs Frames and Identifiers become Chronological and By identifier, and By identifier opens first.
  - The Send panel becomes the transmit list.
  - "Send this frame" becomes Send…, which no longer fills a form but adds a row.

  No file format of the config, no plugin operation and no CLI change.

Out of scope: the network tree and node tabs (`network-tree-and-node-tabs`), the Commission workspace's Nodes table and scan comparison (`commission-workspace`), new state colours and icons (`visual-refresh`). Also out: a trace preview in the bottom panel, replaying a trace from the transmit list, and importing other tools' transmit list files.

## Capabilities

### New Capabilities
None.

### Modified Capabilities
- `canopen-configurator`:
  - Added: Trace toolbar and views, shared display filters, docked inspector and transmit pane, the By identifier view (live updates, sorting, change marks and reference, silent identifiers, selection), the transmit list (storage and files, sending, cyclic jobs), Explain in Frame lab, and Send….
  - Changed: Trace view, Frame inspector panel, Frame lab view, One connection for every view (added by `ui-shell-and-connection`, so it can only be archived after that change), and Keyboard access and announcements (the trace tabs' names).
  - Removed: Send frames from the Trace view.
- `canopen-bus-trace`:
  - Record a trace on the PC: through the runtime or the adapter, connection end and continue.
  - Trace statistics: changed bytes, reference and silent identifiers in the per-identifier table.
  - Views follow the picked network: the transmit list instead of the Send panel.

## Impact

- Configurator page: `tools/deploy/canworks/configurator/static/`:
  - `trace.js` (toolbar, Chronological, Graph, Trigger), with the new `trace_ids.js` (By identifier) and `transmit.js` (transmit list);
  - `explain.js`, as the one inspector component with an entry point for a frame plus its context;
  - `index.html` and `style.css`.
- Configurator server:
  - `tracing.py`: the identifier table gets the last data's changed-byte mask, the reference compare, last seen and incremental updates; a reference route; continue after a connection end with a gap marker; the trace source named by connection kind;
  - `server.py`: the transmit list file on this PC (per folder and network), and open and save of list files;
  - EDS names for decoding in Commission a device.
- Tests: page tests for the By identifier view (in-place update, change marks, reference, silent, sort, filters, keyboard), the transmit list (add, edit, single and cyclic, jobs across tabs, save and open, refusal and force), Send… and Explain in Frame lab round trips, recording through the virtual adapter and the fake runtime with a connection end and Continue, the layout at 1000, 1280 and 1440 px, and axe-core on the new parts. The existing trace page tests are moved to the new names.
- Docs: `docs/configurator.md` (Trace section), `docs/pc-adapter.md`, `docs/tour.md`, `README.md`.
- Version: PC tools minor bump. No plugin change, so no hardware test is needed beyond the page tests.
