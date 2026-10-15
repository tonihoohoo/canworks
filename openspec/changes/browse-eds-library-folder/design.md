## Context

The EDS library folder is set in `renderCommNodes()` (`static/commission.js`) as a text input that posts `{eds_library}` to `/api/online/settings` on change. The server checks that the path is a folder and keeps it in the configurator's settings on this PC (`online.py`, `set_eds_library`). Scans match devices against the folder through `EdsIndex`, which walks it with its subfolders.

The start page already has a folder browser (`browse()` in `static/app.js`, `#browser` in `index.html`) backed by `GET /api/folders?path=`, which returns the path, its parent and its subfolders. It is built into the start page, not a dialog, and it cannot leave a drive root on Windows (`parent` is `None` there).

## Goals / Non-Goals

**Goals:** set the library without typing, see what was picked and whether it holds EDS files, work the same on Windows, macOS and Linux, and work with the keyboard alone.

**Non-Goals:** replacing the start page browser, changing the other typed folder fields, picking files (the EDS file buttons stay as they are), indexing or caching the library differently.

## Decisions

1. **Server-side browse in a page dialog, not a native dialog.** Browser pickers do not reveal a path, and the server needs a path. A native dialog from the server process is unreliable (window order, missing tkinter, headless Linux, a blocked thread). The page already lists folders through `/api/folders`, so the dialog reuses it.

2. **One shared dialog: `chooseFolder({title, start, note})`** in `app.js`, returning the chosen path or `null`. It is a `<dialog>` with the same parts as the start page browser (Up, path field with Go, folder list) plus **Cancel** and **Use this folder**. Focus starts on the folder list, Enter on a folder opens it, Backspace or Alt+Up goes up, Escape cancels, and focus returns to **Choose folder…** on close. The start page keeps its own embedded browser for now.

3. **`/api/folders` additions.**
   - Each entry gains `eds`: the number of `.eds` files directly in that subfolder (one `listdir` per subfolder, which the listing already does to test for `project.json`). The current folder gains the same count.
   - On Windows, `path` `""` (or Up from a drive root) returns the drives as entries (`C:\`, `D:\` …, from the existing drive letters), with `parent` `None`; a drive root's `parent` becomes `""`.
   - Hidden folders stay hidden, as now.

4. **Bounded count for the settings reply.** `/api/online/settings` returns `eds_count` and `eds_count_capped` for the library: a walk like `EdsIndex.files` that stops after 5000 directory entries. The row shows "34 EDS files", "No EDS files in this folder or its subfolders", or "Large folder: more than 5000 entries, scans may be slow". Matching itself is unchanged.

5. **The row.** `EDS library  <path or "None chosen">  [Choose folder…] [Clear]` with the existing hint below. The path is selectable text with the full path as its tooltip; a long path is shortened in the middle. **Clear** asks nothing (the folder itself is untouched, and choosing again is one click).

## Risks / Trade-offs

- A user who liked pasting a path still can: the dialog's path field accepts a pasted path and **Go** or Enter opens it. → No loss.
- Counting EDS files per subfolder adds a `listdir` per subfolder to each listing. Folder listings are small and already stat each entry. → Acceptable; the start page benefits too.
- Listing drives on Windows touches removable drives without media. → Only drive letters that exist are listed, and a drive that fails to list shows the existing "not a folder" message in the dialog, not in the page's message bar.
