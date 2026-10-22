# Design

## Why the rename fails

`os.replace(tmp, dst)` on Windows is `MoveFileExW(MOVEFILE_REPLACE_EXISTING)`. It needs DELETE access to `dst`, and it fails with ERROR_ACCESS_DENIED (5) while any other handle on `dst` was opened without `FILE_SHARE_DELETE`. Writing the `.tmp` succeeded, so the folder was writable; replacing a file written a moment earlier failed. That matches a scanner or indexer opening the new file after `openplc-cli` closed it. On the bench PC (Defender on, Controlled Folder Access off) 10 runs of the same steps never failed and each rename took about 4 ms. The failing PC took about 10 s to create the project (the bench PC 4 to 5 s), which also points to heavier scanning.

## Retry

`replace_file(tmp, path, deadline_s=5.0, in_place=False)`:

- Off Windows it is a plain `os.replace`.
- On Windows it retries on `PermissionError` with waits of 20, 40, 80 … ms, at most 500 ms each, until about 5 s have passed.
- `in_place=True`: when the deadline passes, it copies the `.tmp` content into `path` (open "r+b", truncate, write) and removes the `.tmp`. Only creation uses this, for the editor's files in a project it is making, where nothing else reads the file and a failure removes it.
- Otherwise it removes the `.tmp` and raises `FileLockedError(path)` (a `PermissionError`). Its message reads "<file> is held open by another program (often antivirus or a sync client such as OneDrive); try again".

5 s is long enough for a first scan of a small file and short enough for a Save. Save already shows "Saving…" while it runs.

## Existing folder

`openplc-cli create` refuses an existing path unless `--force` is passed, and with `--force` it writes `project.json`, `devices/configuration.json`, `devices/pin-mapping.json`, `pous/programs/main.st` and the empty `datatypes`, `pous/functions` and `pous/function-blocks` folders. Other files are left alone (checked with editor 4.3.2). `create` therefore:

1. refuses when the folder has `project.json`, `canworks.json`, `canworks/` or any of the editor files above, naming the first one;
2. records what exists before it runs (a set of relative paths);
3. passes `--force` only when the folder existed.

On failure, a folder that `create` made is removed whole, as before. In an existing folder, `create` removes each file and folder that was not in the recorded set, deepest first, and never one that was.

## Console window

`subprocess.run(..., creationflags=CREATE_NO_WINDOW, stdin=DEVNULL)` on Windows. The output is still captured for the error message.

## Not done

- No exclusion or setting change on the user's PC.
- The retry is not added to reads; a read that fails still says it cannot read the file.
