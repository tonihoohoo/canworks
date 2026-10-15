## Why

A device note can replace a built-in field but cannot remove one. The trial of the datasheet notes skill (2026-10-15) hit this on real drives: the built-in CiA 402 note of 0x6071 and 0x6077 puts the unit ‰ (thousandths of rated torque) on the object key, so every sub-object inherits it, also sub 0 (the count) and sub-objects the device uses in mA or 0.1 A. A note on the sub-objects fixes those with their own unit, but sub 0 still shows ‰. The same holds for a built-in list of values the device does not support at all (homing methods on a drive without homing): the note can only add a sentence saying the list does not apply. Writing `"unit": ""` hides the field when the file is read, but the configurator's import drops empty fields, so the workaround is lost on **Import notes…**, and the Note editor has no way to do it.

## What Changes

- **`null` clears a field.** A note field set to `null` in a device notes file (`"unit": null`) removes that field of the built-in note, and on an object key also the field its sub-objects would inherit. A sub-object with its own value still shows its own value. The format stays `canworks-notes.v1`; the schema allows `null` for `text`, `details`, `unit`, `scale`, `values`, `bits` and `manual`. `""` is read as before (no field) and is not a way to clear.
- **Import keeps `null`.** **Import notes…** imports a `null` field when the note it lands on has that field (built-in, inherited or the user's own), and lists the entry as changed; a `null` with nothing to clear is skipped as the same. A merged export writes no `null` (the merged note simply lacks the field), so re-importing it changes nothing.
- **Check.** `notes check` and the Problems pane warn about a `null` field that clears nothing (no built-in, inherited or own value).
- **Note editor.** A field that shows a built-in or inherited value can be cleared: emptying it and keeping the note saves `null` for that field. The emptied field then shows the built-in value as a greyed placeholder marked "hidden", with **Use built-in** next to it to bring it back (removing the `null`). Fields without a built-in value work as today.
- **Notes everywhere follow the merge.** The object dictionary, SDO lists, HTML docs, DBC export, trace decoding and merged export use the merged note, so a cleared field is gone there too.
- **Datasheet notes skill.** Where a built-in field does not fit the device at all (a unit inherited by sub 0, an unsupported value list), the skill writes `null` for it instead of only saying so in `text` and `details`.
- Docs (`docs/configurator.md` Device notes, the skill section) and README follow; PC tools version bump.

## Non-goals

- Clearing single entries of a built-in `values` or `bits` list: a device list already replaces the whole built-in list.
- A `canworks-notes.v2` format: older canworks versions only show a schema finding for `null` and otherwise read the file.

## Capabilities

### New Capabilities
None.

### Modified Capabilities
- `canopen-device-notes`: note fields may be `null`; merge and inheritance with `null`; import of `null`; check of a `null` that clears nothing; the datasheet skill clears built-in fields that do not fit.
- `canopen-configurator`: the Note editor clears a built-in or inherited field and brings it back.

## Impact

- `tools/deploy/canworks/notes.py` (`note`, `_layer`, `apply_changes`, `filled`, `plan_import`, `check`, `update`), `schema/canworks-notes.v1.schema.json` and the repository copy in `schema/`, `configurator/static/app.js` (`editNote`, note layering), tests in `tools/deploy/tests/test_notes.py` and the configurator page tests.
- `.claude/skills/canworks-datasheet-notes/SKILL.md`, docs, README, PC tools version.
- No plugin, config or deploy change; notes still never reach the PLC. No hardware tasks.
