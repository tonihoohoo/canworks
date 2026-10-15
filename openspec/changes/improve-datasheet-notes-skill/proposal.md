## Why

The datasheet notes skill (PR #110) was tried once on three real devices: a servo driver's EDS with a 37-page PDF manual and with the 45-page manual of its newer firmware, and an open-source demo device's EDS with its Markdown object dictionary. All three files checked clean and imported, but the runs showed where the skill's instructions fall short:

- **One question per difference is too many.** A real manual gave 13 and 15 questions even with "same for the rest of this kind". Toni (2026-10-15): "yes table would be good".
- **Built-in bit and value names get lost.** A note's `bits`, `values`, `text` or `details` replace the built-in field as a whole. The skill does not say so; one run dropped the built-in names of two statusword bits, another kept them by guessing.
- **"Follow EDS" is undefined.** Runs had to guess whether a note may still describe a byte layout or bit field that the EDS range contradicts, and how to map a shifted array.
- **The difference list is too narrow.** Names and PDO mapping are not in it, and an empty EDS default, sub 0 and access such as `RW/S` are unclear. EDS errors on objects that get no note (device type default, identity sub 0, PDO COB-ID access) were found but had no place in the report.
- **Page references are ambiguous.** In both manuals the printed page number is one less than the PDF page. A Markdown document has neither.
- **Contradictions inside the datasheet** (two tables disagreeing, a copied row) have no rule.
- **Comparing by hand is error-prone.** Two runs wrote their own EDS parser to compare; one still missed a sub-object. The skeleton lists only manufacturer objects, without defaults, limits or PDO mapping.
- **Inheritance surprises.** A unit on an object key is inherited by sub 0 (the count) and by sub-objects that pack two values.

## What Changes

- **Differences in one table.** The skill collects every EDS/datasheet difference, then shows them in one table before writing: one row per difference or group of the same kind (the objects it covers listed in the row), what the EDS says, what the datasheet says with its page, and the answer it will use, **Follow EDS** by default. The user answers only the rows to change (**Use datasheet** or **Skip**), or accepts the table as it is. This replaces one question per difference and "same for the rest of this kind".
- **`canworks-deploy notes skeleton --all`**: an entry for every object and sub-object of the EDS, standard ones included, each with `x-type`, `x-access`, `x-default`, `x-low`, `x-high` and `x-pdo` (when the EDS gives them), so the skill compares row against row. Without `--all` the output is as today.
- **Skill rules** (SKILL.md):
  - A device note's `bits`, `values`, `text` and `details` replace the built-in field: on a standard object write the device's complete list, and keep built-in entries the datasheet does not contradict.
  - **Follow EDS** means: keep the EDS's layout, type, size and range; use the datasheet's wording where it fits; the note states nothing the EDS contradicts, and `details` names the difference.
  - Differences include names and PDO mapping; an EDS without a default against a datasheet default is a difference; access `RW/S` (or similar) equals `rw`.
  - Page references: the printed page number, with "PDF n" when it differs; for a document without pages or section numbers, the heading.
  - Contradictions inside the datasheet: prefer the detailed section over the summary table, say so in `details`, list it in the report.
  - Unit and scale go on sub-objects, not the object key, when sub 0 or a packed sub-object would inherit them.
  - A table row with only name, type and default is not a description.
  - The import may also change notes the user wrote; the hand-off says to check those rows in the preview.
- **Report** adds "Other EDS problems seen": differences on objects that got no note.
- Docs (`docs/configurator.md` Notes from a datasheet, `docs/deploy.md` Device notes) follow; PC tools version bump.

## Capabilities

### New Capabilities
None.

### Modified Capabilities
- `canopen-device-notes`: differences in one table; report lists other EDS problems; page references.
- `canopen-deploy`: `notes skeleton --all`.

## Impact

- `.claude/skills/canworks-datasheet-notes/SKILL.md`.
- `tools/deploy/canworks/notes.py` (`skeleton` with all objects and the EDS fields), `cli.py` (`--all`), `tools/deploy/tests/test_notes.py`.
- Docs, PC tools version.
- No notes format, configurator, plugin or config change. No hardware tasks. Trial files stay in the project's private folder, not in the repo or CI.
