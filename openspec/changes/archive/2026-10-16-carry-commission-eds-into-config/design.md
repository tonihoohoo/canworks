## Context

Commission a device is a scratch standalone folder (`<settings>/commission`). An EDS added there is held as an unsaved import: bytes in `Session.pending`, a copy in `Session.pending_dir`, referred to by bare name. `Session.open()` clears `pending`, so after **Add to a config…** switches folders the name refers to nothing, and `_use_eds()` refuses it.

## Decisions

**Carry on the server, in the open call.** `/api/open` with `carry_eds` reads the EDS bytes from the current session (pending name → `pending[name]`; absolute path → must be under the Commission folder or the EDS library, normcase compared) before anything changes, then opens the folder and calls `import_eds(basename, data, "keep_both", eds_lint)`. The answer gains `carried_eds` (the import result: name, summary, lint). Doing it in one call means no window where the old session's files are gone and the client still needs them, and a read failure raises before `open()`, so the page stays in Commission.

Rejected: the client fetching the EDS bytes and re-posting them to `/api/eds` after the open. It needs a new download route and a second round trip, and a failure after the open leaves the user in the new config with no node and no way back to the Commission log.

**`addScannedNode()` takes an import result.** A fourth source next to `match` (use_eds) and `file` (`/api/eds`): `imported`, used as `res` directly. `addToConfig()` passes `carried_eds` when the open answer has it; with no EDS in Commission it keeps asking for the file as now.

**`_use_eds()` also accepts pending names.** A bare name that is in `s.pending` resolves through `s.eds_path()` and is returned as it is (already in the draft). This covers any other caller that holds a pending name in the same session, and matches `params.py`, which already allows `pending_dir`.

**normcase.** Windows compares paths case-insensitively; `realpath` usually returns the on-disk case, but the library folder comes from settings and a mapped or typed path can differ in case. Comparing `normcase(realpath(...))` is harmless elsewhere (identity on POSIX).

## Risks

- An EDS with the same name and different content already in the target config: `keep_both` gives it a new name, and the banner already reports the import (`importReport`).
- EDS lint: the page calls `/api/folder_nodes` before it leaves Commission; with `carry_eds` it also checks the EDS under the target config's lint mode, so a lint refusal leaves the page in Commission. The import after the open uses the opened config's own mode, as any import would.
