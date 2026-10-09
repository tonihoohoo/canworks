## 1. Notes model

- [x] 1.1 Add `schema/canworks-notes.v1.schema.json` (copied to `tools/deploy/canworks/schema/`) for the format in design D2; verify the schema accepts the design's example and rejects a wrong `format`, an index key in lower case and a `text` over 200 characters.
- [x] 1.2 Add `tools/deploy/canworks/notes.py`: `load(path)` (missing file, invalid JSON and wrong format handled as in D7), `builtin(eds)` (CiA 301 always, 401/402 from the 0x1000 default), the field-by-field merge with sub-object inheritance (`note`, `Notes.merged`; D2, D3), `skeleton(eds, eds_name)` (D4), `update(doc, changes, eds)` keeping unknown keys and order, `check(eds, doc, ...)` (D7); verify with `tests/test_notes.py` covering the scenarios in `canopen-device-notes`.
- [x] 1.3 Write `builtin_notes/cia301.json`, `builtin_notes/cia401.json`, `builtin_notes/cia402.json` in canworks' own wording with at least the objects in D3; move the bit and mode names from `app.js` `OD_BITS`/`OD_MODES` into them; verify in `tests/test_notes.py` that each file passes the schema, every key is an object index of its profile range, and 0x1001, 0x1002, 0x6040, 0x6041, 0x6060, 0x6061, 0x6098 and the transmission type have their bits or values.

## 2. Configurator server

- [x] 2.1 Add the built-in and device notes of each EDS to the EDS summary (also for a just-imported EDS) and to the OD browser entries; the page sends its unsaved note edits with Check, Save and the exports; verify with `tests/test_configurator_server.py`.
- [x] 2.2 Save: write notes skeletons for EDS files without a notes file and apply note edits through `notes.update`; never touch an unreadable notes file; keep notes with "replace" and give "keep both" its own file; verify with `tests/test_configurator_server.py` (first save, hand-written entry kept, broken file left as it is, keep-both naming) and that no file outside `canworks/` changes.
- [x] 2.3 Notes checks as warnings in the Problems pane with the notes file name, never blocking Save; verify with an API test for an object the EDS does not have.
- [x] 2.4 "Export merged notes" for a node; verify the file holds built-in plus device entries.
- [x] 2.5 Confirm the deploy bundle and `--check-only` ignore notes files; verify with a `tests/test_deploy.py` case that bundles a config with a notes file next to its EDS.

## 3. Configurator page

- [x] 3.1 Object dictionary view: note text under the name, unit and scaled value, value meaning, bit view from `bits` for any object (remove `OD_BITS`/`OD_MODES`), value list with "Other value…" in the editor; verify with `tests/test_configurator_params_page.py` (note text, meaning, unit, value picked by name, search by note text) and the layout fit check.
- [x] 3.2 Note editor dialog (text, details, unit, scale, values and bits, manual) from the OD view, the startup SDO list and the object picker; only fields that differ from the built-in note are kept; undoable; read-only in "Commission a device" without a config; verify with page tests that write a note from the OD view and from the startup SDO list.
- [x] 3.3 Startup SDO list, object picker, Parameters compare and restore lists show note text, meanings and units; verify with `tests/test_configurator_page.py` and `tests/test_configurator_params_page.py`.

## 4. Exports

- [x] 4.1 `docexport`: note column and value meanings in the boot list, note and unit in the PDO table; verify with `tests/test_docexport.py` (startup SDO with a note) and update the golden output once for built-in notes.
- [x] 4.2 `dbcexport`: unit, factor, note text in comments, `VAL_` tables; verify with `tests/test_dbcexport.py` (scaled signal with a unit and a value table, a node without notes unchanged) and the unchanged golden files.

## 5. Docs and release

- [x] 5.1 `docs/configurator.md`: new "Device notes" section (file name, format with an example, built-in notes, merge rule, editor, checks); `docs/network-docs.md` and the DBC part of `docs/deploy.md` for the new columns and value tables; README configurator bullet.
- [x] 5.2 Bump the deploy tool minor version (0.46.0).
- [x] 5.3 CI time: the change adds tests only to the existing Python and page jobs and no new job, so CI time for a small change does not grow; compare the PR's CI run with the last run on `main`. Squash-merge if an intermediate commit was red. Result: 30 job-minutes on the PR against 32 on the last `main` run; the first commit had a red page test, so squash-merge.

## 6. Hardware check

- [x] 6.1 On the bench device with a vendor EDS: save the project once, check the notes skeleton, write a note and a value list for one manufacturer setting in the OD view, read and write it by name, and open the network document and DBC file to see them.
  Result 2026-10-09: skeleton, note editor, OD read with note and meaning, HTML and DBC passed on the bench device. The write by name reached the device, which refused the chosen object while OPERATIONAL (abort 0x06010002, a device rule: the object is written at boot). Found and fixed: notes on DBC SDO signals, note dialog width, startup hint separator (follow-up PR), and the online object dictionary's network match.
