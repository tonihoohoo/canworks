## 1. Groundwork

- [x] 1.1 Rebase onto `ui-shell-and-connection` as merged; check the MODIFIED Trace view and One connection for every view texts against its archived spec
- [x] 1.2 New `trace_ids.js` and `transmit.js` next to `trace.js` (classic scripts, see design 8; Chronological stays in `trace.js`); existing trace page tests moved to the new names (Frames → Chronological, Identifiers → By identifier, Send panel → transmit list), all green before new behaviour is added
- [x] 1.3 `explain.js`: one inspector for Trace and Frame lab, with the actions Explain in Frame lab and Send…

## 2. Server

- [x] 2.1 `tracing.py` identifier table: rows keyed by identifier, extended flag and direction; changed-byte mask and per-byte change time; never-changed mask; last frame time; silent flag; updated as frames are appended
- [x] 2.2 `POST /api/trace/ids` with `since` and `filter`, answering changed rows and removed keys; `POST /api/trace/ids/reference` (now, a frame, or clear) with `ref_diff` and new-after-reference per row; unit tests including a 2,000-identifier synthetic trace
- [x] 2.3 Connection end during recording: fetch what is left, stop, keep frames, end marker with reason; `POST /api/trace/start` with `continue: true` appends after a gap marker on the same network and keeps trigger hits; refused on another network
- [x] 2.4 Trace metadata `connection` (adapter or runtime) in saved files; older files open as before
- [x] 2.5 Transmit list storage: `trace.json` on this PC keyed by folder and network, read and write routes; list file open and save routes with format checking (`canworks-transmit`, version 1)
- [x] 2.6 Cyclic send jobs stop when the page session ends, not when the Trace view is left; jobs carry their network for the status bar
- [x] 2.7 Commission a device: decoding config built from the Nodes tab's EDS files (SDO object names, EMCY, predefined set; PDOs raw) for the trace and Frame lab examples

## 3. Trace layout

- [x] 3.1 Toolbar: one Start / Stop button, Clear, Open…, Save menu (traces folder and Download as…, formats and range), Capture… popover, time mode
- [x] 3.2 View tabs By identifier, Chronological, Graph, Sequences, Trigger; chosen view kept on this PC; shared Filters control with active count and "showing N of M"
- [x] 3.3 Docked inspector: beside at 1280 px and wider, under below; draggable and keyboard-resizable split; closable; size and state kept on this PC
- [x] 3.4 Header names the connection and network; connection-end message; Start dialog with Continue this trace (default), New trace and Cancel

## 4. By identifier view

- [x] 4.1 Table with the columns of the spec, identifier order, sortable headers with `aria-sort`, sort kept; J1939 names with PGN and source address
- [x] 4.2 In-place updates at up to 4 Hz from the incremental route, keeping focus, selection and scroll; virtualised past 200 rows; Pause view with waiting count
- [x] 4.3 Change marks (1 s, tint plus underline), changed bits on hover and focus, never-changed bytes muted; Set reference and Clear reference; new-after-reference mark
- [x] 4.4 Silent rows with time since last seen
- [x] 4.5 Selection with the keyboard; inspector follows the identifier's latest frame with Hold; row actions Show frames, Explain in Frame lab, Send…, Graph signals
- [x] 4.6 Opened files: whole-file table, reference at a picked frame

## 5. Transmit list

- [x] 5.1 Collapsible pane with row and job counts in its header, height kept
- [x] 5.2 Rows: name, identifier, extended, remote, DLC, data, period, count; inline editing with checks as typed; decoded preview and "identifier in use" note; add, duplicate, move, remove, Clear list with confirmation
- [x] 5.3 Send and Start / Stop through the connection bar's connection; `force` confirmation; refusal text on the row; disabled with reason without Allow changes, list still editable
- [x] 5.4 Jobs carry their network for the shell's status bar (listed there by `ui-shell-and-connection`), counted in the pane header; kept across tabs, workspaces and network switches; Stop all
- [x] 5.5 Kept per folder and network on this PC; Save list… and Open list… (replace or add, ask on another network)

## 6. Send… and Frame lab

- [x] 6.1 Send… on Chronological rows, By identifier rows and the Frame lab result: adds a single-send row, opens Trace and the pane, focuses its Send; disabled with reason without a connection with Allow changes; one-time note on first use
- [x] 6.2 Explain in Frame lab: frame, network, bit rate and SDO context; source line with Back to trace; editing drops the context and says so
- [x] 6.3 Frame lab examples in Commission a device from the Nodes tab's EDS files; Frame lab wording ("sends nothing itself") updated

## 7. Tests

- [x] 7.1 Page tests, By identifier: in-place update without focus loss, change marks and bits, reference, silent, sort, filters shared with Chronological, Pause view, keyboard selection, opened file
- [x] 7.2 Page tests, transmit list: single, remote and cyclic sends on the fake runtime, job kept after leaving the tab, count and Stop all, force confirmation, bad data, list kept after reload, save and open (the job limit is covered by the adapter's own tests)
- [x] 7.3 Page tests: Send… from Chronological, By identifier and Frame lab; Explain in Frame lab with SDO segment context and Back to trace
- [x] 7.4 Page tests: recording through the virtual adapter in Commission a device and through the fake runtime; Continue appends after a gap marker. Connection end with frames kept and marker: server tests
- [x] 7.5 Layout fit at 1000, 1280 and 1440 px with the inspector beside or under the list; axe-core, contrast and target size on the Trace view (layout tests); keyboard selection, Send… and send by keyboard in the page tests
- [x] 7.6 Performance check: 2,000-identifier synthetic trace, one table update under 20 ms of script time

## 8. Docs and release

- [x] 8.1 `docs/configurator.md` Trace section (layout, By identifier, reference, transmit list, Send…, Explain in Frame lab, continue after a connection end), `docs/pc-adapter.md`, `docs/tour.md`, `README.md`
- [x] 8.2 PC tools 0.58.0 (`pyproject.toml`, `canworks/__init__.py`, the doc golden JSON files)
