## Context

`notes.note()` merges a sub-object's note from two layers, built-in then device, each with its own inheritance from the object key (`_layer`), and keeps only fields that are not `""` or `None`. A device field therefore replaces a built-in field but cannot remove it, and on an object key it cannot stop sub-objects inheriting the built-in field. The page's note editor (`editNote` in app.js) saves only fields that differ from the built-in note and treats an empty input as "not set".

## Decisions

1. **`null` as the clear marker, not `""`.** JSON `null` is unambiguous and survives JSON round trips; `""` already means "no field" in the editor and the import, and changing that would surprise existing files. Alternative kept out: a separate `"x-clear": ["unit"]` list, which hides the meaning away from the field.
2. **Clear in the device layer before inheritance.** The device layer computes its own fields with inheritance as today, now keeping `null`; the merge then drops a field whose device value is `null`. So `"0x6071": {"unit": null}` clears ‰ on the object and on every sub-object that has no own unit, while `"0x6071:1": {"unit": "mA"}` still shows mA. A sub-object's own `null` beats its object's value.
3. **Same format version.** The schema gains `null` for each field; a file without `null` is unchanged. An older canworks reading a file with `null` shows a schema finding and drops the field, which is the old behaviour.
4. **Import keeps `null` only when it clears something.** A `null` over a field that is not there would be noise in the user's file; it counts as the same.
5. **Merged export writes no `null`.** It writes the merged note as shown, so a cleared field is simply absent. Re-importing a merged export therefore never clears anything, which keeps that path safe.
6. **Editor: empty means clear only where something would show.** The user sees the built-in value in the field; deleting it and keeping the note is the natural gesture for "not this". A greyed placeholder with "hidden" and **Use built-in** makes the state visible and reversible without a new control per field.
7. **Check for useless `null`.** A `null` that clears nothing is a finding, like a key the EDS does not have, so the skill and hand-written files stay tidy.

## Risks / Trade-offs

- **Users clear by accident** by emptying a prefilled field → the placeholder says "hidden", **Use built-in** restores it, and Ctrl+Z undoes the edit.
- **`filled()` and "My notes"** → an entry with only `null` fields counts as the user's note (it changes what is shown), so it is listed under **My notes** with source **Built-in, changed**.
