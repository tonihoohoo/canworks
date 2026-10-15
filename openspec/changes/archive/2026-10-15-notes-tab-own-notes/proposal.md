## Why

The node's **Notes** tab (Configure > node > Notes, and the same tab in Commission) lists every object of the EDS that has any note. On a typical device that is dozens of CiA 301 rows of canworks' built-in text, so the notes the user wrote from the device manual are buried and look the same as the built-in ones. A user who opens the tab to see "what did I write about this device" cannot get that answer.

Managing notes is also scattered:

- **Adding** a note is only possible from a small **Note** button in other lists: the PDO entry picker, the startup SDO rows and the online object dictionary. The Notes tab itself can only edit objects that already have a note, so a manufacturer object with no note cannot be given one there.
- **Importing** notes does not exist. A notes file from a colleague, from another project or from an earlier **Export merged notes** has to be copied by hand next to the EDS.
- **Exporting** is on the Notes tab but only as the merged file, at the far right of the toolbar, where it is easy to miss on a wide screen.

## What Changes

- **The Notes tab shows the user's own notes first.** A view switch above the list: **My notes** (default), **All notes** and **All objects**.
  - *My notes*: every object or sub-object whose device notes entry, with unsaved edits, has at least one filled field (text, details, unit, scale, values, bits, manual). Entries the skeleton wrote with only `name` do not count.
  - *All notes*: today's list, the user's and the built-in notes merged.
  - *All objects*: every object of the EDS, with or without a note, so any object can be given one.
  - Every row says where its note comes from: **Mine**, **Built-in** or **Built-in, changed** (a device entry over a built-in one), by text and not by colour only.
  - The tab's label shows the number of the user's notes ("Notes 4"), and the choice of view is kept per page session like the search.
  - Empty *My notes* says so and offers **Add note…**, **Import notes…** and a link to **All notes**.
- **Add, import and export live on the Notes tab.** One toolbar, left-aligned next to the search:
  - **Add note…** opens a picker of all objects of the EDS (search by index or name, the objects with a note marked) and then the Note editor.
  - **Import notes…** reads a notes file (`canworks-notes.v1`, including a file made by Export), checks it against the schema and the node's EDS, and shows a preview before anything changes: new notes, changed notes, notes that are already the same, and entries skipped because the EDS has no such object; a different EDS identity is a warning, not a refusal. Fields equal to the built-in note are dropped, so importing a merged export does not copy built-in text into the device file. The import is a draft edit: undoable, marked unsaved, written by Save.
  - **Export notes…** offers **My notes** (the device file's filled entries, with unsaved edits) and **Merged with built-in** (today's merged export).
- **The Note buttons move out of the other lists.** The PDO entry picker, the startup SDO rows and the online object dictionary keep showing each object's note text, unit and value meanings, but no longer have their own **Note** button; notes are written on the Notes tab. Each row's **Note** button there still opens the editor.
- README and `docs/configurator.md` are updated.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `canopen-configurator`: Notes tab (views, source marks, toolbar with add, import, export), Note editor (opened from the Notes tab only), Notes in the other node lists (show, no button).
- `canopen-device-notes`: Export merged notes becomes Export notes (own or merged); new Import notes.

## Impact

- `tools/deploy/canworks/configurator/static/node.js` (Notes tab), `app.js` (Note buttons removed from the PDO picker, startup SDO list and online object dictionary; import and export calls), `nodes.js` (Commission Notes tab reuses the same view).
- `tools/deploy/canworks/configurator/server.py` and `notes.py`: `POST /api/import_notes` (check and preview, returns the changes for the page's draft) and an `own` option on `POST /api/export_notes`.
- Page and server tests in `tools/deploy/tests/`. No change to the config file, the deploy tool or the plugin; notes never reach the device.
- No hardware test: notes stay on the PC.
