## 1. Server

- [x] 1.1 `server.py`: `import_dbc(name, data, on_conflict, kind)` with `kind` `j1939` (today's reader) or `raw` (`rawpage.dbc_messages` on the bytes); shared name check, 409 conflict, keep_both suffix and `pending_dbc`
- [x] 1.2 `POST /api/raw/dbc`: `{name, data?, on_conflict?}` like `/api/j1939/dbc` (without `data` reads the network's file, 404 when missing); returns `{name, messages, problems}`
- [x] 1.3 `POST /api/raw/dbc_import`: `name` instead of `text`, bytes from `dbc_path`
- [x] 1.4 Save writes a pending DBC when any network names it in `j1939.dbc` or `raw.dbc`; drops it from `pending_dbc` after writing
- [x] 1.5 State reply says per network whether its `raw.dbc` file exists (folder or pending), for the missing mark
- [x] 1.6 Server tests: upload, conflict (replace, keep both), read back by name, 404, save writes a raw DBC, an unnamed pending DBC is not written

## 2. Shared picker

- [x] 2.1 `dbcpick.js`: `pickDbcMessages({title, columns, rows, problems, listenOnly})` with Leave out / Receive / Send, preselection, "already in" marks, Left out of the import list, Cancel / Add picked messages; load it in `index.html` before `j1939.js` and `rawcan.js`
- [x] 2.2 `j1939.js`: `pickMessages` uses the shared picker; J1939 page tests pass unchanged

## 3. CAN messages page

- [x] 3.1 `rawcan.js`: Import DBC… as a `.file-button` (`accept=".dbc,.DBC"`, input reset after each pick); remove the intermediate dialog
- [x] 3.2 Ask before a second file (Keep a.dbc / Use b.dbc) when `raw.dbc` differs and the network has raw messages
- [x] 3.3 Upload with base64 `data`, conflict question (Replace / Keep both), then the shared picker with columns Message, Identifier, DLC, Cycle, Signals; set `raw.dbc` to the returned name after Add picked messages
- [x] 3.4 Replace the `raw.dbc` text field with the read-only DBC line, missing mark, and Pick messages… when `raw.dbc` is set
- [x] 3.5 `rawRemove`: clear `raw.dbc` with the last message
- [x] 3.6 Page tests (`test_configurator_raw_page.py`): one click opens the picker (file chooser event, no modal before it), import two messages and save writes the DBC file, keep both, second file question, Pick messages… marks existing messages, missing file mark, keyboard reach of the file button

## 4. Docs

- [x] 4.1 `docs/configurator.md` CAN messages section and `docs/raw-can.md`: new flow, file kept in the config folder, no claim that the trace reads `raw.dbc`
- [x] 4.2 README: CAN messages DBC import line, if it describes the flow
- [x] 4.3 Bump the PC tools version

## 5. CI time

- [x] 5.1 Compare the PR's CI wall and summed job time with the baseline (median of the last 5 green `main` runs) and state both in the PR
