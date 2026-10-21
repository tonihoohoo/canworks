# Design

## Context

`targets.unused(cfg)` lists the set values the target does not use, and `targets.remove(cfg, paths)` deletes them. Both already exist and back the check warnings and `/api/switch_target`. After #186 the page hides these values and lists them for the user to remove. Toni wants no user step at all.

## Decisions

### Drop on save, not on open

Removing on open would mark a freshly opened file unsaved and change it without a save. Keeping the values silently would leave junk in the file and the CLI warnings would stay. So the server's save path runs `targets.remove(cfg, [p for p, k, _ in targets.unused(cfg) if targets.removable(k)])` on the config it writes, after the checks pass, and returns `left_out: N`. The page shows "Saved; N settings <target> does not use were left out." and reloads the draft from what was written, so the draft matches the file. Network kinds (`role=slave`, J1939, plain) are not removable and stay as they are today: refused or noted by the existing checks.

Between open and save the values sit in the draft unseen, and the page check does not list them. The command-line check (`canworks-deploy --check`) still warns per value, for hand-edited files.

### Switch without a dialog

`switchTarget(target)` posts `/api/switch_target` with `keep: false, pack: true` and applies the result as one undo step. The banner says:

> The project targets CODESYS now: 4 settings it does not use were removed and every PDO entry kept its variable name. Undo brings the OpenPLC project back.

For OpenPLC ↔ bridge the repack is always done, because locations of one are wrong for the other. Version 1 files become version 2 as before, and the banner names it. The preview call goes away.

### What goes

- `unusedBar`, `unusedProblem`, `unusedRow`, `removeUnusedAll`, `isUnusedItem` grouping in `applyCheck`, the badge skip, `setShowAll`, `S.showAll`, `shownFor` (back to `usedBy`), `.unused-field` and `.unused-list` CSS, the Settings menu checkbox, `show_all_fields` in `UI_SETTINGS`.
- Check items for unused values are left out of the page's Problems entirely, because save removes them. `contract.py` keeps adding them for the CLI. The page filters `it.unused && it.removable`.
- `unusedMark` stays only for network kinds, which are not removable and have no Remove.

### Supervision tab

- `supervisionTab` adds the EMCY fieldset only when `usedBy("nodes.emcy_cob_id") || usedBy("nodes.emcy_code_location")`, which is false on CODESYS. The "section with any visible control" rule from #186 stays, because it keeps Method.
- `heartbeatWatchFields` returns `null` when the EDS has no writable 0x1016 and the node has no `heartbeat_watch`. With a leftover watch it keeps the warning and Remove. CSS: `.grid > .heartbeat-watch { grid-column: 1 / -1; }`, and its `.row-head` and `.hint` show as blocks.
- `emcyFieldset(supported=false, leftover=false)` returns the fieldset with only the hint line, without the disabled grid. With a leftover it stays as today (warning, Remove, grid), because Save is refused until removed.

## Risks

- A user who switches by mistake loses the dropped values once they save. Undo works until then, and the banner says so.
- Values set by hand in the file vanish on the next save from the configurator. The save message names how many. Since nothing used them, nothing changes in what runs.
