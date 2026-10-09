## 1. Notes model

- [ ] 1.1 Add `schema/canworks-notes.v1.schema.json` (copied to `tools/deploy/canworks/schema/`) for the format in design D2; verify the schema accepts the design's example and rejects a wrong `format`, an index key in lower case and a `text` over 200 characters.
- [ ] 1.2 Add `tools/deploy/canworks/notes.py`: `load(path)` (missing file, invalid JSON and wrong format handled as in D7), `builtin(eds)` (CiA 301 always, 401/402 from the 0x1000 default), `merged(eds, device_notes)` field by field with sub-object inheritance (D2, D3), `skeleton(eds, eds_name)` (D4), `update(existing_text, changes, eds)` keeping unknown keys and order, `check(eds, notes)` (D7); verify with `tests/test_notes.py` covering every scenario in `canopen-device-notes`.
- [ ] 1.3 Write `notes/cia301.json`, `notes/cia401.json`, `notes/cia402.json` in canworks' own wording with at least the objects in D3; move the bit and mode names from `app.js` `OD_BITS`/`OD_MODES` into them; verify in `tests/test_notes.py` that each file passes the schema, every key is an object index of its profile range, and 0x1001, 0x1002, 0x6040, 0x6041, 0x6060, 0x6061, 0x6098 and the transmission type have their bits or values.

## 2. Configurator server

- [ ] 2.1 Add each object's merged note to `eds_summary` and to the OD browser entries (`parameters.Entry.to_json`), and an `/api/notes` read/update route working on the draft; verify with `tests/test_configurator_server.py`.
- [ ] 2.2 Save: write notes skeletons for EDS files without a notes file and apply note edits through `notes.update`; never touch an unreadable notes file; keep notes with "replace" and give "keep both" its own file; verify with `tests/test_configurator.py` (first save, hand-written entry kept, broken file left as it is, keep-both naming) and that no file outside `canworks/` changes.
- [ ] 2.3 Notes checks as warnings in the Problems pane with the notes file name, never blocking Save; verify with an API test for an object the EDS no longer has.
- [ ] 2.4 "Export merged notes" for a node; verify the file passes the schema and holds built-in plus device entries.
- [ ] 2.5 Confirm the deploy bundle and `--check-only` ignore notes files; verify with a `tests/test_deploy.py` case that bundles a project with a notes file.

## 3. Configurator page

- [ ] 3.1 Object dictionary view: note text under the name, unit and scaled value, value meaning, bit view from `bits` for any object (remove `OD_BITS`/`OD_MODES`), value list with "Other value…" in the editor; verify with `tests/test_configurator_online_page.py` (vendor bit field, scaled value, mode picked by name) and the layout fit check.
- [ ] 3.2 Note editor dialog (text, details, unit, scale, values and bits tables, manual) from the OD view, the startup SDO editor and picker and the PDO entry picker; only changed fields saved for built-in objects; undoable; hidden in "Commission a device" without a config; verify with page tests for the three Note editor scenarios.
- [ ] 3.3 Startup SDO editor and picker, PDO entry picker, Parameters compare and restore lists show note text, meanings and units; verify with `tests/test_configurator_page.py` and `tests/test_configurator_params_page.py`.

## 4. Exports

- [ ] 4.1 `docexport`: note column and value meanings in the boot list and the PDO table; verify with `tests/test_docexport.py` (startup SDO with a note) and update the golden output once for built-in notes.
- [ ] 4.2 `dbcexport`: unit, factor and scaled range from notes, note text in comments, `VAL_` tables; verify with `tests/test_dbcexport.py` (scaled pressure, 0x6061 value table, a node without notes unchanged byte for byte) and update affected golden files.

## 5. Docs and release

- [ ] 5.1 `docs/configurator.md`: new "Device notes" section (file name, format with an example, built-in notes, merge rule, editor, checks); `docs/network-docs.md` and the DBC part of the docs for the new columns and value tables; README configurator bullet.
- [ ] 5.2 Bump the deploy tool minor version.

## 6. Hardware check

- [ ] 6.1 On the bench device with a vendor EDS: save the project once, check the notes skeleton, write a note and a value list for one manufacturer setting in the OD view, read and write it by name, and open the network document and DBC file to see them.
