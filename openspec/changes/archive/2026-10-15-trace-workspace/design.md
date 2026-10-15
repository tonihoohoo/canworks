## Context

After `ui-shell-and-connection`, Trace is a full-width tool tab in every workspace. Recording and sending go through the one connection in the connection bar, and the status bar lists the recording and the cyclic send jobs. Inside the tab, `trace.js` (1,180 lines) still draws the old page:

- a toolbar with every control expanded;
- the capture filters and the Send panel as expandable sections;
- the statistics line;
- the tabs Frames, Identifiers, Graph, Sequences and Trigger.

The recorder lives in the configurator server (`tracing.py`). It already keeps a per-identifier table (`analysis.id_table()`: count, name, last data, minimum, average and maximum cycle) and answers it on `POST /api/trace/ids`. The page asks for it once a second while the Identifiers tab is open.

The frame inspector (`explain.js`) is drawn by the Trace view for a trace frame (with the server's explanation, `POST /api/trace/explain`) and by the Frame lab for a typed, built or example frame.

Sending uses the diagnostics operations `send_frame` and `send_frame_stop`, on a runtime or on the local adapter backend. They allow 8 cyclic jobs per network and 50 single frames per second per client, and a job ends when its client disconnects.

## Goals / Non-Goals

**Goals:**
- A busy bus is readable at a glance: one row per identifier, updating in place.
- Finding which bytes and bits follow a physical change takes seconds, not hex reading.
- Frames to send are a list that outlives the page and can be shared as a file.
- A frame moves between Trace, Frame lab and the transmit list in one click, with nothing sent without an explicit Send.
- Recording behaves the same through a runtime or an adapter, and a dropped connection costs no frames.

**Non-Goals:**
- New diagnostics operations or plugin changes. Everything uses `trace_*`, `send_frame` and `send_frame_stop` as they are.
- Replay from the transmit list (the `replay` operation exists; a later change can use it).
- Importing transmit lists of other tools.
- A trace preview in the bottom panel.
- New state colours and icons (`visual-refresh`).

## Decisions

### 1. Layout of the Trace tab
```
┌ Start/Stop · Clear · Open… · Save ▾ · Capture… · Relative|UTC ─────────────────┐
│ live from <connection target>, network io · 41,230 frames · 812/s · load 23 %   │  header + statistics
│ [By identifier][Chronological][Graph][Sequences][Trigger]   filters ▾            │
├──────────────────────────────────────────────┬──────────────────────────────────┤
│ view (list or table)                         ┊ frame inspector                  │  split, draggable
├──────────────────────────────────────────────┴──────────────────────────────────┤
│ ▾ Transmit list (3)                                       Stop all · Save · Open │  collapsible pane
└──────────────────────────────────────────────────────────────────────────────────┘
```

- **Start / Stop** is one button: it reads Start, then Stop while recording, and is the first button of the toolbar.
- **Save ▾** holds two entries, each with its format picker and the range picker:
  - "Save to traces folder" (this PC);
  - "Download as…" (a file).

  The two stay labelled apart as today.
- **Capture…** opens the capture filters and the error frame choice in a popover.
- **Filters ▾** holds the display filters shared by By identifier and Chronological: nodes, identifier range, direction, kinds and text. A count of active filters shows on the button. When any filter is active, the statistics line says "showing N of M".
- **The inspector**:
  - is docked right at 1280 px and wider, under the list below that;
  - can be resized with a drag handle (also with the arrow keys when the handle has focus);
  - can be closed and reopened, and its width or height and open state are kept on this PC (`trace.json`, `prefs`);
  - shows only with By identifier and Chronological, while Graph, Sequences and Trigger use the full width as today and open the inspector in the same docked place when a step is clicked.
- **The transmit list** is a collapsible pane under the views. Its height is kept on this PC, and its header shows the row count and the number of running jobs.

*Alternative:* the transmit list as another view tab. Rejected: sending while watching the bus is its main use, so both have to be in view together, as in the analysers compared.

### 2. By identifier view
**Rows.** Rows are keyed by (identifier, extended flag, direction). A frame sent by this PC and the same identifier received are two rows, because they mean different things when testing. The columns are:
- Dir;
- ID (hex, extended as 8 digits);
- Name (decoded name: "TPDO1 node 5", raw message name, PGN name on J1939);
- DLC;
- Data;
- Decoded;
- Count;
- Cycle (last);
- Avg, Min and Max cycle;
- Last seen (age, or the time of the last frame for an opened file).

Numbers are right-aligned, and ID and data are monospace. On a J1939 network the name gives the PGN and source address, as the chronological list does.

**Order and sorting.** Rows are in identifier order by default, so a row never moves while the bus runs. Every column header is a sort button with `aria-sort`, and the chosen sort is kept on this PC.

**Change marks.** For each row the server keeps the data of the previous frame of that identifier. It answers a changed-byte mask (bytes that differ between the last two frames) and the time of the last change per byte.
- A byte is marked as changed for 1 s after it changed. The mark is a background tint plus an underline, so colour is not the only cue.
- Hovering or focusing the data cell shows the bits that changed, as a bit row per changed byte.
- Bytes that never change in the whole trace are drawn in muted text, so moving bytes stand out.

**Reference.** **Set reference** snapshots each row's current data on the server. From then on, bytes that differ from the reference stay marked (a second, stronger mark) until **Clear reference**. A row that appears after the reference is marked "new". This is the "flip the switch and see what moved" workflow. It works while recording and on an opened file (the reference is then the data at a chosen frame or graph cursor).

**Silent identifiers.** A row whose identifier has not been seen for more than three of its average cycles is greyed out with "silent 4.2 s". The limit is at least 1 s, and rows with fewer than 3 frames have no average and are never marked silent. It is a state, not an error colour, until `visual-refresh` adds state colours.

**Updates.** While recording, the page asks for the table four times a second with `since` (the generation it holds). The server answers only the rows that changed, plus removed keys after Clear.
- The page patches rows in place and never re-renders the table.
- Focus, selection and the scroll position stay where they are.
- The table is virtualised past 200 rows. Extended identifiers on J1939 can give thousands.
- **Pause view** stops applying updates (recording continues) and shows "paused, N updates waiting".

**Selection.**
- Selecting a row shows the identifier's latest frame in the inspector. The inspector follows new frames of that identifier.
- **Hold** in the inspector keeps the shown frame while the row keeps updating.
- The arrow keys, Home, End, Page Up and Page Down move the selection, as in the chronological list.

The row's actions sit in a toolbar under the table, applying to the selected row:
- **Show frames**: Chronological, filtered to that identifier;
- **Explain in Frame lab**;
- **Send…**;
- **Graph signals**: adds the row's decoded signals to the graph.

**Opened files.** The table holds the whole file, or the frames inside the display filters, with Last seen as the time of the last frame. Change marks then show the changes between the last two frames of each identifier, and the reference is taken at a picked frame.

*Server:* `POST /api/trace/ids` takes `since` and `filter` and answers `generation`, `rows` (with `key`, `changed`, `changed_at`, `ref_diff`, `static_mask`, `last_us`, `silent`) and `removed`. `POST /api/trace/ids/reference` takes `{"at": "now" | seq | null}`. The per-identifier state is updated as frames are appended, so a request costs the rows that changed, not a pass over the trace.

### 3. Chronological view
Today's Frames list, renamed, with Follow, the time mode, the arrow-key selection and the inspector beside it. Its row actions become Explain in Frame lab, Send… and the sequence links that exist today.

### 4. Recording through any connection
The recorder already reads frames through the connection's `trace_fetch`, whether the target is a runtime or the local adapter backend.
- The header names the connection as the connection bar does (the adapter and bit rate, or the runtime name, and the network).
- Saved files keep the source kind in their metadata (`connection: adapter|runtime`) with the interface, network and bit rate.

**Connection end.** When the connection ends during recording (a bus-off on an adapter, a runtime that stops answering, Disconnect):
- the recorder fetches what it can, stops and keeps the frames;
- it adds an end marker with the reason ("connection ended: bus-off"), drawn as a marker row in Chronological and a marker line in Graph;
- the status bar entry for the recording ends;
- the header says "Recording stopped: connection ended (bus-off)".

**Continue.** Start with frames in the trace asks:
- **Continue this trace** (default): appends after a gap marker that holds the gap's length;
- **New trace**: today's "the current recording is lost unless saved" warning;
- **Cancel**.

Continue is offered only when the network is the same. On another network the choice is only New trace, because the decoding would differ. Continue keeps the trigger and its hits.

### 5. Transmit list
**Rows.** Each row holds:
- `name` (optional);
- `id` (hex), `ext`, `rtr`, `dlc`, `data`;
- `period_ms` (blank or 10–60000) and `count` (optional).

Next to them the row shows its state:
- idle;
- "sent 12:04:31.205" after a single send;
- running with the sent count;
- "refused: <reason>".

Single rows have **Send**, and cyclic rows **Start** or **Stop**. The other actions are edit in place, Duplicate, Move up, Move down and Remove. The list toolbar has:
- **Add frame**;
- **Stop all**;
- **Save list…** and **Open list…**;
- **Clear list**, which asks first with Cancel as the default.

**Checking.** Fields are checked as the user types, with the message under the field:
- the identifier in range for the extended flag;
- the data as whole bytes, at most 8;
- the period from 10 to 60000.

A decoded preview ("RPDO1 node 5: valve_cmd = 1") comes from the frame explanation of the current config. It also warns before sending when the identifier is one the network uses, because that send will need `force`.

**Sending rules.** These are unchanged from the Send panel:
- every send needs a connection with Allow changes;
- a `force` refusal asks with the plugin's reason and resends with `force` only on confirmation;
- the 9th cyclic job on a network is refused with the plugin's message.

Without Allow changes the list stays editable, and its header says why Send and Start are disabled.

**Jobs.** Cyclic jobs are no longer stopped when the user leaves the Trace tab.
- They are listed in the status bar as "Send 0x60A every 100 ms – 412 sent" with Cancel.
- They stop on Stop, Stop all, Disconnect, a connection end or closing the page.
- The server stops them when the page session ends, as the plugin does when its client disconnects.
- The row's state follows the job from the send job list the server already polls.

**Storage.** The current list is kept on this PC in `trace.json` in the configurator's settings folder, keyed by folder and network ("no folder" in Commission a device). It is written on every change, so the list returns after a reload or the next day. It is not in the project folder and not in the config, because sending is a test activity and the config is uploaded to the runtime.

**Files.** Save list… and Open list… use a JSON file chosen by the user (Save list… downloads `<network>.transmit.json`):

```json
{"format": "canworks-transmit", "version": 1, "network": "io",
 "frames": [{"name": "valve open", "id": "0x205", "ext": false, "rtr": false,
             "dlc": 1, "data": "01", "period_ms": null, "count": null}]}
```

Opening a list made for another network asks whether to add it to the picked network anyway. Opening replaces the list or adds to it, by the user's choice.

**Network switch.** The pane shows the picked network's list. Jobs on another network keep running and stay listed in the status bar with the network's name.

### 6. Send… and Explain in Frame lab
**Send…** is one action in three places: a Chronological row, a By identifier row and the Frame lab result. It adds the frame as a new single-send row at the end of the transmit list, opens the Trace tab and the transmit pane if needed, and focuses the new row's Send button. Nothing is sent by Send… itself, so the Frame lab still never sends (its requirement keeps that wording, now "sends nothing itself"). Send… is enabled only while a connection with Allow changes is open; otherwise it is disabled with the reason as its description.

**Explain in Frame lab** opens the Frame lab tool tab with the frame. It passes:
- the frame;
- the trace's network and bit rate;
- the SDO context (the transfer the frame belongs to, if any);
- the frame's place in the trace.

The Frame lab shows "From trace, frame 41,230 (12:04:31.205)" with **Back to trace**, which returns to the trace with that frame selected. Editing any byte or the identifier drops the SDO context and changes the source line to "Edited from trace frame 41,230".

**One inspector.** `explain.js` draws the inspector for both views from the server's explanation model (`fxInspectSeq` for a trace frame, `fxLabExplain` in the Frame lab). It adds the actions to show: Explain in Frame lab and Send… in Trace, and Send… in the Frame lab. The frame lab's own entry points (typed frame, builder, examples, arbitration) stay in the Frame lab module.

### 7. Commission a device: decoding and examples
Without a config, the EDS files on the Nodes tab (from a scan match, Add node from EDS… or picked) feed:
- the trace decoding of SDO object names and EMCY;
- the Frame lab's example frames (boot-up, heartbeat, SDO read of 1018h:01 and its answer per node).

PDOs stay raw, because the device's mapping is not known without reading it. The server builds a temporary decoding config from those EDS files, the same way it decodes a trace file opened with a DBC.

### 8. Code layout
`trace.js` keeps the tab, the toolbar, Chronological, Graph, Trigger and polling. The new files are:
- `trace_ids.js` (By identifier);
- `transmit.js` (the transmit list and Send…);
- the inspector actions in `explain.js`;
- on the server, `transmit.py` (list storage, prefs and list files).

They are classic scripts loaded after `trace.js`, like the rest of the page, so the page keeps working without a build step and the change stays independent of how `ui-shell-and-connection` splits the page. Chronological stays in `trace.js` to keep the diff against the shell change small.

## Risks / Trade-offs

- **[Four updates a second on thousands of identifiers]** → Incremental answers (`since`), in-place patching, virtualisation past 200 rows and a 4 Hz cap. A page test with a 2,000-identifier synthetic trace checks that an update costs less than 20 ms of script time.
- **[Cyclic jobs that outlive the tab are forgotten]** → They are always in the status bar with Cancel, the transmit pane header counts them, and closing the page stops them.
- **[Send… could be taken as "send now"]** → The ellipsis, the focus moving to the row's Send button, and a one-line note in the transmit pane the first time ("Added to the transmit list. Press Send to put it on the bus.").
- **[This change's MODIFIED Trace view text is based on `ui-shell-and-connection`'s version]** → If that change's text changes while it is applied, this change's delta is rebased onto it before this change is applied.
- **[By identifier as default hides the order of events]** → The view choice is kept on this PC, Show frames jumps to Chronological filtered to the row, and Sequences keeps the order-based views.

## Migration Plan

UI only, with nothing stored to migrate:
- `trace.json` is new: the view settings (tab, split, inspector, sort, pane) and the transmit lists.
- Saved pcapng files gain `connection` in their metadata, and older files open as before (connection unknown).
- Rollback is the previous tools version.

## Open Questions

None. The defaults picked here can change in review:
- separate rows per direction;
- three average cycles for silent;
- 1 s change marks;
- the list kept per folder and network on this PC, not in the project;
- Send… disabled without Allow changes.
